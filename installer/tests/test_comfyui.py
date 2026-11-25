"""Behavior tests for the ComfyUI fold-in (manager 0.2.0), against
the same fake Windows machine as test_manager.py. Run from anywhere:

    python3 -m unittest discover -s installer/tests

Coverage: a ComfyUI install makes doctor healthy and records the
pins in state; a second install is all SKIP and rewrites nothing;
ComfyUI is part of the default install, and opting out with
--no-comfyui records its steps as skipped; a missing
model file is repaired by re-download; a CPU-only Gate 1 makes
doctor FAIL; preflight refuses a ComfyUI install on low disk and
changes nothing; switch unloads Ollama before starting ComfyUI and
refuses when the unload does not take; switch back stops ComfyUI
and restarts the tray; the VRAM conflict row appears only when both
stacks are resident; uninstall keeps models and user files by
default, removes models on its flag, and refuses to delete a tree
that holds user files; the smoke workflow template drift guard.
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


class ComfyCase(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        for key in ("LOCAL_MODELS_KIT_FAIL_STEP", "WITH_QWEN", "NUM_CTX",
                    "WITH_COMFYUI", "LOCAL_MODELS_KIT_ROOT", "LOCAL_MODELS_KIT_SOURCE_ROOT"):
            os.environ.pop(key, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.platform = FakePlatform(self.base)
        self.root = self.base / "LocalModelsKit"
        self.lines = []
        self.mgr = mgr.Manager(self.root, self.platform, out=self.lines.append)
        # Shrink the pinned sizes for the fake machine. Every size
        # assertion in this suite is self-consistent (files are
        # compared against the same constants the manager checks),
        # and truncating 21 GB of sparse files per install is slow
        # enough on NTFS to stall the Windows CI job for minutes.
        # The real pins stay in the manager and are asserted as a
        # manifest in TestComfyTemplate.
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

    def install_comfy(self):
        return self.mgr.verb_install(with_comfyui=True)

    def state(self):
        return json.loads((self.root / "state.json").read_bytes())

    def comfy_root(self):
        return self.platform.default_comfy_root()

    def portable(self):
        return self.comfy_root() / mgr.COMFY_PORTABLE_DIRNAME

    def model_path(self, filename):
        subdir = mgr.COMFY_MODELS[filename][0]
        return self.portable() / "ComfyUI" / "models" / subdir / filename

    def doctor_row(self, name, manager=None):
        manager = manager or self.mgr
        rows = [i for i in manager.doctor_items() if i["name"] == name]
        self.assertEqual(len(rows), 1, f"doctor row {name}: {rows}")
        return rows[0]


class TestComfyInstall(ComfyCase):
    def test_install_with_comfyui_healthy_and_recorded(self):
        self.assertEqual(self.install_comfy(), 0)
        fails = [i for i in self.mgr.doctor_items() if i["status"] == "FAIL"]
        self.assertEqual(fails, [], f"doctor should be healthy: {fails}")
        state = self.state()
        for step_id in ("C1", "C2", "C3", "C4"):
            self.assertIn(step_id, state["steps"], step_id)
        record = state["comfyui"]
        self.assertEqual(record["version"], mgr.COMFY_VERSION)
        self.assertEqual(record["archive_sha256"], mgr.COMFY_ARCHIVE_SHA256)
        self.assertEqual(set(record["models"]), set(mgr.COMFY_MODELS))
        self.assertIn("Radeon", record["gate1"]["device"])
        self.assertGreaterEqual(record["gate1"]["vram_total"],
                                mgr.COMFY_MIN_VRAM)
        self.assertTrue(record["gate2"]["prompt_id"])
        self.assertEqual(record["gate2"]["peak_vram"], 23_000_000_000)
        urls = {url for url, _dest, _size in self.platform.downloads}
        self.assertIn(mgr.COMFY_ARCHIVE_URL, urls)
        for _fn, (_sub, _size, _sha, url) in mgr.COMFY_MODELS.items():
            self.assertIn(url, urls)
        self.assertEqual(len(self.platform.extractions), 1)
        for filename in mgr.COMFY_MODELS:
            self.assertEqual(self.model_path(filename).stat().st_size,
                             mgr.COMFY_MODELS[filename][1], filename)

    def test_second_install_comfy_all_skip_rewrites_nothing(self):
        self.assertEqual(self.install_comfy(), 0)
        watched = [self.portable() / mgr.COMFY_LAUNCHER,
                   self.model_path("ae.safetensors")]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}
        downloads_before = len(self.platform.downloads)

        self.new_manager()
        self.assertEqual(self.install_comfy(), 0)
        for step_id in ("C1", "C2", "C3", "C4"):
            self.assertTrue(
                any(l.startswith(f"SKIP {step_id} ") for l in self.lines),
                f"{step_id} should SKIP: {self.lines}")
        self.assertEqual(len(self.platform.downloads), downloads_before)
        self.assertEqual(len(self.platform.extractions), 1)
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}
        self.assertEqual(before, after)

    def test_hand_install_is_adopted_not_redownloaded(self):
        # Simulate the hand install this fold-in was built from: the
        # portable tree and all three models already at the kit root,
        # and no kit state at all.
        hand_archive = self.base / "by-hand.7z"
        hand_archive.write_bytes(b"extracted by hand, long ago")
        self.platform.extract_archive(hand_archive, self.comfy_root())
        for filename, (subdir, size, sha, url) in mgr.COMFY_MODELS.items():
            self.platform.download_file(url, self.model_path(filename),
                                        size, sha)
        self.platform.downloads.clear()
        self.platform.extractions.clear()

        self.assertEqual(self.install_comfy(), 0)
        self.assertTrue(any(l.startswith("SKIP C1 ") for l in self.lines),
                        self.lines)
        self.assertTrue(any(l.startswith("SKIP C2 ") for l in self.lines),
                        self.lines)
        self.assertEqual(self.platform.downloads, [],
                         "adoption must not re-download anything")
        self.assertEqual(self.platform.extractions, [],
                         "adoption must not re-extract over a working tree")
        record = self.state()["comfyui"]
        self.assertTrue(record["adopted"])
        self.assertFalse(record["created_root"])
        self.assertEqual(record["version"], mgr.COMFY_VERSION)

    def test_comfy_opt_out_records_skipped(self):
        self.assertEqual(self.mgr.verb_install(with_comfyui=False), 0)
        state = self.state()
        for step_id in ("C1", "C2", "C3", "C4"):
            self.assertEqual(state["steps"][step_id]["status"], "skipped")
        self.assertFalse(self.comfy_root().exists(),
                         "an Ollama-only install must not create a ComfyUI root")
        names = {i["name"] for i in self.mgr.doctor_items()}
        self.assertNotIn("C1 comfy install", names)
        self.assertEqual(self.platform.downloads, [])

    def test_preflight_comfy_low_disk_refuses_and_changes_nothing(self):
        self.platform.free_bytes = 1_000_000_000
        self.assertEqual(self.mgr.verb_install(with_comfyui=True), 1)
        self.assertTrue(any("Disk space (ComfyUI)" in l for l in self.lines))
        self.assertEqual(self.platform.downloads, [])
        self.assertFalse(self.comfy_root().exists())

    def test_download_failure_surfaces_at_c1(self):
        self.platform.comfy_download_fails = True
        with self.assertRaises(mgr.StepError):
            self.install_comfy()
        state = self.state()
        self.assertNotIn("C1", state["steps"])


class TestComfyDoctorRepair(ComfyCase):
    def test_missing_model_is_repaired(self):
        self.assertEqual(self.install_comfy(), 0)
        target = self.model_path("qwen_3_4b.safetensors")
        target.unlink()
        downloads_before = len(self.platform.downloads)

        self.new_manager()
        self.assertEqual(self.mgr.verb_repair(), 0)
        self.assertTrue(any(l.startswith("FIX C2 ") for l in self.lines),
                        self.lines)
        self.assertEqual(target.stat().st_size,
                         mgr.COMFY_MODELS["qwen_3_4b.safetensors"][1])
        new_downloads = self.platform.downloads[downloads_before:]
        self.assertEqual(len(new_downloads), 1)
        self.assertIn("qwen_3_4b", new_downloads[0][0])

    def test_cpu_only_gate1_fails_doctor(self):
        self.assertEqual(self.install_comfy(), 0)
        self.platform.comfy_cpu_only = True
        row = self.doctor_row("C3 comfy server")
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("CPU-only", row["detail"])

    def test_conflict_row_only_when_both_resident(self):
        self.assertEqual(self.install_comfy(), 0)
        # After the C4 smoke the fake holds 23 GB of VRAM, so ComfyUI
        # counts as resident; with no Ollama model loaded there is
        # still no conflict.
        self.assertEqual(self.doctor_row("VRAM conflict")["status"], "PASS")
        self.platform.ps_models = [{
            "name": "flint-opencode:latest",
            "context_length": 131072, "size_vram": 25_000_000_000}]
        self.assertEqual(self.doctor_row("VRAM conflict")["status"], "WARN")


class TestSwitch(ComfyCase):
    def test_switch_comfy_unloads_ollama_then_starts(self):
        self.assertEqual(self.install_comfy(), 0)
        self.platform.comfy_running = False  # user had closed ComfyUI
        self.platform.comfy_vram_free = self.platform.comfy_vram_total
        self.platform.ps_models = [{
            "name": "flint-opencode:latest",
            "context_length": 131072, "size_vram": 25_000_000_000}]

        self.assertEqual(self.mgr.verb_switch("comfy"), 0)
        self.assertEqual(self.platform.comfy_unload_calls,
                         [{"model": "flint-opencode:latest",
                           "keep_alive": 0}])
        self.assertEqual(self.platform.ps_models, [])
        self.assertTrue(self.platform.comfy_running)
        self.assertEqual(self.state()["last_switch"]["target"], "comfy")

    def test_switch_comfy_refuses_when_unload_does_not_take(self):
        self.assertEqual(self.install_comfy(), 0)
        self.platform.comfy_running = False
        self.platform.ps_models = [{
            "name": "flint-opencode:latest",
            "context_length": 131072, "size_vram": 25_000_000_000}]
        original_post = self.platform.api_post

        def deaf_post(path, payload, timeout=10):
            if path == "/api/generate":
                return {"done": True}  # accepts, but unloads nothing
            return original_post(path, payload, timeout=timeout)

        self.platform.api_post = deaf_post
        with self.assertRaises(mgr.StepError):
            self.mgr.verb_switch("comfy")
        self.assertFalse(self.platform.comfy_running,
                         "ComfyUI must not start on top of a loaded model")

    def test_switch_ollama_stops_comfy_and_restarts_tray(self):
        self.assertEqual(self.install_comfy(), 0)
        restarts_before = self.platform.tray_restarts
        self.assertEqual(self.mgr.verb_switch("ollama"), 0)
        self.assertFalse(self.platform.comfy_running)
        self.assertTrue(self.platform.comfy_free_calls,
                        "switch should ask ComfyUI to free its models first")
        self.assertTrue(any("ComfyUI_windows_portable" in f
                            for f in self.platform.stopped_fragments))
        self.assertGreater(self.platform.tray_restarts, restarts_before)
        self.assertEqual(self.platform.api_probe(), "ollama")
        self.assertEqual(self.state()["last_switch"]["target"], "ollama")

    def test_switch_without_install_says_so(self):
        self.assertEqual(self.mgr.verb_switch("comfy"), 1)
        self.assertTrue(any("Nothing to switch" in l for l in self.lines))

    def test_switch_comfy_requires_the_component(self):
        self.assertEqual(self.mgr.verb_install(with_comfyui=False), 0)
        with self.assertRaises(mgr.StepError):
            self.mgr.verb_switch("comfy")


class TestComfyUninstall(ComfyCase):
    def test_uninstall_default_keeps_models_tree_and_user_files(self):
        self.assertEqual(self.install_comfy(), 0)
        output = self.portable() / "ComfyUI" / "output" / "my picture.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"user art, not the kit's")
        self.assertEqual(self.mgr.verb_uninstall(), 0)
        self.assertFalse(self.platform.comfy_running,
                         "uninstall stops the ComfyUI server first")
        for filename in mgr.COMFY_MODELS:
            self.assertTrue(self.model_path(filename).exists(), filename)
        self.assertEqual(output.read_bytes(), b"user art, not the kit's")
        self.assertTrue(self.portable().exists())
        self.assertTrue(any("Kept: the ComfyUI models" in l
                            for l in self.lines))
        self.assertFalse((self.root / "state.json").exists())

    def test_uninstall_remove_comfyui_models_only(self):
        self.assertEqual(self.install_comfy(), 0)
        self.assertEqual(
            self.mgr.verb_uninstall(remove_comfyui_models=True), 0)
        for filename in mgr.COMFY_MODELS:
            self.assertFalse(self.model_path(filename).exists(), filename)
        self.assertTrue(self.portable().exists(),
                        "the tree stays without --remove-comfyui")

    def test_uninstall_remove_comfyui_takes_the_tree(self):
        self.assertEqual(self.install_comfy(), 0)
        self.assertEqual(
            self.mgr.verb_uninstall(remove_comfyui=True,
                                    remove_comfyui_models=True), 0)
        self.assertFalse(self.portable().exists())
        self.assertFalse(self.comfy_root().exists(),
                         "a kit-created root with nothing left goes too")

    def test_uninstall_remove_comfyui_spares_user_files(self):
        self.assertEqual(self.install_comfy(), 0)
        output = self.portable() / "ComfyUI" / "output" / "keep me.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mine")
        self.assertEqual(self.mgr.verb_uninstall(remove_comfyui=True), 0)
        self.assertTrue(output.exists(),
                        "user files inside the tree are never deleted")
        self.assertTrue(any("WARN  C1 comfy tree" in l for l in self.lines),
                        self.lines)


class TestComfyTemplate(ComfyCase):
    def test_smoke_workflow_embedded_matches_live_file(self):
        live = (REPO_ROOT / "installer" / "templates"
                / "z_image_turbo_smoke.json").read_bytes().decode("utf-8") \
            .replace("\r\n", "\n")
        self.assertEqual(mgr.COMFY_SMOKE_WORKFLOW_TEMPLATE, live)
        loaded = mgr.load_template_text(
            "installer/templates/z_image_turbo_smoke.json",
            mgr.COMFY_SMOKE_WORKFLOW_TEMPLATE)
        self.assertEqual(loaded.replace("\r\n", "\n"), live)

    def test_smoke_workflow_shape_and_neutral_prompt(self):
        wf = json.loads(mgr.COMFY_SMOKE_WORKFLOW_TEMPLATE)
        classes = {node["class_type"] for node in wf.values()}
        for want in ("UNETLoader", "CLIPLoader", "VAELoader",
                     "CLIPTextEncode", "ConditioningZeroOut",
                     "EmptySD3LatentImage", "ModelSamplingAuraFlow",
                     "KSampler", "VAEDecode", "SaveImage"):
            self.assertIn(want, classes)
        sampler = [n for n in wf.values()
                   if n["class_type"] == "KSampler"][0]
        self.assertEqual(sampler["inputs"]["steps"], 8)
        self.assertEqual(sampler["inputs"]["cfg"], 1.0)
        self.assertEqual(sampler["inputs"]["sampler_name"], "res_multistep")
        prompt = [n for n in wf.values()
                  if n["class_type"] == "CLIPTextEncode"][0]["inputs"]["text"]
        self.assertEqual(
            prompt,
            "A matte grey cube on a white table, soft studio light, "
            "plain background")


class TestComfyManifestPins(unittest.TestCase):
    """The real download pins, asserted literally. ComfyCase shrinks
    the sizes on its fake machine, so the production values need a
    guard that never runs under the shrink."""

    def test_model_manifest_pins(self):
        self.assertEqual(mgr.COMFY_MODELS, {
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
        })

    def test_archive_pin(self):
        self.assertEqual(mgr.COMFY_VERSION, "0.46.0")
        self.assertEqual(mgr.COMFY_ARCHIVE_SIZE, 1_702_415_528)
        self.assertEqual(
            mgr.COMFY_ARCHIVE_SHA256,
            "00f42ed58381e194892b74e9085d4d5666fac1aab8f021094c3a745e9b52ad97")


if __name__ == "__main__":
    unittest.main()
