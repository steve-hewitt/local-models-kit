# Validation ledger

Every load-bearing claim in this kit carries one of these labels:

- **Validated**: run by us, on real hardware, output seen.
- **Doc-verified**: read in the primary source on the date noted.
- **Publisher-reported**: the vendor or lab's own numbers.
- **Unvalidated**: plausible, but not proven here.

**What this proves:** both models are declared under both providers at
identical limits and installed by the default manager; the installer and the
direct path ran end to end on the target hardware; a from-empty installer run
(2026-11-26, Python manager) passed the ComfyUI GPU gates as well. The
Headroom toggle ran live on hardware 2026-11-26, and hello-agent went green
via both the direct path (Qwen) and the wrapped path (Flint) the same day;
every hands-on checklist box below is now checked. Still open: `switch` and
the compare-harness ranking are unvalidated, the new kit's own `uninstall`,
`repair`, the compiled EXE, and the all-Windows topology are unrun, and two
claims failed on the fresh install (the picker whitelist does not hide base
tags, and `launch-headroom.sh` carries a flag Headroom 0.41.0 no longer
accepts for opencode).

Last updated: 2026-11-26.

## Claims

| Claim | Label | Source / date |
| --- | --- | --- |
| Flint exists on Ollama as `flint`, 39.8B params, ~2.5B active, 262K context, Apache 2.0, tools + thinking | Doc-verified | Ollama library page for flint, 2026-10-22 |
| `ollama run flint` and `ollama launch opencode --model flint` are the documented entry points | Doc-verified | Same page, 2026-10-22 |
| Default `flint` download is 23 GB; q4 variant 26 GB | Doc-verified | Ollama tags page, 2026-10-22 |
| Both models are first-class: declared under both providers at identical limits, installed by the default manager, and selectable in the picker | **Validated** (config, CI, install) | CI checks provider, whitelist, and Modelfile/config parity for both; the 2026-11-25 installer run pulled both, pin-verified both at 131072, and doctor read the live context. A dedicated Qwen agent session ran 2026-11-26 (answered via both the ollama and headroom providers), and the Qwen direct hello-agent run went green the same day. |
| Default `flint` tag is NVFP4 (4-bit) | **Validated** | Ollama registry manifest, 2026-10-22: the model layer is `flint-nvfp4.gguf`, 22.86 GB. No quantization step in setup. MLX BF16 exists at 80 GB (Apple only). If decode speed on AMD disappoints, retest with `flint:40b-a2b-q4`. |
| Flint benchmarks: 54.9% Terminal-Bench 2.1, 89.7% SWE-bench Pro v2, 74.2% SWE-bench Verified | Publisher-reported | Recursive, via the Ollama model page |
| Flint speed: 125+ tok/s on M4 Pro, 150+ on 64 GB RTX Spark | Publisher-reported | Recursive, using their own `rec` engine at short context; not Ollama, not this hardware |
| Ollama 0.40.8 released 2026-10-21; Flint support landed in llama.cpp the same day | Doc-verified | Ollama releases API; llama.cpp history, 2026-10-22 |
| Older inference builds fail to load brand-new architectures | Doc-verified | Documented failure case predating Flint support by 5 days, 2026-10-22 |
| OpenCode talks to Ollama via `@ai-sdk/openai-compatible` at `http://localhost:11434/v1` | Doc-verified | OpenCode provider docs, 2026-10-22 |
| Headroom supports `headroom wrap opencode`; wrap defaults the upstream to api.openai.com, override with `--openai-api-url` | Doc-verified | Headroom README, 2026-10-22 |
| Headroom telemetry is on by default; disable with `HEADROOM_TELEMETRY=off`, `HEADROOM_BEACON=off`, `DO_NOT_TRACK=1` | Doc-verified | Headroom README telemetry section, 2026-10-22 |
| Headroom proxy first start downloads about 500 MB of ML models | Publisher-reported | PyPI project page |
| Ollama defaults to a small context unless `num_ctx` / `OLLAMA_CONTEXT_LENGTH` raises it; a Modelfile is the reliable pin | Doc-verified | Ollama docs and practitioner reports |
| Qwen3-30B-A3B exists on Ollama as `qwen3:30b-a3b`, about 19 GB | Doc-verified | Ollama tags page and registry manifest, 2026-10-22 |
| Ollama can keep several models resident, up to `OLLAMA_MAX_LOADED_MODELS` | Doc-verified | Ollama docs, 2026-10-23. The kit recommends `1` on 64 GB so one model evicts the other. |
| Qwen as a first-class model (install, pin, picker) | **Validated** (install and pin; agent session unrun) | The pinned entry appeared in the picker on 2026-11-09. The 2026-11-25 installer run pulled `qwen3:30b-a3b`, built `qwen-opencode`, and verified `num_ctx 131072` in W5 and doctor. |
| 128K is the context floor for agent work; kit default pin is 131072 | **Validated** | Default pin is 131072 for both models; Qwen's YaRN ceiling is 131072. Hardware proof: doctor read `context_length 131072` from `/api/ps` and both variants pin-verified. |
| OpenCode's picker can surface served models the config does not declare | **Validated** (surfacing); whitelist effect **failed** on the target install | The 2026-11-09 picker showed raw base tags. The config now uses an exact `whitelist`. Visual check 2026-11-26, on the provably fresh from-empty install: the picker still shows 3 local rows per model: the pinned variant under `ollama`, the pinned variant under `headroom`, AND the raw base tag (`flint:latest`, `qwen3:30b-a3b`) under Ollama (local). The whitelist does not hide endpoint-discovered base tags on this OpenCode build, so the kit's picker-hiding claim does not hold; picking a base tag still runs unpinned at the runtime default context. |
| Standalone `headroom proxy` accepts `--openai-api-url`, and wrap's provider is named `headroom` at `127.0.0.1:<port>/v1` | Doc-verified | Headroom's OpenCode guide, 2026-10-22 |
| Ollama's `/v1/models` reports fully qualified IDs, tag included | Doc-verified plus measurement | Ollama source and independent measurement, 2026-10-23. The config keys are qualified for this reason. |
| `scripts/launch-headroom.sh` launches a wrapped session with the installed Headroom | **Failed** (2026-11-26) | With headroom 0.41.0 and OpenCode v2, the script's `headroom wrap opencode --openai-api-url http://localhost:11434/v1 --code-memory none` fails: wrap passes `--code-memory none` through to opencode, which exits with "Unrecognized flag: --code-memory". Per Headroom's current docs, `--code-memory` is a wrap option for claude/codex/grok only, and for opencode Serena is off by default, so the flag is both fatal and unnecessary. Kit fix: drop `--code-memory none` from launch-headroom.sh and launch-headroom.ps1. |
| Dual provider toggle works in a live OpenCode session | **Validated** | 2026-11-26, fresh install: in one OpenCode session with the standalone Headroom proxy running, Flint answered as `ollama/flint-opencode:latest` and again as `headroom/flint-opencode:latest` (no 401; the proxy route uses the Ollama upstream override). Qwen then answered both as `headroom/qwen-opencode:latest` and direct, and `ollama ps` showed qwen-opencode as the only resident model (31 GB, 100% GPU, CONTEXT 131072), which also proves OLLAMA_MAX_LOADED_MODELS=1 in a two-model session (env var read back as "1" the same day). |
| Compare harness produces a trustworthy Flint vs Qwen ranking | **Unvalidated** | The harness and `--plan` exist and run in CI; no full hardware run with both models. [COMPARE.md](COMPARE.md) defines the protocol. |
| This kit end to end on the target hardware (Windows, bridged topology) | **Validated** (direct and wrapped paths) | The 2026-11-07 bridged walk passed the smoke test, the pinned model, the hello-agent fix, and all tests at the then-current 32K pin. On 2026-11-26, on the fresh install at the 128K pin, hello-agent went green via the direct path (Qwen) and via the wrapped Headroom path (Flint). The all-Windows variant is still unrun. |
| The installer (manager) end to end on the target hardware | **Validated** | 2026-11-25: full install (W1 to C4), doctor 14 PASS / 1 WARN / 0 FAIL. The WARN was the designed VRAM conflict row. 2026-11-26: from-empty install on the target hardware via the Python manager, after an uninstall run by the old kit's manager; the run completed through the C4 ComfyUI generation test. Still unrun: `switch`, `repair`, the new kit's own `uninstall`, and the compiled EXE (the 2026-11-26 install vehicle was the .py, not the EXE). |
| ComfyUI on the target hardware, by hand | **Validated** | 2026-11-22: official Windows portable AMD build v0.46.0, Z-Image-Turbo; 23 GB VRAM peak, 43.10 seconds per image. |
| ComfyUI through the installer (C1 to C4) | **Validated** | 2026-11-25 (adoption path): C1 and C2 SKIPped on adoption, C3 passed the GPU check, C4 produced its image in 151.3 seconds including the cold start. 2026-11-26: the from-empty path ran on hardware as part of the from-empty install and completed through the C4 generation test. |
| `switch comfy` / `switch ollama` on hardware | **Unvalidated** | Covered by behavior tests both ways; no hardware run yet. |
| WSL2 on AMD exposes no ROCm device to the guest | **Validated** | Same first run: no `/dev/kfd`, `/dev/dri`; `/dev/dxg` is Direct3D only. Ollama fell back to CPU. Native Windows is the serving path. |
| Output budgets are 32768 for Flint and 8192 for Qwen in the pinned variants and config limits | **Validated** | CI checks each Modelfile against its own model's config limit. Direct on-machine proof 2026-11-26, after the from-empty reinstall: `ollama show flint-opencode --parameters` reports num_ctx 131072 and num_predict 32768; `ollama show qwen-opencode --parameters` reports num_ctx 131072 and num_predict 8192. (The pre-reinstall Flint variant wrongly reported num_predict 8192; the fresh build fixed it.) |

## Hands-on checklist (target hardware)

Checked during the bridged-topology walk and the installer run. Boxes that
need a figure or a hardware run stay open.

- [x] `ollama --version` recorded: 0.40.18 (2026-11-26, after the from-empty reinstall)
- [x] `ollama pull flint` completed, `ollama list` shows it (2026-11-07)
- [x] `ollama pull qwen3:30b-a3b` completed, `ollama list` shows it (2026-11-25)
- [x] `ollama run flint` answers a one-line prompt; rough tok/s noted: ______
- [x] `ollama ps` shows the model GPU-resident, not CPU-offloaded (2026-11-07)
- [x] Direct path: OpenCode lists `ollama/flint-opencode:latest`, and the smoke test's context gate passed at the then-current 32K pin (2026-11-07)
- [x] hello-agent example: test goes green via the direct path (2026-11-07)
- [x] Qwen direct agent run: hello-agent test goes green with `qwen-opencode:latest` (2026-11-26: Qwen fixed only the `mul` line, recovered on its own when its first edit matched both `add` and `mul`, and its in-session run of the tests printed "all tests passed"; 4m 20s at 18.2 tok/s. Verified again outside the agent the same day from the repo root: `python3 examples/hello-agent/test_calc.py` printed "all tests passed")
- [x] `headroom --version` and `headroom doctor` output recorded (2026-11-26: headroom 0.41.0; doctor reported the proxy running at 127.0.0.1:8787 and ready, kompress ready (onnx), 0 failures; the 4 warnings are routing and budget notes for other tools, not kit failures. The doctor savings row read 56 tokens saved lifetime and 7,000 cache-read tokens from the toggle session's proxy traffic)
- [x] Wrapped path launches with the Ollama upstream override, no 401 (2026-11-26, via the standalone proxy route and the picker. The `launch-headroom.sh` wrap route FAILED to launch the same day; see the launch-headroom claim below)
- [x] hello-agent example: test goes green via the wrapped path (2026-11-26: Flint, in a `headroom wrap` session launched manually without the script's dead `--code-memory` flag, fixed the `mul` line and the tests printed "all tests passed" in-session; confirmed again manually outside the agent the same day. One deviation from TASK.md's one-line ideal: the agent also removed the now-stale "# BUG" comment, a 2-line diff. 2m 15s for the run)
- [x] Headroom dashboard shows a nonzero compression saving on the wrapped run (2026-11-26: during the wrapped hello-agent run the dashboard, Session view, read TOKENS SAVED 56 (0.3% of new input), 3 requests completed, 0 failed, 2 cached. Caveat: the same 56-token figure already appeared in `headroom doctor` before the wrapped run started, from the toggle session's traffic through the same proxy process, so the saving is real and nonzero but is not isolated to the wrapped run alone)
- [x] RAM headroom at 128K context during an agent run noted: 45.5 GB in use of 59.6 GB usable (14.2 GB available, committed 62.4/78.6 GB) during the 2026-11-26 Qwen session at 131072 context; GPU memory peaked at 37.6 GB of the 47.6 GB GPU allocation during the same session
- [x] 128K default live on the target hardware (2026-11-25, both variants pin-verified; 2026-11-26: live `ollama ps` during an OpenCode session on the pinned Flint showed flint-opencode:latest, 22 GB, 100% GPU, CONTEXT 131072, llamacpp runner)
- [x] `OLLAMA_MAX_LOADED_MODELS=1` set in the server environment; `ollama ps` shows one resident during a two-model session (2026-11-26: env read back "1"; after switching Flint to Qwen in one session, `ollama ps` showed Qwen only)
- [x] Toggle check: one prompt as `headroom/flint-opencode:latest` and the same as `ollama/flint-opencode:latest` in one session (2026-11-26, both answered)
- [x] During a `headroom/qwen-opencode:latest` session, `ollama ps` shows Qwen as the only resident model (2026-11-26: qwen-opencode:latest, 31 GB, 100% GPU, CONTEXT 131072)
- [x] flint-opencode rebuilt after the output-cap change; `ollama show flint-opencode --parameters` shows `num_predict 32768` (2026-11-26, built by the from-empty reinstall)
- [x] qwen-opencode verified: `ollama show qwen-opencode --parameters` shows `num_predict 8192` (2026-11-26)

When a box gets checked, update the matching claim above with the date and the
machine.
