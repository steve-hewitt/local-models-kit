#!/usr/bin/env bash
# Measure real decode and prefill speed for the local model via Ollama's
# native API, which reports eval_count and eval_duration directly.
# This replaces publisher speed claims with your machine's actual number.
#
# Usage: ./scripts/bench.sh [model_tag] [runs]
set -euo pipefail

MODEL_TAG="${1:-${MODEL_TAG:-flint-opencode:latest}}"
RUNS="${2:-3}"
PROMPT="Write a Python function that checks whether a string is a palindrome, with a docstring and two example calls. Output only code."

# Record the effective context next to every number: a bench taken at
# Ollama's 4096 default is not comparable to one taken at the kit's
# pinned 131072 (this bit the first hands-on run, at the old 4096
# default; compare.sh already records num_ctx, bench now does too).
SHOW="$(curl -fsS --max-time 10 http://localhost:11434/api/show \
  -H 'Content-Type: application/json' -d "{\"name\":\"$MODEL_TAG\"}" 2>/dev/null || echo '{}')"
EFFECTIVE_CTX="$(printf '%s' "$SHOW" | python3 -c "
import sys, json
try:
    params = json.load(sys.stdin).get('parameters', '')
    for line in params.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == 'num_ctx':
            print(parts[1]); break
    else:
        print('not reported')
except Exception:
    print('not reported')
" 2>/dev/null || echo 'not reported')"
echo "Benchmarking $MODEL_TAG on this machine ($RUNS runs, warm-up included as run 1)"
EXPECTED_CTX="${NUM_CTX:-131072}"
case "$MODEL_TAG" in
  *qwen*) EXPECTED_CTX="${QWEN_NUM_CTX:-131072}" ;;
esac
echo "Effective num_ctx (from /api/show): $EFFECTIVE_CTX"
if [ "$EFFECTIVE_CTX" != "$EXPECTED_CTX" ]; then
  echo "WARNING: effective num_ctx is $EFFECTIVE_CTX, not the kit's pinned $EXPECTED_CTX."
  echo "Numbers from this run are not comparable to runs at $EXPECTED_CTX. The pinned"
  echo "*-opencode variants report their pin; base tags report nothing and"
  echo "run at Ollama's 4096 default."
fi
printf "%-6s %-12s %-12s %-10s\n" "run" "decode_t/s" "prefill_t/s" "tokens"

for i in $(seq 1 "$RUNS"); do
  RESP="$(curl -fsS --max-time 600 http://localhost:11434/api/generate \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL_TAG\",\"prompt\":\"$PROMPT\",\"stream\":false}")"
  echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ec, ed = d.get('eval_count', 0), d.get('eval_duration', 0)
pc, pd = d.get('prompt_eval_count', 0), d.get('prompt_eval_duration', 0)
dec = ec / (ed / 1e9) if ed else 0
pre = pc / (pd / 1e9) if pd else 0
print(f'{\"$i\":<6} {dec:<12.1f} {pre:<12.1f} {ec:<10}')
"
done

echo
echo "Record the median decode number, with date, machine, context size, and"
echo "Ollama version, in docs/reference/VALIDATION.md. Publisher numbers were measured"
echo "with a different engine on different hardware; yours is the one that counts."
