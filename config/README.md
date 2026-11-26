# Config notes

`opencode.json` declares **two providers** using the OpenAI-compatible package
`@ai-sdk/openai-compatible`:

- `ollama`: direct to Ollama at `http://localhost:11434/v1`
- `headroom`: to the local Headroom proxy at `http://127.0.0.1:8787/v1`

Every declared model is a context-pinned variant under both providers, so the
provider prefix is the compression toggle: `ollama/...` never touches
Headroom; `headroom/...` always does.

## Models

Both models are first-class picker options. The kit ships **no default**: it
writes no top-level `model` field, so installing it does not change what a
bare `opencode` session opens on. Choose either model in `/models`, or set a
startup default yourself:

```json
"model":"ollama/flint-opencode:latest"
```

```json
"model":"ollama/qwen-opencode:latest"
```

The installer can write that field for you with `install --set-default`
(Flint, or Qwen with `--no-flint`). Kit launch scripts pin their own session
only; bare `opencode` is unaffected.

Only the pinned variants are declared: `flint-opencode:latest` and
`qwen-opencode:latest`. Each provider's `whitelist` matches its declared
models, but current OpenCode still surfaces endpoint-discovered base tags in
the picker, so pick only the "context-pinned 128K" rows. A base tag
(`flint:latest`, `qwen3:30b-a3b`) has no `num_ctx` pin and must not be used as
an agent model.

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
`OPENAI_TARGET_API_URL`. Wrap does not pin a model; select the Headroom
"context-pinned 128K" row in `/models` for the wrapped session.

## Zero-config check

Ollama ships its own launcher:

```
ollama launch opencode --model flint
```

Useful as a sanity check. If that works and the kit config does not, the diff
is in this folder, not your machine.

More detail: [docs/reference/ARCHITECTURE.md](../docs/reference/ARCHITECTURE.md)
and [docs/reference/DESIGN-NOTES.md](../docs/reference/DESIGN-NOTES.md).
