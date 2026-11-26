# Manual setup

The installer is the recommended path; see the [README](README.md). Use this
page if you prefer the scripts, or if you want Ollama on native Windows and
OpenCode in WSL.

## All-Windows manual path

Run these in PowerShell. Start from a clean window.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
winget install Ollama.Ollama
winget install Git.Git
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","131072","User")
# Quit Ollama from the system tray, then relaunch it from the Start menu.
git clone https://github.com/steve-hewitt/local-models-kit.git
cd local-models-kit
.\scripts\setup.ps1
.\scripts\smoke-test.ps1
.\scripts\launch-direct.ps1
.\scripts\launch-headroom.ps1
```

`setup.ps1` pulls Flint and builds `flint-opencode`. For Qwen instead, set
`$env:MODEL_TAG = "qwen3:30b-a3b"` before running it; to install both, set
`$env:WITH_QWEN = "1"`. The installer includes both by default.

Linux/macOS: install `zstd` first on Debian/Ubuntu, then use
`scripts/setup.sh`, `scripts/smoke-test.sh`, `scripts/launch-direct.sh`, and
`scripts/launch-headroom.sh`.

The setup scripts merge the two provider blocks into an existing OpenCode
config and leave its `model` field alone. To have them write the primary
pinned model (Flint, or Qwen when that is what they built), set
`KIT_SET_DEFAULT=1` before running the script (PowerShell:
`$env:KIT_SET_DEFAULT = "1"`). The launch scripts pin only their own session;
a bare `opencode` is unaffected.

## Windows serves, WSL drives

Follow [docs/WSL.md](docs/WSL.md). It is the complete step-by-step for this
topology. In short:

1. On Windows: `.\scripts\setup.ps1 -ServerOnly`.
2. Enable mirrored networking in `.wslconfig`, then `wsl --shutdown` and
   `wsl -d Ubuntu`.
3. In WSL: `./scripts/setup.sh --client-only`, then `./scripts/smoke-test.sh`.
4. Launch with `./scripts/launch-direct.sh examples/hello-agent`.

Do not run `ollama serve` inside WSL; WSL2 on AMD has no ROCm and would serve
from the CPU.

## Options and shutdown

- **Qwen:** installed by default by the installer; on the manual path use
  `WITH_QWEN=1` or `MODEL_TAG=qwen3:30b-a3b`. Switch models in `/models`.
- **Headroom:** optional. See [docs/WSL.md, Add-on B](docs/WSL.md#add-on-b-get-headroom-going)
  or use `scripts/launch-headroom.*`.
- **ComfyUI:** managed by the installer. See [docs/COMFYUI.md](docs/COMFYUI.md).
- **Off:** exit OpenCode, run `wsl --shutdown`, then
  `ollama stop flint-opencode:latest` (or `qwen-opencode:latest`) and confirm
  `ollama ps` is empty. For
  the full sequence, including the execution-policy restore, see
  [docs/WSL.md, Part 5](docs/WSL.md#part-5-turning-it-off-and-putting-things-back).

Evidence and known limits: [docs/reference/VALIDATION.md](docs/reference/VALIDATION.md).
