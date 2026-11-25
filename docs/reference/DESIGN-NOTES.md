# Design notes and history

These are reference notes for maintainers and curious readers, not setup
instructions. Start with the repo README for installation.

## Installer design

- One Python file, standard library only, state-driven.
- Every step checks before it acts and reports DONE, SKIP, or FIX. A second
  install over a healthy machine rewrites nothing.
- State lives in `state.json`; logs in `logs/manager.log`.
- File I/O is byte-exact (`read_bytes` / `write_bytes`) so hash-based drift
  checks stay honest on Windows.
- All machine effects (winreg, winget, the Ollama CLI, the HTTP API, `wsl.exe`,
  file roots) sit behind one platform seam. The tests run on Linux against a
  fake Windows platform.
- Preflight checks the Windows build, disk, WSL distro, network, and the Ollama
  endpoint before changing anything.

### The OpenCode L2 rule

The manager never downgrades or replaces an OpenCode that is already
installed. The incident behind the rule: a cold login shell could not see the
OpenCode PATH entry, so the step trusted PATH, called a healthy OpenCode 2.0.26
missing, and ran the OpenCode 1 installer. OpenCode 1 could not read the 2.x
database, and the user had to restore 2.0.26 by hand. L2 now probes the
canonical binary by absolute path first, repairs a broken login-shell PATH with
a marker-guarded `~/.profile` block, and refuses to install over a binary file
that exists but does not answer.

### Tests

The behavior suite runs the manager against a fake Windows machine
(`installer/tests/fake_platform.py`): in-memory env, model store, and API, with
WSL homes as real folders so byte and mtime assertions mean something. Run it
from the repo root with `python -m unittest discover -s installer/tests`. The
suite covers install idempotence, resume after failure, config drift and
repair, `.wslconfig` merge and restore, context substitution, uninstall
defaults, the ComfyUI gates, switch refusals, and the embedded-template drift
guard. CI runs it on Ubuntu and Windows and builds the EXE.

## Config rationale

- **Pinned variants only.** Base tags carry no `num_ctx`. The first hands-on
  run advertised 32768 while Ollama ran 4096, truncating a 6,653-token prompt
  to 2,050. The config now declares only `*-opencode` variants.
- **Whitelist.** The picker can surface endpoint-served base tags. Each
  provider's `whitelist` exactly matches its declared pinned models.
- **No `small_model` pin.** Side traffic follows the session's own route
  instead of leaking around the proxy.
- **No `apiKey`.** The stack is local and keyless. A placeholder was added
  during a QC pass and removed.
- **Output budgets.** Flint is 32768, Qwen 8192; reasoning tokens count against
  them.
- **Port 8787.** The standalone proxy and `headroom wrap` both want it. Do not
  run both at once.

## Validation process

- Labels: Validated, Doc-verified, Publisher-reported, Unvalidated. Evidence
  lives in [VALIDATION.md](VALIDATION.md).
- The first hands-on run (2026-10-24, WSL2 CPU-only) exposed the unpinned-default
  failure. The fix was structural: declare only pinned variants, and make the
  smoke test read the effective `num_ctx` from `/api/show`.
- "Slate 40B" was a working name; no such model exists. Flint was the intended
  model, and the name question is closed.
- "Gate 0" is the byte-exact I/O lesson. "Gate 1" and "Gate 2" are the ComfyUI
  GPU-visible and generation-smoke checks. They are internal labels; the
  user-facing docs call them the GPU check and the generation smoke.
- Phase 1 and the spike refer to the manager's first implementation. The
  installer is the survivor of that work.

## Design rules

- **Local only.** No cloud fallback, no keys, no accounts. If a step wants one,
  that is a bug.
- **Baseline before layers.** Headroom, Modelfile variants, and MCP must be
  individually bypassable so failures can be bisected.
- **Evidence labels.** Claims are marked; see [VALIDATION.md](VALIDATION.md).
- **Telemetry off.** Headroom's anonymous beacon is off in every launch path.

## History notes

- The installer was validated on the target hardware on 2026-11-25; the ComfyUI
  manual flow was validated on 2026-11-22.
- The ComfyUI fold-in added C1-C4, `switch`, doctor rows, and uninstall rules.
- The `.wslconfig` merge preserves user lines and restores a competing value on
  uninstall.
- Uninstall keeps models and ComfyUI files by default; removal flags are
  explicit.
- The EXE is unsigned, so SmartScreen is expected for downloaded copies.
