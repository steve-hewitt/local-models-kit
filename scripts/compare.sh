#!/usr/bin/env bash
# A/B compare harness: Flint vs Qwen, direct vs Headroom, same workload.
#
# Cells:
#   bench  : raw decode speed per model via Ollama's /api/generate
#            counters (eval_count / eval_duration), N runs after one
#            discarded warm-up run, median taken.
#   agent  : the hello-agent task via `opencode run -m <provider>/<model>`
#            in a throwaway copy, per provider route (ollama, headroom).
#            Each cell first warms its model with a 1-token generate
#            (timed separately, reported as warm-up) so model load does
#            not contaminate the route comparison, and cells interleave
#            by model so no route systematically pays cold loads.
#            Records pass/fail, wall time, warm-up time, whether the
#            test file was left untouched (it must be; the task says
#            so), and a diff of the final calc.py in the cell log.
#
# The default models are the context-pinned variants, named by their
# OpenCode config keys (the same strings Ollama reports at /v1/models).
# Bench calls use the same names against Ollama's API, where the
# qualified form is canonical.
#
# Usage:
#   ./scripts/compare.sh [--plan] [--skip-agent] [--runs 3] [--timeout 600]
#                        [--models "flint-opencode:latest qwen-opencode:latest"]
#
# --plan prints the cell matrix and exits. CI uses it to prove the harness
# loads; no models or servers are touched.
#
# Output: a markdown report in results/compare-<timestamp>.md plus a
# summary on stdout. Model misbehavior is data, not a harness failure:
# the script exits nonzero only when the harness itself cannot run.
set -uo pipefail

KIT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="flint-opencode:latest qwen-opencode:latest"
RUNS=3
TIMEOUT=600
PLAN=0
SKIP_AGENT=0
PROXY_PORT="${HEADROOM_PORT:-8787}"
PROMPT="The tests in test_calc.py are failing. Find the bug in calc.py, fix only what is wrong, and run the tests to confirm they pass. Do not change the tests."
BENCH_PROMPT="Write a Python function that checks whether a string is a palindrome, with a docstring and two example calls. Output only code."

while [ $# -gt 0 ]; do
  case "$1" in
    --plan) PLAN=1 ;;
    --skip-agent) SKIP_AGENT=1 ;;
    --runs) RUNS="$2"; shift ;;
    --timeout) TIMEOUT="$2"; shift ;;
    --models) MODELS="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$PLAN" -eq 1 ]; then
  echo "Compare plan"
  echo "  bench cells (raw tok/s via Ollama API, $RUNS runs each after 1 warm-up, median):"
  for m in $MODELS; do echo "    - $m"; done
  if [ "$SKIP_AGENT" -eq 1 ]; then
    echo "  agent cells: skipped (--skip-agent)"
  else
    echo "  agent cells (hello-agent via opencode run, timeout ${TIMEOUT}s, model-major order, per-cell warm-up):"
    for m in $MODELS; do
      echo "    - ollama/$m"
      echo "    - headroom/$m (only if a proxy answers on 127.0.0.1:$PROXY_PORT)"
    done
  fi
  echo "  report: results/compare-<timestamp>.md"
  exit 0
fi

command -v ollama >/dev/null || { echo "ollama not found" >&2; exit 1; }
curl -fsS --max-time 5 http://localhost:11434/api/tags >/dev/null || { echo "Ollama API not answering on localhost:11434" >&2; exit 1; }

# The test-file integrity check needs a SHA-256 tool. Stock macOS has
# shasum but not sha256sum; python3 is already a harness prerequisite.
# If none exists, refuse to run: a check that silently compares two
# empty strings would report "untouched: yes" for a tampered file.
hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
  else
    return 1
  fi
}

# Run the agent for one cell with a real timeout on every supported
# platform. GNU timeout and gtimeout (coreutils on macOS) return 124;
# the fallback is a background watchdog, since a bare run would hang
# forever on a stuck agent.
run_agent() {  # $1 = cell dir, $2 = route/model, $3 = log file
  AGENT_TIMED_OUT=0
  if command -v timeout >/dev/null 2>&1; then
    (cd "$1" && timeout "$TIMEOUT" opencode run -m "$2" "$PROMPT" > "$3" 2>&1)
    AGENT_RC=$?
    [ "$AGENT_RC" -eq 124 ] && AGENT_TIMED_OUT=1
  elif command -v gtimeout >/dev/null 2>&1; then
    (cd "$1" && gtimeout "$TIMEOUT" opencode run -m "$2" "$PROMPT" > "$3" 2>&1)
    AGENT_RC=$?
    [ "$AGENT_RC" -eq 124 ] && AGENT_TIMED_OUT=1
  else
    (cd "$1" && exec opencode run -m "$2" "$PROMPT" > "$3" 2>&1) &
    local pid=$!
    ( sleep "$TIMEOUT"
      if kill -0 "$pid" 2>/dev/null; then
        touch "$1/.timedout"
        kill -TERM "$pid" 2>/dev/null
        sleep 5
        kill -KILL "$pid" 2>/dev/null
      fi ) &
    local watchdog=$!
    wait "$pid" 2>/dev/null
    AGENT_RC=$?
    kill "$watchdog" 2>/dev/null
    wait "$watchdog" 2>/dev/null
    [ -f "$1/.timedout" ] && AGENT_TIMED_OUT=1
  fi
}

STAMP="$(date +%Y%m%d-%H%M%S)"
RESULTS_DIR="$KIT_ROOT/results"
mkdir -p "$RESULTS_DIR"
REPORT="$RESULTS_DIR/compare-$STAMP.md"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Effective num_ctx per model, from the server itself, so every report
# records the conditions it was measured under.
NUMCTX_LINE=""
for m in $MODELS; do
  SHOW="$(curl -fsS --max-time 10 http://localhost:11434/api/show \
    -H 'Content-Type: application/json' -d "{\"name\":\"$m\"}" 2>/dev/null || echo '{}')"
  NC="$(echo "$SHOW" | python3 -c "
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
")"
  NUMCTX_LINE="$NUMCTX_LINE $m=$NC"
done

{
  echo "# Compare run $STAMP"
  echo
  echo "- Host: $(hostname)"
  echo "- Ollama: $(ollama --version 2>/dev/null | head -n1)"
  echo "- OpenCode: $(opencode --version 2>/dev/null || echo 'not found')"
  echo "- Bench runs per model: $RUNS (plus 1 warm-up run, shown first and excluded from the median)"
  echo "- Effective num_ctx per /api/show:$NUMCTX_LINE"
  echo "- small_model: not pinned by the kit config, so title and summary traffic follows each cell's own route; no side channel around the proxy and no second model loaded by the harness config"
  echo
  echo "## Raw decode speed (Ollama API counters)"
  echo
  echo "| Model | Decode tok/s per run (first is warm-up) | Median |"
  echo "| --- | --- | --- |"
} > "$REPORT"

for m in $MODELS; do
  VALUES=""
  TOTAL_RUNS=$((RUNS + 1))
  for i in $(seq 1 "$TOTAL_RUNS"); do
    RESP="$(curl -fsS --max-time 600 http://localhost:11434/api/generate \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"$m\",\"prompt\":\"$BENCH_PROMPT\",\"stream\":false}" 2>/dev/null || echo '{}')"
    V="$(echo "$RESP" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ec, ed = d.get('eval_count', 0), d.get('eval_duration', 0)
    print(f'{ec / (ed / 1e9):.1f}' if ed else 'NA')
except Exception:
    print('NA')
")"
    VALUES="$VALUES $V"
  done
  MEDIAN="$(echo $VALUES | python3 -c "
import sys
vals = [None if x == 'NA' else float(x) for x in sys.stdin.read().split()]
kept = sorted(v for v in vals[1:] if v is not None)
print(f'{kept[len(kept)//2]:.1f}' if kept else 'NA')
")"
  echo "| $m | $VALUES | $MEDIAN |" >> "$REPORT"
  echo "bench $m: runs [$VALUES ] median $MEDIAN tok/s (first run excluded)"
done

if [ "$SKIP_AGENT" -eq 0 ]; then
  command -v opencode >/dev/null || { echo "opencode not found, agent cells cannot run" >&2; exit 1; }
  hash_file "$KIT_ROOT/examples/hello-agent/test_calc.py" >/dev/null || {
    echo "no SHA-256 tool available (need sha256sum, shasum, or python3);" >&2
    echo "the test-file integrity check cannot run, so no report will be produced." >&2
    exit 1
  }
  PROXY_UP=0
  CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$PROXY_PORT/health" || true)"
  if [ "$CODE" = "200" ]; then PROXY_UP=1; fi

  {
    echo
    echo "## Agent task: hello-agent (one run per cell)"
    echo
    echo "| Route | Model | Result | Seconds | Warm-up s | Test file untouched |"
    echo "| --- | --- | --- | --- | --- | --- |"
  } >> "$REPORT"

  for m in $MODELS; do
    for route in ollama headroom; do
      if [ "$route" = "headroom" ] && [ "$PROXY_UP" -eq 0 ]; then
        echo "| headroom | $m | skipped, proxy not running | NA | NA | NA |" >> "$REPORT"
        echo "agent headroom/$m: skipped (proxy not running)"
        continue
      fi
      CELL="$WORK/$route-$(echo "$m" | tr '/:' '__')"
      mkdir -p "$CELL"
      cp "$KIT_ROOT/examples/hello-agent/calc.py" "$KIT_ROOT/examples/hello-agent/test_calc.py" "$CELL/"
      BEFORE="$(hash_file "$CELL/test_calc.py")"
      # Warm the model (1-token generate) so its load time is measured
      # here, not inside the cell's wall time.
      WARM_START="$(date +%s)"
      curl -fsS --max-time 900 http://localhost:11434/api/generate \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"$m\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}" \
        > /dev/null 2>&1 || true
      WARM_SECS=$(( $(date +%s) - WARM_START ))
      LOG="$RESULTS_DIR/compare-$STAMP-$route-$(echo "$m" | tr '/:' '__').log"
      START="$(date +%s)"
      run_agent "$CELL" "$route/$m" "$CELL/agent.log"
      END="$(date +%s)"
      SECS=$((END - START))
      if [ "$AGENT_TIMED_OUT" -eq 1 ]; then
        RESULT="timeout in ${TIMEOUT}s"
      elif (cd "$CELL" && python3 test_calc.py > /dev/null 2>&1); then
        RESULT="pass"
      else
        RESULT="fail"
      fi
      AFTER="$(hash_file "$CELL/test_calc.py")"
      if [ "$BEFORE" = "$AFTER" ]; then UNTOUCHED="yes"; else UNTOUCHED="NO"; fi
      {
        cat "$CELL/agent.log"
        echo
        echo "== calc.py diff vs the pristine example (empty means the file is unchanged) =="
        diff -u "$KIT_ROOT/examples/hello-agent/calc.py" "$CELL/calc.py" || true
      } > "$LOG" 2>/dev/null || true
      echo "| $route | $m | $RESULT | $SECS | $WARM_SECS | $UNTOUCHED |" >> "$REPORT"
      echo "agent $route/$m: $RESULT in ${SECS}s (warm-up ${WARM_SECS}s), test untouched: $UNTOUCHED"
    done
  done
fi

{
  echo
  echo "How to read this: docs/reference/COMPARE.md. One agent run per cell is an"
  echo "anecdote with a timestamp, not a benchmark. The bench medians are"
  echo "the comparable numbers; the agent cells answer 'did it do the job'."
} >> "$REPORT"

echo
echo "Report written to $REPORT"
