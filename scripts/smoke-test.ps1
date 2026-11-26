# Smoke test: proves each layer works, in bisection order.
# Run after setup.ps1. Safe to re-run any time.
#
# This test exists because the first hands-on run (2026-10-24, WSL2)
# passed every old check while the agent was broken: the default model
# was the unpinned flint:latest (effective context 4096, prompt
# truncated from 6653 tokens to 2050) and Ollama was CPU-only under
# WSL2 with no ROCm device. So this version checks the things that
# actually decide whether agent work works:
#   - the selected model is the context-pinned *-opencode variant
#   - its effective num_ctx from /api/show is at least the kit context
#   - the loaded model's context from /api/ps agrees
#   - GPU residency: CPU-only (size_vram 0) is a loud warning, not a pass
#   - the kit config declares no unpinned model, and every declared
#     limit matches its Modelfile pin
# Headroom is optional: it is only needed for the headroom paths, so a
# missing binary or a stopped proxy warns instead of failing.
$KitRoot = Split-Path -Parent $PSScriptRoot
$ModelTag = if ($env:MODEL_TAG) { $env:MODEL_TAG } else { "flint" }
$ExpectedCtx = if ($env:NUM_CTX) { [int]$env:NUM_CTX } else { 131072 }
if ($ModelTag -like "qwen*") { $ExpectedCtx = if ($env:QWEN_NUM_CTX) { [int]$env:QWEN_NUM_CTX } else { 131072 } }
$fail = 0
$warn = 0

# Agent work must use the pinned variant built from MODEL_TAG, never
# the base tag: base tags carry no num_ctx and Ollama falls back to
# 4096, which truncates OpenCode's prompt.
if ($ModelTag -match "-opencode") { $Selected = $ModelTag }
elseif ($ModelTag -like "flint*") { $Selected = if ($env:CUSTOM_MODEL_TAG) { $env:CUSTOM_MODEL_TAG } else { "flint-opencode" } }
elseif ($ModelTag -like "qwen*") { $Selected = if ($env:QWEN_CUSTOM_TAG) { $env:QWEN_CUSTOM_TAG } else { "qwen-opencode" } }
else { $Selected = $ModelTag }
if ($Selected -notmatch ":") { $Selected = "$Selected`:latest" }

function Check($name, $ok) {
    if ($ok) { Write-Host "PASS  $name" -ForegroundColor Green }
    else { Write-Host "FAIL  $name" -ForegroundColor Red; $script:fail++ }
}
function Warn($msg) { Write-Host "WARN  $msg" -ForegroundColor Yellow; $script:warn++ }

Write-Host "Selected model for agent work: $Selected (expected context >= $ExpectedCtx)"

Write-Host "== versions =="
try { Check "ollama --version: $((ollama --version) -join ' ')" $true } catch { Check "ollama present" $false }
try { Check "opencode --version: $((opencode --version) -join ' ')" $true } catch { Check "opencode present" $false }
if (Get-Command headroom -ErrorAction SilentlyContinue) { Write-Host "PASS  headroom present" -ForegroundColor Green }
else { Warn "headroom not found (optional: only the headroom paths need it; the direct path works without it)" }

Write-Host "== kit config =="
try {
    $cfg = Get-Content (Join-Path $KitRoot "config\opencode.json") -Raw | ConvertFrom-Json
    $flintCtx = [int](Select-String -Path (Join-Path $KitRoot "models\Modelfile.flint-opencode") -Pattern "PARAMETER num_ctx (\d+)").Matches[0].Groups[1].Value
    $qwenCtx = [int](Select-String -Path (Join-Path $KitRoot "models\Modelfile.qwen-opencode") -Pattern "PARAMETER num_ctx (\d+)").Matches[0].Groups[1].Value
    $ok = $true
    $defaultProp = $cfg.PSObject.Properties["model"]
    if ($defaultProp -and $defaultProp.Value) {
        $default = [string]$defaultProp.Value
        if (($default -like "ollama/*" -or $default -like "headroom/*") -and $default -notmatch "-opencode") {
            $ok = $false
        }
    }
    foreach ($pname in $cfg.provider.PSObject.Properties.Name) {
        $declared = @($cfg.provider.$pname.models.PSObject.Properties.Name)
        $whitelistProp = $cfg.provider.$pname.PSObject.Properties["whitelist"]
        $whitelist = if ($whitelistProp) { @($whitelistProp.Value) } else { @() }
        if ($declared.Count -ne $whitelist.Count) { $ok = $false }
        foreach ($key in $declared) {
            if ($key -notmatch "-opencode") { $ok = $false }
            $wantCtx = if ($key -like "qwen*") { $qwenCtx } else { $flintCtx }
            if ($cfg.provider.$pname.models.$key.limit.context -ne $wantCtx) { $ok = $false }
            if ($whitelist -notcontains $key) { $ok = $false }
        }
    }
    Check "every declared model is a pinned *-opencode variant, every declared limit matches its Modelfile pin, and each picker whitelist matches its declared models" $ok
} catch { Warn "kit config could not be parsed; config checks skipped ($($_.Exception.Message))" }

Write-Host "== ollama server =="
try {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 10
    Check "Ollama API answers at localhost:11434" $true
    $names = $tags.models | ForEach-Object { $_.name }
    Check "pinned model present in ollama list: $Selected" ($names -contains $Selected)
} catch {
    Check "Ollama API answers at localhost:11434 (is Ollama running?)" $false
}

Write-Host "== effective context (from /api/show) =="
try {
    $showBody = @{ name = $Selected } | ConvertTo-Json
    $show = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post -ContentType "application/json" -Body $showBody -TimeoutSec 10
    if ($show.parameters -match "num_ctx\s+(\d+)" -and [int]$Matches[1] -ge $ExpectedCtx) {
        Check "effective num_ctx for $Selected is $($Matches[1]) (>= $ExpectedCtx)" $true
    } else {
        Check "effective num_ctx for $Selected is reported and >= $ExpectedCtx (an unpinned model runs at 4096 and truncates agent prompts; run setup to build the *-opencode variant)" $false
    }
} catch { Check "could not read /api/show for $Selected" $false }

Write-Host "== raw model round trip =="
try {
    $body = @{
        model = $Selected
        messages = @(@{ role = "user"; content = "Reply with exactly this word: ready" })
        stream = $false
    } | ConvertTo-Json -Depth 5
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/v1/chat/completions" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 300
    $text = $resp.choices[0].message.content
    Check "model answered via OpenAI-compatible API: $text" ($text -match "ready")
} catch {
    Check "model round trip via /v1/chat/completions ($Selected)" $false
    Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor DarkYellow
}

Write-Host "== residency (from /api/ps) =="
try {
    $ps = Invoke-RestMethod -Uri "http://localhost:11434/api/ps" -TimeoutSec 10
    $m = $ps.models | Where-Object { $_.name -eq $Selected -or $_.model -eq $Selected } | Select-Object -First 1
    if (-not $m) { Warn "selected model not loaded in /api/ps yet; residency not verified" }
    elseif ($null -ne $m.context_length -and $m.context_length -lt $ExpectedCtx) {
        Check "loaded context_length is $($m.context_length) (>= $ExpectedCtx)" $false
    } elseif (-not $m.size_vram -or $m.size_vram -eq 0) {
        Warn "model is CPU-only (size_vram is 0): agent turns will be slow. On the target Windows machine this should be GPU-resident. Under WSL2 on AMD this is expected: ROCm is not exposed there (see docs/HARDWARE.md)."
    } else {
        Check "model loaded with context_length $($m.context_length), size_vram $($m.size_vram) bytes (GPU-resident)" $true
    }
} catch { Warn "could not read /api/ps; residency not verified" }

Write-Host "== headroom proxy (optional) =="
try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8787/health" -TimeoutSec 3 -UseBasicParsing
    Check "headroom proxy answers at 127.0.0.1:8787/health" ($health.StatusCode -eq 200)
} catch { Warn "headroom proxy not running on 8787 (only needed for the headroom paths; start it with scripts/start-headroom-proxy.ps1)" }

Write-Host ""
if ($fail -eq 0) {
    Write-Host "All checks passed with $warn warning(s). Now run the hello-agent example (see examples/hello-agent)." -ForegroundColor Green
    if ($warn -gt 0) { Write-Host "Warnings above are real limitations of this environment, not noise: read them before judging agent speed or quality." -ForegroundColor Yellow }
} else {
    Write-Host "$fail check(s) failed, $warn warning(s). Bisect with docs/TROUBLESHOOTING.md, in order." -ForegroundColor Yellow
    exit 1
}
