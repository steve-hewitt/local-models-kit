#!/usr/bin/env python3
"""Local Models Kit manager: the engine inside the kit installer.

One Python program, standard library only, with six verbs:
install, doctor, repair, update, uninstall, switch. It performs the steps the
kit's guides and setup scripts describe (docs/WSL.md Parts 1 to 3 and
scripts/setup.ps1 -ServerOnly plus scripts/setup.sh --client-only),
natively: Ollama and the models on the Windows side, OpenCode in WSL,
driven from here through wsl.exe. It never shells out to the kit's own
setup scripts on Windows; those stay as the Tier 1 source-run path and
as the readable specification of what this program does.

Step IDs are the installer build plan's inventory, and they are the
vocabulary of the state file, the log, and doctor's report:

  W1 Ollama installed (winget), at least MIN_OLLAMA
  W2 Server env vars in the User environment
  W3 Ollama tray restarted, server answers /api/version
  W4 Base model tags pulled (the chosen models; flint and
     qwen3:30b-a3b by default)
  W5 Context-pinned variants built (num_ctx per family)
  W6 Windows-side verify: hello round trip, residency recorded
  B1 .wslconfig managed block: networkingMode=mirrored under [wsl2]
  B2 WSL restarted so B1 takes effect
  L1 WSL distro detected (default Ubuntu)
  L2 OpenCode present inside the distro
  L3 Kit OpenCode config installed inside the distro (backup first)
  L4 Client-side smoke from inside WSL
  C1 ComfyUI portable present, pinned to the v0.46.0 archive
  C2 Z-Image-Turbo model files present, sizes pinned
  C3 Gate 1: ComfyUI launches and reports a Radeon GPU
  C4 Gate 2: an API smoke workflow produces a real image

A sixth verb, switch, hands the GPU between the Ollama stack and
ComfyUI; the two do not fit in the target machine's GPU memory
allocation at the same time. The default install is the full stack
(Flint, Qwen, and ComfyUI); the C steps are recorded as skipped
only when ComfyUI is opted out (--no-comfyui).

Every step checks before it acts and reports DONE, SKIP, or FIX. The
JSON state file under the install root is flushed after each step: it
is the resume mechanism, doctor's claim list, and the uninstall
manifest. All file I/O is byte-exact (write_bytes and bytes round
trips only). Text-mode writes translate newlines on Windows and
silently poison hash and content comparisons; Gate 0 of the installer
plan proved that the hard way, and this file does not regress it.

Every platform effect (registry and environment, winget, the ollama
CLI and API, wsl.exe, file roots, clocks) sits behind the Platform
seam below, so the logic runs on Linux against a fake platform in
installer/tests/. On a non-Windows host the real verbs refuse; only
--plan and the test suite run there.

Validation status: validated end to end on the target hardware on
2026-11-25 (see installer/README.md for what that run covered and
what is still unrun on hardware).
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

KIT_VERSION = "1.0.0"  # first public release
MANAGER_VERSION = "1.0.0"  # public release; validated on the target hardware, 2026-11-25

MIN_OLLAMA = (0, 40, 8)
MIN_WINDOWS_BUILD = 22621  # Windows 11 22H2: mirrored networking floor
OLLAMA_API = "http://localhost:11434"

FLINT_BASE_TAG = "flint"
FLINT_VARIANT = "flint-opencode"
QWEN_BASE_TAG = "qwen3:30b-a3b"
QWEN_VARIANT = "qwen-opencode"

DEFAULT_NUM_CTX = 131072
MAX_NUM_CTX = 262144  # Flint's documented ceiling
QWEN_NUM_CTX = 131072  # Qwen3-30B-A3B's YaRN ceiling; never raised

# Download sizes the preflight budgets for, in bytes (setup script
# figures: flint about 23 GB, qwen about 19 GB), plus fixed spare.
MODEL_BYTES = {FLINT_BASE_TAG: 23_000_000_000, QWEN_BASE_TAG: 19_000_000_000}
SPARE_BYTES = 10_000_000_000

# ----------------------------------------------------------------------
# ComfyUI fold-in (manager 0.2.0). Since 0.2.1 ComfyUI is part of
# the default install, like Qwen; an install that opts out with
# --no-comfyui never touches it.
# The pins below are exact, verified 2026-11-22: the portable archive
# from the Comfy-Org/ComfyUI v0.46.0 GitHub release, and the three
# Z-Image-Turbo model files from the Comfy-Org/z_image_turbo Hugging
# Face repo (sizes and SHA-256 from the Hugging Face API; they match
# the byte counts the ComfyUI template itself reports).
# ----------------------------------------------------------------------

COMFY_API = "http://127.0.0.1:8188"
COMFY_PORT = 8188
COMFY_VERSION = "0.46.0"
COMFY_ARCHIVE_FILE = "ComfyUI_windows_portable_amd.7z"
COMFY_ARCHIVE_SIZE = 1_702_415_528
COMFY_ARCHIVE_SHA256 = \
    "00f42ed58381e194892b74e9085d4d5666fac1aab8f021094c3a745e9b52ad97"
COMFY_ARCHIVE_URL = ("https://github.com/Comfy-Org/ComfyUI/releases/"
                     "download/v0.46.0/ComfyUI_windows_portable_amd.7z")
COMFY_PORTABLE_DIRNAME = "ComfyUI_windows_portable"
COMFY_LAUNCHER = "run_amd_gpu.bat"
COMFY_MIN_VRAM = 16_000_000_000  # Gate 1 floor: a real GPU carve-out

# filename -> (models subdir, size in bytes, sha256, download URL)
COMFY_MODELS = {
    "z_image_turbo_bf16.safetensors": (
        "diffusion_models", 12_309_866_400,
        "2407613050b809ffdff18a4ac99af83ea6b95443ecebdf80e064a79c825574a6",
        "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/"
        "split_files/diffusion_models/z_image_turbo_bf16.safetensors"),
    "qwen_3_4b.safetensors": (
        "text_encoders", 8_044_982_048,
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
        "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/"
        "split_files/text_encoders/qwen_3_4b.safetensors"),
    "ae.safetensors": (
        "vae", 335_304_388,
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
        "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/"
        "split_files/vae/ae.safetensors"),
}
COMFY_MODELS_BYTES = sum(v[1] for v in COMFY_MODELS.values())

# The Gate 2 smoke workflow, in ComfyUI API format. Converted
# faithfully from the official Comfy-Org workflow template
# image_z_image_turbo.json (subgraph expanded: UNETLoader,
# CLIPLoader type lumina2, VAELoader, CLIPTextEncode,
# ConditioningZeroOut for the negative, EmptySD3LatentImage
# 1024x1024, ModelSamplingAuraFlow shift 3, KSampler 8 steps,
# cfg 1.0, res_multistep, simple scheduler, VAEDecode, SaveImage),
# with a fixed seed and a neutral test prompt. The live twin lives
# at installer/templates/z_image_turbo_smoke.json; a test pins the
# two together, same as the other templates.
COMFY_SMOKE_WORKFLOW_TEMPLATE = '{\n  "1": {\n    "class_type": "UNETLoader",\n    "inputs": {\n      "unet_name": "z_image_turbo_bf16.safetensors",\n      "weight_dtype": "default"\n    }\n  },\n  "2": {\n    "class_type": "CLIPLoader",\n    "inputs": {\n      "clip_name": "qwen_3_4b.safetensors",\n      "type": "lumina2",\n      "device": "default"\n    }\n  },\n  "3": {\n    "class_type": "VAELoader",\n    "inputs": {\n      "vae_name": "ae.safetensors"\n    }\n  },\n  "4": {\n    "class_type": "CLIPTextEncode",\n    "inputs": {\n      "text": "A matte grey cube on a white table, soft studio light, plain background",\n      "clip": [\n        "2",\n        0\n      ]\n    }\n  },\n  "5": {\n    "class_type": "ConditioningZeroOut",\n    "inputs": {\n      "conditioning": [\n        "4",\n        0\n      ]\n    }\n  },\n  "6": {\n    "class_type": "EmptySD3LatentImage",\n    "inputs": {\n      "width": 1024,\n      "height": 1024,\n      "batch_size": 1\n    }\n  },\n  "7": {\n    "class_type": "ModelSamplingAuraFlow",\n    "inputs": {\n      "model": [\n        "1",\n        0\n      ],\n      "shift": 3.0\n    }\n  },\n  "8": {\n    "class_type": "KSampler",\n    "inputs": {\n      "model": [\n        "7",\n        0\n      ],\n      "positive": [\n        "4",\n        0\n      ],\n      "negative": [\n        "5",\n        0\n      ],\n      "latent_image": [\n        "6",\n        0\n      ],\n      "seed": 42,\n      "steps": 8,\n      "cfg": 1.0,\n      "sampler_name": "res_multistep",\n      "scheduler": "simple",\n      "denoise": 1.0\n    }\n  },\n  "9": {\n    "class_type": "VAEDecode",\n    "inputs": {\n      "samples": [\n        "8",\n        0\n      ],\n      "vae": [\n        "3",\n        0\n      ]\n    }\n  },\n  "10": {\n    "class_type": "SaveImage",\n    "inputs": {\n      "images": [\n        "9",\n        0\n      ],\n      "filename_prefix": "local-models-kit_smoke"\n    }\n  }\n}\n'

ENV_MAX_LOADED = "OLLAMA_MAX_LOADED_MODELS"
ENV_CONTEXT_LENGTH = "OLLAMA_CONTEXT_LENGTH"

WSLCONFIG_BEGIN = "# --- local-models-kit managed begin ---"
WSLCONFIG_END = "# --- local-models-kit managed end ---"

# OpenCode (L2). The canonical binary inside the distro is
# ~/.opencode/bin/opencode; both OpenCode installers put it there.
# The only installer command this program may run is the OpenCode 2
# one: the vendor's original install URL (this address without the
# /v2/) now serves OpenCode 1 only (it resolves the newest 1.x and
# refuses 2.x), and running it over an OpenCode 2 install silently
# downgrades it. See the L2 section.
OPENCODE_INSTALL_COMMAND = \
    "curl -fsSL https://opencode.ai/v2/install | bash"
OPENCODE_PATH_BEGIN = "# >>> local-models-kit opencode path >>>"
OPENCODE_PATH_END = "# <<< local-models-kit opencode path <<<"
OPENCODE_PATH_BLOCK = (
    OPENCODE_PATH_BEGIN + "\n"
    'export PATH="$HOME/.opencode/bin:$PATH"\n'
    + OPENCODE_PATH_END + "\n")


def _clean_opencode_version(text: str):
    """Normalize an `opencode --version` answer to the bare version.
    OpenCode 2 prints 'opencode v2.0.26'; the kit's other version
    strings are bare numbers, and the uncleaned value doubled the
    name in every message that names the tool (the first live Biff
    run printed 'opencode opencode v2.0.26')."""
    text = text.strip()
    if text.lower().startswith("opencode "):
        text = text.split(None, 1)[1].strip()
    if text.startswith("v") and len(text) > 1 and text[1].isdigit():
        text = text[1:]
    return text or None

# Template placeholders: replaced at authoring time with the exact
# contents of models/Modelfile.flint-opencode, models/Modelfile
# .qwen-opencode and config/opencode.json from the repo, so a compiled
# manager carries the kit's templates with it. When the manager runs
# from a repo checkout it prefers the live files (see _load_template).
FLINT_MODELF_TEMPLATE = "# Context-pinned Flint variant for OpenCode.\n# Build it with:\n#   ollama create flint-opencode -f models/Modelfile.flint-opencode\n# Verify with:\n#   ollama show flint-opencode --parameters\n# The setup scripts rewrite this file's FROM line to the tag they\n# pulled (MODEL_TAG) before building, so a non-default Flint tag pins\n# itself rather than the default build named below.\n#\n# Why bake this in instead of relying on client settings?\n# Ollama's runtime context defaults are much smaller than Flint's 262K\n# maximum, and client-side settings do not reliably override them.\n# A Modelfile is the one place the value always wins.\n#\n# 131072 (128K) is the kit default since 2026-11-09: 32K proved\n# unusable for real agent work and 128K is the floor. Flint's own ceiling is 262K; the setup scripts honor NUM_CTX\n# to rebuild this variant higher (they rewrite this line in the temp\n# copy they build from). The KV cache grows linearly with context;\n# see docs/HARDWARE.md before raising it on a 64 GB machine.\n#\n# num_predict is 32768 for Flint: Recursive's model card recommends an\n# output budget of at least 32768 tokens for hard problems, reasoning\n# included. At the old 8192 a hard turn could spend the whole budget\n# thinking and get cut off before answering. Qwen's variant stays 8192.\n\nFROM flint\n\nPARAMETER num_ctx 131072\nPARAMETER num_predict 32768\n"
QWEN_MODELF_TEMPLATE = "# Context-pinned Qwen3-30B-A3B variant for OpenCode.\n# Build it with:\n#   ollama create qwen-opencode -f models/Modelfile.qwen-opencode\n# (The setup scripts build this automatically when WITH_QWEN=1, and\n# rewrite the FROM line below to the tag they pulled, so a non-default\n# Qwen tag pins itself rather than the default tag named below.)\n# Same reasoning as the Flint Modelfile: bake the context in so the\n# runtime default cannot silently shrink it. 131072 is both the kit\n# default and this model's documented ceiling: Qwen3-30B-A3B is a\n# 32,768-native model that reaches 131,072 with YaRN (Qwen model card\n# and technical report). Do not raise Qwen past it; the setup scripts\n# keep Qwen on QWEN_NUM_CTX (default 131072) even when NUM_CTX raises\n# the Flint pin higher.\n\nFROM qwen3:30b-a3b\n\nPARAMETER num_ctx 131072\nPARAMETER num_predict 8192\n"
CONFIG_TEMPLATE_JSON = '{\n  "$schema": "https://opencode.ai/config.json",\n  "model": "ollama/flint-opencode:latest",\n  "provider": {\n    "ollama": {\n      "models": {\n        "flint-opencode:latest": {\n          "limit": {\n            "context": 131072,\n            "output": 32768\n          },\n          "name": "Flint 40B, context-pinned 128K",\n          "tool_call": true\n        },\n        "qwen-opencode:latest": {\n          "limit": {\n            "context": 131072,\n            "output": 8192\n          },\n          "name": "Qwen3 30B A3B, context-pinned 128K",\n          "tool_call": true\n        }\n      },\n      "name": "Ollama (local)",\n      "npm": "@ai-sdk/openai-compatible",\n      "options": {\n        "baseURL": "http://localhost:11434/v1"\n      },\n      "whitelist": [\n        "flint-opencode:latest",\n        "qwen-opencode:latest"\n      ]\n    },\n    "headroom": {\n      "models": {\n        "flint-opencode:latest": {\n          "limit": {\n            "context": 131072,\n            "output": 32768\n          },\n          "name": "Flint 40B, context-pinned 128K, via Headroom",\n          "tool_call": true\n        },\n        "qwen-opencode:latest": {\n          "limit": {\n            "context": 131072,\n            "output": 8192\n          },\n          "name": "Qwen3 30B A3B, context-pinned 128K, via Headroom",\n          "tool_call": true\n        }\n      },\n      "name": "Headroom proxy (local)",\n      "npm": "@ai-sdk/openai-compatible",\n      "options": {\n        "baseURL": "http://127.0.0.1:8787/v1"\n      },\n      "whitelist": [\n        "flint-opencode:latest",\n        "qwen-opencode:latest"\n      ]\n    }\n  }\n}\n'

STEP_ORDER = ["W1", "W2", "W3", "W4", "W5", "W6", "B1", "B2",
              "L1", "L2", "L3", "L4", "C1", "C2", "C3", "C4"]

STEP_PLAN = {
    "W1": ("Ollama installed via winget",
           "ollama --version parses and is at least 0.40.8"),
    "W2": ("Server env vars set (User scope)",
           "OLLAMA_MAX_LOADED_MODELS=1 and OLLAMA_CONTEXT_LENGTH match the chosen context"),
    "W3": ("Ollama tray restarted",
           "the server answers /api/version (restart only when W2 changed something)"),
    "W4": ("Base models pulled",
           "each chosen tag is present in the server's model list"),
    "W5": ("Context-pinned variants built",
           "/api/show reports the pinned num_ctx for each variant"),
    "W6": ("Windows-side verify",
           "the first chosen variant answers a hello round trip; residency is recorded"),
    "B1": (".wslconfig mirrored networking",
           "exactly one managed block sits under [wsl2] with networkingMode=mirrored"),
    "B2": ("WSL restarted",
           "a restart is pending only when B1 changed the file this run"),
    "L1": ("WSL distro detected",
           "wsl -l -q lists the chosen distro (default Ubuntu)"),
    "L2": ("OpenCode present in the distro",
           "the canonical binary ~/.opencode/bin/opencode answers by absolute path, and a login shell finds it on PATH"),
    "L3": ("Kit config installed in the distro",
           "~/.config/opencode/opencode.json matches the rendered template byte for byte"),
    "L4": ("Client-side smoke from WSL",
           "from inside the distro: the API answers, the variant is listed, its num_ctx is pinned"),
    "C1": ("ComfyUI portable installed",
           "the pinned v0.46.0 portable is extracted and its launcher is present"),
    "C2": ("Z-Image-Turbo models present",
           "the three model files sit in their models subfolders at pinned sizes"),
    "C3": ("ComfyUI Gate 1: GPU visible",
           "/system_stats reports a Radeon device with a large VRAM total, not CPU-only"),
    "C4": ("ComfyUI Gate 2: generation smoke",
           "the embedded Z-Image-Turbo API workflow produces a real output image"),
}


class StepError(Exception):
    """A step failed in a way the user can act on."""


class CmdResult:
    def __init__(self, rc, out=b"", err=b""):
        self.rc = rc
        self.out = out
        self.err = err

    def text(self):
        return self.out.decode("utf-8", errors="replace")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ctx_label(n: int) -> str:
    return f"{n // 1024}K" if n % 1024 == 0 else str(n)


def parse_version(text: str):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def normalize_tag(name: str) -> str:
    return name if ":" in name else name + ":latest"


def write_bytes_exact(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    write_bytes_exact(tmp, data)
    os.replace(tmp, path)


# ----------------------------------------------------------------------
# Platform seam. The Manager only ever touches the machine through
# these methods. WindowsPlatform is the real one; the test suite
# substitutes a fake with the same contract.
# ----------------------------------------------------------------------

class Platform:
    name = "abstract"

    def is_windows(self) -> bool:
        raise NotImplementedError

    def windows_build(self):
        raise NotImplementedError

    def now(self) -> datetime:
        return datetime.now()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def free_disk_bytes(self, path: Path) -> int:
        raise NotImplementedError

    def network_available(self) -> bool:
        raise NotImplementedError

    def default_install_root(self) -> Path:
        raise NotImplementedError

    def user_profile_dir(self) -> Path:
        raise NotImplementedError

    def get_user_env(self, name: str):
        raise NotImplementedError

    def set_user_env(self, name: str, value: str) -> None:
        raise NotImplementedError

    def unset_user_env(self, name: str) -> None:
        raise NotImplementedError

    def run(self, argv, timeout=None, input_bytes=None) -> CmdResult:
        raise NotImplementedError

    def find_on_path(self, name: str):
        raise NotImplementedError

    def api_probe(self) -> str:
        """One of: 'ollama', 'other', 'free' (nothing answering)."""
        raise NotImplementedError

    def api_get(self, path: str, timeout: int = 10):
        raise NotImplementedError

    def api_post(self, path: str, payload: dict, timeout: int = 10):
        raise NotImplementedError

    def restart_ollama_tray(self) -> None:
        raise NotImplementedError

    def wsl_distros(self):
        """List of distro names, or None when wsl.exe is unusable."""
        raise NotImplementedError

    def wsl_run(self, distro: str, argv, timeout=None, input_bytes=None) -> CmdResult:
        raise NotImplementedError

    def wsl_home(self, distro: str):
        raise NotImplementedError

    def wsl_read_file(self, distro: str, path: str):
        raise NotImplementedError

    def wsl_write_file(self, distro: str, path: str, data: bytes) -> None:
        raise NotImplementedError

    def wsl_file_exists(self, distro: str, path: str) -> bool:
        raise NotImplementedError

    def wsl_copy_file(self, distro: str, src: str, dst: str) -> bool:
        raise NotImplementedError

    def wsl_api_get(self, distro: str, path: str):
        raise NotImplementedError

    def wsl_api_post(self, distro: str, path: str, payload: dict):
        raise NotImplementedError


    # ----- ComfyUI seam (fold-in, 0.2.0) -----

    def default_comfy_root(self) -> Path:
        raise NotImplementedError

    def comfy_probe(self) -> str:
        """One of: 'comfy', 'other', 'free' (nothing answering)."""
        raise NotImplementedError

    def comfy_get(self, path: str, timeout: int = 10):
        raise NotImplementedError

    def comfy_post(self, path: str, payload: dict, timeout: int = 10):
        raise NotImplementedError

    def download_file(self, url: str, dest: Path, expected_size: int,
                      expected_sha256: str) -> None:
        """Download url to dest, verifying size and SHA-256 before
        the file lands at dest. Raises StepError on any failure;
        a partial or mismatched file never reaches dest."""
        raise NotImplementedError

    def extract_archive(self, archive: Path, dest_dir: Path) -> None:
        """Extract a .7z archive into dest_dir. Raises StepError."""
        raise NotImplementedError

    def start_detached(self, argv, cwd=None) -> None:
        raise NotImplementedError

    def stop_process_by_path(self, fragment: str) -> int:
        """Stop processes whose executable path contains fragment.
        Returns how many were stopped."""
        raise NotImplementedError

    def port_in_use(self, port: int) -> bool:
        raise NotImplementedError


class WindowsPlatform(Platform):
    name = "windows"

    def is_windows(self) -> bool:
        return sys.platform == "win32"

    def windows_build(self):
        try:
            return sys.getwindowsversion().build
        except Exception:
            return None

    def free_disk_bytes(self, path: Path) -> int:
        probe = Path(path)
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        return shutil.disk_usage(str(probe)).free

    def network_available(self) -> bool:
        for host in ("ollama.com", "github.com"):
            try:
                with socket.create_connection((host, 443), timeout=5):
                    return True
            except OSError:
                continue
        return False

    def default_install_root(self) -> Path:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "LocalModelsKit"
        return Path.home() / "AppData" / "Local" / "LocalModelsKit"

    def user_profile_dir(self) -> Path:
        profile = os.environ.get("USERPROFILE")
        return Path(profile) if profile else Path.home()

    # User environment variables live in HKCU\Environment. Reads and
    # writes go through winreg; a WM_SETTINGCHANGE broadcast nudges
    # newly started processes to pick changes up.
    def _env_key(self, access):
        import winreg
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, access)

    def get_user_env(self, name: str):
        import winreg
        try:
            with self._env_key(winreg.KEY_READ) as key:
                value, _kind = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None
        except OSError:
            return None

    def set_user_env(self, name: str, value: str) -> None:
        import winreg
        with self._env_key(winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        self._broadcast_env_change()

    def unset_user_env(self, name: str) -> None:
        import winreg
        try:
            with self._env_key(winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
        self._broadcast_env_change()

    def _broadcast_env_change(self) -> None:
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                0x0002, 5000, None)
        except Exception:
            pass  # best effort; a fresh login always sees the values

    def run(self, argv, timeout=None, input_bytes=None) -> CmdResult:
        try:
            proc = subprocess.run(
                [str(a) for a in argv], input=input_bytes,
                capture_output=True, timeout=timeout)
            return CmdResult(proc.returncode, proc.stdout, proc.stderr)
        except FileNotFoundError:
            return CmdResult(127, b"", f"not found: {argv[0]}".encode())
        except subprocess.TimeoutExpired:
            return CmdResult(124, b"", b"timed out")

    def find_on_path(self, name: str):
        return shutil.which(name)

    def _api_request(self, method: str, path: str, payload=None, timeout=10):
        url = OLLAMA_API + path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def api_probe(self) -> str:
        try:
            body = self._api_request("GET", "/api/version", timeout=5)
            return "ollama" if isinstance(body, dict) and "version" in body else "other"
        except urllib.error.HTTPError:
            return "other"
        except Exception:
            return "free"

    def api_get(self, path: str, timeout: int = 10):
        try:
            return self._api_request("GET", path, timeout=timeout)
        except Exception:
            return None

    def api_post(self, path: str, payload: dict, timeout: int = 10):
        try:
            return self._api_request("POST", path, payload, timeout=timeout)
        except Exception:
            return None

    def restart_ollama_tray(self) -> None:
        # Best effort mirror of the guide's manual step (quit the tray
        # app, relaunch it). Gate 2 on the target hardware is where this earns
        # or loses its keep; W3 verifies by polling /api/version.
        self.run(["taskkill", "/IM", "ollama app.exe", "/F"], timeout=30)
        local = os.environ.get("LOCALAPPDATA", "")
        app = Path(local) / "Programs" / "Ollama" / "ollama app.exe"
        if app.exists():
            try:
                subprocess.Popen([str(app)],
                                 creationflags=0x00000008,  # DETACHED_PROCESS
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except OSError:
                pass

    def wsl_distros(self):
        result = self.run(["wsl", "-l", "-q"], timeout=30)
        if result.rc != 0:
            return None
        raw = result.out
        for encoding in ("utf-16-le", "utf-8"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        names = [line.strip().strip("\x00") for line in text.splitlines()]
        return [n for n in names if n]

    def wsl_run(self, distro: str, argv, timeout=None, input_bytes=None) -> CmdResult:
        return self.run(["wsl", "-d", distro, "--"] + list(argv),
                        timeout=timeout, input_bytes=input_bytes)

    def wsl_home(self, distro: str):
        result = self.wsl_run(distro, ["bash", "-lc", 'printf %s "$HOME"'], timeout=30)
        if result.rc != 0:
            return None
        home = result.text().strip()
        return home or None

    def wsl_read_file(self, distro: str, path: str):
        result = self.wsl_run(
            distro, ["bash", "-c", f"base64 -w 0 -- {shlex.quote(path)}"], timeout=30)
        if result.rc != 0:
            return None
        try:
            return base64.b64decode(result.out.strip(), validate=True)
        except Exception:
            return None

    def wsl_write_file(self, distro: str, path: str, data: bytes) -> None:
        parent = path.rsplit("/", 1)[0]
        if parent:
            mk = self.wsl_run(distro, ["bash", "-c", f"mkdir -p -- {shlex.quote(parent)}"],
                              timeout=30)
            if mk.rc != 0:
                raise StepError(f"could not create the directory for {path} in {distro}")
        result = self.wsl_run(
            distro, ["bash", "-c", f"base64 -d > {shlex.quote(path)}"],
            timeout=30, input_bytes=base64.b64encode(data))
        if result.rc != 0:
            raise StepError(f"could not write {path} in {distro}: {result.err.decode('utf-8', errors='replace').strip()}")

    def wsl_file_exists(self, distro: str, path: str) -> bool:
        result = self.wsl_run(distro, ["bash", "-c", f"test -f {shlex.quote(path)}"],
                              timeout=30)
        return result.rc == 0

    def wsl_copy_file(self, distro: str, src: str, dst: str) -> bool:
        result = self.wsl_run(
            distro, ["bash", "-c", f"cp -- {shlex.quote(src)} {shlex.quote(dst)}"],
            timeout=30)
        return result.rc == 0

    # API probes executed inside the distro (python3 is a documented
    # prerequisite there, Part 3 Step 1 of the guide). The script
    # prints the response body on stdout; any failure exits nonzero.
    _WSL_API_SCRIPT = (
        "import json, sys, urllib.request\n"
        "url, payload = sys.argv[1], sys.argv[2]\n"
        "data = payload.encode() if payload else None\n"
        "req = urllib.request.Request(url, data=data, method='POST' if data else 'GET')\n"
        "if data: req.add_header('Content-Type', 'application/json')\n"
        "sys.stdout.write(urllib.request.urlopen(req, timeout=15).read().decode())\n"
    )

    def _wsl_api(self, distro: str, path: str, payload):
        arg = json.dumps(payload) if payload is not None else ""
        result = self.wsl_run(
            distro, ["python3", "-c", self._WSL_API_SCRIPT, OLLAMA_API + path, arg],
            timeout=40)
        if result.rc != 0:
            return None
        try:
            return json.loads(result.out.decode("utf-8"))
        except Exception:
            return None

    def wsl_api_get(self, distro: str, path: str):
        return self._wsl_api(distro, path, None)

    def wsl_api_post(self, distro: str, path: str, payload: dict):
        return self._wsl_api(distro, path, payload)


    # ----- ComfyUI seam: real implementations -----
    #
    # Nothing in this section has run on a real Windows machine yet;
    # Gate 2 on the target hardware is its first contact, same status as the
    # rest of this class had in Phase 1.

    def default_comfy_root(self) -> Path:
        # The location the manual ComfyUI flow was validated at on
        # the target machine: short, outside OneDrive, easy to find.
        return Path("C:\\ComfyUI")

    def _comfy_request(self, method: str, path: str, payload=None, timeout=10):
        url = COMFY_API + path
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def comfy_probe(self) -> str:
        try:
            body = self._comfy_request("GET", "/system_stats", timeout=5)
            return "comfy" if isinstance(body, dict) and "devices" in body \
                else "other"
        except urllib.error.HTTPError:
            return "other"
        except Exception:
            return "free"

    def comfy_get(self, path: str, timeout: int = 10):
        try:
            return self._comfy_request("GET", path, timeout=timeout)
        except Exception:
            return None

    def comfy_post(self, path: str, payload: dict, timeout: int = 10):
        try:
            return self._comfy_request("POST", path, payload, timeout=timeout)
        except Exception:
            return None

    def download_file(self, url: str, dest: Path, expected_size: int,
                      expected_sha256: str) -> None:
        # Stream to a .part sibling, hash as we go, and only rename
        # into place when size and hash both verify. A failed or
        # truncated download deletes the .part and raises, so repair
        # can simply try again.
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        digest = hashlib.sha256()
        written = 0
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "local-models-kit-manager"})
            with urllib.request.urlopen(req, timeout=120) as resp, \
                    part.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
        except Exception as exc:
            part.unlink(missing_ok=True)
            raise StepError(f"download of {url} failed: {exc}")
        if written != expected_size:
            part.unlink(missing_ok=True)
            raise StepError(
                f"download of {dest.name} is {written} bytes, expected "
                f"{expected_size}; the partial file was deleted")
        actual = digest.hexdigest()
        if actual != expected_sha256:
            part.unlink(missing_ok=True)
            raise StepError(
                f"SHA-256 of downloaded {dest.name} is {actual}, expected "
                f"{expected_sha256}; the file was deleted, not installed")
        os.replace(part, dest)

    def extract_archive(self, archive: Path, dest_dir: Path) -> None:
        # Python's standard library has no 7z reader. The tar.exe
        # bundled with Windows 11 is bsdtar (libarchive) and extracts
        # .7z with no extra software (Microsoft's tar documentation).
        if not (self.find_on_path("tar.exe") or self.find_on_path("tar")):
            raise StepError(
                "tar.exe was not found on PATH; it ships with Windows 11 "
                "and is how the manager extracts the ComfyUI portable "
                "archive. Restore it (or extract the archive by hand "
                "into the ComfyUI root) and re-run")
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        result = self.run(["tar.exe", "-xf", str(archive), "-C", str(dest_dir)],
                          timeout=1800)
        if result.rc != 0:
            raise StepError(
                "tar.exe could not extract "
                f"{archive}: " + result.err.decode("utf-8", errors="replace").strip())

    def start_detached(self, argv, cwd=None) -> None:
        try:
            subprocess.Popen(
                [str(a) for a in argv],
                cwd=str(cwd) if cwd else None,
                creationflags=0x00000008 | 0x00000200,  # DETACHED | NEW_PROCESS_GROUP
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise StepError(f"could not start {argv[0]}: {exc}")

    def stop_process_by_path(self, fragment: str) -> int:
        # Scoped stop: enumerate processes with the Toolhelp snapshot
        # and terminate only those whose full image path contains
        # the fragment (the kit's ComfyUI portable directory). No
        # name-based kill: an unrelated python.exe is never touched.
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD),
                        ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", wintypes.LONG),
                        ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]

        kernel32 = ctypes.windll.kernel32
        needle = fragment.lower()
        stopped = 0
        snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snap == -1:
            return 0
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                pid = entry.th32ProcessID
                handle = kernel32.OpenProcess(
                    0x1000 | 0x0001, False, pid)  # QUERY_LIMITED_INFORMATION | TERMINATE
                if handle:
                    try:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(len(buf))
                        if kernel32.QueryFullProcessImageNameW(
                                handle, 0, buf, ctypes.byref(size)):
                            if needle in buf.value.lower():
                                if kernel32.TerminateProcess(handle, 0):
                                    stopped += 1
                    finally:
                        kernel32.CloseHandle(handle)
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        return stopped

    def port_in_use(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except OSError:
            return False


def build_platform():
    """The real platform on Windows; None anywhere else."""
    if sys.platform == "win32":
        return WindowsPlatform()
    return None


# ----------------------------------------------------------------------
# Template loading. Running from a repo checkout (Tier 1) prefers the
# live kit files; a compiled manager (Tier 2 and 3) falls back to the
# embedded copies above. Both routes render identically because the
# embedded copies are the repo files, and a test keeps them honest.
# ----------------------------------------------------------------------

def kit_root_candidates():
    roots = []
    env = os.environ.get("LOCAL_MODELS_KIT_SOURCE_ROOT")
    if env:
        roots.append(Path(env))
    here = Path(__file__).resolve()
    # installer/manager/<this file> -> the repo root is two levels up
    roots.append(here.parent.parent.parent)
    roots.append(Path.cwd())
    return roots


def load_template_text(relpath: str, embedded: str) -> str:
    for root in kit_root_candidates():
        candidate = root / relpath
        try:
            if candidate.is_file():
                return candidate.read_bytes().decode("utf-8")
        except OSError:
            continue
    return embedded


def render_modelfile(template_text: str, from_tag: str, num_ctx: int) -> bytes:
    text = re.sub(r"^FROM .*", f"FROM {from_tag}", template_text, flags=re.M)
    text = re.sub(r"^PARAMETER num_ctx .*", f"PARAMETER num_ctx {num_ctx}",
                  text, flags=re.M)
    return text.encode("utf-8")


def render_config(num_ctx: int, qwen_num_ctx: int = QWEN_NUM_CTX,
                  with_flint: bool = True, with_qwen: bool = True) -> bytes:
    """The installed OpenCode config: the template with each model's
    context limit and picker label written from the chosen pins,
    exactly as setup.ps1 and setup.sh render it. Qwen keys always get
    qwen_num_ctx, so raising Flint never drags Qwen past its ceiling,
    and each provider's whitelist exactly matches its declared models.

    Models the install leaves out are removed from every provider,
    models and whitelist alike, and the default model becomes the
    first chosen variant: the config never advertises a model the
    install did not pull (the 2026-10-24 P0 hygiene rule).
    """
    template = load_template_text("config/opencode.json", CONFIG_TEMPLATE_JSON)
    cfg = json.loads(template)
    families = []
    if with_flint:
        families.append("flint")
    if with_qwen:
        families.append("qwen")
    for provider in cfg.get("provider", {}).values():
        models = provider.get("models", {})
        for key in list(models):
            if not any(key.startswith(family) for family in families):
                del models[key]
        for key, model in models.items():
            ctx = qwen_num_ctx if key.startswith("qwen") else num_ctx
            model.setdefault("limit", {})["context"] = ctx
            if "name" in model:
                model["name"] = model["name"].replace("128K", ctx_label(ctx))
        provider["whitelist"] = list(models.keys())
    primary = FLINT_VARIANT if with_flint else QWEN_VARIANT
    cfg["model"] = f"ollama/{primary}:latest"
    return (json.dumps(cfg, indent=2) + "\n").encode("utf-8")


class Manager:
    def __init__(self, root: Path, platform: Platform, out=print):
        self.root = Path(root)
        self.platform = platform
        self.out = out
        self.state_path = self.root / "state.json"
        self.log_path = self.root / "logs" / "manager.log"
        self.state = None
        self.retry_hint = "local-models-kit install"

    # ---------- output and state ----------

    def log(self, line: str) -> None:
        stamp = self.platform.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(f"{stamp} {line}\n")
        except OSError:
            pass  # logging must never take the install down
        self.out(line)

    def say(self, verb: str, step: str, detail: str = "") -> None:
        suffix = f" ({detail})" if detail else ""
        self.log(f"{verb} {step}{suffix}")

    def load_state(self):
        if self.state is not None:
            return self.state
        if self.state_path.exists():
            try:
                self.state = json.loads(self.state_path.read_bytes().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise StepError(
                    f"the state file at {self.state_path} is unreadable; "
                    "move it aside and re-run install to start fresh")
        else:
            self.state = {
                "kit_version": KIT_VERSION,
                "manager_version": MANAGER_VERSION,
                "created": self.platform.now().isoformat(timespec="seconds"),
                "choices": {},
                "steps": {},
                "env": {},
                "models": {},
                "ollama": {},
                "wsl": {},
                "wslconfig": {},
                "opencode_config": {},
                "comfyui": {},
            }
        return self.state

    def save_state(self) -> None:
        self.state["updated"] = self.platform.now().isoformat(timespec="seconds")
        data = (json.dumps(self.state, indent=2, sort_keys=True) + "\n").encode("utf-8")
        atomic_write_bytes(self.state_path, data)

    def _maybe_fail(self, step: str) -> None:
        # Test hook, same pattern as the spike: LOCAL_MODELS_KIT_FAIL_STEP=W4
        # makes that step raise once reached, to prove resume works.
        if os.environ.get("LOCAL_MODELS_KIT_FAIL_STEP") == step:
            raise StepError(f"injected failure at step {step} (test hook)")

    # ---------- choices ----------

    def resolve_choices(self, with_flint=None, with_qwen=None, num_ctx=None,
                        distro=None, with_comfyui=None,
                        comfy_root=None) -> dict:
        """CLI flags beat the recorded choices, which beat env and
        defaults, so re-running install resumes with the same shape.
        The full stack (Flint, Qwen, ComfyUI) is the default shape;
        the --no-* flags opt a component out, and the --with-* flags
        are the way back in when recorded state holds an opt-out."""
        state = self.load_state()
        recorded = state.get("choices", {})

        def pick(flag, key, env_name, default):
            if flag is not None:
                return flag
            if key in recorded:
                return recorded[key]
            if env_name:
                env = os.environ.get(env_name)
                if env not in (None, ""):
                    return env
            return default

        chosen_flint = pick(with_flint, "with_flint", "WITH_FLINT", True)
        if isinstance(chosen_flint, str):
            chosen_flint = chosen_flint == "1"
        chosen_qwen = pick(with_qwen, "with_qwen", "WITH_QWEN", True)
        if isinstance(chosen_qwen, str):
            chosen_qwen = chosen_qwen == "1"
        chosen_ctx = pick(num_ctx, "num_ctx", "NUM_CTX", DEFAULT_NUM_CTX)
        chosen_ctx = int(chosen_ctx)
        if not (1024 <= chosen_ctx <= MAX_NUM_CTX):
            raise StepError(
                f"NUM_CTX {chosen_ctx} is out of range; the kit supports "
                f"1024 to {MAX_NUM_CTX} (Flint's ceiling)")
        chosen_distro = pick(distro, "distro", None, None)
        chosen_comfy = pick(with_comfyui, "with_comfyui", "WITH_COMFYUI", True)
        if isinstance(chosen_comfy, str):
            chosen_comfy = chosen_comfy == "1"
        chosen_comfy_root = pick(comfy_root, "comfy_root", None, None)
        choices = {
            "with_flint": bool(chosen_flint),
            "with_qwen": bool(chosen_qwen),
            "num_ctx": chosen_ctx,
            "qwen_num_ctx": QWEN_NUM_CTX,
            "distro": chosen_distro,
            "with_comfyui": bool(chosen_comfy),
            "comfy_root": str(chosen_comfy_root) if chosen_comfy_root else None,
        }
        if not choices["with_flint"] and not choices["with_qwen"]:
            raise StepError(
                "no models chosen: --no-flint and --no-qwen together "
                "leave the kit with no model to serve; drop one of "
                "the two flags")
        state["choices"] = choices
        return choices

    def desired_models(self, choices: dict):
        """(base tags to pull, [(variant, from tag, ctx, template)])"""
        pulls = []
        builds = []
        if choices.get("with_flint", True):
            pulls.append(FLINT_BASE_TAG)
            builds.append((FLINT_VARIANT, FLINT_BASE_TAG,
                           choices.get("num_ctx", DEFAULT_NUM_CTX),
                           "flint"))
        if choices.get("with_qwen", True):
            pulls.append(QWEN_BASE_TAG)
            builds.append((QWEN_VARIANT, QWEN_BASE_TAG, QWEN_NUM_CTX,
                           "qwen"))
        return pulls, builds

    def _primary_variant(self, choices: dict):
        """(variant, its pinned num_ctx) for the first chosen model:
        Flint when chosen, else Qwen. W6 and L4 verify against it,
        and the rendered config defaults to it."""
        _pulls, builds = self.desired_models(choices)
        if not builds:
            return FLINT_VARIANT, choices.get("num_ctx", DEFAULT_NUM_CTX)
        variant, _from_tag, ctx, _family = builds[0]
        return variant, ctx

    # ---------- preflight ----------

    def preflight(self, choices: dict):
        """All blockers at once, each with its fix. Changes nothing."""
        p = self.platform
        blockers = []

        build = p.windows_build()
        if build is not None and build < MIN_WINDOWS_BUILD:
            blockers.append((
                "Windows build",
                f"build {build} is older than {MIN_WINDOWS_BUILD}",
                "update to Windows 11 22H2 or later; mirrored networking "
                "does not exist before it (the guide's NAT fallback is a "
                "manual path, not an automated one)"))

        pulls, _builds = self.desired_models(choices)
        needed = sum(MODEL_BYTES[t] for t in pulls) + SPARE_BYTES
        free = p.free_disk_bytes(p.user_profile_dir())
        if free < needed:
            blockers.append((
                "Disk space",
                f"{free // 1_000_000_000} GB free, {needed // 1_000_000_000} GB needed "
                f"for the chosen models plus 10 GB spare",
                "free space on the drive holding your user profile "
                "(the models live in .ollama there), or leave a model "
                "out with --no-flint or --no-qwen"))

        distros = p.wsl_distros()
        if distros is None:
            blockers.append((
                "WSL",
                "wsl.exe did not answer; WSL is missing or broken",
                "run: wsl --install -d Ubuntu (admin; Windows may ask "
                "for a reboot), then launch Ubuntu once and create your user"))
        elif not distros:
            blockers.append((
                "WSL distro",
                "WSL is present but no distribution is installed",
                "run: wsl --install -d Ubuntu, then launch Ubuntu once "
                "and create your user"))
        elif choices["distro"] and choices["distro"] not in distros:
            blockers.append((
                "WSL distro",
                f"distro {choices['distro']!r} is not installed "
                f"(found: {', '.join(distros)})",
                f"install it with: wsl --install -d {choices['distro']}, "
                "or re-run without --distro"))

        if not p.network_available():
            blockers.append((
                "Network",
                "no route to ollama.com or github.com",
                "the install downloads Ollama (winget), two models, and "
                "OpenCode; connect to the internet and re-run"))

        if p.api_probe() == "other":
            blockers.append((
                "Ollama endpoint",
                "something answers on localhost:11434 but it is not Ollama",
                "stop the program holding port 11434, or fix that "
                "install; the kit will not share the port"))


        if choices.get("with_comfyui"):
            comfy_root = self._comfy_root()
            comfy_needed = COMFY_ARCHIVE_SIZE + COMFY_MODELS_BYTES + SPARE_BYTES
            comfy_free = p.free_disk_bytes(comfy_root)
            if comfy_free < comfy_needed:
                blockers.append((
                    "Disk space (ComfyUI)",
                    f"{comfy_free // 1_000_000_000} GB free at {comfy_root}, "
                    f"{comfy_needed // 1_000_000_000} GB needed for the "
                    "portable archive, the Z-Image-Turbo models, plus "
                    "10 GB spare",
                    "free space on the ComfyUI drive, or leave "
                    "ComfyUI out with --no-comfyui"))
            if p.comfy_probe() == "other":
                blockers.append((
                    "ComfyUI endpoint",
                    "something answers on port 8188 but it is not ComfyUI",
                    "stop the program holding port 8188; the kit will "
                    "not share the port"))

        return blockers

    # ---------- step runner ----------

    def run_step(self, step_id: str, repair: bool = False) -> str:
        state = self.load_state()
        check = getattr(self, f"check_{step_id.lower()}")
        apply_step = getattr(self, f"apply_{step_id.lower()}")
        status, detail = check()
        if status == "ok":
            self.say("SKIP", step_id, detail or "already correct")
            state["steps"][step_id] = {
                "status": "ok", "detail": detail,
                "at": self.platform.now().isoformat(timespec="seconds")}
            self.save_state()
            return "skip"
        result_detail = apply_step()
        status, detail = check()
        if status != "ok":
            raise StepError(
                f"step {step_id} did not verify after acting: {detail}")
        self.say("FIX" if repair else "DONE", step_id, result_detail or detail)
        state["steps"][step_id] = {
            "status": "done", "detail": result_detail or detail,
            "at": self.platform.now().isoformat(timespec="seconds")}
        self.save_state()
        return "done"

    def run_all_steps(self, choices: dict, repair: bool = False) -> None:
        state = self.load_state()
        for step_id in STEP_ORDER:
            if step_id.startswith("C") and not choices.get("with_comfyui"):
                self.say("SKIP", step_id,
                         "ComfyUI opted out for this install; it is in "
                         "the default install, add it back with "
                         "install --with-comfyui")
                state["steps"][step_id] = {
                    "status": "skipped",
                    "detail": "ComfyUI opted out",
                    "at": self.platform.now().isoformat(timespec="seconds")}
                self.save_state()
                continue
            self.run_step(step_id, repair=repair)


    # ---------- shared probes ----------

    def _ollama_version(self):
        result = self.platform.run(["ollama", "--version"], timeout=30)
        if result.rc != 0:
            return None
        return parse_version(result.text())

    def _server_tags(self):
        """Normalized tag names the server reports, or None when no
        probe can say (server down and the CLI cannot list either)."""
        body = self.platform.api_get("/api/tags")
        if isinstance(body, dict) and isinstance(body.get("models"), list):
            return {normalize_tag(m.get("name", "")) for m in body["models"]}
        result = self.platform.run(["ollama", "list"], timeout=30)
        if result.rc == 0:
            names = set()
            for line in result.text().splitlines()[1:]:
                parts = line.split()
                if parts:
                    names.add(normalize_tag(parts[0]))
            return names
        return None

    def _variant_num_ctx(self, variant: str):
        body = self.platform.api_post("/api/show", {"name": normalize_tag(variant)},
                                      timeout=30)
        if not isinstance(body, dict):
            return None
        m = re.search(r"num_ctx\s+(\d+)", str(body.get("parameters", "")))
        return int(m.group(1)) if m else None

    def _hello_round_trip(self, variant: str):
        body = self.platform.api_post(
            "/v1/chat/completions",
            {"model": normalize_tag(variant),
             "messages": [{"role": "user",
                           "content": "Reply with exactly this word: ready"}],
             "stream": False},
            timeout=300)
        try:
            content = body["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            return False, "no readable reply"
        return ("ready" in content.lower()), content.strip()

    # ---------- W1: Ollama installed ----------

    def check_w1(self):
        version = self._ollama_version()
        if version is None:
            return "missing", "ollama is not on PATH"
        if version < MIN_OLLAMA:
            return "drifted", (f"ollama {'.'.join(map(str, version))} is older "
                               f"than {'.'.join(map(str, MIN_OLLAMA))}")
        return "ok", f"ollama {'.'.join(map(str, version))}"

    def apply_w1(self):
        self._maybe_fail("W1")
        was_missing = self._ollama_version() is None
        result = self.platform.run(
            ["winget", "install", "--id", "Ollama.Ollama", "--exact",
             "--accept-package-agreements", "--accept-source-agreements"],
            timeout=1800)
        if result.rc != 0:
            raise StepError(
                "winget could not install Ollama: "
                + result.err.decode("utf-8", errors="replace").strip()
                + " (or install it from https://ollama.com/download and re-run)")
        version = self._ollama_version()
        if version is None:
            raise StepError(
                "winget reports Ollama installed, but this process still "
                "cannot see ollama on PATH; open a new terminal and re-run "
                "install (installers update PATH for new processes)")
        self.load_state()["ollama"] = {
            "version": ".".join(map(str, version)),
            "installed_by_kit": was_missing}
        return f"installed ollama {'.'.join(map(str, version))} via winget"

    # ---------- W2: server env vars ----------

    def _desired_env(self, choices: dict):
        return {ENV_MAX_LOADED: "1",
                ENV_CONTEXT_LENGTH: str(choices["num_ctx"])}

    def check_w2(self):
        choices = self.load_state()["choices"]
        for name, want in self._desired_env(choices).items():
            current = self.platform.get_user_env(name)
            if current is None:
                return "missing", f"{name} is not set"
            if current != want:
                return "drifted", f"{name} is {current!r}, want {want!r}"
        return "ok", "both server env vars match"

    def apply_w2(self):
        self._maybe_fail("W2")
        state = self.load_state()
        choices = state["choices"]
        recorded = state.setdefault("env", {})
        changed = []
        for name, want in self._desired_env(choices).items():
            current = self.platform.get_user_env(name)
            if current != want:
                if name not in recorded:
                    recorded[name] = {"previous": current, "value": want}
                else:
                    recorded[name]["value"] = want
                self.platform.set_user_env(name, want)
                changed.append(name)
        if changed:
            state["tray_restart_pending"] = True
        return "set " + ", ".join(changed) if changed else "no change"

    # ---------- W3: tray restarted, server answers ----------

    def check_w3(self):
        state = self.load_state()
        if self.platform.api_probe() != "ollama":
            return "missing", "the Ollama server does not answer /api/version"
        if state.get("tray_restart_pending"):
            return "drifted", "env vars changed; the running server has not picked them up"
        return "ok", "server answers and no restart is pending"

    def apply_w3(self):
        self._maybe_fail("W3")
        state = self.load_state()
        self.platform.restart_ollama_tray()
        for _attempt in range(30):
            if self.platform.api_probe() == "ollama":
                state["tray_restart_pending"] = False
                body = self.platform.api_get("/api/version")
                if isinstance(body, dict):
                    state.setdefault("ollama", {})["server_version"] = body.get("version")
                return "tray restarted; server answers /api/version"
            self.platform.sleep(2)
        raise StepError(
            "the Ollama server did not answer after a tray restart; "
            "start Ollama from the Start menu, then re-run install")

    # ---------- W4: base models pulled ----------

    def check_w4(self):
        choices = self.load_state()["choices"]
        pulls, _builds = self.desired_models(choices)
        tags = self._server_tags()
        if tags is None:
            return "missing", "cannot list models (server and CLI both silent)"
        missing = [t for t in pulls if normalize_tag(t) not in tags]
        if missing:
            return "missing", "not pulled: " + ", ".join(missing)
        return "ok", "pulled: " + ", ".join(pulls)

    def apply_w4(self):
        self._maybe_fail("W4")
        choices = self.load_state()["choices"]
        pulls, _builds = self.desired_models(choices)
        tags = self._server_tags() or set()
        done = []
        for tag in pulls:
            if normalize_tag(tag) in tags:
                continue
            last_err = ""
            for attempt in range(1, 4):
                result = self.platform.run(["ollama", "pull", tag], timeout=3600)
                if result.rc == 0:
                    break
                last_err = result.err.decode("utf-8", errors="replace").strip()
                if attempt < 3:
                    self.log(f"pull of {tag} failed (attempt {attempt}); "
                             f"retrying, ollama resumes partial downloads")
                    self.platform.sleep(5 * attempt)
            else:
                raise StepError(f"ollama pull {tag} failed after 3 attempts: {last_err}")
            done.append(tag)
        state = self.load_state()
        state.setdefault("models", {}).update(
            {normalize_tag(t): {"pulled": True} for t in pulls})
        return "pulled " + ", ".join(done) if done else "already present"

    # ---------- W5: pinned variants built ----------

    def check_w5(self):
        choices = self.load_state()["choices"]
        _pulls, builds = self.desired_models(choices)
        problems = []
        for variant, _from_tag, ctx, _family in builds:
            actual = self._variant_num_ctx(variant)
            if actual is None:
                problems.append(f"{variant} not built")
            elif actual != ctx:
                problems.append(f"{variant} num_ctx is {actual}, want {ctx}")
        if problems:
            return "missing", "; ".join(problems)
        return "ok", "; ".join(f"{v} at num_ctx {c}" for v, _f, c, _fam in builds)

    def apply_w5(self):
        self._maybe_fail("W5")
        choices = self.load_state()["choices"]
        _pulls, builds = self.desired_models(choices)
        state = self.load_state()
        built = []
        tmp_dir = self.root / "tmp"
        for variant, from_tag, ctx, family in builds:
            if self._variant_num_ctx(variant) == ctx:
                continue
            template = load_template_text(
                f"models/Modelfile.{family}-opencode",
                FLINT_MODELF_TEMPLATE if family == "flint" else QWEN_MODELF_TEMPLATE)
            modelfile = tmp_dir / f"Modelfile.{variant}"
            write_bytes_exact(modelfile, render_modelfile(template, from_tag, ctx))
            result = self.platform.run(
                ["ollama", "create", variant, "-f", str(modelfile)], timeout=1800)
            if result.rc != 0:
                raise StepError(
                    f"ollama create {variant} failed: "
                    + result.err.decode("utf-8", errors="replace").strip())
            state.setdefault("models", {})[normalize_tag(variant)] = {
                "from": from_tag, "num_ctx": ctx}
            built.append(variant)
        return "built " + ", ".join(built) if built else "already built"

    # ---------- W6: Windows-side verify ----------

    def check_w6(self):
        choices = self.load_state()["choices"]
        variant, pin = self._primary_variant(choices)
        ok, detail = self._hello_round_trip(variant)
        if not ok:
            return "missing", f"hello round trip failed: {detail}"
        state = self.load_state()
        residency = {"round_trip": "ready", "cpu_only": None}
        ps = self.platform.api_get("/api/ps")
        if isinstance(ps, dict):
            for entry in ps.get("models", []):
                if normalize_tag(str(entry.get("name", ""))) == normalize_tag(variant):
                    ctx = entry.get("context_length")
                    vram = entry.get("size_vram", 0)
                    residency["context_length"] = ctx
                    residency["size_vram"] = vram
                    residency["cpu_only"] = not vram
                    if ctx is not None and ctx < pin:
                        state["residency"] = residency
                        return "drifted", (f"loaded context_length is {ctx}, "
                                           f"below the pin {pin}")
                    break
        state["residency"] = residency
        note = "; CPU-only (size_vram 0), agent turns will be slow" \
            if residency.get("cpu_only") else ""
        return "ok", f"hello round trip answered{note}"

    def apply_w6(self):
        self._maybe_fail("W6")
        # The check is the act for a verify step: one retry covers a
        # server that was still loading the model on the first pass.
        self.platform.sleep(3)
        choices = self.load_state()["choices"]
        variant, _pin = self._primary_variant(choices)
        ok, detail = self._hello_round_trip(variant)
        if not ok:
            raise StepError(
                f"the pinned variant does not answer a hello round trip: {detail}. "
                "Check that the Ollama tray app is running, then re-run install")
        return "hello round trip answered on retry"


    # ---------- B1: .wslconfig managed block ----------
    #
    # The kit owns exactly one thing in .wslconfig: under [wsl2], a
    # marker-wrapped block holding networkingMode=mirrored. Everything
    # else in the file is the user's and is preserved byte for byte as
    # far as line editing allows. A networkingMode line the user set
    # themselves inside [wsl2] is replaced by the managed one and its
    # value is recorded in state, so uninstall can restore it.

    def _wslconfig_path(self) -> Path:
        return self.platform.user_profile_dir() / ".wslconfig"

    @staticmethod
    def _split_lines(data: bytes):
        text = data.decode("utf-8", errors="surrogateescape")
        lines = text.splitlines(keepends=True)
        newline = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"
        return lines, newline

    @staticmethod
    def _section_of(lines, index):
        """The [section] name governing lines[index], or None."""
        section = None
        for line in lines[:index]:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip().lower()
        return section

    def _wslconfig_analysis(self, lines):
        begins = [i for i, l in enumerate(lines) if l.strip() == WSLCONFIG_BEGIN]
        ends = [i for i, l in enumerate(lines) if l.strip() == WSLCONFIG_END]
        managed_ok = False
        foreign_modes = []  # (index, value) networkingMode lines outside the block
        block_span = None
        if len(begins) == 1 and len(ends) == 1 and begins[0] < ends[0]:
            block_span = (begins[0], ends[0])
            inner = [l.strip() for l in lines[begins[0]:ends[0] + 1]]
            managed_ok = ("networkingMode=mirrored" in inner
                          and self._section_of(lines, begins[0]) == "wsl2")
        for i, line in enumerate(lines):
            if block_span and block_span[0] <= i <= block_span[1]:
                continue
            m = re.match(r"\s*networkingMode\s*=\s*(\S+)", line)
            if m and self._section_of(lines, i) == "wsl2":
                foreign_modes.append((i, m.group(1)))
        return managed_ok, foreign_modes, block_span

    def check_b1(self):
        path = self._wslconfig_path()
        if not path.exists():
            return "missing", ".wslconfig does not exist"
        lines, _nl = self._split_lines(path.read_bytes())
        managed_ok, foreign, _span = self._wslconfig_analysis(lines)
        if managed_ok and not foreign:
            return "ok", "managed block carries networkingMode=mirrored"
        if foreign:
            return "drifted", ("a networkingMode outside the managed block "
                               "competes with it")
        return "missing", "no managed block under [wsl2]"

    def apply_b1(self):
        self._maybe_fail("B1")
        state = self.load_state()
        path = self._wslconfig_path()
        existed = path.exists()
        data = path.read_bytes() if existed else b""
        lines, newline = self._split_lines(data)
        _ok, foreign, span = self._wslconfig_analysis(lines)

        record = state.setdefault("wslconfig", {})
        record["path"] = str(path)
        record["had_file"] = existed
        if foreign and "replaced_networking_mode" not in record:
            record["replaced_networking_mode"] = foreign[0][1]

        # Drop the old managed block and any competing foreign lines.
        drop = set()
        if span:
            drop.update(range(span[0], span[1] + 1))
        drop.update(i for i, _v in foreign)
        lines = [l for i, l in enumerate(lines) if i not in drop]

        block = [WSLCONFIG_BEGIN + newline,
                 "networkingMode=mirrored" + newline,
                 WSLCONFIG_END + newline]
        # Insert at the end of the [wsl2] section, or create the
        # section at the end of the file when there is none.
        wsl2_header = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]") \
                    and stripped[1:-1].strip().lower() == "wsl2":
                wsl2_header = i
                break
        if wsl2_header is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            lines.append("[wsl2]" + newline)
            lines.extend(block)
            record["created_section"] = True
        else:
            insert_at = len(lines)
            for j in range(wsl2_header + 1, len(lines)):
                stripped = lines[j].strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    insert_at = j
                    break
            if insert_at > 0 and not lines[insert_at - 1].endswith(("\n", "\r")):
                lines[insert_at - 1] += newline
            lines[insert_at:insert_at] = block
            record.setdefault("created_section", False)
        write_bytes_exact(path, "".join(lines).encode("utf-8", errors="surrogateescape"))
        state["wsl_restart_pending"] = True
        return "managed block written to .wslconfig"

    def _remove_wslconfig_block(self) -> str:
        """Uninstall half of B1. Returns a detail string."""
        state = self.load_state()
        record = state.get("wslconfig", {})
        path = self._wslconfig_path()
        if not path.exists():
            return "no .wslconfig present"
        lines, newline = self._split_lines(path.read_bytes())
        _ok, _foreign, span = self._wslconfig_analysis(lines)
        if not span:
            return "no managed block present"
        lines = [l for i, l in enumerate(lines) if not (span[0] <= i <= span[1])]
        previous = record.get("replaced_networking_mode")
        if previous:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]") \
                        and stripped[1:-1].strip().lower() == "wsl2":
                    lines.insert(i + 1, f"networkingMode={previous}" + newline)
                    break
        if record.get("created_section"):
            # Remove the [wsl2] header too when nothing else remains in it.
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]") \
                        and stripped[1:-1].strip().lower() == "wsl2":
                    rest = [l for l in lines[i + 1:]
                            if l.strip() and not l.strip().startswith("#")]
                    if not rest:
                        del lines[i]
                    break
        remaining = "".join(lines)
        if not record.get("had_file") and not remaining.strip():
            path.unlink()
            return "managed block removed; kit-created .wslconfig deleted"
        write_bytes_exact(path, remaining.encode("utf-8", errors="surrogateescape"))
        return "managed block removed from .wslconfig"

    # ---------- B2: WSL restart ----------

    def check_b2(self):
        state = self.load_state()
        if state.get("wsl_restart_pending"):
            return "drifted", "a .wslconfig change is waiting for a WSL restart"
        return "ok", "no restart pending"

    def apply_b2(self):
        self._maybe_fail("B2")
        state = self.load_state()
        distro = self._distro_name()
        result = self.platform.run(["wsl", "--shutdown"], timeout=120)
        if result.rc != 0:
            raise StepError("wsl --shutdown failed: "
                            + result.err.decode("utf-8", errors="replace").strip())
        probe = self.platform.wsl_run(distro, ["true"], timeout=120)
        if probe.rc != 0:
            raise StepError(
                f"WSL restarted but {distro} did not answer afterwards")
        state["wsl_restart_pending"] = False
        return f"WSL restarted; {distro} answers"

    # ---------- L1: distro detected ----------

    def _distro_name(self):
        state = self.load_state()
        recorded = state.get("wsl", {}).get("distro")
        if recorded:
            return recorded
        choices = state.get("choices", {})
        if choices.get("distro"):
            return choices["distro"]
        distros = self.platform.wsl_distros() or []
        if "Ubuntu" in distros:
            return "Ubuntu"
        return distros[0] if distros else "Ubuntu"

    def check_l1(self):
        state = self.load_state()
        distros = self.platform.wsl_distros()
        if distros is None:
            return "missing", "wsl.exe did not answer"
        want = state.get("choices", {}).get("distro")
        if want:
            if want in distros:
                return "ok", f"distro {want} present"
            return "missing", f"distro {want} not in: {', '.join(distros) or 'none'}"
        if "Ubuntu" in distros:
            return "ok", "distro Ubuntu present"
        if distros:
            return "ok", f"no Ubuntu; using {distros[0]}"
        return "missing", "no distro installed"

    def apply_l1(self):
        self._maybe_fail("L1")
        distros = self.platform.wsl_distros() or []
        name = self._distro_name()
        if name not in distros:
            raise StepError(
                f"distro {name} is not installed; run: wsl --install -d {name}")
        state = self.load_state()
        home = self.platform.wsl_home(name)
        state["wsl"] = {"distro": name, "home": home}
        return f"using distro {name} (home {home or 'unknown'})"

    # ---------- L2: OpenCode in the distro ----------
    #
    # The canonical install location is ~/.opencode/bin/opencode,
    # where both OpenCode installers put the binary. L2 probes that
    # binary by absolute path first, because a login shell's PATH is
    # a separate question: the OpenCode PATH entry lives in ~/.bashrc
    # behind its non-interactive early return, so a cold login shell
    # started through wsl.exe can answer "not found" while a healthy
    # OpenCode sits at the canonical path. The pre-0.2.1 check
    # trusted PATH alone, called the install missing, and its apply
    # ran the vendor's original install URL, which now serves
    # OpenCode 1 only; on the incident machine that silently
    # downgraded a working OpenCode 2.0.26 to 1.19.6, and 1.x cannot
    # read a 2.x database, so OpenCode refused to start. The
    # standing rule (2026-11-22): the kit should
    # never, under any circumstances, downgrade OpenCode that is
    # already installed. It holds structurally, not by comment: an
    # existing canonical binary is never replaced by any installer
    # (the installer command exists only on the no-binary path
    # below), a binary file that exists but does not answer counts
    # as installed and stops the step for a human, and the only
    # installer this step can run is the OpenCode 2 one.

    def _opencode_home(self, distro: str):
        state = self.load_state()
        home = state.get("wsl", {}).get("home") or self.platform.wsl_home(distro)
        if home:
            state.setdefault("wsl", {})["home"] = home
        return home

    def _opencode_binary_path(self, distro: str) -> str:
        home = self._opencode_home(distro)
        base = home or "~"
        return f"{base}/.opencode/bin/opencode"

    def _opencode_binary_version(self, distro: str):
        """The canonical binary's version, run by absolute path, or
        None when no binary there answers."""
        path = self._opencode_binary_path(distro)
        if not self.platform.wsl_file_exists(distro, path):
            return None
        result = self.platform.wsl_run(
            distro, ["bash", "-c", f"{shlex.quote(path)} --version"],
            timeout=60)
        if result.rc != 0:
            return None
        return _clean_opencode_version(result.text())

    def _opencode_version(self, distro: str):
        """The version a fresh login shell finds on PATH, or None.
        This answers "can a cold shell find opencode", a different
        question from "is it installed" (the canonical probe)."""
        result = self.platform.wsl_run(
            distro, ["bash", "-lc", "opencode --version"], timeout=60)
        if result.rc != 0:
            return None
        return _clean_opencode_version(result.text())

    def check_l2(self):
        distro = self._distro_name()
        binary = self._opencode_binary_path(distro)
        binary_version = self._opencode_binary_version(distro)
        path_version = self._opencode_version(distro)
        if binary_version is not None and path_version is not None:
            return "ok", f"opencode {binary_version} in {distro}"
        if binary_version is not None:
            # Installed, but cold login shells cannot find it. That
            # is drift, not absence: apply repairs PATH, and must
            # never "repair" it with a reinstall.
            return "drifted", (
                f"opencode {binary_version} is installed at {binary} "
                f"in {distro}, but a fresh login shell cannot find "
                "it on PATH (its PATH entry sits where login shells "
                "do not read it)")
        if path_version is not None:
            return "ok", (
                f"opencode {path_version} in {distro} (found on a "
                f"login shell's PATH; no binary at the canonical "
                f"{binary})")
        if self.platform.wsl_file_exists(distro, binary):
            # A binary file is there but answers neither probe. It
            # is still an installed OpenCode under the standing rule
            # (never replace an existing install), so this is drift
            # for a human to look at, never a missing install.
            return "drifted", (
                f"a binary file sits at {binary} in {distro} but "
                "does not answer --version; the kit treats any "
                "existing binary as installed and will not replace it")
        return "missing", (
            f"no opencode binary at {binary} in {distro}, and none "
            "found on a login shell's PATH")

    def _fix_opencode_path(self, distro: str) -> bool:
        """Append the marker-guarded PATH block to ~/.profile in
        the distro (login shells read ~/.profile; ~/.bashrc is not
        read past its early return by non-interactive login shells).
        Byte-exact like every kit file write; a no-op when the
        marker is already present. Returns True when it wrote."""
        home = self._opencode_home(distro)
        base = home or "~"
        profile = f"{base}/.profile"
        current = self.platform.wsl_read_file(distro, profile) or b""
        if OPENCODE_PATH_BEGIN.encode("utf-8") in current:
            return False
        data = current
        if data and not data.endswith(b"\n"):
            data += b"\n"
        self.platform.wsl_write_file(
            distro, profile, data + OPENCODE_PATH_BLOCK.encode("utf-8"))
        return True

    def apply_l2(self):
        self._maybe_fail("L2")
        distro = self._distro_name()
        binary = self._opencode_binary_path(distro)
        binary_version = self._opencode_binary_version(distro)
        state = self.load_state()
        if binary_version is None and \
                self.platform.wsl_file_exists(distro, binary):
            # A binary file is there but will not answer. Under the
            # standing rule (2026-11-22) the kit never, under
            # any circumstances, downgrades or replaces an OpenCode
            # that is already installed, and a present file is an
            # installed OpenCode. Stop and let a human look at it;
            # no installer runs over it, ever.
            raise StepError(
                f"an opencode binary file exists at {binary} in "
                f"{distro} but does not answer --version; the kit "
                "never replaces or downgrades an installed OpenCode, "
                "so it will not install over it. Check that binary "
                "by hand (it may be corrupt or caught mid-update), "
                "then re-run install")
        if binary_version is not None:
            # A binary already lives at the canonical path, of
            # whatever version the user runs. It is never replaced:
            # no installer command exists on this branch. The only
            # repair here is the login-shell PATH.
            if self._opencode_version(distro) is not None:
                state.setdefault("wsl", {})["opencode_version"] = \
                    binary_version
                return (f"opencode {binary_version} already at "
                        f"{binary}; nothing to do")
            self._fix_opencode_path(distro)
            if self._opencode_version(distro) is None:
                raise StepError(
                    f"opencode {binary_version} is installed at "
                    f"{binary}, and the kit's PATH block is in "
                    "~/.profile, but a fresh login shell still "
                    "cannot find it; a ~/.bash_profile or ~/.bash_login "
                    "that does not source ~/.profile wins over it at "
                    "login, so check which of those files exists in "
                    "the distro and what it reads")
            state.setdefault("wsl", {})["opencode_version"] = binary_version
            state["wsl"]["opencode_path_fix"] = "~/.profile"
            return (f"opencode {binary_version} was already installed "
                    f"at {binary}; added ~/.opencode/bin to PATH in "
                    "~/.profile so login shells find it (no reinstall: "
                    "an existing binary is never replaced)")
        path_version = self._opencode_version(distro)
        if path_version is not None:
            # An opencode the user installed some other way answers
            # on PATH. It is theirs; leave it alone.
            state.setdefault("wsl", {})["opencode_version"] = path_version
            return (f"opencode {path_version} already answers on PATH "
                    f"in {distro}; nothing to do")
        # No binary anywhere: the one path that may run an
        # installer, and the installer is the OpenCode 2 one.
        # The vendor's original install URL serves OpenCode 1 only
        # and must never be used here (see the section comment).
        result = self.platform.wsl_run(
            distro, ["bash", "-lc", OPENCODE_INSTALL_COMMAND],
            timeout=900)
        if result.rc != 0:
            raise StepError(
                "the OpenCode install script failed in "
                f"{distro}: " + result.err.decode("utf-8", errors="replace").strip()
                + " (the documented route is https://opencode.ai/v2/install; "
                "npm install -g @opencode/cli is the alternative)")
        version = self._opencode_binary_version(distro) \
            or self._opencode_version(distro)
        if version is None:
            raise StepError(
                "the OpenCode 2 installer ran but no binary answers "
                f"at {binary} in {distro}, and none answers on PATH; "
                "check the installer output above and the contents "
                "of ~/.opencode/bin in the distro")
        state.setdefault("wsl", {})["opencode_version"] = version
        state["wsl"]["opencode_installed_by_kit"] = True
        return f"installed opencode {version} in {distro}"

    # ---------- L3: kit config in the distro ----------

    def _config_path_in_wsl(self, distro: str) -> str:
        state = self.load_state()
        home = state.get("wsl", {}).get("home") or self.platform.wsl_home(distro)
        if home:
            state.setdefault("wsl", {})["home"] = home
        base = home or "~"
        return f"{base}/.config/opencode/opencode.json"

    def _desired_config(self) -> bytes:
        choices = self.load_state()["choices"]
        return render_config(choices["num_ctx"], choices["qwen_num_ctx"],
                             with_flint=choices.get("with_flint", True),
                             with_qwen=choices.get("with_qwen", True))

    def check_l3(self):
        distro = self._distro_name()
        path = self._config_path_in_wsl(distro)
        current = self.platform.wsl_read_file(distro, path)
        if current is None:
            return "missing", f"no config at {path}"
        if current == self._desired_config():
            return "ok", "installed config matches the rendered template"
        return "drifted", "installed config differs from the rendered template"

    def apply_l3(self):
        self._maybe_fail("L3")
        distro = self._distro_name()
        path = self._config_path_in_wsl(distro)
        state = self.load_state()
        desired = self._desired_config()
        existing = self.platform.wsl_read_file(distro, path)
        record = state.setdefault("opencode_config", {})
        if existing is not None and existing != desired:
            stamp = self.platform.now().strftime("%Y%m%d-%H%M%S")
            backup = f"{path}.bak-{stamp}"
            counter = 0
            while self.platform.wsl_file_exists(distro, backup):
                counter += 1
                backup = f"{path}.bak-{stamp}-{counter}"
            if not self.platform.wsl_copy_file(distro, path, backup):
                raise StepError(f"could not back up the existing config to {backup}")
            record["backup_path"] = backup
            record["backup_sha256"] = sha256_bytes(existing)
            record["had_previous"] = True
        elif existing is None:
            record.setdefault("had_previous", False)
        self.platform.wsl_write_file(distro, path, desired)
        record["path"] = path
        record["installed_sha256"] = sha256_bytes(desired)
        choices = state["choices"]
        pins = []
        if choices.get("with_flint", True):
            pins.append(f"Flint context {choices['num_ctx']}")
        if choices.get("with_qwen", True):
            pins.append(f"Qwen context {choices['qwen_num_ctx']}")
        return (f"config installed ({', '.join(pins)}"
                + (f"; previous config backed up to {record.get('backup_path')}"
                   if record.get("backup_path") else "") + ")")

    # ---------- L4: client-side smoke from WSL ----------

    def check_l4(self):
        distro = self._distro_name()
        choices = self.load_state()["choices"]
        variant, pin = self._primary_variant(choices)
        version = self.platform.wsl_api_get(distro, "/api/version")
        if not isinstance(version, dict):
            return "missing", ("the Ollama API does not answer from inside "
                               f"{distro} (mirrored networking not in effect?)")
        tags = self.platform.wsl_api_get(distro, "/api/tags")
        names = set()
        if isinstance(tags, dict):
            names = {normalize_tag(str(m.get("name", "")))
                     for m in tags.get("models", [])}
        if normalize_tag(variant) not in names:
            return "missing", f"{variant} is not visible from {distro}"
        ctx = None
        show = self.platform.wsl_api_post(
            distro, "/api/show", {"name": normalize_tag(variant)})
        if isinstance(show, dict):
            m = re.search(r"num_ctx\s+(\d+)", str(show.get("parameters", "")))
            if m:
                ctx = int(m.group(1))
        if ctx is None or ctx < pin:
            return "drifted", (f"effective num_ctx from {distro} is "
                               f"{ctx}, want at least {pin}")
        return "ok", (f"from {distro}: API answers, {variant} visible, "
                      f"num_ctx {ctx}")

    def apply_l4(self):
        self._maybe_fail("L4")
        raise StepError(
            "the client-side smoke cannot be repaired from here: from "
            "inside the distro the Windows server is unreachable or the "
            "variant is not visible. Check that the Ollama tray app is "
            "running on Windows, that B1/B2 put mirrored networking in "
            "effect (wsl --shutdown, then start the distro again), and "
            "that W5 built the variant; then re-run repair")


    # ---------- C1-C4: ComfyUI ----------
    #
    # ComfyUI is portable and relocatable, so it gets its own root
    # (default C:\ComfyUI), separate from the kit root, which still
    # holds only state and logs. State records what the kit placed
    # there, per file, so uninstall can undo selectively and never
    # has to guess. ComfyUI is part of the default install; nothing
    # here runs when it is opted out (--no-comfyui).

    def _comfy_root(self) -> Path:
        state = self.load_state()
        recorded = state.get("comfyui", {}).get("root")
        chosen = state.get("choices", {}).get("comfy_root")
        if chosen:
            return Path(chosen)
        if recorded:
            return Path(recorded)
        return self.platform.default_comfy_root()

    def _comfy_portable(self) -> Path:
        return self._comfy_root() / COMFY_PORTABLE_DIRNAME

    def _comfy_app_dir(self) -> Path:
        return self._comfy_portable() / "ComfyUI"

    def _comfy_launcher(self) -> Path:
        return self._comfy_portable() / COMFY_LAUNCHER

    def _comfy_archive_path(self) -> Path:
        return self._comfy_root() / "downloads" / COMFY_ARCHIVE_FILE

    def _comfy_model_path(self, filename: str) -> Path:
        subdir = COMFY_MODELS[filename][0]
        return self._comfy_app_dir() / "models" / subdir / filename

    def _comfy_stats(self):
        body = self.platform.comfy_get("/system_stats", timeout=10)
        return body if isinstance(body, dict) else None

    def _comfy_gpu(self, stats):
        """(device dict, problem) from a /system_stats body. The
        device passes Gate 1 when its name names a Radeon and its
        vram_total clears the floor; a CPU fallback device, an empty
        device list, or a small carve-out all fail, with the reason."""
        if not stats:
            return None, "the ComfyUI server does not answer /system_stats"
        devices = stats.get("devices") or []
        if not devices:
            return None, "ComfyUI reports no devices (CPU-only fallback)"
        for device in devices:
            name = str(device.get("name", ""))
            vram = int(device.get("vram_total") or 0)
            if "cpu" in name.lower():
                return None, f"ComfyUI is running CPU-only (device {name!r})"
            if "radeon" in name.lower() and vram >= COMFY_MIN_VRAM:
                return device, ""
        first = devices[0]
        return None, (f"no Radeon GPU with at least "
                      f"{COMFY_MIN_VRAM // 1_000_000_000} GB reported; "
                      f"first device is {first.get('name')!r} with "
                      f"vram_total {first.get('vram_total')}")

    def _start_comfyui(self) -> None:
        launcher = self._comfy_launcher()
        if not launcher.exists():
            raise StepError(
                f"the ComfyUI launcher is missing at {launcher}; "
                "run repair (step C1) first")
        self.platform.start_detached(["cmd", "/c", str(launcher)],
                                     cwd=self._comfy_portable())

    def _wait_comfy(self, attempts: int = 60) -> bool:
        for _attempt in range(attempts):
            if self.platform.comfy_probe() == "comfy":
                return True
            self.platform.sleep(2)
        return False

    def _stop_comfyui(self) -> None:
        """The switch/uninstall stop path: ask the server to unload
        its models first (best effort), then stop the portable's
        processes by exact path, then verify the port is quiet."""
        if self.platform.comfy_probe() == "comfy":
            self.platform.comfy_post(
                "/free", {"unload_models": True, "free_memory": True},
                timeout=30)
        self.platform.stop_process_by_path(str(self._comfy_portable()))
        for _attempt in range(15):
            if not self.platform.port_in_use(COMFY_PORT):
                return
            self.platform.sleep(1)

    # ---------- C1: portable present, pinned ----------

    def check_c1(self):
        state = self.load_state()
        record = state.get("comfyui", {})
        launcher = self._comfy_launcher()
        if not launcher.exists():
            return "missing", f"no launcher at {launcher}"
        if record.get("version") is None:
            # A portable tree is already at the kit's root but the kit
            # has no record of it: the hand install this fold-in was
            # built from. Adopt it instead of downloading and
            # extracting the same pinned build over a working tree.
            # The pin is still enforced where it can be: C2 verifies
            # every model file by size, C3 and C4 prove the tree runs
            # the pinned workflow on the GPU. A record that names a
            # DIFFERENT version is drift, below, not adoption.
            record = state.setdefault("comfyui", {})
            record.update({
                "version": COMFY_VERSION,
                "root": str(self._comfy_root()),
                "portable_dir": str(self._comfy_portable()),
                "app_dir": str(self._comfy_app_dir()),
                "launcher": str(launcher),
                "archive": str(self._comfy_archive_path()),
                "archive_size": COMFY_ARCHIVE_SIZE,
                "archive_sha256": COMFY_ARCHIVE_SHA256,
                "created_root": False,
                "adopted": True,
            })
            record.setdefault("models", {})
            return "ok", (f"ComfyUI {COMFY_VERSION} portable at "
                          f"{self._comfy_portable()} (adopted: already "
                          "installed by hand, recorded without changes)")
        if record.get("version") != COMFY_VERSION:
            return "drifted", (f"state records ComfyUI "
                               f"{record.get('version')!r}, the kit pins "
                               f"{COMFY_VERSION}")
        if record.get("archive_sha256") != COMFY_ARCHIVE_SHA256:
            return "drifted", "the recorded archive hash does not match the pin"
        return "ok", f"ComfyUI {COMFY_VERSION} portable at {self._comfy_portable()}"

    def apply_c1(self):
        self._maybe_fail("C1")
        state = self.load_state()
        root = self._comfy_root()
        created_root = not root.exists()
        archive = self._comfy_archive_path()
        have_archive = archive.exists() and \
            archive.stat().st_size == COMFY_ARCHIVE_SIZE
        if not have_archive:
            self.log(f"Downloading the ComfyUI {COMFY_VERSION} portable "
                     f"archive ({COMFY_ARCHIVE_SIZE // 1_000_000_000} GB) "
                     "from the official GitHub release")
            self.platform.download_file(
                COMFY_ARCHIVE_URL, archive,
                COMFY_ARCHIVE_SIZE, COMFY_ARCHIVE_SHA256)
        self.platform.extract_archive(archive, root)
        if not self._comfy_launcher().exists():
            raise StepError(
                f"extraction finished but {self._comfy_launcher()} is not "
                "there; the archive layout is not the pinned portable's")
        record = state.setdefault("comfyui", {})
        record.update({
            "version": COMFY_VERSION,
            "root": str(root),
            "portable_dir": str(self._comfy_portable()),
            "app_dir": str(self._comfy_app_dir()),
            "launcher": str(self._comfy_launcher()),
            "archive": str(archive),
            "archive_size": COMFY_ARCHIVE_SIZE,
            "archive_sha256": COMFY_ARCHIVE_SHA256,
            "created_root": created_root,
        })
        record.setdefault("models", {})
        return f"ComfyUI {COMFY_VERSION} portable extracted to {self._comfy_portable()}"

    # ---------- C2: Z-Image-Turbo models present ----------

    def check_c2(self):
        problems = []
        for filename, (_subdir, size, _sha, _url) in COMFY_MODELS.items():
            path = self._comfy_model_path(filename)
            if not path.exists():
                problems.append(f"{filename} missing")
            elif path.stat().st_size != size:
                problems.append(
                    f"{filename} is {path.stat().st_size} bytes, want {size}")
        if problems:
            return "missing", "; ".join(problems)
        return "ok", "all three Z-Image-Turbo files present at pinned sizes"

    def apply_c2(self):
        self._maybe_fail("C2")
        state = self.load_state()
        done = []
        for filename, (_subdir, size, sha, url) in COMFY_MODELS.items():
            dest = self._comfy_model_path(filename)
            if dest.exists() and dest.stat().st_size == size:
                continue
            self.log(f"Downloading {filename} "
                     f"({size // 1_000_000_000} GB) directly into "
                     f"{dest.parent.name}; size and SHA-256 are verified "
                     "before it lands")
            self.platform.download_file(url, dest, size, sha)
            if not dest.exists() or dest.stat().st_size != size:
                raise StepError(
                    f"{filename} did not land at {dest} with the pinned size")
            done.append(filename)
        record = state.setdefault("comfyui", {})
        record["models"] = {
            filename: {"subdir": subdir, "size": size, "sha256": sha}
            for filename, (subdir, size, sha, _url) in COMFY_MODELS.items()}
        return ("downloaded " + ", ".join(done)) if done else "already present"

    # ---------- C3: Gate 1, launches and sees the GPU ----------

    def check_c3(self):
        stats = self._comfy_stats()
        device, problem = self._comfy_gpu(stats)
        if device is None:
            return "missing", problem
        state = self.load_state()
        state.setdefault("comfyui", {})["gate1"] = {
            "device": str(device.get("name", "")),
            "vram_total": int(device.get("vram_total") or 0)}
        return "ok", (f"Gate 1: {device.get('name')} with "
                      f"{int(device.get('vram_total') or 0) // 1_000_000_000} "
                      "GB reported by /system_stats")

    def apply_c3(self):
        self._maybe_fail("C3")
        if self.platform.comfy_probe() == "other":
            raise StepError(
                "something that is not ComfyUI answers on port 8188; "
                "stop it, then re-run")
        if self.platform.comfy_probe() != "comfy":
            self._start_comfyui()
            if not self._wait_comfy():
                raise StepError(
                    "ComfyUI did not answer on port 8188 after launch; "
                    f"run {self._comfy_launcher()} by hand once and read "
                    "its window: the startup log names the device it "
                    "found, and CPU-only there is the Gate 1 failure")
        device, problem = self._comfy_gpu(self._comfy_stats())
        if device is None:
            raise StepError(f"Gate 1 failed: {problem}")
        return f"Gate 1 passed: {device.get('name')}"

    # ---------- C4: Gate 2, a real generation ----------

    def _comfy_history_outputs(self, prompt_id: str):
        body = self.platform.comfy_get(f"/history/{prompt_id}", timeout=10)
        if not isinstance(body, dict):
            return None
        entry = body.get(prompt_id)
        if not isinstance(entry, dict):
            return None
        outputs = entry.get("outputs") or {}
        images = []
        for node_out in outputs.values():
            if isinstance(node_out, dict):
                images.extend(node_out.get("images") or [])
        return images

    def check_c4(self):
        state = self.load_state()
        gate2 = state.get("comfyui", {}).get("gate2") or {}
        prompt_id = gate2.get("prompt_id")
        if not prompt_id:
            return "missing", "the Gate 2 smoke has not run yet"
        images = self._comfy_history_outputs(prompt_id)
        if not images:
            return "missing", ("the recorded smoke run has no output "
                               "image in the server history")
        return "ok", (f"Gate 2: smoke run {prompt_id} produced "
                      f"{len(images)} image(s) in "
                      f"{gate2.get('seconds')} seconds")

    def apply_c4(self):
        self._maybe_fail("C4")
        state = self.load_state()
        if self.platform.comfy_probe() != "comfy":
            self._start_comfyui()
            if not self._wait_comfy():
                raise StepError("ComfyUI did not come up for the Gate 2 smoke")
        template = load_template_text(
            "installer/templates/z_image_turbo_smoke.json",
            COMFY_SMOKE_WORKFLOW_TEMPLATE)
        try:
            workflow = json.loads(template)
        except ValueError as exc:
            raise StepError(f"the embedded smoke workflow does not parse: {exc}")
        stats_before = self._comfy_stats() or {}
        devices_before = stats_before.get("devices") or [{}]
        vram_total = int(devices_before[0].get("vram_total") or 0)
        min_free = int(devices_before[0].get("vram_free") or vram_total)
        started = self.platform.now()
        body = self.platform.comfy_post(
            "/prompt", {"prompt": workflow, "client_id": "local-models-kit-manager"},
            timeout=60)
        prompt_id = body.get("prompt_id") if isinstance(body, dict) else None
        if not prompt_id:
            raise StepError(
                f"ComfyUI refused the smoke workflow: {body!r}. A node "
                "error here usually means a model file is not where the "
                "workflow expects it; run doctor and check C2")
        images = None
        for _attempt in range(120):
            stats_now = self._comfy_stats() or {}
            devices_now = stats_now.get("devices") or []
            if devices_now:
                free_now = int(devices_now[0].get("vram_free") or min_free)
                min_free = min(min_free, free_now)
            images = self._comfy_history_outputs(prompt_id)
            if images:
                break
            self.platform.sleep(2)
        if not images:
            raise StepError(
                "the Gate 2 smoke produced no image before the timeout; "
                "open the ComfyUI window and read its log for the node "
                "that failed")
        seconds = (self.platform.now() - started).total_seconds()
        record = state.setdefault("comfyui", {})
        record["gate2"] = {
            "prompt_id": prompt_id,
            "seconds": round(seconds, 2),
            "peak_vram": (vram_total - min_free) if vram_total else None,
            "at": self.platform.now().isoformat(timespec="seconds")}
        return (f"Gate 2 passed: an image in {seconds:.1f} seconds "
                f"(prompt {prompt_id})")

    # ---------- doctor ----------

    def doctor_items(self):
        """(name, status, detail, repair) rows. Status is PASS, WARN,
        or FAIL. Every claim the state file makes is checked live."""
        p = self.platform
        items = []

        def add(name, status, detail, repair=""):
            items.append({"name": name, "status": status,
                          "detail": detail, "repair": repair})

        if not self.state_path.exists():
            add("install state", "FAIL",
                f"no state file at {self.state_path}; this root was never installed",
                "install")
            return items
        state = self.load_state()
        choices = state.get("choices", {})
        num_ctx = int(choices.get("num_ctx", DEFAULT_NUM_CTX))
        distro = self._distro_name()

        version = self._ollama_version()
        if version is None:
            add("W1 ollama", "FAIL", "ollama is not on PATH", "W1")
        elif version < MIN_OLLAMA:
            add("W1 ollama", "FAIL",
                f"ollama {'.'.join(map(str, version))} is older than "
                f"{'.'.join(map(str, MIN_OLLAMA))}", "W1")
        else:
            add("W1 ollama", "PASS", f"ollama {'.'.join(map(str, version))}")

        env_bad = []
        for name, want in self._desired_env(
                {"num_ctx": num_ctx}).items():
            current = p.get_user_env(name)
            if current != want:
                env_bad.append(f"{name} is {current!r}, want {want!r}")
        if env_bad:
            add("W2 env vars", "FAIL", "; ".join(env_bad), "W2")
        else:
            add("W2 env vars", "PASS", "both server env vars match")

        if p.api_probe() != "ollama":
            add("W3 server", "FAIL",
                "the Ollama server does not answer /api/version "
                "(is the tray app running?)", "W3")
        else:
            add("W3 server", "PASS", "the Ollama server answers /api/version")

        pulls, builds = self.desired_models(
            {"with_flint": bool(choices.get("with_flint", True)),
             "with_qwen": bool(choices.get("with_qwen")), "num_ctx": num_ctx})
        tags = self._server_tags()
        if tags is None:
            add("W4 models", "WARN", "cannot list models right now")
        else:
            missing = [t for t in pulls if normalize_tag(t) not in tags]
            if missing:
                add("W4 models", "FAIL", "not pulled: " + ", ".join(missing), "W4")
            else:
                add("W4 models", "PASS", "pulled: " + ", ".join(pulls))

        variant_problems = []
        for variant, _from_tag, ctx, _family in builds:
            actual = self._variant_num_ctx(variant)
            if actual is None:
                variant_problems.append(f"{variant} not built")
            elif actual != ctx:
                variant_problems.append(f"{variant} num_ctx is {actual}, want {ctx}")
        if variant_problems:
            add("W5 variants", "FAIL", "; ".join(variant_problems), "W5")
        else:
            add("W5 variants", "PASS",
                "; ".join(f"{v} at num_ctx {c}" for v, _f, c, _fam in builds))

        primary, primary_pin = self._primary_variant(choices)
        ps = p.api_get("/api/ps")
        entry = None
        if isinstance(ps, dict):
            for candidate in ps.get("models", []):
                if normalize_tag(str(candidate.get("name", ""))) == normalize_tag(primary):
                    entry = candidate
                    break
        if entry is None:
            add("W6 residency", "WARN",
                f"{primary} is not loaded; residency unverified "
                "(send OpenCode a prompt, then re-run doctor)")
        else:
            ctx = entry.get("context_length")
            vram = entry.get("size_vram", 0)
            if ctx is not None and ctx < primary_pin:
                add("W6 residency", "FAIL",
                    f"loaded context_length is {ctx}, below the pin {primary_pin}", "W5")
            elif not vram:
                add("W6 residency", "WARN",
                    "the model is CPU-only (size_vram 0); agent turns "
                    "will be slow. On the target machine this should be "
                    "GPU-resident; a WSL-local server shadowing the "
                    "Windows one is the usual cause")
            else:
                add("W6 residency", "PASS",
                    f"loaded with context_length {ctx}, size_vram {vram} bytes")

        status, detail = self.check_b1()
        add("B1 .wslconfig", "PASS" if status == "ok" else "FAIL", detail, "B1")

        distros = p.wsl_distros()
        if distros is None or distro not in distros:
            add("L1 distro", "FAIL",
                f"distro {distro} is not available", "L1")
        else:
            add("L1 distro", "PASS", f"distro {distro} present")

        oc_binary_path = self._opencode_binary_path(distro)
        oc_binary = self._opencode_binary_version(distro)
        oc_path = self._opencode_version(distro)
        if oc_binary is not None and oc_path is not None:
            add("L2 opencode", "PASS", f"opencode {oc_binary} in {distro}")
        elif oc_binary is not None:
            add("L2 opencode", "WARN",
                f"opencode {oc_binary} is installed at {oc_binary_path} "
                "but a fresh login shell cannot find it on PATH", "L2")
        elif oc_path is not None:
            add("L2 opencode", "PASS", f"opencode {oc_path} in {distro}")
        else:
            add("L2 opencode", "FAIL",
                f"no opencode binary at {oc_binary_path} in {distro}, "
                "and none on a login shell's PATH", "L2")

        status, detail = self.check_l3()
        add("L3 config", "PASS" if status == "ok" else "FAIL", detail, "L3")

        status, detail = self.check_l4()
        add("L4 client smoke", "PASS" if status == "ok" else "FAIL",
            detail, "B1/B2, then L4")


        if choices.get("with_comfyui"):
            status, detail = self.check_c1()
            add("C1 comfy install", "PASS" if status == "ok" else "FAIL",
                detail, "C1")

            status, detail = self.check_c2()
            add("C2 comfy models", "PASS" if status == "ok" else "FAIL",
                detail, "C2")

            probe = p.comfy_probe()
            if probe == "free":
                add("C3 comfy server", "PASS",
                    "not launched; ComfyUI is on-demand, start it with "
                    "switch comfy or its launcher")
            elif probe == "other":
                add("C3 comfy server", "FAIL",
                    "something that is not ComfyUI answers on port 8188",
                    "C3")
            else:
                device, problem = self._comfy_gpu(self._comfy_stats())
                if device is None:
                    add("C3 comfy server", "FAIL", problem, "C3")
                else:
                    add("C3 comfy server", "PASS",
                        f"running on {device.get('name')}")

            # VRAM conflict rule, exactly as implemented: a conflict
            # is an Ollama model loaded (per /api/ps) at the same
            # time as the ComfyUI server answering with at least
            # 1 GB of its reported VRAM in use. Either side alone is
            # fine; both resident at once is what the switch verb
            # exists to prevent on a shared-memory machine.
            ollama_loaded = []
            if isinstance(ps, dict):
                ollama_loaded = ps.get("models") or []
            comfy_stats = self._comfy_stats() if probe == "comfy" else None
            comfy_used = 0
            if comfy_stats:
                devices_now = comfy_stats.get("devices") or []
                if devices_now:
                    comfy_used = int(devices_now[0].get("vram_total") or 0) \
                        - int(devices_now[0].get("vram_free") or 0)
            if ollama_loaded and comfy_used >= 1_000_000_000:
                add("VRAM conflict", "WARN",
                    "an Ollama model is loaded while ComfyUI holds "
                    f"{comfy_used // 1_000_000_000} GB of VRAM; on this "
                    "machine the two stacks take turns",
                    "switch")
            else:
                add("VRAM conflict", "PASS",
                    "only one stack holds VRAM right now")
        return items

    def print_doctor(self, items) -> int:
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for item in items:
            counts[item["status"]] += 1
            line = f"{item['status']}  {item['name']}: {item['detail']}"
            if item["status"] == "FAIL" and item["repair"]:
                line += f" (repair: run repair; step {item['repair']})"
            self.log(line)
        self.log(f"Doctor: {counts['PASS']} pass, {counts['WARN']} warn, "
                 f"{counts['FAIL']} fail")
        return 1 if counts["FAIL"] else 0

    # ---------- verbs ----------

    def verb_install(self, with_flint=None, with_qwen=None, num_ctx=None,
                     distro=None, with_comfyui=None, comfy_root=None) -> int:
        choices = self.resolve_choices(with_flint=with_flint,
                                       with_qwen=with_qwen,
                                       num_ctx=num_ctx, distro=distro,
                                       with_comfyui=with_comfyui,
                                       comfy_root=comfy_root)
        blockers = self.preflight(choices)
        if blockers:
            self.log("Preflight found problems; nothing was changed:")
            for name, problem, fix in blockers:
                self.log(f"BLOCKER {name}: {problem}")
                self.log(f"  fix: {fix}")
            return 1
        self.save_state()
        pulls, _builds = self.desired_models(choices)
        pins = []
        if choices["with_flint"]:
            pins.append(f"Flint context {choices['num_ctx']}")
        if choices["with_qwen"]:
            pins.append(f"Qwen context {choices['qwen_num_ctx']}")
        self.log(f"Installing Local Models Kit (kit {KIT_VERSION}): "
                 f"models {', '.join(pulls)}, " + ", ".join(pins)
                 + (f", ComfyUI {COMFY_VERSION} at {self._comfy_root()}"
                    if choices.get("with_comfyui") else ""))
        self.run_all_steps(choices)
        self.log("Install steps complete; running doctor:")
        return self.print_doctor(self.doctor_items())

    def verb_doctor(self) -> int:
        return self.print_doctor(self.doctor_items())

    def verb_repair(self) -> int:
        if not self.state_path.exists():
            self.log("Nothing to repair: no install state at "
                     f"{self.state_path}. Run install first.")
            return 1
        choices = self.resolve_choices()
        self.run_all_steps(choices, repair=True)
        self.log("Repair pass complete; running doctor:")
        return self.print_doctor(self.doctor_items())


    def verb_switch(self, target: str) -> int:
        """Hand the GPU from one stack to the other. VRAM is the
        whole reason: on the target machine the best Ollama load
        (Flint plus its 128K KV cache) and ComfyUI at its measured
        23 GB peak do not fit inside the GPU allocation at once, so
        the stacks take turns, and each direction verifies the other
        side is really down before starting its own."""
        if not self.state_path.exists():
            self.log("Nothing to switch: no install state at "
                     f"{self.state_path}. Run install first.")
            return 1
        state = self.load_state()
        p = self.platform

        if target == "comfy":
            if not state.get("choices", {}).get("with_comfyui"):
                raise StepError(
                    "ComfyUI is not part of this install (it was opted "
                    "out); re-run install --with-comfyui to add it")
            status, detail = self.check_c1()
            if status != "ok":
                raise StepError(f"ComfyUI is not installed: {detail}")
            ps = p.api_get("/api/ps")
            loaded = []
            if isinstance(ps, dict):
                loaded = [str(m.get("name", "")) for m in ps.get("models", [])]
            for name in loaded:
                p.api_post("/api/generate",
                           {"model": name, "keep_alive": 0}, timeout=120)
                self.log(f"Unloaded {name} from Ollama")
            ps = p.api_get("/api/ps")
            remaining = ps.get("models") if isinstance(ps, dict) else None
            if remaining:
                raise StepError(
                    "Ollama still reports loaded models after unload: "
                    + ", ".join(str(m.get("name", "")) for m in remaining)
                    + "; refusing to start ComfyUI on top of them")
            if p.comfy_probe() == "other":
                raise StepError(
                    "something that is not ComfyUI answers on port 8188; "
                    "stop it, then re-run switch")
            if p.comfy_probe() != "comfy":
                self._start_comfyui()
                if not self._wait_comfy():
                    raise StepError(
                        "ComfyUI did not answer on port 8188 after launch")
            device, problem = self._comfy_gpu(self._comfy_stats())
            if device is None:
                raise StepError(f"ComfyUI came up wrong: {problem}")
            state["last_switch"] = {
                "target": "comfy",
                "at": p.now().isoformat(timespec="seconds")}
            self.save_state()
            self.say("DONE", "switch comfy",
                     f"Ollama unloaded; ComfyUI is up on {device.get('name')}")
            return 0

        if target == "ollama":
            self._stop_comfyui()
            if p.port_in_use(COMFY_PORT):
                raise StepError(
                    "port 8188 is still answering after the ComfyUI "
                    "stop; close the ComfyUI window by hand, then "
                    "re-run switch ollama")
            p.restart_ollama_tray()
            for _attempt in range(30):
                if p.api_probe() == "ollama":
                    break
                p.sleep(2)
            else:
                raise StepError(
                    "the Ollama server did not answer after the tray "
                    "restart; start Ollama from the Start menu, then "
                    "re-run doctor")
            state["last_switch"] = {
                "target": "ollama",
                "at": p.now().isoformat(timespec="seconds")}
            self.save_state()
            self.say("DONE", "switch ollama",
                     "ComfyUI stopped; the Ollama server answers")
            return 0

        raise StepError(f"unknown switch target {target!r}; use comfy or ollama")

    def verb_update(self) -> int:
        # Honest stub: update checking is not implemented yet, and a
        # fake updater would be worse than none. When it lands it will
        # fetch the release manifest from the pinned GitHub releases
        # URL, verify its hash fail-closed, and hand off to the new
        # manager with state carried over.
        self.log(f"Local Models Kit manager {MANAGER_VERSION} (kit {KIT_VERSION})")
        if self.state_path.exists():
            state = self.load_state()
            self.log(f"Installed kit version: {state.get('kit_version')} "
                     f"(manager {state.get('manager_version')})")
        self.log("update checking is not implemented yet; see the "
                 "releases page for the current version.")
        self.log("Releases: "
                 "https://github.com/steve-hewitt/local-models-kit/releases")
        self.log("For now, update by pulling a fresh clone of the kit "
                 "and re-running install; your choices carry over "
                 "through the state file.")
        return 0

    def verb_uninstall(self, remove_models: bool = False,
                       remove_ollama: bool = False,
                       remove_comfyui: bool = False,
                       remove_comfyui_models: bool = False) -> int:
        if not self.state_path.exists():
            self.log(f"SKIP uninstall: no install state at {self.state_path}; "
                     "nothing was installed from this root")
            return 0
        state = self.load_state()
        p = self.platform
        distro = self._distro_name()
        choices = state.get("choices", {})

        # ComfyUI first, before anything else: stop its server, then
        # follow the flags. Default keeps the portable tree and the
        # models (they are the expensive downloads); the removal
        # flags parallel the Ollama ones. The tree is removed whole
        # only when no unrecorded user files are found inside it; a
        # ComfyUI folder accumulates outputs, extra models, and
        # custom nodes that are not the kit's to delete.
        comfy_record = state.get("comfyui", {})
        if choices.get("with_comfyui") or comfy_record:
            self._stop_comfyui()
            self.say("DONE", "C3 comfy server", "stopped")
            models_record = comfy_record.get("models") or {}
            kept_model_bytes = sum(
                int(rec.get("size") or 0) for rec in models_record.values())
            if remove_comfyui_models:
                for filename in models_record:
                    path = self._comfy_model_path(filename)
                    if path.exists():
                        path.unlink()
                self.say("DONE", "C2 comfy models",
                         "the three Z-Image-Turbo files removed")
            elif models_record:
                self.log(f"Kept: the ComfyUI models (about "
                         f"{kept_model_bytes // 1_000_000_000} GB in "
                         f"{self._comfy_app_dir() / 'models'}). Re-run "
                         "uninstall with --remove-comfyui-models to "
                         "delete them.")
            if remove_comfyui:
                portable = self._comfy_portable()
                app_dir = self._comfy_app_dir()
                user_files = []
                if app_dir.exists():
                    for sub in ("output", "custom_nodes", "input"):
                        folder = app_dir / sub
                        if folder.exists():
                            user_files.extend(
                                str(f) for f in folder.rglob("*")
                                if f.is_file())
                    models_dir = app_dir / "models"
                    if models_dir.exists():
                        recorded = {self._comfy_model_path(fn)
                                    for fn in models_record}
                        user_files.extend(
                            str(f) for f in models_dir.rglob("*")
                            if f.is_file() and f not in recorded)
                archive = self._comfy_archive_path()
                if user_files:
                    self.log("WARN  C1 comfy tree: user files were "
                             "found inside the portable tree, so the "
                             "tree is left in place; the kit will not "
                             "delete your files:")
                    for f in user_files[:10]:
                        self.log(f"  left: {f}")
                    if len(user_files) > 10:
                        self.log(f"  and {len(user_files) - 10} more")
                    if archive.exists():
                        archive.unlink()
                        self.say("DONE", "C1 comfy archive",
                                 "the downloaded archive was removed")
                else:
                    if portable.exists():
                        shutil.rmtree(portable)
                    downloads = self._comfy_root() / "downloads"
                    if downloads.exists():
                        shutil.rmtree(downloads)
                    if comfy_record.get("created_root") and \
                            self._comfy_root().exists() and \
                            not any(self._comfy_root().iterdir()):
                        self._comfy_root().rmdir()
                    self.say("DONE", "C1 comfy tree",
                             f"portable tree removed from {self._comfy_root()}")
            else:
                self.log("Kept: the ComfyUI portable tree at "
                         f"{self._comfy_portable()}. Re-run uninstall "
                         "with --remove-comfyui to remove it (user "
                         "files inside it are never deleted).")

        # OpenCode config: restore the backup byte for byte when one
        # exists; remove the kit's config when it replaced nothing;
        # leave a config the user changed after install alone.
        record = state.get("opencode_config", {})
        config_path = record.get("path")
        if config_path:
            backup = record.get("backup_path")
            if backup and p.wsl_file_exists(distro, backup):
                if p.wsl_copy_file(distro, backup, config_path):
                    restored = p.wsl_read_file(distro, config_path)
                    if restored is not None and sha256_bytes(restored) == \
                            record.get("backup_sha256"):
                        self.say("DONE", "L3 config",
                                 f"restored your previous config from {backup}")
                        p.wsl_run(distro, ["bash", "-c",
                                           f"rm -- {shlex.quote(backup)}"],
                                  timeout=30)
                    else:
                        self.log("WARN  L3 config: restore did not verify "
                                 "byte for byte; the backup is kept at "
                                 f"{backup}")
                else:
                    self.log(f"WARN  L3 config: could not copy {backup} back")
            elif record.get("installed_sha256"):
                current = p.wsl_read_file(distro, config_path)
                if current is not None and \
                        sha256_bytes(current) == record["installed_sha256"]:
                    p.wsl_run(distro, ["bash", "-c",
                                       f"rm -- {shlex.quote(config_path)}"],
                              timeout=30)
                    self.say("DONE", "L3 config",
                             "removed the kit config (it had replaced nothing)")
                elif current is not None:
                    self.log("WARN  L3 config: the config changed after "
                             "install, so it is left in place; the kit "
                             "will not delete your edits")

        # .wslconfig managed block.
        self.say("DONE", "B1 .wslconfig", self._remove_wslconfig_block()
                 + " (takes effect the next time WSL starts)")

        # Env vars: restore the recorded previous values, or unset
        # when the kit introduced them. A value the user changed
        # after install is theirs; leave it and say so.
        for name, rec in state.get("env", {}).items():
            current = p.get_user_env(name)
            previous = rec.get("previous")
            if current != rec.get("value"):
                self.log(f"WARN  W2 {name}: now {current!r}, changed "
                         "after install; left as is")
            elif previous is None:
                p.unset_user_env(name)
                self.say("DONE", f"W2 {name}", "unset")
            else:
                p.set_user_env(name, previous)
                self.say("DONE", f"W2 {name}", f"restored to {previous!r}")

        pulls, builds = self.desired_models(
            {"with_flint": bool(choices.get("with_flint", True)),
             "with_qwen": bool(choices.get("with_qwen")),
             "num_ctx": int(choices.get("num_ctx", DEFAULT_NUM_CTX))})
        if remove_models:
            for variant, _f, _c, _fam in builds:
                p.run(["ollama", "rm", variant], timeout=120)
            for tag in pulls:
                p.run(["ollama", "rm", tag], timeout=120)
            self.say("DONE", "W4/W5 models",
                     "variants and pulled models removed")
        else:
            kept_gb = sum(MODEL_BYTES[t] for t in pulls) // 1_000_000_000
            self.log(f"Kept: the pulled models (about {kept_gb} GB in "
                     "your .ollama store). Remove them any time with "
                     "ollama rm, or re-run uninstall with --remove-models.")

        if remove_ollama:
            result = p.run(["winget", "uninstall", "--id", "Ollama.Ollama",
                            "--exact", "--accept-source-agreements"],
                           timeout=900)
            if result.rc == 0:
                self.say("DONE", "W1 ollama", "uninstalled via winget")
            else:
                self.log("WARN  W1 ollama: winget uninstall did not "
                         "complete; remove Ollama from Settings, Apps")
        else:
            self.log("Kept: Ollama itself. Remove it with winget "
                     "uninstall Ollama.Ollama, or re-run uninstall "
                     "with --remove-ollama.")
            # Restart the tray so the env changes above take effect
            # for the server that stays behind.
            try:
                if p.api_probe() == "ollama":
                    p.restart_ollama_tray()
                    self.say("DONE", "W3 tray",
                             "restarted so the env changes take effect")
            except Exception:
                self.log("WARN  W3 tray: restart did not complete; "
                         "quit and relaunch Ollama from the tray")

        if state.get("wsl", {}).get("opencode_installed_by_kit"):
            self.log("Kept: OpenCode in the distro (the kit installed "
                     "it, but it is a general tool; remove it from "
                     "inside the distro if you want it gone).")

        self.state_path.unlink(missing_ok=True)
        self.say("DONE", "state", "install state removed; logs kept at "
                 f"{self.log_path}")
        return 0


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def print_plan(out=print) -> None:
    out(f"Local Models Kit manager {MANAGER_VERSION} (kit {KIT_VERSION}): install plan")
    out("Choices: the default install is the full stack (Flint, "
        "Qwen, and ComfyUI); --no-flint, --no-qwen, and "
        "--no-comfyui leave a component out (at least one model "
        "must stay). --num-ctx sets the Flint pin "
        "(default 131072, max 262144); the Qwen pin is always "
        "131072. --comfy-root sets where the portable lives.")
    out("Preflight first: Windows build, disk space, WSL and distro, "
        "network, the Ollama endpoint. All blockers print at once.")
    for step_id in STEP_ORDER:
        name, check = STEP_PLAN[step_id]
        out(f"  {step_id}  {name}")
        out(f"       check: {check}")
    out("Then doctor runs and prints PASS, WARN, FAIL per item.")


def _resolve_root(args, platform) -> Path:
    if getattr(args, "root", None):
        return Path(args.root)
    env = os.environ.get("LOCAL_MODELS_KIT_ROOT")
    if env:
        return Path(env)
    if platform is not None:
        return platform.default_install_root()
    return Path.cwd() / ".local_models_kit"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="local-models-kit",
        description="local-models-kit installer manager (see installer/README.md)")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_install = sub.add_parser("install", help="preflight, then W/B/L steps, then doctor")
    p_install.add_argument("--with-flint", action="store_true",
                           help="include the Flint model (in the default "
                                "install; also the way back in when "
                                "recorded state has it out)")
    p_install.add_argument("--no-flint", action="store_true",
                           help="leave the Flint model out of this install")
    p_install.add_argument("--with-qwen", action="store_true",
                           help="include the Qwen model (in the default "
                                "install; also the way back in when "
                                "recorded state has it out)")
    p_install.add_argument("--no-qwen", action="store_true",
                           help="leave the Qwen model out of this install")
    p_install.add_argument("--num-ctx", type=int, default=None)
    p_install.add_argument("--distro", default=None)
    p_install.add_argument("--with-comfyui", action="store_true",
                           help="include ComfyUI (in the default "
                                "install; also the way back in when "
                                "recorded state has it out)")
    p_install.add_argument("--no-comfyui", action="store_true",
                           help="leave ComfyUI out of this install")
    p_install.add_argument("--comfy-root", default=None,
                           help="where the ComfyUI portable lives "
                                "(default C:\\ComfyUI)")
    p_install.add_argument("--root", default=None)
    p_install.add_argument("--plan", action="store_true",
                           help="print the step plan and exit (runs anywhere)")

    for name in ("doctor", "repair", "update"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=None)

    p_switch = sub.add_parser(
        "switch", help="hand the GPU between the Ollama stack and ComfyUI")
    p_switch.add_argument("target", choices=["comfy", "ollama"])
    p_switch.add_argument("--root", default=None)

    p_un = sub.add_parser("uninstall")
    p_un.add_argument("--root", default=None)
    p_un.add_argument("--remove-models", action="store_true",
                      help="also remove the pulled models and built variants")
    p_un.add_argument("--remove-ollama", action="store_true",
                      help="also uninstall Ollama itself, through winget")
    p_un.add_argument("--remove-comfyui", action="store_true",
                      help="also remove the ComfyUI portable tree "
                           "(never deletes user files found inside it)")
    p_un.add_argument("--remove-comfyui-models", action="store_true",
                      help="also remove the Z-Image-Turbo model files")

    args = parser.parse_args(argv)

    if args.verb == "install" and args.plan:
        print_plan()
        return 0

    platform = build_platform()
    if platform is None and args.verb != "update":
        print(f"local-models-kit {args.verb}: this verb runs on Windows only. "
              "This host is not Windows, so nothing was touched. "
              "On this machine only 'install --plan' and the behavior "
              "suite in installer/tests/ run.", file=sys.stderr)
        return 2

    root = _resolve_root(args, platform)
    if platform is None:  # update on a non-Windows host: state lookups only
        platform = _NullPlatform()
    manager = Manager(root, platform)
    manager.retry_hint = "local-models-kit " + " ".join(argv)

    try:
        if args.verb == "install":
            with_flint = True if args.with_flint else (
                False if args.no_flint else None)
            with_qwen = True if args.with_qwen else (
                False if args.no_qwen else None)
            with_comfyui = True if args.with_comfyui else (
                False if args.no_comfyui else None)
            return manager.verb_install(with_flint=with_flint,
                                        with_qwen=with_qwen,
                                        num_ctx=args.num_ctx,
                                        distro=args.distro,
                                        with_comfyui=with_comfyui,
                                        comfy_root=args.comfy_root)
        if args.verb == "doctor":
            return manager.verb_doctor()
        if args.verb == "repair":
            return manager.verb_repair()
        if args.verb == "update":
            return manager.verb_update()
        if args.verb == "switch":
            return manager.verb_switch(args.target)
        if args.verb == "uninstall":
            return manager.verb_uninstall(
                remove_models=args.remove_models,
                remove_ollama=args.remove_ollama,
                remove_comfyui=args.remove_comfyui,
                remove_comfyui_models=args.remove_comfyui_models)
    except StepError as exc:
        manager.log(f"FAILED: {exc}")
        manager.log(f"Log: {manager.log_path}")
        manager.log(f"Retry: {manager.retry_hint}")
        return 1
    except Exception as exc:  # every failure ends with the log path
        manager.log(f"FAILED: {type(exc).__name__}: {exc}")
        manager.log(f"Log: {manager.log_path}")
        manager.log(f"Retry: {manager.retry_hint}")
        return 1
    return 0


class _NullPlatform(Platform):
    """For 'update' off Windows: answers 'nothing there' to the state
    lookups the stub makes, and refuses everything else."""

    name = "null"

    def is_windows(self) -> bool:
        return False

    def __getattr__(self, item):
        def _refuse(*a, **kw):
            raise StepError("not available on this host")
        return _refuse


if __name__ == "__main__":
    sys.exit(main())
