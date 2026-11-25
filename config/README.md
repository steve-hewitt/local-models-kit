# Config notes

`opencode.json` declares **two providers** using the OpenAI-compatible package
`@ai-sdk/openai-compatible`:

- `ollama`: direct to Ollama at `http://localhost:11434/v1`
- `headroom`: to the local Headroom proxy at `http://127.0.0.1:8787/v1`

Every declared model is a context-pinned variant under both providers, so the
provider prefix is the compression toggle: `ollama/...` never touches
Headroom; `headroom/...` always does.

## Models

Both models are first-class. The `model` field ships as
`ollama/flint-opencode:latest`; Qwen is an equal choice. To make Qwen the
default, change that field to `ollama/qwen-opencode:latest`. Both are declared
with identical limits and whitelists.

Only the pinned variants are declared: `flint-opencode:latest` and
`qwen-opencode:latest`. Each provider's `whitelist` exactly matches its
declared models, so raw base tags served by Ollama stay out of the picker. A
base tag (`flint:latest`, `qwen3:30b-a3b`) has no `num_ctx` pin and must not be
used as an agent model.

## Rules that matter

- `tool_call: true` is required; without it OpenCode may treat the model as a
  chat model instead of an agent model.
- `limit.context` and `num_ctx` must agree. The kit default is 131072 (128K).
- `limit.output` and `num_predict` are per model: Flint 32768, Qwen 8192.
- No `small_model` pin. Side traffic follows the session's own route instead
  of leaking around the proxy.
- No `apiKey` anywhere. The stack is local and keyless.
- Port 8787 is baked in. If you change `HEADROOM_PORT`, edit `baseURL` here to
  match.
- Model keys must match the fully qualified IDs Ollama reports, tag included.

## Headroom wrap

`headroom wrap opencode` injects its own config and starts its proxy. Pass the
upstream override at launch:

```
headroom wrap opencode --openai-api-url http://localhost:11434/v1
```

Without it, wrap defaults to `https://api.openai.com/v1` and local requests
fail with a 401. The kit's launch scripts set both the flag and
`OPENAI_TARGET_API_URL`.

## Zero-config check

Ollama ships its own launcher:

```
ollama launch opencode --model flint
```

Useful as a sanity check. If that works and the kit config does not, the diff
is in this folder, not your machine.

More detail: [docs/reference/ARCHITECTURE.md](../docs/reference/ARCHITECTURE.md)
and [docs/reference/DESIGN-NOTES.md](../docs/reference/DESIGN-NOTES.md).
