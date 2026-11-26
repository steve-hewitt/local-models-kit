#!/usr/bin/env bash
# Smoke test: proves each layer works, in bisection order.
# Run after setup.sh. Safe to re-run any time.
#
# This test exists because the first hands-on run (2026-10-24, WSL2)
# passed every old check while the agent was broken: the default model
# was the unpinned flint:latest (effective context 4096, prompt
# truncated from 6653 tokens to 2050) and Ollama was CPU-only under
# WSL2 with no ROCm device. So this version checks the things that
# actually decide whether agent work works:
#   - the selected model is the context-pinned *-opencode variant
#   - its effective num_ctx from /api/show is at least the kit context
#   - the loaded model's context from /api/ps agrees
#   - GPU residency: CPU-only (size_vram 0) is a loud warning, not a pass
#   - the kit config declares no unpinned model, and every declared
#     limit matches its Modelfile pin
# Headroom is optional: it is only needed for the headroom paths, so a
# missing binary or a stopped proxy warns instead of failing.
set -uo pipefail

KIT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_TAG="${MODEL_TAG:-flint}"
EXPECTED_CTX="${NUM_CTX:-131072}"
case "$MODEL_TAG" in
  qwen*) EXPECTED_CTX="${QWEN_NUM_CTX:-131072}" ;;
esac
FAIL=0
WARN=0

# Agent work must use the pinned variant built from MODEL_TAG, never
# the base tag: base tags carry no num_ctx and Ollama falls back to
# 4096, which truncates OpenCode's prompt.
case "$MODEL_TAG" in
  *-opencode|*-opencode:*) SELECTED="$MODEL_TAG" ;;
  flint*) SELECTED="${CUSTOM_MODEL_TAG:-flint-opencode}" ;;
  qwen*)  SELECTED="${QWEN_CUSTOM_TAG:-qwen-opencode}" ;;
  *)      SELECTED="$MODEL_TAG" ;;
esac
case "$SELECTED" in *:*) ;; *) SELECTED="$SELECTED:latest" ;; esac

check() { # check <name> <0=pass>
  if [ "$2" -eq 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; FAIL=$((FAIL+1)); fi
}
warn() { echo "WARN  $1"; WARN=$((WARN+1)); }

echo "Selected model for agent work: $SELECTED (expected context >= $EXPECTED_CTX)"

echo "== versions =="
if ollama --version >/dev/null 2>&1; then
  check "ollama CLI: $(ollama --version 2>/dev/null | head -n1)" 0
else
  # Client-only sides (WSL driving a Windows server, docs/WSL.md) have
  # no ollama CLI and need none: the API is the interface, and every
  # server check below already goes through it. Get the server version
  # from /api/version instead of failing a correct setup.
  API_VER="$(curl -fsS --max-time 10 http://localhost:11434/api/version 2>/dev/null | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  if [ -n "$API_VER" ]; then
    echo "PASS  ollama server via API: version $API_VER (no local CLI; expected when WSL is client-only)"
  else
    check "ollama: no local CLI, and the server API does not answer at localhost:11434" 1
  fi
fi
opencode --version >/dev/null 2>&1; check "opencode: $(opencode --version 2>/dev/null | head -n1)" $?
if command -v headroom >/dev/null 2>&1; then
  echo "PASS  headroom present"
else
  warn "headroom not found (optional: only the headroom paths need it; the direct path works without it)"
fi

echo "== environment =="
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null || [ "$(systemd-detect-virt 2>/dev/null || true)" = "wsl" ]; then
  warn "WSL2 detected. That is fine in the bridged topology (docs/WSL.md): WSL runs the client, Windows runs the server. What would be CPU-only is an Ollama server running inside this guest (no /dev/kfd; /dev/dxg is Direct3D, not ROCm). The residency check below is the tell: size_vram above 0 means you are talking to the Windows GPU server; CPU-only there means a WSL-local server is shadowing it."
fi

echo "== kit config =="
if [ -f "$KIT_ROOT/config/opencode.json" ] && command -v python3 >/dev/null 2>&1; then
  python3 - "$KIT_ROOT/config/opencode.json" "$KIT_ROOT" <<'PYEOF'
import json, re, sys
cfg = json.load(open(sys.argv[1]))
root = sys.argv[2]
def modelfile_ctx(name):
    text = open(f"{root}/models/Modelfile.{name}").read()
    return int(re.search(r"PARAMETER num_ctx (\d+)", text).group(1))
family_ctx = {"flint": modelfile_ctx("flint-opencode"), "qwen": modelfile_ctx("qwen-opencode")}
default = cfg.get("model")
if default and (str(default).startswith("ollama/") or str(default).startswith("headroom/")):
    assert "-opencode" in str(default), f"kit default {default!r} is not a context-pinned *-opencode variant"
for pname, provider in cfg.get("provider", {}).items():
    for key, model in provider.get("models", {}).items():
        assert "-opencode" in key, f"{pname}/{key} is declared but not context-pinned; an unpinned entry must not be offered for agent work"
        want = family_ctx[key.split("-")[0]]
        assert model["limit"]["context"] == want, f"{pname}/{key} limit.context is {model['limit']['context']}, expected {want} to match its Modelfile num_ctx"
    assert set(provider.get("whitelist", [])) == set(provider.get("models", {})), (
        f"{pname} whitelist must exactly match its declared models; otherwise the picker can "
        "surface unpinned base tags that the endpoint also serves")
print("config ok")
PYEOF
  check "every declared model is a pinned *-opencode variant, every declared limit matches its Modelfile pin, and each picker whitelist matches its declared models" $?
else
  warn "kit config or python3 not found; config checks skipped"
fi

echo "== ollama server =="
TAGS="$(curl -fsS --max-time 10 http://localhost:11434/api/tags 2>/dev/null)"
check "Ollama API answers at localhost:11434" $?
if [ -n "${TAGS:-}" ]; then
  echo "$TAGS" | grep -q "$SELECTED"; check "pinned model present: $SELECTED" $?
fi

echo "== effective context (from /api/show) =="
SHOW="$(curl -fsS --max-time 10 http://localhost:11434/api/show \
  -H 'Content-Type: application/json' -d "{\"name\":\"$SELECTED\"}" 2>/dev/null)"
if [ -n "${SHOW:-}" ] && command -v python3 >/dev/null 2>&1; then
  NUM_CTX="$(printf '%s' "$SHOW" | python3 -c "
import sys, json
try:
    params = json.load(sys.stdin).get('parameters', '')
    for line in params.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == 'num_ctx':
            print(parts[1]); break
    else:
        print('')
except Exception:
    print('')
")"
  if [ -n "$NUM_CTX" ] && [ "$NUM_CTX" -ge "$EXPECTED_CTX" ]; then
    echo "PASS  effective num_ctx for $SELECTED is $NUM_CTX (>= $EXPECTED_CTX)"
  else
    echo "FAIL  effective num_ctx for $SELECTED is '${NUM_CTX:-not reported}' (expected >= $EXPECTED_CTX). An unpinned model runs at 4096 and truncates agent prompts. Run setup to build the *-opencode variant."
    FAIL=$((FAIL+1))
  fi
else
  check "could not read /api/show for $SELECTED" 1
fi

echo "== raw model round trip =="
RESP="$(curl -fsS --max-time 300 http://localhost:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$SELECTED\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly this word: ready\"}],\"stream\":false}" 2>/dev/null)"
check "model round trip via /v1/chat/completions ($SELECTED)" $?
if [ -n "${RESP:-}" ]; then
  echo "$RESP" | grep -qi "ready"; check "model answered with the expected word" $?
fi

echo "== residency (from /api/ps) =="
PS_JSON="$(curl -fsS --max-time 10 http://localhost:11434/api/ps 2>/dev/null)"
if [ -n "${PS_JSON:-}" ] && command -v python3 >/dev/null 2>&1; then
  printf '%s' "$PS_JSON" | SELECTED="$SELECTED" EXPECTED_CTX="$EXPECTED_CTX" python3 -c "
import sys, json, os
sel = os.environ['SELECTED']; want = int(os.environ['EXPECTED_CTX'])
try:
    models = json.load(sys.stdin).get('models', [])
except Exception:
    models = []
m = next((x for x in models if x.get('name') == sel or x.get('model') == sel), None)
if m is None:
    print('WARN  selected model not loaded in /api/ps yet; residency not verified')
    sys.exit(4)
ctx = m.get('context_length')
vram = m.get('size_vram', 0)
if ctx is not None and ctx < want:
    print(f'FAIL  loaded context_length is {ctx} (< {want}): prompts will truncate')
    sys.exit(3)
if not vram:
    print('WARN  model is CPU-only (size_vram is 0): agent turns will be slow (the 2026-10-24 WSL2 run took 56s to 1m40s per turn). On the target Windows machine this should be GPU-resident.')
    sys.exit(4)
print(f'PASS  model loaded with context_length {ctx}, size_vram {vram} bytes (GPU-resident)')
"
  PS_RC=$?
  # python exit codes: 0 = pass, 3 = context failure, 4 = warning.
  if [ "$PS_RC" -eq 3 ]; then FAIL=$((FAIL+1)); fi
  if [ "$PS_RC" -eq 4 ]; then WARN=$((WARN+1)); fi
else
  warn "could not read /api/ps; residency not verified"
fi

echo "== headroom proxy (optional) =="
if curl -fsS --max-time 3 http://127.0.0.1:8787/health >/dev/null 2>&1; then
  echo "PASS  headroom proxy answers at 127.0.0.1:8787/health"
else
  warn "headroom proxy not running on 8787 (only needed for the headroom paths; start it with scripts/start-headroom-proxy.sh)"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  if [ "$WARN" -gt 0 ]; then
    echo "All checks passed with $WARN warning(s). Now run the hello-agent example (see examples/hello-agent)."
    echo "Warnings above are real limitations of this environment, not noise: read them before judging agent speed or quality."
  else
    echo "All checks passed. Now run the hello-agent example (see examples/hello-agent)."
  fi
else
  echo "$FAIL check(s) failed, $WARN warning(s). Bisect with docs/TROUBLESHOOTING.md, in order."
  exit 1
fi
