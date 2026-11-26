#!/usr/bin/env bash
# Full stack launch: OpenCode through Headroom, upstream set to local Ollama.
# Usage: ./scripts/launch-headroom.sh [project folder]
#
# The two settings that make this work at all:
#   1. --openai-api-url / OPENAI_TARGET_API_URL point Headroom at Ollama.
#      Without them, wrap defaults to https://api.openai.com/v1 and you get a 401.
#   2. Telemetry is forced off.
# Current Headroom does not take the old code-navigation memory flag for
# opencode. Wrap injects its own OPENCODE_CONFIG_CONTENT; do not stack a
# second injection. Verified on OpenCode 2.0.26, 2026-11-26: a wrapped
# session does not open on a Headroom-provider model unless the user picks
# one, so the guidance below sends them to /models.
set -euo pipefail
export HEADROOM_TELEMETRY=off HEADROOM_BEACON=off DO_NOT_TRACK=1
export OPENAI_TARGET_API_URL="http://localhost:11434/v1"
export OLLAMA_CONTEXT_LENGTH="${NUM_CTX:-131072}"
cd "${1:-.}"
echo "Full stack: OpenCode -> Headroom -> Ollama (localhost:11434), telemetry off"
echo "Kit launches pin the model for this session only; bare opencode is unaffected."
echo "Headroom wrap does not pin a model. In /models, select the Headroom 'Flint 40B,"
echo "context-pinned 128K' row (headroom/flint-opencode:latest) before agent work."
echo "Do not pick a raw flint:latest row: it is the unpinned base tag."
exec headroom wrap opencode --openai-api-url http://localhost:11434/v1
