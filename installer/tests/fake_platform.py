"""A fake Windows machine for the Local Models Kit manager tests.

Implements the manager's Platform contract in memory and in a temp
directory: a user profile, a registry-free env dict, an Ollama server
with a model store, and WSL distros whose home directories are real
folders under the temp root (so byte and mtime assertions mean
something). No test here touches a real machine.
"""

import base64
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "manager"))
from local_models_kit_manager import (CmdResult, Platform, StepError,  # noqa: E402
                               OPENCODE_INSTALL_COMMAND,
                               OPENCODE_PATH_BEGIN, normalize_tag)

GB = 1_000_000_000


class FakePlatform(Platform):
    name = "fake"

    def __init__(self, base):
        self.base = Path(base)
        self.profile = self.base / "User"
        self.profile.mkdir(parents=True, exist_ok=True)
        self.env = {}
        self.build = 26100
        self.free_bytes = 500 * GB
        self.network = True
        self.endpoint_other = False
        self.distros = ["Ubuntu"]
        self.wsl_broken = False
        self.bridge_ok = True
        self.ollama_installed = False
        self.ollama_version = (0, 40, 8)
        self.server_running = False
        self.tags = {}       # normalized name -> {"num_ctx": int or None}
        self.ps_models = []  # entries shaped like /api/ps models
        # OpenCode in a distro, modeled the way L2 now probes it:
        # a canonical binary at ~/.opencode/bin/opencode (a real
        # file under the fake home, with a version), whether a fresh
        # login shell finds opencode on PATH, and any opencode that
        # answers on PATH without a canonical binary.
        self.opencode_binary = {}    # distro -> version at canonical path
        self.opencode_path_ok = {}   # distro -> login shells find it
        self.opencode_elsewhere = {}  # distro -> version on PATH only
        self.opencode_install_fails = False
        self.opencode_install_version = "2.0.26"
        self.wsl_commands = []       # every wsl_run argv, in order
        self.tray_restarts = 0
        self.pulled = []
        self.created = []
        self.removed = []
        self.winget_calls = []
        self.sleeps = []
        self.comfy_running = False
        self.comfy_cpu_only = False
        self.comfy_download_fails = False
        self.comfy_endpoint_other = False
        self.comfy_device_name = "AMD Radeon 8060S Graphics"
        self.comfy_vram_total = 48_000_000_000
        self.comfy_vram_free = 48_000_000_000
        self.comfy_history = {}
        self.comfy_prompts = 0
        self.comfy_free_calls = []
        self.comfy_unload_calls = []  # Ollama /api/generate keep_alive 0
        self.downloads = []
        self.extractions = []
        self.detached = []
        self.stopped_fragments = []
        self._clock = datetime(2026, 1, 1, 12, 0, 0)
        self._wsl_root = self.base / "wsl"
        self.home_in_wsl = "/home/testuser"

    # ----- identity, time, space -----

    def is_windows(self):
        return True

    def windows_build(self):
        return self.build

    def now(self):
        self._clock += timedelta(seconds=1)
        return self._clock

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def free_disk_bytes(self, path):
        return self.free_bytes

    def network_available(self):
        return self.network

    def default_install_root(self):
        return self.base / "LocalModelsKit"

    def user_profile_dir(self):
        return self.profile

    # ----- user env -----

    def get_user_env(self, name):
        return self.env.get(name)

    def set_user_env(self, name, value):
        self.env[name] = value

    def unset_user_env(self, name):
        self.env.pop(name, None)

    # ----- processes -----

    def find_on_path(self, name):
        if name == "ollama" and self.ollama_installed:
            return "C:\\fake\\ollama.exe"
        return None

    def run(self, argv, timeout=None, input_bytes=None):
        argv = [str(a) for a in argv]
        if argv[:2] == ["ollama", "--version"]:
            if not self.ollama_installed:
                return CmdResult(1, b"", b"not recognized")
            ver = ".".join(map(str, self.ollama_version))
            return CmdResult(0, f"ollama version is {ver}\n".encode())
        if argv and argv[0] == "winget":
            self.winget_calls.append(argv)
            if "install" in argv and "Ollama.Ollama" in argv:
                self.ollama_installed = True
                self.server_running = True  # installing starts the tray
            if "uninstall" in argv and "Ollama.Ollama" in argv:
                self.ollama_installed = False
                self.server_running = False
            return CmdResult(0, b"ok")
        if argv[:2] == ["ollama", "pull"] and len(argv) == 3:
            if not self.ollama_installed:
                return CmdResult(1, b"", b"ollama missing")
            self.server_running = True
            self.tags.setdefault(normalize_tag(argv[2]), {"num_ctx": None})
            self.pulled.append(argv[2])
            return CmdResult(0, b"success")
        if argv[:2] == ["ollama", "create"] and len(argv) == 5:
            if not self.ollama_installed:
                return CmdResult(1, b"", b"ollama missing")
            text = Path(argv[4]).read_bytes().decode("utf-8")
            m = re.search(r"PARAMETER num_ctx (\d+)", text)
            self.tags[normalize_tag(argv[2])] = {
                "num_ctx": int(m.group(1)) if m else None}
            self.created.append(argv[2])
            return CmdResult(0, b"success")
        if argv[:2] == ["ollama", "rm"] and len(argv) == 3:
            self.tags.pop(normalize_tag(argv[2]), None)
            self.removed.append(argv[2])
            return CmdResult(0, b"deleted")
        if argv[:2] == ["ollama", "list"]:
            if not self.ollama_installed:
                return CmdResult(1, b"", b"ollama missing")
            lines = ["NAME\tID\tSIZE\tMODIFIED"]
            lines += [f"{name}\tabc\t1 GB\tnow" for name in sorted(self.tags)]
            return CmdResult(0, ("\n".join(lines) + "\n").encode())
        if argv[:2] == ["wsl", "--shutdown"]:
            return CmdResult(1, b"", b"wsl broken") if self.wsl_broken \
                else CmdResult(0)
        if argv and argv[0] == "taskkill":
            self.server_running = False
            return CmdResult(0)
        if argv[:2] == ["tar.exe", "-xf"] and len(argv) == 5 and argv[3] == "-C":
            archive, dest = Path(argv[2]), Path(argv[4])
            if not archive.is_file():
                return CmdResult(1, b"", b"tar: archive not found")
            portable = dest / "ComfyUI_windows_portable"
            (portable / "ComfyUI" / "models" / "diffusion_models").mkdir(parents=True, exist_ok=True)
            (portable / "ComfyUI" / "models" / "text_encoders").mkdir(parents=True, exist_ok=True)
            (portable / "ComfyUI" / "models" / "vae").mkdir(parents=True, exist_ok=True)
            (portable / "run_amd_gpu.bat").write_bytes(b"@echo off\r\nrem fake launcher\r\n")
            (portable / "ComfyUI" / "main.py").write_bytes(b"# fake comfy main\n")
            (portable / "python_embeded").mkdir(parents=True, exist_ok=True)
            (portable / "python_embeded" / "python.exe").write_bytes(b"")
            self.extractions.append((str(archive), str(dest)))
            return CmdResult(0)
        return CmdResult(1, b"", f"fake: unhandled {argv}".encode())

    # ----- Ollama API (Windows side, and the same server via WSL) -----

    def api_probe(self):
        if self.endpoint_other:
            return "other"
        return "ollama" if self.server_running else "free"

    def _api_get(self, path):
        if not self.server_running:
            return None
        if path == "/api/version":
            return {"version": ".".join(map(str, self.ollama_version))}
        if path == "/api/tags":
            return {"models": [{"name": n} for n in sorted(self.tags)]}
        if path == "/api/ps":
            return {"models": list(self.ps_models)}
        return None

    def _api_post(self, path, payload):
        if not self.server_running:
            return None
        if path == "/api/show":
            name = normalize_tag(str(payload.get("name", "")))
            info = self.tags.get(name)
            if info is None:
                return None
            params = ""
            if info.get("num_ctx"):
                params = f"num_ctx {info['num_ctx']}"
            return {"parameters": params}
        if path == "/api/generate":
            if payload.get("keep_alive") == 0:
                name = normalize_tag(str(payload.get("model", "")))
                self.ps_models = [
                    m for m in self.ps_models
                    if normalize_tag(str(m.get("name", ""))) != name]
                self.comfy_unload_calls.append(payload)
            return {"done": True}
        if path == "/v1/chat/completions":
            name = normalize_tag(str(payload.get("model", "")))
            if name in self.tags:
                return {"choices": [{"message": {"content": "ready"}}]}
            return None
        return None

    def api_get(self, path, timeout=10):
        return self._api_get(path)

    def api_post(self, path, payload, timeout=10):
        return self._api_post(path, payload)

    def restart_ollama_tray(self):
        self.tray_restarts += 1
        self.server_running = self.ollama_installed

    # ----- WSL -----

    def wsl_distros(self):
        if self.wsl_broken:
            return None
        return list(self.distros)

    def wsl_home(self, distro):
        self._home_dir(distro)  # ensure it exists
        return self.home_in_wsl

    def _home_dir(self, distro):
        home = self._wsl_root / distro / "home" / "testuser"
        home.mkdir(parents=True, exist_ok=True)
        return home

    def _map(self, distro, path):
        home = self._home_dir(distro)
        if path == self.home_in_wsl:
            return home
        prefix = self.home_in_wsl + "/"
        if path.startswith(prefix):
            return home / path[len(prefix):]
        raise ValueError(f"fake only maps paths under {self.home_in_wsl}: {path}")

    def wsl_read_file(self, distro, path):
        target = self._map(distro, path)
        return target.read_bytes() if target.is_file() else None

    def wsl_write_file(self, distro, path, data):
        target = self._map(distro, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if path.endswith("/.profile") and \
                OPENCODE_PATH_BEGIN.encode("utf-8") in data:
            # The kit's PATH block landed in the file login shells
            # read, so cold login shells now find the binary.
            self.opencode_path_ok[distro] = True

    def seed_opencode(self, distro, version, on_path=True, canonical=True):
        """Plant an OpenCode the way a real install leaves it: the
        canonical binary as a real file (or, with canonical=False,
        an opencode that only answers on PATH), plus the login
        shell PATH state."""
        if canonical:
            self.opencode_binary[distro] = version
            target = self._home_dir(distro) / ".opencode" / "bin" / "opencode"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake opencode binary\n")
        else:
            self.opencode_elsewhere[distro] = version
        self.opencode_path_ok[distro] = on_path

    def _install_opencode(self, distro):
        self.seed_opencode(distro, self.opencode_install_version,
                           on_path=True, canonical=True)

    def wsl_file_exists(self, distro, path):
        return self._map(distro, path).is_file()

    def wsl_copy_file(self, distro, src, dst):
        source, target = self._map(distro, src), self._map(distro, dst)
        if not source.is_file():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return True

    def wsl_run(self, distro, argv, timeout=None, input_bytes=None):
        argv = [str(a) for a in argv]
        self.wsl_commands.append(list(argv))
        if distro not in self.distros:
            return CmdResult(1, b"", b"distro not found")
        if argv == ["true"]:
            return CmdResult(0)
        if argv[:2] == ["bash", "-lc"] and len(argv) == 3:
            command = argv[2]
            if command == "opencode --version":
                version = self.opencode_binary.get(distro) or \
                    self.opencode_elsewhere.get(distro)
                if version and self.opencode_path_ok.get(distro):
                    return CmdResult(0, (version + "\n").encode())
                return CmdResult(127, b"", b"opencode: command not found")
            if command == OPENCODE_INSTALL_COMMAND:
                if self.opencode_install_fails:
                    return CmdResult(1, b"", b"curl failed")
                self._install_opencode(distro)
                return CmdResult(0, b"installed")
            if command.startswith('printf %s "$HOME"'):
                return CmdResult(0, self.home_in_wsl.encode())
        if argv[:2] == ["bash", "-c"] and len(argv) == 3:
            return self._wsl_shell(distro, argv[2], input_bytes)
        if argv and argv[0] == "python3" and "-c" in argv:
            return self._wsl_api(argv)
        return CmdResult(1, b"", f"fake: unhandled wsl {argv}".encode())

    def _wsl_shell(self, distro, script, input_bytes):
        parts = shlex_split(script)
        try:
            if len(parts) == 2 and parts[1] == "--version" and \
                    parts[0].endswith("/.opencode/bin/opencode"):
                # The canonical binary run by absolute path (L2's
                # primary probe): answers from the planted file,
                # whatever the login shell PATH state is.
                version = self.opencode_binary.get(distro)
                if version and self._map(distro, parts[0]).is_file():
                    return CmdResult(0, (version + "\n").encode())
                return CmdResult(127, b"", b"no such file")
            if parts[:3] == ["base64", "-w", "0"] or parts[:2] == ["base64", "-w"]:
                target = self._map(distro, parts[-1])
                if not target.is_file():
                    return CmdResult(1, b"", b"no such file")
                return CmdResult(0, base64.b64encode(target.read_bytes()))
            if parts[:2] == ["mkdir", "-p"]:
                self._map(distro, parts[-1]).mkdir(parents=True, exist_ok=True)
                return CmdResult(0)
            if parts[:2] == ["base64", "-d"]:
                target = self._map(distro, parts[-1].lstrip("> ").strip())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(base64.b64decode(input_bytes or b""))
                return CmdResult(0)
            if parts[:2] == ["test", "-f"]:
                exists = self._map(distro, parts[2]).is_file()
                return CmdResult(0 if exists else 1)
            if parts[:1] == ["cp"]:
                source, target = self._map(distro, parts[-2]), self._map(distro, parts[-1])
                if not source.is_file():
                    return CmdResult(1, b"", b"no such file")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                return CmdResult(0)
            if parts[:1] == ["rm"]:
                target = self._map(distro, parts[-1])
                target.unlink(missing_ok=True)
                return CmdResult(0)
        except Exception as exc:  # surface as a failed command, not a crash
            return CmdResult(1, b"", f"fake shell: {exc}".encode())
        return CmdResult(1, b"", f"fake: unhandled shell {script}".encode())

    def _wsl_api(self, argv):
        if not self.bridge_ok:
            return CmdResult(1, b"", b"connection refused")
        url, payload = argv[-2], argv[-1]
        path = url.replace("http://localhost:11434", "")
        if payload:
            body = self._api_post(path, json.loads(payload))
        else:
            body = self._api_get(path)
        if body is None:
            return CmdResult(1, b"", b"no answer")
        return CmdResult(0, json.dumps(body).encode())

    def wsl_api_get(self, distro, path):
        if not self.bridge_ok:
            return None
        return self._api_get(path)

    def wsl_api_post(self, distro, path, payload):
        if not self.bridge_ok:
            return None
        return self._api_post(path, payload)

    # ----- ComfyUI (fold-in) -----
    #
    # A simulated ComfyUI server plus the file/process seam. Files
    # are real (sparse, truncated to the expected size) under the
    # temp base so size and mtime assertions mean something. The
    # fake download_file does NOT verify content hashes: it
    # fabricates a file of the right size, because hashing 12 GB of
    # zeros would prove nothing. Hash verification lives inside the
    # real platform's download_file and is not covered here.

    def default_comfy_root(self):
        return self.base / "ComfyUI"

    def comfy_probe(self):
        if self.comfy_endpoint_other:
            return "other"
        return "comfy" if self.comfy_running else "free"

    def comfy_get(self, path, timeout=10):
        if not self.comfy_running:
            return None
        if path == "/system_stats":
            if self.comfy_cpu_only:
                devices = [{"name": "cpu", "type": "cpu",
                            "vram_total": 0, "vram_free": 0}]
            else:
                devices = [{"name": self.comfy_device_name,
                            "type": "cuda",
                            "vram_total": self.comfy_vram_total,
                            "vram_free": self.comfy_vram_free}]
            return {"system": {"comfyui_version": "0.46.0"},
                    "devices": devices}
        if path.startswith("/history/"):
            prompt_id = path.rsplit("/", 1)[-1]
            entry = self.comfy_history.get(prompt_id)
            return {prompt_id: entry} if entry else {}
        return None

    def comfy_post(self, path, payload, timeout=10):
        if not self.comfy_running:
            return None
        if path == "/prompt":
            self.comfy_prompts += 1
            prompt_id = f"fake-prompt-{self.comfy_prompts}"
            self.comfy_history[prompt_id] = {
                "outputs": {"10": {"images": [{
                    "filename": "local-models-kit_smoke_00001_.png",
                    "subfolder": "", "type": "output"}]}},
                "status": {"completed": True}}
            self.comfy_vram_free = \
                self.comfy_vram_total - 23_000_000_000
            return {"prompt_id": prompt_id}
        if path == "/free":
            self.comfy_free_calls.append(payload)
            self.comfy_vram_free = self.comfy_vram_total
            return {}
        return None

    def download_file(self, url, dest, expected_size, expected_sha256):
        if self.comfy_download_fails:
            raise StepError(f"fake: download failed for {url}")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            fh.truncate(expected_size)
        self.downloads.append((url, str(dest), expected_size))

    def extract_archive(self, archive, dest_dir):
        result = self.run(["tar.exe", "-xf", str(archive), "-C", str(dest_dir)])
        if result.rc != 0:
            raise StepError(
                "fake: tar.exe failed: "
                + result.err.decode("utf-8", errors="replace"))

    def start_detached(self, argv, cwd=None):
        argv = [str(a) for a in argv]
        self.detached.append((argv, str(cwd)))
        if any("run_amd_gpu" in a for a in argv) or \
                "ComfyUI_windows_portable" in str(cwd):
            self.comfy_running = True

    def stop_process_by_path(self, fragment):
        self.stopped_fragments.append(fragment)
        if "ComfyUI_windows_portable" in fragment and self.comfy_running:
            self.comfy_running = False
            return 1
        return 0

    def port_in_use(self, port):
        return (port == 8188 and self.comfy_running) or \
            (port == 11434 and self.server_running)


def shlex_split(script):
    import shlex
    return shlex.split(script)
