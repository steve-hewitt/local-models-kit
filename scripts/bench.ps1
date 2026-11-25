# Measure real decode and prefill speed for the local model via Ollama's
# native API, which reports eval_count and eval_duration directly.
# This replaces publisher speed claims with your machine's actual number.
# Usage: .\scripts\bench.ps1 [model_tag] [runs]
param(
    [string]$ModelTag = $(if ($env:MODEL_TAG) { $env:MODEL_TAG } else { "flint-opencode:latest" }),
    [int]$Runs = 3
)
$prompt = "Write a Python function that checks whether a string is a palindrome, with a docstring and two example calls. Output only code."

# Record the effective context next to every number: a bench taken at
# Ollama's 4096 default is not comparable to one taken at the kit's
# pinned 131072. compare.ps1 already records num_ctx; bench now does too.
$numCtx = "not reported"
try {
    $showBody = @{ name = $ModelTag } | ConvertTo-Json
    $show = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post -ContentType "application/json" -Body $showBody -TimeoutSec 10
    if ($show.parameters -match "num_ctx\s+(\d+)") { $numCtx = $Matches[1] }
} catch { $numCtx = "not reported" }
Write-Host "Benchmarking $ModelTag on this machine ($Runs runs, warm-up included as run 1)"
Write-Host "Effective num_ctx (from /api/show): $numCtx"
$expectedCtx = if ($env:NUM_CTX) { $env:NUM_CTX } else { "131072" }
if ($ModelTag -like "*qwen*") { $expectedCtx = if ($env:QWEN_NUM_CTX) { $env:QWEN_NUM_CTX } else { "131072" } }
if ($numCtx -ne $expectedCtx) {
    Write-Host "WARNING: effective num_ctx is $numCtx, not the kit's pinned $expectedCtx." -ForegroundColor Yellow
    Write-Host "Numbers from this run are not comparable to runs at $expectedCtx. The pinned"
    Write-Host "*-opencode variants report their pin; base tags report nothing and"
    Write-Host "run at Ollama's 4096 default."
}
"{0,-6} {1,-12} {2,-12} {3,-10}" -f "run", "decode_t/s", "prefill_t/s", "tokens"

for ($i = 1; $i -le $Runs; $i++) {
    $body = @{ model = $ModelTag; prompt = $prompt; stream = $false } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 600
    $dec = if ($r.eval_duration) { $r.eval_count / ($r.eval_duration / 1e9) } else { 0 }
    $pre = if ($r.prompt_eval_duration) { $r.prompt_eval_count / ($r.prompt_eval_duration / 1e9) } else { 0 }
    "{0,-6} {1,-12:N1} {2,-12:N1} {3,-10}" -f $i, $dec, $pre, $r.eval_count
}

Write-Host ""
Write-Host "Record the median decode number, with date, machine, context size, and"
Write-Host "Ollama version, in docs/reference/VALIDATION.md. Publisher numbers were measured"
Write-Host "with a different engine on different hardware; yours is the one that counts."
