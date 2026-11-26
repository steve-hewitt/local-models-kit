# Full stack launch: OpenCode through Headroom, upstream set to local Ollama.
# Usage: .\scripts\launch-headroom.ps1 [project folder]
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
param([string]$ProjectDir = ".")
$env:HEADROOM_TELEMETRY = "off"
$env:HEADROOM_BEACON = "off"
$env:DO_NOT_TRACK = "1"
$env:OPENAI_TARGET_API_URL = "http://localhost:11434/v1"
$env:OLLAMA_CONTEXT_LENGTH = if ($env:NUM_CTX) { $env:NUM_CTX } else { "131072" }
Set-Location $ProjectDir
Write-Host "Full stack: OpenCode -> Headroom -> Ollama (localhost:11434), telemetry off"
Write-Host "Kit launches pin the model for this session only; bare opencode is unaffected."
Write-Host "Headroom wrap does not pin a model. In /models, select the Headroom 'Flint 40B,"
Write-Host "context-pinned 128K' row (headroom/flint-opencode:latest) before agent work."
Write-Host "Do not pick a raw flint:latest row: it is the unpinned base tag."
headroom wrap opencode --openai-api-url http://localhost:11434/v1
