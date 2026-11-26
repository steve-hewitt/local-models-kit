# Local Models Kit installer

One Python file, standard library only, that installs, checks, repairs,
switches, and uninstalls the kit with state. Run it on Windows in PowerShell,
not in WSL: it is a Windows program and drives WSL itself through `wsl.exe`.

Flint and Qwen are co-equal first-class models. The default install includes
both; W6 verifies the first chosen variant (Flint by default) and W5 and doctor
pin-verify both. Neither is a startup default: the installer merges the two
provider blocks as picker options and leaves an existing `model` field alone.
Use `install --set-default` to write the primary pinned model (Flint, or Qwen
with `--no-flint`).

## The manager

`manager/local_models_kit_manager.py` is the program. `local-models-kit.exe`
is the same file compiled; see "Running as an EXE" below.

| Verb | What it does |
| --- | --- |
| `install` | Preflight, then the steps below, then doctor. Flags: `--no-flint`, `--no-qwen`, `--no-comfyui` (leave a component out), `--with-flint`, `--with-qwen`, `--with-comfyui` (force one in when recorded state has it out), `--set-default` (write the primary pinned model as the OpenCode default; off by default), `--num-ctx N`, `--distro NAME`, `--comfy-root DIR`, `--plan`. |
| `doctor` | Checks every recorded claim against the machine. PASS, WARN, or FAIL; a FAIL names the repairing step. |
| `repair` | Runs only the steps whose checks fail, re-verifies, reports FIX. |
| `update` | Stub: prints the current version and the releases URL. |
| `switch` | `switch comfy` or `switch ollama`: hands the GPU between the image stack and the agent stack, with verification both ways. |
| `uninstall` | State-driven undo. Flags: `--remove-models`, `--remove-ollama`, `--remove-comfyui`, `--remove-comfyui-models`. |

Shared flags: `--root DIR` picks the install root (default
`%LOCALAPPDATA%\LocalModelsKit`, or `$LOCAL_MODELS_KIT_ROOT`). State lives in
`state.json`; logs in `logs/manager.log`. Every failure ends with the log path
and the retry command.

## What install does

| ID | Step | Check |
| --- | --- | --- |
| W1 | Ollama installed via winget | `ollama --version` parses, at least 0.40.8 |
| W2 | Server env vars set | `OLLAMA_MAX_LOADED_MODELS=1`; `OLLAMA_CONTEXT_LENGTH` matches the chosen context |
| W3 | Ollama tray restarted | `/api/version` answers; restart only when W2 changed something |
| W4 | Base models pulled | Each chosen tag is present (`flint` and `qwen3:30b-a3b` by default) |
| W5 | Pinned variants built | `/api/show` reports the pinned `num_ctx` per variant |
| W6 | Windows-side verify | The first chosen variant answers a hello round trip; residency is recorded |
| B1 | `.wslconfig` mirrored networking | Exactly one managed block under `[wsl2]` with `networkingMode=mirrored` |
| B2 | WSL restarted | Pending only when B1 changed the file |
| L1 | WSL distro detected | `wsl -l -q` lists it |
| L2 | OpenCode present | Canonical binary answers by absolute path, and a login shell finds it on PATH |
| L3 | Kit OpenCode config installed | Both kit provider blocks are present and structurally match the template; user keys and a user default are preserved |
| L4 | Client-side smoke | From WSL: API answers, variant listed, `num_ctx` pinned |
| C1 | ComfyUI portable installed | Pinned archive extracted; launcher present |
| C2 | Z-Image-Turbo models present | Three files present at pinned sizes; hashes checked at download |
| C3 | ComfyUI GPU check | A Radeon device with at least 16 GB VRAM, not CPU-only |
| C4 | ComfyUI generation smoke | The embedded workflow produces a real image |

Every step checks before it acts and reports DONE, SKIP, or FIX. A second
install over a healthy machine is all SKIP; `repair` only re-runs failing
checks; `uninstall` removes only what the kit added.

## File merges

**`.wslconfig`** is a managed-block merge, never an overwrite. The kit's block
(marked with `local-models-kit managed begin/end`) goes at the end of the
`[wsl2]` section; user lines survive, repeated installs leave one block, and
uninstall restores a competing `networkingMode`.

**OpenCode config** is a provider-block merge: the kit replaces only
`provider.ollama` and `provider.headroom`, with the chosen context values
substituted; every other key, provider, and MCP entry is preserved. The
previous file is backed up next to it as
`opencode.json.bak-YYYYMMDD-HHMMSS`, and its hash is recorded. The kit writes
no top-level `model` unless `--set-default` asks for it.

## Uninstall

Uninstall reads state and removes only what the kit put there: the two kit
provider blocks are removed from the OpenCode config, and if the kit set the
default, the prior `model` value is restored (or the field removed); the
`.wslconfig` managed block is removed; the two env vars are restored or
unset. Models and Ollama are kept by default:
`--remove-models` deletes the kit's variants and base tags, and
`--remove-ollama` uninstalls Ollama through winget. OpenCode in WSL is left in
place.

ComfyUI stops first. Its portable tree and models are kept by default;
`--remove-comfyui-models` deletes the three model files, and
`--remove-comfyui` removes the tree and archive only when no user files
(outputs, extra models, custom nodes) are found. See [docs/COMFYUI.md](../docs/COMFYUI.md).

## Running as an EXE

The manager compiles to one Windows EXE with PyInstaller. The `.py` remains the
auditable source.

1. **Compile locally:** from the repo root, run `installer\build_exe.bat`
   after `pip install pyinstaller`. Output: `dist\local-models-kit.exe`.
2. **Download the CI build:** every push builds the EXE on Windows and uploads
   it as the `local-models-kit-exe` artifact; releases will attach it.

The EXE is unsigned, so a downloaded copy can draw a SmartScreen prompt. Build
locally to avoid the download mark. The verbs and flags are identical:
`local-models-kit.exe install` is the same as running the `.py`.

## If something fails

- Run `doctor` first; a FAIL names the repairing step.
- Run `repair` to re-run only the failing checks.
- `switch comfy` / `switch ollama` resolves GPU contention.
- Read `logs/manager.log` in the install root.

More detail: [docs/reference/DESIGN-NOTES.md](../docs/reference/DESIGN-NOTES.md)
(installer internals and history) and
[docs/reference/VALIDATION.md](../docs/reference/VALIDATION.md) (what is
validated).
