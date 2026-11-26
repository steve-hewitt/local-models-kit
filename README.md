# local-models-kit

A fully local coding agent plus a local image stack. **Ollama** serves the
models, **Flint 40B** and **Qwen3-30B-A3B** are the two first-class coding
models, **OpenCode** is the agent, and **Headroom** optionally compresses
context. **ComfyUI** with Z-Image-Turbo runs on the same GPU. No cloud API, no
keys, nothing leaves the machine.

## What you need

- Windows 11 with WSL2 and Ubuntu. The installer drives WSL itself.
- Target hardware: **Ryzen AI Max 395, Radeon 8060S, 64 GB unified memory,
  Windows 11.** See [docs/HARDWARE.md](docs/HARDWARE.md) for sizing and
  smaller machines.
- Free disk: about 80 GB for the default install (both models plus ComfyUI),
  or about 45 GB with `--no-comfyui`.
- No account, login, or API key.

## Install

From **PowerShell**, not WSL:

```powershell
git clone https://github.com/steve-hewitt/local-models-kit.git
cd local-models-kit
python installer\manager\local_models_kit_manager.py install
```

That installs the full stack: Flint and Qwen, their context-pinned variants,
the OpenCode provider blocks, and ComfyUI. It ends with a doctor report. The
install does **not** set a startup default model: both models arrive as
picker options, and an existing `model` field is left alone. Add
`--set-default` to make the primary pinned model (Flint, or Qwen with
`--no-flint`) the default. The same command has `--no-flint`, `--no-qwen`,
and `--no-comfyui` opt-outs. The compiled `local-models-kit.exe` is the same
program; see [installer/README.md](installer/README.md).

The first run downloads both models (about 42 GB) plus the ComfyUI archive and
model files (about 21 GB). Give it time; do not kill it at the first quiet
minute.

## Verify

Re-run the health check from PowerShell:

```powershell
python installer\manager\local_models_kit_manager.py doctor
```

Every row should be PASS or an expected WARN. Run the smoke test for your
topology:

```bash
./scripts/smoke-test.sh          # WSL agent side
```

```powershell
.\scripts\smoke-test.ps1         # all-Windows
```

Then run the proof task in [examples/hello-agent](examples/hello-agent/): ask
the agent to fix the failing test, and confirm `python3 test_calc.py` passes
outside the agent. That is the end-to-end check.

## Choose a model

Flint and Qwen are co-equal, and neither is a startup default. Both are
installed, both pin 128K context, and both appear under the `ollama` and
`headroom` providers. Pick either in `/models` inside OpenCode, or per run
with `opencode run -m ollama/qwen-opencode:latest`.

To set a startup default yourself, add
`"model": "ollama/flint-opencode:latest"` (or
`"model": "ollama/qwen-opencode:latest"`) to the installed config, or install
with `--set-default` (Qwen with `--no-flint`). Kit launch scripts pin the
model for their own session only; a bare `opencode` is unaffected. Model
details and the comparison table are in
[docs/reference/ARCHITECTURE.md](docs/reference/ARCHITECTURE.md).

## Manual or split setup

The installer is the recommended path. If you prefer scripts, or you want
Ollama on native Windows and OpenCode in WSL, use
[MANUAL-SETUP.md](MANUAL-SETUP.md). The full Windows-serves/WSL-drives
walkthrough is [docs/WSL.md](docs/WSL.md).

## Troubleshooting

Start with [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). For WSL2 on AMD,
read the CPU-only warning in [docs/HARDWARE.md](docs/HARDWARE.md) first: WSL2
does not expose ROCm, so Ollama belongs on native Windows.

ComfyUI is part of the default install and has its own guide:
[docs/COMFYUI.md](docs/COMFYUI.md).

## Learn more

- [docs/reference/ARCHITECTURE.md](docs/reference/ARCHITECTURE.md): models,
  providers, request flow, failure bisection.
- [docs/reference/VALIDATION.md](docs/reference/VALIDATION.md): what is
  validated, what is not, and the hands-on checklist.
- [docs/reference/COMPARE.md](docs/reference/COMPARE.md): reading bench and
  agent comparison runs.
- [docs/reference/DESIGN-NOTES.md](docs/reference/DESIGN-NOTES.md): installer
  internals and design history.
- [config/README.md](config/README.md): provider and model configuration
  rules.

Status: the installer and direct path are validated on the target hardware.
Details: [docs/reference/VALIDATION.md](docs/reference/VALIDATION.md).

## License

MIT for the kit code and docs. Flint is Apache 2.0 (Recursive); Qwen3 is
Apache 2.0 (Alibaba). Headroom is Apache 2.0. Ollama is MIT. OpenCode has its
own license; this kit only ships configuration for it.
