#!/usr/bin/env bash
# Full stack launch: OpenCode through Headroom, upstream set to local Ollama.
# Usage: ./scripts/launch-headroom.sh [project folder]
#
# The two settings that make this work at all:
#   1. --openai-api-url / OPENAI_TARGET_API_URL point Headroom at Ollama.
#      Without them, wrap defaults to https://api.openai.com/v1 and you get a 401.
#   2. Telemetry is forced off.
# Current Headroom does not take the old code-navigation memory flag for
# opencode and registers no Serena for opencode by default. wrap does register
# Headroom's own MCP retrieve tool.
set -euo pipefail
export HEADROOM_TELEMETRY=off HEADROOM_BEACON=off DO_NOT_TRACK=1
export OPENAI_TARGET_API_URL="http://localhost:11434/v1"
export OLLAMA_CONTEXT_LENGTH="${NUM_CTX:-131072}"
cd "${1:-.}"
echo "Full stack: OpenCode -> Headroom -> Ollama (localhost:11434), telemetry off"
echo "Use a context-pinned *-opencode model (the config default is ollama/flint-opencode:latest; picker label 'Flint 40B, context-pinned 128K'). Do not pick a raw flint:latest row for agent work: it is the unpinned base tag."
exec headroom wrap opencode --openai-api-url http://localhost:11434/v1
