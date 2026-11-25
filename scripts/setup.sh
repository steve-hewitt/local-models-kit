#!/usr/bin/env bash
# Setup for local-models-kit on Linux / macOS.
# Run from the repo root:  ./scripts/setup.sh
#
# --client-only is for the "Windows serves, WSL drives" topology
# (docs/WSL.md): this side runs OpenCode only. The Ollama server, the
# model pull, and the pinned variant build all live on the Windows
# side, so client-only skips every Ollama install, pull, and build
# step, never runs a local server, and only checks OpenCode, checks
# that the remote server answers at localhost:11434, and installs
# the OpenCode config. Also settable as KIT_CLIENT_ONLY=1.
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_TAG="${MODEL_TAG:-flint}"
# Context pins. 131072 (128K) is the kit default since 2026-11-09
# (the old 32768 default was unusable for agent work; 128K is
# the floor). NUM_CTX sets the primary model's pin and can go up to
# 262144 for Flint. Qwen keeps its own pin: 131072 is Qwen3-30B-A3B's
# documented YaRN ceiling, so raising NUM_CTX never drags Qwen past
# what the model supports. Both values are baked into the built
# variants and into the installed config below.
NUM_CTX="${NUM_CTX:-131072}"
QWEN_NUM_CTX="${QWEN_NUM_CTX:-131072}"
MIN_OLLAMA="0.40.8"

CLIENT_ONLY="${KIT_CLIENT_ONLY:-0}"
for arg in "$@"; do
  case "$arg" in
    --client-only) CLIENT_ONLY=1 ;;
    *) echo "Unknown argument: $arg (supported: --client-only)" >&2; exit 2 ;;
  esac
done

echo "== local-models-kit setup =="
if [ "$CLIENT_ONLY" = "1" ]; then
  echo "Client-only mode: OpenCode side only. The Ollama server and"
  echo "models live on the other side (Windows); nothing Ollama gets"
  echo "installed, pulled, built, or served here."
fi

have() { command -v "$1" >/dev/null 2>&1; }

version_lt() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" = "$1" ] && [ "$1" != "$2" ]; }

# --- Ollama ---------------------------------------------------------------
if [ "$CLIENT_ONLY" = "1" ]; then
  # No local Ollama is required, wanted, or used as a server here. An
  # ollama binary left in the guest is harmless as a client, but never
  # run `ollama serve` in WSL: it would be CPU-only and could shadow
  # the Windows server on port 11434.
  if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    echo "WSL2 detected: expected in client-only mode. WSL is the client;"
    echo "the server is the native Windows Ollama from Part 1 of docs/WSL.md."
  fi
  if have ollama; then
    echo "Note: an ollama binary exists here. That is fine as a client,"
    echo "but do not run 'ollama serve' in this guest (CPU-only, and it"
    echo "can shadow the Windows server on port 11434)."
  else
    echo "No local ollama binary: expected in client-only mode."
  fi
  if have curl && curl -fsS --max-time 10 http://localhost:11434/api/version >/dev/null 2>&1; then
    echo "Ollama server answers at localhost:11434 (the Windows server, via mirrored networking)."
  else
    echo "WARNING: the Ollama server does not answer at localhost:11434 yet." >&2
    echo "Finish Part 2 of docs/WSL.md (mirrored networking, wsl --shutdown)" >&2
    echo "and make sure the Windows Ollama tray app is running, then run" >&2
    echo "the smoke test. Continuing with the client-side setup anyway." >&2
  fi
  if ! have curl; then
    echo "WARNING: curl not found. The smoke test needs it; install with:"
    echo "  sudo apt-get install -y curl"
  fi
  if ! have python3; then
    echo "WARNING: python3 not found. The smoke test uses it for config"
    echo "and residency checks; install with: sudo apt-get install -y python3"
  fi
else
  if ! have ollama; then
    echo "Ollama not found. Install it:"
    echo "  Linux:  curl -fsSL https://ollama.com/install.sh | sh"
    echo "          (Debian/Ubuntu: the installer needs zstd first:"
    echo "           sudo apt-get install -y zstd)"
    echo "  macOS:  brew install ollama   (or the app from https://ollama.com/download)"
    exit 1
  fi
  # WSL2 warning: the guest has no ROCm device, so Ollama runs CPU-only.
  if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
    echo "WARNING: WSL2 detected. WSL2 does not expose AMD ROCm compute"
    echo "(no /dev/kfd; /dev/dxg is Direct3D, not ROCm), so Ollama will"
    echo "run CPU-only in this guest no matter what the Windows side sees."
    echo "For GPU speed, run Ollama natively on Windows. In WSL2, expect"
    echo "slow turns, or use a smaller model. See docs/HARDWARE.md."
    echo "If Windows is meant to serve and WSL only drives, stop here and"
    echo "re-run with --client-only instead (see docs/WSL.md, Part 3)."
  fi
  OLLAMA_VER="$(ollama --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)"
  echo "Ollama: ${OLLAMA_VER:-unknown}"
  if [ -n "$OLLAMA_VER" ] && version_lt "$OLLAMA_VER" "$MIN_OLLAMA"; then
    echo "WARNING: Ollama $OLLAMA_VER is older than $MIN_OLLAMA (2026-10-21)."
    echo "Flint support landed 2026-10-21. Update Ollama before debugging any model load failure."
  fi
fi

# --- OpenCode -------------------------------------------------------------
if ! have opencode; then
  echo "OpenCode not found. Install it:"
  echo "  curl -fsSL https://opencode.ai/v2/install | bash"
  echo "  or: npm install -g @opencode/cli"
  exit 1
fi
echo "OpenCode: $(opencode --version)"

# --- Headroom -------------------------------------------------------------
export HEADROOM_TELEMETRY=off HEADROOM_BEACON=off DO_NOT_TRACK=1
# Headroom is optional: only the headroom paths need it. The direct
# path (the baseline this kit tells you to prove first) must not be
# blocked by a missing optional layer.
if ! have headroom; then
  echo "WARNING: Headroom not found; continuing without it."
  echo "The direct path will work. Install Headroom later for the"
  echo "compressed paths. Preferred install (isolated env, needs uv):"
  echo '  uv tool install --python 3.13 "headroom-ai[all]"'
  echo "Fallback:"
  echo '  pip install "headroom-ai[all]"'
else
  echo "Headroom: installed (telemetry forced off by this kit)"
fi

# --- Model ----------------------------------------------------------------
if [ "$CLIENT_ONLY" = "1" ]; then
  echo "Client-only: skipping the model pull and the pinned variant build."
  echo "The Windows side did both in Part 1 of docs/WSL.md (setup.ps1"
  echo "-ServerOnly). If the pinned model is missing there, go back to"
  echo "that step; do not pull or serve from this guest."
else
echo "Pulling model $MODEL_TAG (about 23 GB for flint, one-time)..."
ollama pull "$MODEL_TAG"

# The prefix picks the family's Modelfile (for its parameters) and the
# variant's default name. The variant itself is always built FROM the
# tag that was pulled: the shipped Modelfiles hardcode a FROM line for
# the family default, so building from one directly would pull and pin
# that default even when MODEL_TAG names another tag in the family.
case "$MODEL_TAG" in
  flint*) MODELF="models/Modelfile.flint-opencode"; DEFAULT_CUSTOM="flint-opencode" ;;
  qwen*)  MODELF="models/Modelfile.qwen-opencode";  DEFAULT_CUSTOM="qwen-opencode" ;;
  *)      MODELF="" ;;
esac
BUILT_NAME=""
BUILT_FROM=""
if [ -n "$MODELF" ]; then
  CUSTOM_TAG="${CUSTOM_MODEL_TAG:-$DEFAULT_CUSTOM}"
  case "$MODEL_TAG" in
    qwen*) BUILD_CTX="$QWEN_NUM_CTX" ;;
    *)     BUILD_CTX="$NUM_CTX" ;;
  esac
  TMP_MODELF="$(mktemp)"
  sed -e "s|^FROM .*|FROM $MODEL_TAG|" -e "s|^PARAMETER num_ctx .*|PARAMETER num_ctx $BUILD_CTX|" "$KIT_ROOT/$MODELF" > "$TMP_MODELF"
  echo "Building context-pinned variant $CUSTOM_TAG from $MODEL_TAG (context $BUILD_CTX, parameters from $MODELF)..."
  ollama create "$CUSTOM_TAG" -f "$TMP_MODELF"
  rm -f "$TMP_MODELF"
  BUILT_NAME="$CUSTOM_TAG"
  BUILT_FROM="$MODEL_TAG"
else
  echo "No context-pinned variant ships for $MODEL_TAG; skipping that build."
  echo "The model itself is pulled and declared models still work; context"
  echo "then follows Ollama's runtime default instead of the kit's pin."
fi

# --- Optional Qwen model ----------------------------------------------------
if [ "${WITH_QWEN:-0}" = "1" ]; then
  QWEN_TAG="${QWEN_TAG:-qwen3:30b-a3b}"
  QWEN_CUSTOM_TAG="${QWEN_CUSTOM_TAG:-qwen-opencode}"
  echo "Pulling optional model $QWEN_TAG (about 19 GB, one-time)..."
  ollama pull "$QWEN_TAG"
  if [ "$BUILT_NAME" = "$QWEN_CUSTOM_TAG" ] && [ "$BUILT_FROM" = "$QWEN_TAG" ]; then
    echo "Variant $QWEN_CUSTOM_TAG was already built from $QWEN_TAG above; skipping the duplicate build."
  else
    TMP_MODELF="$(mktemp)"
    sed -e "s|^FROM .*|FROM $QWEN_TAG|" -e "s|^PARAMETER num_ctx .*|PARAMETER num_ctx $QWEN_NUM_CTX|" "$KIT_ROOT/models/Modelfile.qwen-opencode" > "$TMP_MODELF"
    echo "Building context-pinned variant $QWEN_CUSTOM_TAG from $QWEN_TAG (context $QWEN_NUM_CTX)..."
    ollama create "$QWEN_CUSTOM_TAG" -f "$TMP_MODELF"
    rm -f "$TMP_MODELF"
  fi
fi
fi

# --- OpenCode config ------------------------------------------------------
# The installed config's context limits and picker labels are written
# from NUM_CTX / QWEN_NUM_CTX, so the config OpenCode budgets against
# always matches the variants built above. The repo config stays the
# 131072 default template; substitution happens only in the installed
# copy. python3 does the structured edit; without it, install the
# template as-is and say so.
install_config() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$KIT_ROOT/config/opencode.json" "$CONFIG_PATH" "$NUM_CTX" "$QWEN_NUM_CTX" <<'PYEOF'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
flint_ctx, qwen_ctx = int(sys.argv[3]), int(sys.argv[4])
def label(n):
    return f"{n // 1024}K" if n % 1024 == 0 else str(n)
cfg = json.load(open(src))
for provider in cfg["provider"].values():
    for key, model in provider["models"].items():
        ctx = qwen_ctx if key.startswith("qwen") else flint_ctx
        model["limit"]["context"] = ctx
        model["name"] = model["name"].replace("128K", label(ctx))
with open(dst, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print(f"Kit config installed to {dst} (Flint context {flint_ctx}, Qwen context {qwen_ctx})")
PYEOF
  else
    cp "$KIT_ROOT/config/opencode.json" "$CONFIG_PATH"
    echo "Kit config installed to $CONFIG_PATH (default 131072 contexts; python3 not found, so NUM_CTX was not substituted into the installed copy)"
  fi
}
CONFIG_DIR="$HOME/.config/opencode"
CONFIG_PATH="$CONFIG_DIR/opencode.json"
mkdir -p "$CONFIG_DIR"
if [ -f "$CONFIG_PATH" ]; then
  BACKUP="$CONFIG_PATH.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$CONFIG_PATH" "$BACKUP"
  echo "Existing OpenCode config backed up to $BACKUP"
  printf "Overwrite global config with the kit config? (y/N) "
  read -r answer
  if [ "$answer" = "y" ]; then
    install_config
  else
    echo "Skipped. Kit config is at $KIT_ROOT/config/opencode.json for per-project use."
  fi
else
  install_config
fi

echo
if [ "$CLIENT_ONLY" = "1" ]; then
  echo "Ollama service environment: nothing to set on this side. Those"
  echo "variables belong to the Windows server and were set in Part 1"
  echo "of docs/WSL.md before the tray app was restarted."
else
  echo "Ollama service environment (one-time, recommended on the 64 GB target):"
  echo "the pinned variants fix the context per model, but two server-side"
  echo "knobs still belong in the Ollama service environment, not in a"
  echo "shell export (an export here cannot reach a systemd service that"
  echo "is already running). On Linux:"
  echo "  sudo systemctl edit ollama"
  echo "    [Service]"
  echo "    Environment=\"OLLAMA_MAX_LOADED_MODELS=1\""
  echo "    Environment=\"OLLAMA_CONTEXT_LENGTH=$NUM_CTX\""
  echo "  sudo systemctl restart ollama"
  echo "On macOS, set the same variables before starting the Ollama app,"
  echo "or launch the server from a shell that has them exported."
fi
echo
echo "Setup done. Next:"
echo "  ./scripts/smoke-test.sh"
echo "  ./scripts/launch-direct.sh     (baseline)"
echo "  ./scripts/launch-headroom.sh   (full stack, needs Headroom)"
