# Validation ledger

Every load-bearing claim in this kit carries one of these labels:

- **Validated**: run by us, on real hardware, output seen.
- **Doc-verified**: read in the primary source on the date noted.
- **Publisher-reported**: the vendor or lab's own numbers.
- **Unvalidated**: plausible, but not proven here.

**What this proves:** both models are declared under both providers at
identical limits and installed by the default manager; the installer and the
direct path ran end to end on the target hardware; the ComfyUI adoption path
passed both GPU gates. The Headroom toggle and `switch` are covered by tests
but not yet run on hardware. A dedicated Qwen agent session is still unrun.

Last updated: 2026-11-25.

## Claims

| Claim | Label | Source / date |
| --- | --- | --- |
| Flint exists on Ollama as `flint`, 39.8B params, ~2.5B active, 262K context, Apache 2.0, tools + thinking | Doc-verified | Ollama library page for flint, 2026-10-22 |
| `ollama run flint` and `ollama launch opencode --model flint` are the documented entry points | Doc-verified | Same page, 2026-10-22 |
| Default `flint` download is 23 GB; q4 variant 26 GB | Doc-verified | Ollama tags page, 2026-10-22 |
| Both models are first-class: declared under both providers at identical limits, installed by the default manager, and selectable in the picker | **Validated** (config, CI, install) | CI checks provider, whitelist, and Modelfile/config parity for both; the 2026-11-25 installer run pulled both, pin-verified both at 131072, and doctor read the live context. A dedicated Qwen agent session is unrun. |
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
| OpenCode's picker can surface served models the config does not declare | **Validated** (surfacing); whitelist effect still open | The 2026-11-09 picker showed raw base tags. The config now uses an exact `whitelist`; a visual check on the target install after an OpenCode restart is still open. |
| Standalone `headroom proxy` accepts `--openai-api-url`, and wrap's provider is named `headroom` at `127.0.0.1:<port>/v1` | Doc-verified | Headroom's OpenCode guide, 2026-10-22 |
| Ollama's `/v1/models` reports fully qualified IDs, tag included | Doc-verified plus measurement | Ollama source and independent measurement, 2026-10-23. The config keys are qualified for this reason. |
| Dual provider toggle works in a live OpenCode session | **Unvalidated** | Not run in a live session. Checklist: start the proxy, run one prompt direct and the same prompt via Headroom, confirm both answer. |
| Compare harness produces a trustworthy Flint vs Qwen ranking | **Unvalidated** | The harness and `--plan` exist and run in CI; no full hardware run with both models. [COMPARE.md](COMPARE.md) defines the protocol. |
| This kit end to end on the target hardware (Windows, bridged topology) | **Validated** (direct path) | The 2026-11-07 bridged walk passed the smoke test, the pinned model, the hello-agent fix, and all tests at the then-current 32K pin. The all-Windows variant is still unrun. |
| The installer (manager) end to end on the target hardware | **Validated** | 2026-11-25: full install (W1 to C4), doctor 14 PASS / 1 WARN / 0 FAIL. The WARN was the designed VRAM conflict row. Still unrun: a from-empty install, `switch`, `repair`, `uninstall`, and the compiled EXE. |
| ComfyUI on the target hardware, by hand | **Validated** | 2026-11-22: official Windows portable AMD build v0.46.0, Z-Image-Turbo; 23 GB VRAM peak, 43.10 seconds per image. |
| ComfyUI through the installer (C1 to C4) | **Validated** (adoption path) | 2026-11-25: C1 and C2 SKIPped on adoption, C3 passed the GPU check, C4 produced its image in 151.3 seconds including the cold start. The from-empty path is code- and CI-tested but has not run on hardware. |
| `switch comfy` / `switch ollama` on hardware | **Unvalidated** | Covered by behavior tests both ways; no hardware run yet. |
| WSL2 on AMD exposes no ROCm device to the guest | **Validated** | Same first run: no `/dev/kfd`, `/dev/dri`; `/dev/dxg` is Direct3D only. Ollama fell back to CPU. Native Windows is the serving path. |
| Output budgets are 32768 for Flint and 8192 for Qwen in the pinned variants and config limits | **Unvalidated** | CI checks each Modelfile against its own model's config limit; the direct on-machine proof is unrecorded: `ollama show flint-opencode --parameters` for 32768, `qwen-opencode` for 8192. |

## Hands-on checklist (target hardware)

Checked during the bridged-topology walk and the installer run. Boxes that
need a figure or a hardware run stay open.

- [ ] `ollama --version` recorded: ______
- [x] `ollama pull flint` completed, `ollama list` shows it (2026-11-07)
- [x] `ollama pull qwen3:30b-a3b` completed, `ollama list` shows it (2026-11-25)
- [x] `ollama run flint` answers a one-line prompt; rough tok/s noted: ______
- [x] `ollama ps` shows the model GPU-resident, not CPU-offloaded (2026-11-07)
- [x] Direct path: OpenCode lists `ollama/flint-opencode:latest`, and the smoke test's context gate passed at the then-current 32K pin (2026-11-07)
- [x] hello-agent example: test goes green via the direct path (2026-11-07)
- [ ] Qwen direct agent run: hello-agent test goes green with `qwen-opencode:latest`
- [ ] `headroom --version` and `headroom doctor` output recorded
- [ ] Wrapped path launches with the Ollama upstream override, no 401
- [ ] hello-agent example: test goes green via the wrapped path
- [ ] Headroom dashboard shows a nonzero compression saving on the wrapped run
- [ ] RAM headroom at 128K context during an agent run noted: ______
- [x] 128K default live on the target hardware (2026-11-25, both variants pin-verified)
- [ ] `OLLAMA_MAX_LOADED_MODELS=1` set in the server environment; `ollama ps` shows one resident during a two-model session
- [ ] Toggle check: one prompt as `headroom/flint-opencode:latest` and the same as `ollama/flint-opencode:latest` in one session
- [ ] During a `headroom/qwen-opencode:latest` session, `ollama ps` shows Qwen as the only resident model
- [ ] flint-opencode rebuilt after the output-cap change; `ollama show flint-opencode --parameters` shows `num_predict 32768`
- [ ] qwen-opencode verified: `ollama show qwen-opencode --parameters` shows `num_predict 8192`

When a box gets checked, update the matching claim above with the date and the
machine.
