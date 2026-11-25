# Start the Headroom proxy standalone, pointed at local Ollama.
# Run this in its OWN terminal and leave it running. Then launch OpenCode
# in a second terminal (scripts/launch-direct.ps1 works; the config is
# global) and pick a headroom/... model in /models to route through it.
# Picking an ollama/... model in the same session bypasses the proxy
# entirely. That is the toggle.
#
# Why the flags matter:
#   --openai-api-url http://localhost:11434/v1
#       Without this the proxy forwards OpenAI-compatible traffic to
#       https://api.openai.com/v1 and local requests die with a 401.
#       Documented in Headroom's own OpenCode guide; the flag means the
#       same for `headroom proxy` as for `headroom wrap`.
#   Telemetry is forced off, same as every other launch path in this kit.
#
# Stop it with Ctrl+C in this terminal.
#
# Port note: the OpenCode config points at 8787. If you override
# HEADROOM_PORT here, also update baseURL in config/opencode.json to
# match, or the headroom/... models will not connect.
$Port = if ($env:HEADROOM_PORT) { $env:HEADROOM_PORT } else { "8787" }
if ($Port -ne "8787") {
    Write-Host "WARNING: HEADROOM_PORT is $Port, but config/opencode.json points the" -ForegroundColor Yellow
    Write-Host "headroom provider at port 8787. The headroom/... models will NOT" -ForegroundColor Yellow
    Write-Host "connect unless you also edit baseURL in the config to" -ForegroundColor Yellow
    Write-Host "http://127.0.0.1:$Port/v1." -ForegroundColor Yellow
}
$env:HEADROOM_TELEMETRY = "off"
$env:HEADROOM_BEACON = "off"
$env:DO_NOT_TRACK = "1"
$env:OPENAI_TARGET_API_URL = "http://localhost:11434/v1"
Write-Host "Headroom proxy on port $Port, upstream Ollama (localhost:11434), telemetry off"
Write-Host "Leave this terminal running. Ctrl+C stops the proxy."
headroom proxy --port $Port --openai-api-url http://localhost:11434/v1
