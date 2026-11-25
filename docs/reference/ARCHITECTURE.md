# Architecture

## The stack, layer by layer

### Ollama (serving)
- Local model server. OpenAI-compatible API at `http://localhost:11434/v1`, native API at `/api`.
- Handles model download, quantization selection, and the KV cache.
- Key environment: `OLLAMA_CONTEXT_LENGTH` sets the server-side context ceiling. The Modelfile `num_ctx` pins it per model and wins where they disagree in practice.
- Minimum version for this kit: **0.40.8** (2026-10-21). Flint's architecture support landed in llama.cpp on 2026-10-21, and Qwen3 also needs a modern build; inference builds older than the architecture they are asked to load fail in confusing ways. Treat the version check as step zero, not an afterthought.

### Models (Flint 40B and Qwen3-30B-A3B)

Two first-class models ship with the kit. Both are installed by the default
installer, both are declared under both providers as context-pinned variants
at 128K, and both are selected the same way: `/models` inside OpenCode, or
`opencode run -m ...` per run. Flint is the shipped default; Qwen is an equal
choice.

| | Recursive Flint | Qwen3-30B-A3B |
| --- | --- | --- |
| Ollama tag | `flint` / `flint:40b` | `qwen3:30b-a3b` |
| Total / active parameters | 39.8B / about 2.5B (MoE, 256 experts, 6 per token) | 30B / about 3B (MoE) |
| Download | 23 GB (NVFP4, already quantized) | about 19 GB |
| Context | 262K advertised; 128K pinned by default; up to 262144 optional | 128K (YaRN ceiling); pinned at 128K |
| Output budget in the pinned variant | 32768 | 8192 |
| License | Apache 2.0 | Apache 2.0 |
| Best fit | coding-agent work; publisher tunes for tools and thinking | general instruct with tools and thinking; the like-for-like MoE comparison point |

**Recursive Flint** (released 2026-10-21) is built specifically for local
coding agents. Ollama tags seen 2026-10-22: `flint` / `flint:40b` /
`flint:40b-a2b` at 23 GB, `flint:40b-a2b-q4` at 26 GB, an NVFP4 GGUF variant
at 23 GB, and MLX BF16 at 80 GB (Apple only). Default pick: `flint` (23 GB),
the tag the Ollama page documents for `ollama run flint` and
`ollama launch opencode --model flint`.

**Qwen3-30B-A3B** is the co-equal general instruct model: same MoE shape
class and a similar download size, with tool calling and thinking modes. It is
the like-for-like comparison point for Flint. `qwen3-coder:30b` is a
coding-tuned sibling if you prefer a specialist.

Working style: both are capable local models; Flint's publisher says it
rewards explicit instructions and smaller subtasks more than frontier cloud
models, and the same working agreement applies to Qwen.

### Headroom (compression)
- Local context compression layer from headroomlabs-ai. Compresses tool outputs, logs, files, and history before they reach the model. Reversible: originals are cached locally (CCR) and the model can retrieve them.
- Publisher's current headline for coding agents is about 20% fewer tokens, with 60 to 95% on JSON-heavy payloads. Earlier, larger headline numbers were revised down by the project itself. Budget your expectations at the revised numbers.
- Three integration modes: library, proxy, and agent wrap, plus an MCP server (`headroom_compress`, `headroom_retrieve`, `headroom_stats`).
- This kit uses **wrap mode** for OpenCode: `headroom wrap opencode` starts the proxy, injects config, registers the Serena code-navigation MCP server by default, and launches the agent. The kit passes `--code-memory none` by default to keep the stack minimal; remove that flag if you want Serena.
- Upstream trap: wrap defaults OpenAI-compatible traffic to `https://api.openai.com/v1`. Override with `--openai-api-url http://localhost:11434/v1` or `OPENAI_TARGET_API_URL`. Non-negotiable on a local stack.
- Telemetry: anonymous beacon is ON by default (ratios, counters, provider and model IDs, OS and arch; the project states it never sends prompts, code, or file paths). This kit sets `HEADROOM_TELEMETRY=off`, `HEADROOM_BEACON=off`, and `DO_NOT_TRACK=1` in every launch path.
- First proxy start may download ML models (~500 MB, publisher-stated). One-time, but do not mistake it for a hang on first run.

### OpenCode (the agent)
- Terminal coding agent. Config at `~/.config/opencode/opencode.json` (Windows: `%USERPROFILE%\.config\opencode\opencode.json`).
- Talks to Ollama through the `@ai-sdk/openai-compatible` provider package pointed at the local base URL.
- `/models` inside the TUI lists the configured local models (pinned `*-opencode` variants only). `opencode run -m ollama/flint-opencode:latest "..."` or `opencode run -m ollama/qwen-opencode:latest "..."` runs one-shot from the shell.

## The toggle (two providers, one config)

The kit's `opencode.json` declares the same models under two providers:

- `ollama/...` goes straight to Ollama on port 11434.
- `headroom/...` goes to a standalone Headroom proxy on port 8787, started with `scripts/start-headroom-proxy.*`, which runs `headroom proxy --port 8787 --openai-api-url http://localhost:11434/v1` with telemetry off. Headroom's OpenCode guide documents that the `--openai-api-url` flag means the same thing for `headroom proxy` as for `headroom wrap`, and that wrap's own generated provider is also named `headroom` and points at `127.0.0.1:<port>/v1`. The kit deliberately mirrors both choices so the manual and wrapped setups line up. Whether they are fully interchangeable in practice is unverified: sharing a port and a provider name is also a collision surface, so do not run the standalone proxy and a wrap launch at the same time (see TROUBLESHOOTING, item 2c).

Switching compression is then just picking a different model entry in `/models` or with `-m`, inside a running session. The proxy only needs to be running for the `headroom/...` entries; with it stopped, those entries fail with a connection error and the direct entries are unaffected.

Trade-off vs. wrap mode: the standalone proxy does not register Headroom's MCP tools or Serena with OpenCode the way wrap does. What you get through the proxy is compression (and CCR retrieval injection on the request path). If a session needs the MCP tools, use the wrapped launch instead.

## Request flow, wrapped path

```
OpenCode -> Headroom proxy (localhost:8787)
         -> compression pipeline (CacheAligner, ContentRouter,
            SmartCrusher for JSON, CodeCompressor for code,
            Kompress-v2-base for text, CCR cache for originals)
         -> Ollama (localhost:11434/v1) -> Flint or Qwen
```

## Failure bisection order

When something breaks, remove layers in this order and retest after each:

1. Direct path (no Headroom): `scripts/launch-direct.*`
2. Zero-config path: `ollama launch opencode --model flint` (or `--model qwen3:30b-a3b`)
3. Raw model: `ollama run flint` or `ollama run qwen3:30b-a3b` with a one-line prompt
4. Raw API: `curl http://localhost:11434/api/tags`

The first step that fails owns the bug. Do not tune prompts to work around an infrastructure failure.
