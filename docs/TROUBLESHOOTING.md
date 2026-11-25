# Troubleshooting

Ordered by how likely each one is to bite on a fresh install.

## 1. Model fails to load, unknown architecture, or garbage errors on first pull

Your inference build predates the model. Flint support landed 2026-10-21;
Qwen3 also needs a modern build.

Fix: update Ollama to 0.40.8 or newer, restart the service, pull again. Confirm
the version before debugging anything else.

## 2. Wrapped path returns 401 Incorrect API key provided

Headroom wrap sent traffic to OpenAI's API, its default upstream.

Fix: launch with the override (the kit scripts do):

```
headroom wrap opencode --openai-api-url http://localhost:11434/v1
```

## 2b. A `headroom/...` model fails with a connection error, but `ollama/...` works

The standalone proxy is not running. Start it in its own terminal with
`scripts/start-headroom-proxy.ps1` (or `.sh`) and leave it open. If the error
is a 401 instead of a connection refusal, restart it via the kit script, which
passes the Ollama upstream override.

## 2c. Do not run the standalone proxy and `headroom wrap` at the same time

Both want port 8787 and both configure a provider named `headroom`. Pick one
path per session: standalone proxy plus a manual launch, or wrap on its own.

## 3. Agent loses the thread, truncates, or ignores earlier context

Context mismatch between OpenCode and Ollama.

Fix: `ollama show flint-opencode --parameters` (or `qwen-opencode` for Qwen)
should show `num_ctx 131072`, and `config/opencode.json` should show the
matching `limit.context`. Restart Ollama after changing either. Check
`OLLAMA_CONTEXT_LENGTH` is not set smaller in your environment.

## 3b. The log says "truncating input prompt", or `ollama ps` shows CONTEXT 4096

You are running an unpinned base tag. Use a `*-opencode` variant
(`ollama/flint-opencode:latest` or `ollama/qwen-opencode:latest`). The smoke
test reads the effective `num_ctx` from `/api/show` and fails on this.

## 3c. Everything is slow and `ollama ps` shows 100% CPU / size_vram 0

The model is CPU-resident. On native Windows, the GPU path failed; check the
server log and the platform notes in [HARDWARE.md](HARDWARE.md). Under WSL2 on
AMD this is expected: WSL2 exposes no ROCm device. Serve from native Windows,
or accept CPU turns and use a smaller model. The smoke test warns instead of
passing quietly.

## 3d. The first turn looks hung

The first prompt pays model load, and both models are thinking-capable; a
one-word greeting can spend hundreds of reasoning tokens. Give it minutes, not
seconds, especially CPU-only. Watch `ollama ps` and the server log.

## 4. Model runs, but painfully slowly

Check in order:

1. `ollama ps`: is the model fully on GPU, or partially / fully on CPU?
2. Context size: a huge `num_ctx` inflates KV cache and slows everything.
3. Thermals on long runs.
4. Another process holding unified memory (a second model, a game, a VM).

## 5. OpenCode does not list the local model

- Is Ollama running? `curl http://localhost:11434/api/tags` should return JSON.
- Does the model key match `ollama list` output exactly?
- Is the config in `~/.config/opencode/opencode.json` (Windows:
  `%USERPROFILE%\.config\opencode\opencode.json`)?
- Restart OpenCode after config edits.

## 6. Headroom first launch appears to hang

First start can download about 500 MB of ML models. Give it time and check
`headroom doctor` in a second terminal. Subsequent starts are fast.

## 7. Headroom works but saves almost nothing

Expected on short chats and prose-heavy work. Check `headroom dashboard` during
a long, tool-heavy task, and confirm traffic is going through the proxy.

## 8. You want Headroom completely back out

```
headroom unwrap opencode
```

Then use the direct path. Nothing in the direct path depends on Headroom.

## 9. Windows: script execution policy blocks the .ps1 files

Symptom: `cannot be loaded because running scripts is disabled on this system`.

Least invasive, and what the guides use:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Permanent per-user option:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Restore it when you are done:

```powershell
Set-ExecutionPolicy -Scope CurrentUser Restricted
Get-ExecutionPolicy -List
```

The process scope needs no restore. [WSL.md](WSL.md) Part 5 covers the full
shutdown and restore sequence.

## 10. Still stuck

Bisect with [reference/ARCHITECTURE.md](reference/ARCHITECTURE.md#failure-bisection-order),
and record which step first fails, with exact versions and error text.
