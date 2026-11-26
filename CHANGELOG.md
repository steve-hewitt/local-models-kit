# Changelog

## Unreleased

- Removed `--code-memory none` from the Headroom launch scripts. Headroom
  0.41.0 does not accept that flag for `opencode`; `headroom wrap` forwarded
  it to OpenCode, which exited with "Unrecognized flag: --code-memory".
  Current Headroom registers no Serena server for `opencode` by default.
- Corrected the picker-whitelist documentation. The whitelist still matches
  each provider's declared pinned models, but on current OpenCode it does not
  filter endpoint-discovered base tags out of the picker; the config README,
  launch messages, and CI step now say so.
- The kit no longer sets a default model on install. It merges only the
  `ollama` and `headroom` provider blocks into an existing OpenCode config,
  preserving the user's `model`, other providers, and MCP entries. The shipped
  config has no top-level `model`; the installer and manual setup install
  providers as picker options.
- Added `install --set-default` (and `KIT_SET_DEFAULT=1` on the manual path)
  for users who want the primary pinned model written as the default. A
  proven kit-imposed old default is removed on upgrade, and state records the
  choice so repair and uninstall can restore it.
- Kit launch scripts now pin the model for their own session only. On OpenCode
  2, `launch-direct` uses `OPENCODE_CONFIG_CONTENT` with `--standalone`;
  Headroom wrap does not pin, so its guidance points at the Headroom
  "context-pinned 128K" row. A bare `opencode` is unaffected.
- Doctor's L3 check is structural rather than byte-for-byte: it verifies the
  kit provider blocks and tolerates user keys, a user default, and other
  providers. Uninstall removes only the kit's provider blocks.

## 1.0.0 - 2026-11-25

First public release of local-models-kit.

- A fully local coding-agent stack: Ollama serves the models, Flint 40B and
  Qwen3-30B-A3B do the work, OpenCode is the agent, and optional Headroom
  compression sits between them. No cloud API, no keys, nothing leaves the
  machine.
- Context-pinned model variants at 128K (Flint can go to 262K; Qwen stays at
  its 128K YaRN ceiling), declared under both the direct `ollama` and the
  `headroom` providers, with picker whitelists that hide unpinned base tags.
- A stateful Windows installer/manager (`install`, `doctor`, `repair`,
  `switch`, `uninstall`, and a documented `update` stub) with a PyInstaller
  single-file build, plus matching POSIX and PowerShell setup, smoke-test,
  bench, compare, and launch scripts.
- ComfyUI with Z-Image-Turbo on the same GPU, including a `switch` verb that
  hands the GPU between the image stack and the agent stack.
- A validation ledger, WSL walkthrough, hardware sizing guide, troubleshooting
  notes, and a hello-agent end-to-end proof task.
- CI that validates config shape, script syntax, template drift, the installer
  behavior suite, and the hello-agent task without running a model.
