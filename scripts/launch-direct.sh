#!/usr/bin/env bash
# Baseline launch: OpenCode straight to Ollama, no Headroom.
# Always prove this path first. Usage: ./scripts/launch-direct.sh [project folder]
#
# The model must be the context-pinned variant
# (ollama/flint-opencode:latest). The base flint:latest tag carries
# no num_ctx, so Ollama serves it at the 4096 default and truncates
# OpenCode's prompt; that was the first hands-on run's main failure
# (2026-10-24).
#
# How the model gets selected depends on the OpenCode line. This
# script pins only the session it launches; a bare `opencode` is
# unaffected.
#   - OpenCode 1: the top-level -m flag exists, so this script passes
#     it explicitly.
#   - OpenCode 2: the top-level -m flag is gone ("Unrecognized flag:
#     -m in command opencode"), and there is no root --model either.
#     The script exports OPENCODE_CONFIG_CONTENT with a {"model": ...}
#     snippet and passes --standalone. Verified on 2.0.26, 2026-11-26:
#     with --standalone the TUI footer names the pinned Flint; without
#     it the shared background service ignores the env snippet.
# (`opencode run` still accepts -m/--model on both lines; the compare
# harness is unaffected.)
#
# OLLAMA_CONTEXT_LENGTH is exported below for one case only: if THIS
# shell also starts the Ollama server (`ollama serve`), the server
# reads it at startup. An Ollama service started any other way
# (systemd, tray app) never sees this shell's environment.
set -euo pipefail
export OLLAMA_CONTEXT_LENGTH="${NUM_CTX:-131072}"
MODEL="ollama/flint-opencode:latest"
cd "${1:-.}"
echo "Direct path: OpenCode -> Ollama (localhost:11434), model $MODEL (context pinned at 131072)."
VER_RAW="$(opencode --version 2>/dev/null | head -n1 || true)"
VER="$(printf '%s' "$VER_RAW" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1 || true)"
case "$VER" in
  1.*)
    echo "OpenCode $VER: passing -m $MODEL explicitly (the v1 top-level flag)."
    echo "Kit launches pin the model for this session only; bare opencode is unaffected."
    echo "In the TUI, /models should show the row labeled 'Flint 40B, context-pinned 128K' ($MODEL)."
    echo "Do not pick a raw flint:latest row if an older installed config shows one: it is the unpinned base tag."
    exec opencode -m "$MODEL"
    ;;
  2.*)
    echo "OpenCode $VER: pinning this session with OPENCODE_CONFIG_CONTENT and --standalone."
    echo "Kit launches pin the model for this session only; bare opencode is unaffected."
    echo "The TUI footer must name 'Flint 40B, context-pinned 128K' ($MODEL)."
    echo "A raw flint:latest row may appear in the picker; do not pick it, it is the unpinned base tag."
    export OPENCODE_CONFIG_CONTENT="{\"model\":\"$MODEL\"}"
    exec opencode --standalone
    ;;
  *)
    echo "WARNING: could not parse an OpenCode version from 'opencode --version' (got '${VER_RAW:-no output}')." >&2
    echo "Launching without a model pin. In the TUI, verify with /models that the live model is" >&2
    echo "$MODEL (picker label 'Flint 40B, context-pinned 128K') before doing agent work; if it is" >&2
    echo "not selected, switch to that labeled row there. Bare opencode is unaffected by this script." >&2
    exec opencode
    ;;
esac
