# Hardware sizing

Primary target: **Ryzen AI Max 395, Radeon 8060S, 64 GB unified memory,
Windows 11.** The math generalizes.

## The budget

Unified memory means one pool serves OS, apps, weights, and KV cache.

| Consumer | Size | Notes |
| --- | --- | --- |
| Flint weights (`flint`, quantized) | 23 GB | Ollama library listing, 2026-10-22 |
| Qwen3-30B-A3B weights (`qwen3:30b-a3b`) | about 19 GB | Ollama registry, 2026-10-22 |
| KV cache at 128K context | model-dependent; Qwen about 13 GB; Flint unpublished | grows linearly with context |
| Windows + desktop apps | 8 to 12 GB typical | measure yours |
| Headroom + its ML models | about 0.5 to 1 GB | plus about 500 MB one-time download |
| OpenCode + tooling | under 1 GB | negligible next to the model |

Rule of thumb: **weights + KV cache should stay under about 70% of total RAM**
if the machine is also your daily driver. One model at the 128K default fits
64 GB; both resident at high context does not, so set
`OLLAMA_MAX_LOADED_MODELS=1`.

## ComfyUI and the GPU allocation

The GPU side of the unified pool is set in the laptop's GPU/shared-memory
utility, usually in a card named "Memory Allocated to GPU" (Shared Memory
Size). The reference setup allocates 48 GB to the GPU, leaving 16 GB as system
RAM. ComfyUI with Z-Image-Turbo peaked at 23 GB of VRAM and about 43 seconds
per 1024 by 1024 image. A loaded Flint or Qwen plus its 128K KV cache is the
same size class, so the two stacks do not fit at once. The manager's `switch`
verb unloads one side before starting the other. One stack at a time is a
sizing rule, not a preference.

## Context settings ladder

| num_ctx | Use it when |
| --- | --- |
| 16384 | quick single-file edits; WSL-guest fallback |
| 32768 | retired as too small for agent work |
| 65536 | middle setting if memory pressure shows up |
| **131072 (kit default)** | normal agent work; Qwen's YaRN ceiling |
| 262144 | Flint only, its native ceiling; watch RAM |

Both models are MoE with about 2.5B to 3B active params, so decode speed stays
high at 30B to 40B class. Bench both; the kit's compare and bench scripts
record real numbers. Publisher speed claims are not promises for this stack.

## Quantization

The default `flint` tag is Recursive's NVFP4 build (4-bit, verified from the
Ollama registry manifest). Whether llama.cpp under Ollama handles it at full
speed on AMD is unvalidated. Fallback: pull `flint:40b-a2b-q4` (26 GB,
conventional GGUF 4-bit) and set `MODEL_TAG=flint:40b-a2b-q4`.

## Strix Halo platform notes

- Allocate generously to the GPU side if your BIOS or Adrenalin settings
  expose a VRAM carve-out.
- If `ollama run flint` or `ollama run qwen3:30b-a3b` is unexpectedly slow,
  check `ollama ps` and the server log to confirm the model is GPU-resident
  before changing anything else.
- Sustained agent runs are sustained inference; suspect heat before software
  if speeds decay over a long session.

## WSL2 on AMD

WSL2 exposes no ROCm device, so Ollama inside WSL2 runs CPU-only, however fast
the Windows GPU is. Serve from native Windows Ollama and use WSL for tooling.
Setup and the smoke test detect WSL and warn. See [WSL.md](WSL.md) and
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Ollama service environment

Two knobs belong to the Ollama server:

- `OLLAMA_MAX_LOADED_MODELS=1` on the 64 GB target.
- `OLLAMA_CONTEXT_LENGTH=131072` as a fallback for unpinned tags.

Linux (systemd): `sudo systemctl edit ollama`, add a `[Service]` section with
both `Environment=` lines, then restart. Windows: set them as user environment
variables and restart the Ollama tray app. Setup prints these steps.

## Smaller machines

- 32 GB: Flint at 23 GB (or Qwen at 19 GB) is possible but tight. Use a
  smaller tag via `MODEL_TAG`, or run at 16K context.
- 16 GB: do not run either 30B-class model. Pick a 9B to 14B coder tag and
  keep the rest of the kit identical.
