"""Behavior tests for the Local Models Kit manager, against a fake Windows
machine (fake_platform.py). Run from anywhere:

    python3 -m unittest discover -s installer/tests

Every test uses a fresh temp machine. The required coverage from the
installer build plan: install makes doctor healthy; a second install
is all SKIP and rewrites nothing; an injected mid-install failure
resumes from state; doctor catches a tampered config and repair
fixes it; the .wslconfig merge preserves user lines with exactly one
managed block after two installs; config substitution at 131072 and
at 262144 with Qwen held at 131072; uninstall restores a backed-up
config byte for byte and keeps models by default; uninstall on a
never-installed root is a safe no-op.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "manager"))

import local_models_kit_manager as mgr  # noqa: E402
from fake_platform import FakePlatform  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DISTRO = "Ubuntu"


class ManagerCase(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        for key in ("LOCAL_MODELS_KIT_FAIL_STEP", "WITH_FLINT", "WITH_QWEN",
                    "NUM_CTX", "WITH_COMFYUI", "LOCAL_MODELS_KIT_ROOT",
                    "LOCAL_MODELS_KIT_SOURCE_ROOT"):
            os.environ.pop(key, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.platform = FakePlatform(self.base)
        self.root = self.base / "LocalModelsKit"
        self.lines = []
        self.mgr = mgr.Manager(self.root, self.platform, out=self.lines.append)
        # A bare install is the full stack now, ComfyUI included,
        # so shrink the pinned ComfyUI sizes exactly as
        # test_comfyui's ComfyCase does (same reasoning: the
        # assertions stay self-consistent, and no test truncates
        # 21 GB of sparse files). The real pins are asserted as a
        # manifest in test_comfyui's TestComfyManifestPins.
        self._real_models = mgr.COMFY_MODELS
        self._real_archive_size = mgr.COMFY_ARCHIVE_SIZE
        self._real_models_bytes = mgr.COMFY_MODELS_BYTES
        mgr.COMFY_MODELS = {
            fn: (sub, 100_000 + 1_000 * i, sha, url)
            for i, (fn, (sub, _size, sha, url))
            in enumerate(self._real_models.items())}
        mgr.COMFY_ARCHIVE_SIZE = 2_048
        mgr.COMFY_MODELS_BYTES = sum(v[1] for v in mgr.COMFY_MODELS.values())

    def tearDown(self):
        mgr.COMFY_MODELS = self._real_models
        mgr.COMFY_ARCHIVE_SIZE = self._real_archive_size
        mgr.COMFY_MODELS_BYTES = self._real_models_bytes
        self._env.stop()
        self.tmp.cleanup()

    # ----- helpers -----

    def new_manager(self):
        self.lines = []
        self.mgr = mgr.Manager(self.root, self.platform, out=self.lines.append)
        return self.mgr

    def install(self, **kw):
        return self.mgr.verb_install(**kw)

    def config_path(self):
        return f"{self.platform.home_in_wsl}/.config/opencode/opencode.json"

    def installed_config(self):
        data = self.platform.wsl_read_file(DISTRO, self.config_path())
        self.assertIsNotNone(data, "config should be installed")
        return data

    def step_lines(self, verb):
        return [l for l in self.lines if l.startswith(verb + " ")]

    def assert_doctor_healthy(self, manager=None):
        manager = manager or self.mgr
        items = manager.doctor_items()
        fails = [i for i in items if i["status"] == "FAIL"]
        self.assertEqual(fails, [], f"doctor should be healthy: {fails}")
        return items


class TestInstall(ManagerCase):
    def test_install_makes_doctor_healthy(self):
        self.assertEqual(self.install(), 0)
        items = self.assert_doctor_healthy()
        by_name = {i["name"]: i["status"] for i in items}
        for name in ("W1 ollama", "W2 env vars", "W5 variants",
                     "B1 .wslconfig", "L2 opencode", "L3 config",
                     "L4 client smoke"):
            self.assertEqual(by_name[name], "PASS", name)
        state = json.loads((self.root / "state.json").read_bytes())
        self.assertEqual(state["kit_version"], mgr.KIT_VERSION)
        for step_id in mgr.STEP_ORDER:
            self.assertIn(step_id, state["steps"], step_id)
        self.assertEqual(self.platform.pulled,
                         ["flint", "qwen3:30b-a3b"])
        self.assertEqual(self.platform.created,
                         ["flint-opencode", "qwen-opencode"])

    def test_second_install_all_skip_and_rewrites_nothing(self):
        self.assertEqual(self.install(with_qwen=True), 0)
        watched = [self.platform.user_profile_dir() / ".wslconfig"]
        config_real = self.platform._map(DISTRO, self.config_path())
        watched.append(config_real)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}

        self.new_manager()
        self.assertEqual(self.install(with_qwen=True), 0)
        for step_id in mgr.STEP_ORDER:
            self.assertTrue(
                any(l.startswith(f"SKIP {step_id} ") for l in self.lines),
                f"{step_id} should SKIP on the second run: {self.lines}")
        self.assertEqual(self.step_lines("DONE"), [])
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}
        self.assertEqual(before, after,
                         "an idempotent rerun must not rewrite correct files")

    def test_install_resumes_after_injected_failure(self):
        with mock.patch.dict(os.environ, {"LOCAL_MODELS_KIT_FAIL_STEP": "W4"}):
            with self.assertRaises(mgr.StepError):
                self.install()
        state = json.loads((self.root / "state.json").read_bytes())
        for done_step in ("W1", "W2", "W3"):
            self.assertIn(done_step, state["steps"], done_step)
        self.assertNotIn("W4", state["steps"])
        self.assertEqual(self.platform.pulled, [])

        self.new_manager()
        self.assertEqual(self.install(), 0)
        self.assertTrue(any(l.startswith("SKIP W1 ") for l in self.lines))
        self.assertEqual(self.platform.pulled,
                         ["flint", "qwen3:30b-a3b"])
        self.assert_doctor_healthy(self.mgr)

    def test_preflight_reports_blockers_and_changes_nothing(self):
        self.platform.free_bytes = 1_000_000_000  # 1 GB: far too small
        self.assertEqual(self.install(), 1)
        self.assertTrue(any("Disk space" in l for l in self.lines))
        self.assertEqual(self.platform.pulled, [])
        self.assertFalse((self.root / "state.json").exists()
                         and json.loads((self.root / "state.json").read_bytes())
                         .get("steps"),
                         "no step may be recorded when preflight blocks")

    def test_preflight_names_a_missing_distro(self):
        self.assertEqual(self.install(distro="Debian"), 1)
        self.assertTrue(any("WSL distro" in l and "Debian" in l
                            for l in self.lines))


class TestDoctorRepair(ManagerCase):
    def test_tampered_config_is_detected_and_repaired(self):
        self.assertEqual(self.install(), 0)
        desired = self.installed_config()
        tampered = json.loads(desired)
        tampered["provider"]["ollama"]["models"]["flint-opencode:latest"][
            "limit"]["context"] = 999
        self.platform.wsl_write_file(
            DISTRO, self.config_path(),
            (json.dumps(tampered, indent=2) + "\n").encode())

        items = self.mgr.doctor_items()
        l3 = [i for i in items if i["name"] == "L3 config"]
        self.assertEqual(l3[0]["status"], "FAIL")

        self.new_manager()
        self.assertEqual(self.mgr.verb_repair(), 0)
        self.assertTrue(any(l.startswith("FIX L3 ") for l in self.lines))
        self.assertEqual(self.installed_config(), desired)
        self.assert_doctor_healthy(self.mgr)

    def test_repair_without_install_says_so(self):
        self.assertEqual(self.mgr.verb_repair(), 1)
        self.assertTrue(any("Nothing to repair" in l for l in self.lines))


class TestWslconfig(ManagerCase):
    USER_FILE = (b"# my own settings\n[wsl2]\nmemory=32GB\n"
                 b"[experimental]\nautoProxy=true\n")

    def test_merge_preserves_user_lines_and_stays_single(self):
        profile = self.platform.user_profile_dir()
        (profile / ".wslconfig").write_bytes(self.USER_FILE)
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.install(), 0)
        data = (profile / ".wslconfig").read_bytes()
        text = data.decode("utf-8")
        self.assertIn("# my own settings", text)
        self.assertIn("memory=32GB", text)
        self.assertIn("[experimental]", text)
        self.assertIn("autoProxy=true", text)
        self.assertEqual(text.count(mgr.WSLCONFIG_BEGIN), 1)
        self.assertEqual(text.count(mgr.WSLCONFIG_END), 1)
        self.assertEqual(text.count("networkingMode=mirrored"), 1)
        begin = text.index(mgr.WSLCONFIG_BEGIN)
        self.assertGreater(begin, text.index("[wsl2]"))
        self.assertLess(begin, text.index("[experimental]"))

    def test_merge_replaces_a_competing_user_value_and_restores_it(self):
        profile = self.platform.user_profile_dir()
        (profile / ".wslconfig").write_bytes(
            b"[wsl2]\nnetworkingMode=nat\nmemory=16GB\n")
        self.assertEqual(self.install(), 0)
        text = (profile / ".wslconfig").read_bytes().decode("utf-8")
        self.assertNotIn("networkingMode=nat", text)
        self.assertEqual(text.count("networkingMode=mirrored"), 1)
        self.assertIn("memory=16GB", text)
        self.assertEqual(self.mgr.verb_uninstall(), 0)
        text = (profile / ".wslconfig").read_bytes().decode("utf-8")
        self.assertIn("networkingMode=nat", text)
        self.assertNotIn("local-models-kit managed", text)
        self.assertIn("memory=16GB", text)


class TestConfigSubstitution(ManagerCase):
    def contexts(self, cfg):
        out = {}
        for key, model in cfg["provider"]["ollama"]["models"].items():
            out[key] = (model["limit"]["context"], model["name"])
        return out

    def assert_config_shape(self, cfg, flint_ctx, flint_label):
        for pname, provider in cfg["provider"].items():
            self.assertEqual(sorted(provider["whitelist"]),
                             sorted(provider["models"].keys()),
                             f"{pname} whitelist must match its declared models")
            models = provider["models"]
            self.assertEqual(
                models["flint-opencode:latest"]["limit"]["context"], flint_ctx,
                f"{pname} Flint context")
            self.assertEqual(
                models["qwen-opencode:latest"]["limit"]["context"], 131072,
                f"{pname} Qwen context must stay at its ceiling")
        ctxs = self.contexts(cfg)
        self.assertEqual(ctxs["flint-opencode:latest"],
                         (flint_ctx, f"Flint 40B, context-pinned {flint_label}"))
        self.assertEqual(ctxs["qwen-opencode:latest"][0], 131072)
        self.assertIn("128K", ctxs["qwen-opencode:latest"][1])

    def test_default_131072(self):
        self.assertEqual(self.install(with_qwen=True), 0)
        cfg = json.loads(self.installed_config())
        self.assert_config_shape(cfg, 131072, "128K")
        self.assertEqual(
            self.platform.tags["flint-opencode:latest"]["num_ctx"], 131072)
        self.assertEqual(
            self.platform.tags["qwen-opencode:latest"]["num_ctx"], 131072)

    def test_flint_262144_qwen_held(self):
        self.assertEqual(self.install(with_qwen=True, num_ctx=262144), 0)
        cfg = json.loads(self.installed_config())
        self.assert_config_shape(cfg, 262144, "256K")
        self.assertEqual(
            self.platform.tags["flint-opencode:latest"]["num_ctx"], 262144)
        self.assertEqual(
            self.platform.tags["qwen-opencode:latest"]["num_ctx"], 131072)

    def test_num_ctx_above_flint_ceiling_is_refused(self):
        with self.assertRaises(mgr.StepError):
            self.install(num_ctx=524288)


class TestUninstall(ManagerCase):
    ORIGINAL = b'{"user": "mine", "custom": true}\n'

    def preseed_config(self):
        self.platform.wsl_write_file(DISTRO, self.config_path(), self.ORIGINAL)

    def test_uninstall_restores_backup_and_keeps_models(self):
        self.preseed_config()
        self.assertEqual(self.install(with_qwen=True), 0)
        self.assertNotEqual(self.installed_config(), self.ORIGINAL)
        state = json.loads((self.root / "state.json").read_bytes())
        self.assertTrue(state["opencode_config"]["backup_path"])

        self.assertEqual(self.mgr.verb_uninstall(), 0)
        restored = self.platform.wsl_read_file(DISTRO, self.config_path())
        self.assertEqual(restored, self.ORIGINAL,
                         "the backed-up config must return byte for byte")
        self.assertIn("flint:latest", self.platform.tags)
        self.assertIn("qwen3:30b-a3b", self.platform.tags)
        self.assertEqual(self.platform.env, {},
                         "kit env vars are unset again (none pre-existed)")
        self.assertFalse((self.root / "state.json").exists())
        self.assertTrue(any("Kept: the pulled models" in l
                            for l in self.lines))

    def test_uninstall_with_remove_models_flag(self):
        self.assertEqual(self.install(with_qwen=True), 0)
        self.assertEqual(
            self.mgr.verb_uninstall(remove_models=True), 0)
        self.assertEqual(self.platform.tags, {})
        self.assertIn("flint", self.platform.removed)

    def test_uninstall_never_installed_is_a_noop(self):
        self.assertEqual(self.mgr.verb_uninstall(), 0)
        self.assertTrue(any("SKIP uninstall" in l for l in self.lines))
        self.assertEqual(self.platform.tags, {})
        self.assertEqual(self.platform.env, {})

    def test_uninstall_restores_a_preexisting_env_value(self):
        self.platform.env[mgr.ENV_MAX_LOADED] = "3"
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.platform.env[mgr.ENV_MAX_LOADED], "1")
        self.assertEqual(self.mgr.verb_uninstall(), 0)
        self.assertEqual(self.platform.env.get(mgr.ENV_MAX_LOADED), "3")


class TestOpenCodeL2(ManagerCase):
    """Regression coverage for the 2026-11-22 incident: L2 trusted
    a login shell's PATH, called a healthy OpenCode 2 install
    missing, and reinstalled it from the OpenCode 1 installer URL,
    downgrading it to a build that could not read its database.
    The rules under test: an existing canonical binary is never
    reinstalled over, a broken login PATH is repaired in
    ~/.profile, and the only installer command is the v2 one."""

    def profile_path(self):
        return f"{self.platform.home_in_wsl}/.profile"

    def curl_commands(self):
        return [argv for argv in self.platform.wsl_commands
                if any("curl" in str(a) for a in argv)]

    def test_existing_binary_broken_path_repairs_profile_no_installer(self):
        # The incident machine: OpenCode 2.0.26 at the canonical
        # path, interactive shells find it, cold login shells do not.
        self.platform.seed_opencode(DISTRO, "2.0.26", on_path=False)
        status, detail = self.mgr.check_l2()
        self.assertNotEqual(status, "ok")
        self.assertIn("2.0.26", detail)
        self.assertIn("cannot find", detail)

        self.assertEqual(self.install(), 0)
        self.assertEqual(self.curl_commands(), [],
                         "no installer may run over an existing binary")
        self.assertEqual(self.platform.opencode_binary[DISTRO], "2.0.26",
                         "the user's version is untouched")
        profile = self.platform.wsl_read_file(DISTRO, self.profile_path())
        self.assertIsNotNone(profile)
        text = profile.decode("utf-8")
        self.assertEqual(text.count(mgr.OPENCODE_PATH_BEGIN), 1)
        self.assertIn('export PATH="$HOME/.opencode/bin:$PATH"', text)
        state = json.loads((self.root / "state.json").read_bytes())
        self.assertEqual(state["wsl"]["opencode_path_fix"], "~/.profile")
        self.assertNotIn("opencode_installed_by_kit", state["wsl"])
        self.assertEqual(state["wsl"]["opencode_version"], "2.0.26")
        status, _detail = self.mgr.check_l2()
        self.assertEqual(status, "ok")
        self.assert_doctor_healthy()

    def test_profile_fix_is_idempotent(self):
        self.platform.seed_opencode(DISTRO, "2.0.26", on_path=False)
        self.mgr.apply_l2()
        # Second apply: the PATH probe now answers, so it is a
        # no-op and writes nothing.
        profile_real = self.platform._map(DISTRO, self.profile_path())
        before = (profile_real.read_bytes(), profile_real.stat().st_mtime_ns)
        self.mgr.apply_l2()
        after = (profile_real.read_bytes(), profile_real.stat().st_mtime_ns)
        self.assertEqual(before, after)
        text = profile_real.read_bytes().decode("utf-8")
        self.assertEqual(text.count(mgr.OPENCODE_PATH_BEGIN), 1)
        self.assertEqual(self.curl_commands(), [])

    def test_profile_block_present_but_login_still_broken_fails_loudly(self):
        # The block is already in ~/.profile (written directly, so
        # the fake's PATH state does not move) yet login shells
        # still cannot find the binary: a shadowing ~/.bash_profile
        # is the real-world shape. Apply must fail with the precise
        # message, not fall back to an installer.
        self.platform.seed_opencode(DISTRO, "2.0.26", on_path=False)
        profile_real = self.platform._map(DISTRO, self.profile_path())
        profile_real.write_bytes(mgr.OPENCODE_PATH_BLOCK.encode("utf-8"))
        with self.assertRaises(mgr.StepError) as caught:
            self.mgr.apply_l2()
        self.assertIn("still", str(caught.exception))
        self.assertIn("bash_profile", str(caught.exception))
        self.assertEqual(self.curl_commands(), [])

    def test_no_binary_anywhere_installs_from_the_v2_url(self):
        self.assertEqual(self.install(), 0)
        installers = [argv for argv in self.platform.wsl_commands
                      if any("opencode.ai" in str(a) for a in argv)]
        self.assertEqual(
            installers,
            [["bash", "-lc",
              "curl -fsSL https://opencode.ai/v2/install | bash"]])
        state = json.loads((self.root / "state.json").read_bytes())
        self.assertTrue(state["wsl"]["opencode_installed_by_kit"])
        self.assertEqual(state["wsl"]["opencode_version"], "2.0.26")

    def test_existing_binary_healthy_path_is_left_alone(self):
        self.platform.seed_opencode(DISTRO, "2.0.26", on_path=True)
        status, _detail = self.mgr.check_l2()
        self.assertEqual(status, "ok")
        self.assertEqual(self.install(), 0)
        self.assertTrue(any(l.startswith("SKIP L2 ") for l in self.lines),
                        self.lines)
        self.assertEqual(self.curl_commands(), [])
        self.assertIsNone(
            self.platform.wsl_read_file(DISTRO, self.profile_path()),
            "no .profile fix is written when PATH already works")

    def test_version_output_is_normalized(self):
        # OpenCode 2 answers --version as 'opencode v2.0.26'. The
        # kit records and reports the bare version; the first live
        # Biff run printed 'opencode opencode v2.0.26' before this
        # normalization existed.
        self.platform.seed_opencode(DISTRO, "opencode v2.0.26",
                                    on_path=True)
        status, detail = self.mgr.check_l2()
        self.assertEqual(status, "ok")
        self.assertIn("opencode 2.0.26", detail)
        self.assertNotIn("opencode opencode", detail)
        self.assertNotIn("v2.0.26", detail)

    def test_binary_file_present_but_silent_is_never_replaced(self):
        # A binary file at the canonical path that does not answer
        # --version (corrupt, or caught mid-update). The standing
        # standing rule: never, under any circumstances, downgrade
        # or replace an installed OpenCode. The file's presence is
        # an install's presence: drifted, apply refuses, and no
        # installer command is ever issued.
        target = self.platform._map(
            DISTRO, f"{self.platform.home_in_wsl}/.opencode/bin/opencode")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake opencode binary\n")
        status, detail = self.mgr.check_l2()
        self.assertEqual(status, "drifted")
        self.assertIn("will not replace", detail)
        with self.assertRaises(mgr.StepError) as caught:
            self.mgr.apply_l2()
        self.assertIn("never replaces or downgrades",
                      str(caught.exception))
        self.assertEqual(self.curl_commands(), [])

    def test_opencode_on_path_without_canonical_binary_is_ok(self):
        self.platform.seed_opencode(DISTRO, "9.9.9", on_path=True,
                                    canonical=False)
        status, detail = self.mgr.check_l2()
        self.assertEqual(status, "ok")
        self.assertIn("9.9.9", detail)
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.curl_commands(), [],
                         "an install found on PATH is the user's to keep")


class TestDefaultChoices(ManagerCase):
    """The kit's default install is the full stack (maintainer
    rulings, 2026-11-22): Flint, Qwen, and ComfyUI, and the
    opt-outs are the --no-* flags (the --without-* spellings are
    gone). Explicit flags beat recorded state in both directions:
    a recorded opt-out is exactly why the --with-* flags remain."""

    def test_bare_choices_are_the_full_stack(self):
        choices = self.mgr.resolve_choices()
        self.assertTrue(choices["with_flint"])
        self.assertTrue(choices["with_qwen"])
        self.assertTrue(choices["with_comfyui"])

    def test_flag_opt_outs_win_over_the_default(self):
        # A fresh manager per assertion: resolve_choices records
        # its result, so sequential opt-outs on one manager would
        # accumulate (and two model opt-outs together are an error).
        self.assertFalse(
            self.mgr.resolve_choices(with_flint=False)["with_flint"])
        self.assertFalse(
            self.new_manager().resolve_choices(with_qwen=False)["with_qwen"])
        self.assertFalse(self.new_manager().resolve_choices(
            with_comfyui=False)["with_comfyui"])

    def test_no_flags_beat_a_recorded_true(self):
        self.mgr.resolve_choices()
        self.mgr.save_state()
        self.assertFalse(
            self.new_manager().resolve_choices(with_flint=False)["with_flint"])
        self.assertFalse(
            self.new_manager().resolve_choices(with_qwen=False)["with_qwen"])
        self.assertFalse(self.new_manager().resolve_choices(
            with_comfyui=False)["with_comfyui"])

    def test_with_flags_beat_a_recorded_false(self):
        self.mgr.resolve_choices(with_qwen=False)
        self.mgr.save_state()
        self.assertTrue(
            self.new_manager().resolve_choices(with_qwen=True)["with_qwen"])

        self.mgr.resolve_choices(with_flint=False, with_qwen=True)
        self.mgr.save_state()
        self.assertTrue(
            self.new_manager().resolve_choices(with_flint=True)["with_flint"])

        self.mgr.resolve_choices(with_comfyui=False)
        self.mgr.save_state()
        self.assertTrue(self.new_manager().resolve_choices(
            with_comfyui=True)["with_comfyui"])

    def test_recorded_opt_out_wins_over_the_default(self):
        self.mgr.resolve_choices(with_qwen=False, with_comfyui=False)
        self.mgr.save_state()
        choices = self.new_manager().resolve_choices()
        self.assertFalse(choices["with_qwen"])
        self.assertFalse(choices["with_comfyui"])

    def test_env_opt_outs_win_over_the_default(self):
        # One model at a time: env-opting both models out together
        # is the both-models-out error, tested separately below.
        with mock.patch.dict(os.environ, {"WITH_FLINT": "0",
                                          "WITH_COMFYUI": "0"}):
            choices = self.mgr.resolve_choices()
        self.assertFalse(choices["with_flint"])
        self.assertFalse(choices["with_comfyui"])
        self.assertTrue(choices["with_qwen"])
        with mock.patch.dict(os.environ, {"WITH_QWEN": "0"}):
            choices = self.new_manager().resolve_choices()
        self.assertFalse(choices["with_qwen"])
        self.assertTrue(choices["with_flint"])

    def test_both_models_out_is_an_error(self):
        with self.assertRaises(mgr.StepError) as caught:
            self.mgr.resolve_choices(with_flint=False, with_qwen=False)
        self.assertIn("--no-flint", str(caught.exception))
        self.assertIn("--no-qwen", str(caught.exception))

    def test_recorded_opt_out_plus_flag_reaches_both_models_out(self):
        self.mgr.resolve_choices(with_qwen=False)
        self.mgr.save_state()
        with self.assertRaises(mgr.StepError):
            self.new_manager().resolve_choices(with_flint=False)


class TestRenderConfigChoices(ManagerCase):
    """The rendered config advertises only the chosen models, in
    both providers, and defaults to the first chosen variant."""

    def test_flint_out_removes_flint_everywhere(self):
        cfg = json.loads(mgr.render_config(131072, with_flint=False))
        self.assertEqual(cfg["model"], "ollama/qwen-opencode:latest")
        for provider in cfg["provider"].values():
            self.assertFalse(any(k.startswith("flint")
                                 for k in provider["models"]))
            self.assertFalse(any(k.startswith("flint")
                                 for k in provider["whitelist"]))
            self.assertEqual(provider["whitelist"],
                             list(provider["models"].keys()))
            qwen = provider["models"]["qwen-opencode:latest"]
            self.assertEqual(qwen["limit"]["context"], 131072)

    def test_qwen_out_removes_qwen_everywhere(self):
        cfg = json.loads(mgr.render_config(131072, with_qwen=False))
        self.assertEqual(cfg["model"], "ollama/flint-opencode:latest")
        for provider in cfg["provider"].values():
            self.assertFalse(any(k.startswith("qwen")
                                 for k in provider["models"]))
            self.assertFalse(any(k.startswith("qwen")
                                 for k in provider["whitelist"]))
            self.assertEqual(provider["whitelist"],
                             list(provider["models"].keys()))
            self.assertIn("flint-opencode:latest", provider["models"])

    def test_flint_out_keeps_qwen_at_its_own_pin(self):
        cfg = json.loads(mgr.render_config(262144, with_flint=False))
        for provider in cfg["provider"].values():
            qwen = provider["models"]["qwen-opencode:latest"]
            self.assertEqual(qwen["limit"]["context"], 131072)


class TestNoFlintInstall(ManagerCase):
    def test_install_without_flint_runs_on_qwen_only(self):
        self.assertEqual(self.install(with_flint=False), 0)
        self.assertEqual(self.platform.pulled, ["qwen3:30b-a3b"])
        self.assertEqual(self.platform.created, ["qwen-opencode"])
        self.assert_doctor_healthy()
        cfg = json.loads(self.installed_config())
        self.assertEqual(cfg["model"], "ollama/qwen-opencode:latest")
        for provider in cfg["provider"].values():
            self.assertFalse(any(k.startswith("flint")
                                 for k in provider["models"]))
            self.assertFalse(any(k.startswith("flint")
                                 for k in provider["whitelist"]))
        state = json.loads((self.root / "state.json").read_bytes())
        self.assertFalse(state["choices"]["with_flint"])
        self.assertTrue(state["choices"]["with_qwen"])


class TestStubsAndCli(ManagerCase):
    def test_update_is_an_honest_stub(self):
        self.assertEqual(self.mgr.verb_update(), 0)
        joined = "\n".join(self.lines)
        self.assertIn("not implemented yet", joined)
        self.assertIn("releases", joined)

    def test_plan_prints_the_step_inventory(self):
        lines = []
        mgr.print_plan(out=lines.append)
        joined = "\n".join(lines)
        for step_id in mgr.STEP_ORDER:
            self.assertIn(step_id, joined)

    def test_real_verbs_refuse_off_windows(self):
        if sys.platform == "win32":
            self.skipTest("the refusal only applies off Windows")
        self.assertEqual(mgr.main(["doctor", "--root", str(self.root)]), 2)
        self.assertEqual(mgr.main(["install", "--plan"]), 0)


class TestTemplates(ManagerCase):
    def test_embedded_templates_match_the_repo_files(self):
        # .gitattributes pins LF checkouts; the replace keeps the
        # guard honest on a clone made before it, where a Windows
        # checkout may already carry CRLF in the working tree.
        def repo_text(rel):
            return (REPO_ROOT / rel).read_bytes().decode("utf-8") \
                .replace("\r\n", "\n")
        flint = repo_text("models/Modelfile.flint-opencode")
        qwen = repo_text("models/Modelfile.qwen-opencode")
        config = repo_text("config/opencode.json")
        self.assertEqual(mgr.FLINT_MODELF_TEMPLATE, flint)
        self.assertEqual(mgr.QWEN_MODELF_TEMPLATE, qwen)
        self.assertEqual(mgr.CONFIG_TEMPLATE_JSON, config)

    def test_rendered_default_config_matches_the_repo_template(self):
        repo_cfg = json.loads((REPO_ROOT / "config" / "opencode.json")
                              .read_bytes())
        rendered = json.loads(mgr.render_config(131072))
        self.assertEqual(rendered, repo_cfg)


if __name__ == "__main__":
    unittest.main()
