# Full stack launch: OpenCode through Headroom, upstream set to local Ollama.
# Usage: .\scripts\launch-headroom.ps1 [project folder]
#
# The two settings that make this work at all:
#   1. --openai-api-url / OPENAI_TARGET_API_URL point Headroom at Ollama.
#      Without them, wrap defaults to https://api.openai.com/v1 and you get a 401.
#   2. Telemetry is forced off.
# --code-memory none skips Headroom's default Serena install to keep the
# stack minimal. Delete that flag if you want semantic code navigation.
param([string]$ProjectDir = ".")
$env:HEADROOM_TELEMETRY = "off"
$env:HEADROOM_BEACON = "off"
$env:DO_NOT_TRACK = "1"
$env:OPENAI_TARGET_API_URL = "http://localhost:11434/v1"
$env:OLLAMA_CONTEXT_LENGTH = if ($env:NUM_CTX) { $env:NUM_CTX } else { "131072" }
Set-Location $ProjectDir
Write-Host "Full stack: OpenCode -> Headroom -> Ollama (localhost:11434), telemetry off"
Write-Host "Use a context-pinned *-opencode model (the config default is ollama/flint-opencode:latest; picker label 'Flint 40B, context-pinned 128K'). Do not pick a raw flint:latest row for agent work: it is the unpinned base tag."
headroom wrap opencode --openai-api-url http://localhost:11434/v1 --code-memory none
