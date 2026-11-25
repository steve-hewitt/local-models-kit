# Changelog

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
  notes, a project AGENTS template, and a hello-agent end-to-end proof task.
- CI that validates config shape, script syntax, template drift, the installer
  behavior suite, and the hello-agent task without running a model.
