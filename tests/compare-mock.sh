#!/usr/bin/env bash
# End-to-end exercise of scripts/compare.sh against fake servers and a
# fake agent with known behavior. This is the QC pass from the changelog,
# committed so CI can run it as a regression guard instead of trusting a
# one-time manual run.
#
# Fakes:
#   tests/fake-servers.py  Ollama API on 11434 (fixed 50.0 tok/s
#                          counters, num_ctx 131072) and a Headroom
#                          /health endpoint on 8787.
#   fake ollama binary     answers --version.
#   fake opencode binary   answers --version; for `run`, behaves per
#                          MOCK_AGENT_MODE: fix (applies the known
#                          one-function fix), noop (does nothing),
#                          tamper (fixes, then edits the test file),
#                          sleep (hangs, to prove timeout labeling).
#
# Assertions per mode, all against the generated report:
#   fix    -> agent cells pass, tests untouched, median 50.0, num_ctx
#             recorded from /api/show
#   noop   -> agent cells fail
#   tamper -> agent cells pass but the integrity column says NO
#   sleep  -> agent cells report "timeout in 3s"
#
# Needs exclusive use of ports 11434 and 8787. Exits nonzero on the
# first failed assertion.
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOCK_DIR="$(mktemp -d)"
SERVER_PID=""
BEFORE_LIST="$MOCK_DIR/before.txt"
ls "$KIT_ROOT/results" > "$BEFORE_LIST" 2>/dev/null || true

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  # Remove only the reports this run created.
  for f in "$KIT_ROOT"/results/compare-*; do
    [ -e "$f" ] || continue
    grep -qx "$(basename "$f")" "$BEFORE_LIST" || rm -f "$f"
  done
  rm -rf "$MOCK_DIR"
}
trap cleanup EXIT

if curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "port 11434 is already answering; the mock needs it exclusively" >&2
  exit 1
fi

if curl -fsS --max-time 2 http://127.0.0.1:8787/health >/dev/null 2>&1; then
  echo "port 8787 is already answering; the mock needs it exclusively" >&2
  exit 1
fi

mkdir -p "$MOCK_DIR/bin"
cat > "$MOCK_DIR/bin/ollama" << 'EOF'
#!/usr/bin/env bash
[ "${1:-}" = "--version" ] && echo "ollama version is 0.0.0-mock"
exit 0
EOF
cat > "$MOCK_DIR/bin/opencode" << 'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then echo "opencode 0.0.0-mock"; exit 0; fi
if [ "${1:-}" = "run" ]; then
  case "${MOCK_AGENT_MODE:-fix}" in
    fix|tamper)
      python3 - << 'PYEOF'
import pathlib
p = pathlib.Path("calc.py")
src = p.read_text()
buggy = "def mul(a, b):\n    # BUG: this adds instead of multiplying.\n    return a + b"
assert buggy in src, "deliberate bug block not found"
p.write_text(src.replace(buggy, "def mul(a, b):\n    return a * b"))
PYEOF
      if [ "${MOCK_AGENT_MODE}" = "tamper" ]; then
        echo "# tampered by the mock agent" >> test_calc.py
      fi
      ;;
    noop) ;;
    sleep) sleep 30 ;;
  esac
fi
exit 0
EOF
chmod +x "$MOCK_DIR/bin/ollama" "$MOCK_DIR/bin/opencode"
export PATH="$MOCK_DIR/bin:$PATH"

python3 "$KIT_ROOT/tests/fake-servers.py" &
SERVER_PID=$!
for i in $(seq 1 20); do
  curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null || { echo "fake Ollama API did not come up" >&2; exit 1; }
curl -fsS --max-time 2 http://127.0.0.1:8787/health >/dev/null || { echo "fake proxy health did not come up" >&2; exit 1; }

fail() { echo "MOCK ASSERTION FAILED: $1" >&2; exit 1; }

latest_report() { ls -t "$KIT_ROOT"/results/compare-*.md | head -n1; }

run_case() {  # $1 = mode, $2 = timeout
  MOCK_AGENT_MODE="$1" "$KIT_ROOT/scripts/compare.sh" --runs 1 --timeout "$2" > "$MOCK_DIR/out-$1.txt" 2>&1 \
    || { cat "$MOCK_DIR/out-$1.txt" >&2; fail "compare.sh exited nonzero in mode $1"; }
  latest_report
}

R="$(run_case fix 60)"
grep -q "| ollama | flint-opencode:latest | pass |" "$R" || fail "fix mode: direct Flint cell did not pass"
grep -q "| headroom | qwen-opencode:latest | pass |" "$R" || fail "fix mode: headroom Qwen cell did not pass"
grep -q "| 50.0 |" "$R" || fail "fix mode: bench median is not the mocked 50.0 tok/s"
grep -q "flint-opencode:latest=131072" "$R" || fail "fix mode: report header lacks the /api/show num_ctx"
grep -q "| yes |" "$R" || fail "fix mode: integrity column does not say yes"
echo "mock case fix: ok"

R="$(run_case noop 60)"
grep -q "| ollama | flint-opencode:latest | fail |" "$R" || fail "noop mode: cell did not report fail"
echo "mock case noop: ok"

R="$(run_case tamper 60)"
grep -q "| ollama | flint-opencode:latest | pass |" "$R" || fail "tamper mode: cell did not pass"
grep -q "| NO |" "$R" || fail "tamper mode: integrity column did not say NO"
echo "mock case tamper: ok"

R="$(run_case sleep 3)"
grep -q "timeout in 3s" "$R" || fail "sleep mode: cell did not report the timeout"
echo "mock case sleep: ok"

echo "compare-mock: all cases passed"
