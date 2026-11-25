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
# How the model gets selected depends on the OpenCode line, and the
# difference is not cosmetic (verified hands-on against the real
# OpenCode 2.2.6 binary, 2026-11-07):
#   - OpenCode 1: the top-level -m flag exists, so this script passes
#     it explicitly as belt-and-suspenders over the config default.
#   - OpenCode 2: the top-level -m flag is gone ("Unrecognized flag:
#     -m in command opencode"), and there is no top-level --model in
#     the root command either. An interactive v2 session takes its
#     model from the installed config default, which kit setup sets
#     to the same pinned variant (verified: a bare v2 launch with
#     the kit config and a reachable server opens on
#     "Flint 40B, context-pinned 128K"). So on v2 this script launches
#     bare and tells you to check the TUI footer, which names the
#     live model; /models switches it if it ever differs.
# (`opencode run` still accepts -m/--model on both lines, verified in
# the v2.2.6 `run --help`; the compare harness is unaffected.)
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
    echo "In the TUI, /models should show the row labeled 'Flint 40B, context-pinned 128K' ($MODEL)."
    echo "Do not pick a raw flint:latest row if an older installed config shows one: it is the unpinned base tag."
    exec opencode -m "$MODEL"
    ;;
  2.*)
    echo "OpenCode $VER: v2 has no top-level model flag; the session model is the config default"
    echo "installed by setup, which is $MODEL. Check the TUI footer: it must name the pinned Flint"
    echo "model. If it names anything else, switch with /models by selecting the row labeled"
    echo "'Flint 40B, context-pinned 128K'. The current config whitelist should hide raw base tags;"
    echo "if a raw flint:latest row appears, the installed config predates that fix."
    exec opencode
    ;;
  *)
    echo "WARNING: could not parse an OpenCode version from 'opencode --version' (got '${VER_RAW:-no output}')." >&2
    echo "Launching without a model flag. In the TUI, verify with /models that the live model is" >&2
    echo "$MODEL (picker label 'Flint 40B, context-pinned 128K') before doing agent work; if it is" >&2
    echo "not selected, switch to that labeled row there." >&2
    exec opencode
    ;;
esac
