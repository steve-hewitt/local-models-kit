# A/B compare harness: Flint vs Qwen, direct vs Headroom, same workload.
# Windows counterpart of scripts/compare.sh; see that file and
# docs/reference/COMPARE.md for the full design.
#
# Usage:
#   .\scripts\compare.ps1 [-Plan] [-SkipAgent] [-Runs 3] [-TimeoutSec 600]
#                         [-Models @("flint-opencode:latest", "qwen-opencode:latest")]
#
# The default models are the context-pinned variants, named by their
# OpenCode config keys (the same strings Ollama reports at /v1/models).
# -Plan prints the cell matrix and exits (CI uses it; touches nothing).
# Output: markdown report in results/compare-<timestamp>.md.
param(
    [string[]]$Models = @("flint-opencode:latest", "qwen-opencode:latest"),
    [int]$Runs = 3,
    [int]$TimeoutSec = 600,
    [switch]$Plan,
    [switch]$SkipAgent
)
$KitRoot = Split-Path -Parent $PSScriptRoot
$TaskPrompt = "The tests in test_calc.py are failing. Find the bug in calc.py, fix only what is wrong, and run the tests to confirm they pass. Do not change the tests."
$BenchPrompt = "Write a Python function that checks whether a string is a palindrome, with a docstring and two example calls. Output only code."
$ProxyPort = if ($env:HEADROOM_PORT) { $env:HEADROOM_PORT } else { "8787" }

if ($Plan) {
    Write-Host "Compare plan"
    Write-Host "  bench cells (raw tok/s via Ollama API, $Runs runs each after 1 warm-up, median):"
    $Models | ForEach-Object { Write-Host "    - $_" }
    if ($SkipAgent) {
        Write-Host "  agent cells: skipped (-SkipAgent)"
    } else {
        Write-Host "  agent cells (hello-agent via opencode run, timeout ${TimeoutSec}s, model-major order, per-cell warm-up):"
        $Models | ForEach-Object { Write-Host "    - ollama/$_"; Write-Host "    - headroom/$_ (only if a proxy answers on 127.0.0.1:$ProxyPort)" }
    }
    Write-Host "  report: results/compare-<timestamp>.md"
    return
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { throw "ollama not found" }
try { $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 }
catch { throw "Ollama API not answering on localhost:11434" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$resultsDir = Join-Path $KitRoot "results"
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
$report = Join-Path $resultsDir "compare-$stamp.md"
$work = Join-Path ([System.IO.Path]::GetTempPath()) "kit-compare-$stamp"
New-Item -ItemType Directory -Force -Path $work | Out-Null

try {
    # Effective num_ctx per model, from the server itself, so every
    # report records the conditions it was measured under.
    $numCtxParts = @()
    foreach ($m in $Models) {
        try {
            $showBody = @{ name = $m } | ConvertTo-Json
            $show = Invoke-RestMethod -Uri "http://localhost:11434/api/show" -Method Post -ContentType "application/json" -Body $showBody -TimeoutSec 10
            if ($show.parameters -match "num_ctx\s+(\d+)") { $numCtxParts += "$m=$($Matches[1])" }
            else { $numCtxParts += "$m=not reported" }
        } catch { $numCtxParts += "$m=not reported" }
    }

    $lines = @(
        "# Compare run $stamp",
        "",
        "- Host: $env:COMPUTERNAME",
        "- Ollama: $((ollama --version) -join ' ')",
        "- OpenCode: $(try { (opencode --version) -join ' ' } catch { 'not found' })",
        "- Bench runs per model: $Runs (plus 1 warm-up run, shown first and excluded from the median)",
        "- Effective num_ctx per /api/show: $($numCtxParts -join ' ')",
        "- small_model: not pinned by the kit config, so title and summary traffic follows each cell's own route; no side channel around the proxy and no second model loaded by the harness config",
        "",
        "## Raw decode speed (Ollama API counters)",
        "",
        "| Model | Decode tok/s per run (first is warm-up) | Median |",
        "| --- | --- | --- |"
    )

    foreach ($m in $Models) {
        $vals = @()
        for ($i = 0; $i -lt ($Runs + 1); $i++) {
            $body = @{ model = $m; prompt = $BenchPrompt; stream = $false } | ConvertTo-Json
            try {
                $r = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 600
                $vals += if ($r.eval_duration) { [math]::Round($r.eval_count / ($r.eval_duration / 1e9), 1) } else { "NA" }
            } catch { $vals += "NA" }
        }
        $kept = @($vals | Select-Object -Skip 1 | Where-Object { $_ -ne "NA" } | Sort-Object)
        $median = if ($kept.Count) { $kept[[math]::Floor($kept.Count / 2)] } else { "NA" }
        $lines += "| $m | $($vals -join ' ') | $median |"
        Write-Host "bench ${m}: runs [$($vals -join ' ')] median $median tok/s (first run excluded)"
    }

    if (-not $SkipAgent) {
        $opencodeCmd = Get-Command opencode -ErrorAction SilentlyContinue
        if (-not $opencodeCmd) { throw "opencode not found, agent cells cannot run" }
        # Resolve the real path (an npm install is a .cmd shim) so the
        # process we start, watch, and kill is unambiguous.
        $opencodePath = $opencodeCmd.Source
        $proxyUp = $false
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:$ProxyPort/health" -TimeoutSec 3 -UseBasicParsing
            if ($health.StatusCode -eq 200) { $proxyUp = $true }
        } catch {
            # No healthy response means the headroom cells skip, by design.
            $proxyUp = $false
        }

        $lines += @("", "## Agent task: hello-agent (one run per cell)", "",
            "| Route | Model | Result | Seconds | Warm-up s | Test file untouched |",
            "| --- | --- | --- | --- | --- | --- |")

        foreach ($m in $Models) {
            foreach ($route in @("ollama", "headroom")) {
                if ($route -eq "headroom" -and -not $proxyUp) {
                    $lines += "| headroom | $m | skipped, proxy not running | NA | NA | NA |"
                    Write-Host "agent headroom/${m}: skipped (proxy not running)"
                    continue
                }
                $cellName = "$route-$($m -replace '[/:]', '_')"
                $cell = Join-Path $work $cellName
                New-Item -ItemType Directory -Force -Path $cell | Out-Null
                Copy-Item (Join-Path $KitRoot "examples\hello-agent\calc.py") $cell
                Copy-Item (Join-Path $KitRoot "examples\hello-agent\test_calc.py") $cell
                $before = (Get-FileHash (Join-Path $cell "test_calc.py") -Algorithm SHA256).Hash
                # Warm the model (1-token generate) so its load time is
                # measured here, not inside the cell's wall time.
                $warmBody = @{ model = $m; prompt = "hi"; stream = $false; options = @{ num_predict = 1 } } | ConvertTo-Json
                $warmSw = [System.Diagnostics.Stopwatch]::StartNew()
                try { $null = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post -ContentType "application/json" -Body $warmBody -TimeoutSec 900 } catch { }
                $warmSw.Stop()
                $warmSecs = [math]::Round($warmSw.Elapsed.TotalSeconds)
                $log = Join-Path $resultsDir "compare-$stamp-$cellName.log"
                $sw = [System.Diagnostics.Stopwatch]::StartNew()
                # Single argument string with the prompt quoted: array-form
                # ArgumentList is joined unreliably on Windows PowerShell 5.1,
                # which can split the prompt into separate arguments.
                $proc = Start-Process -FilePath $opencodePath -ArgumentList "run -m $route/$m `"$TaskPrompt`"" -WorkingDirectory $cell -PassThru -NoNewWindow -RedirectStandardOutput $log -RedirectStandardError "$log.err"
                if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
                    # Kill the whole tree. With npm installs opencode is a
                    # .cmd shim around node; $proc.Kill() alone kills the
                    # shim and leaves the agent running and editing files
                    # after the result has been recorded.
                    try { taskkill /T /F /PID $proc.Id 2>$null | Out-Null }
                    catch { try { $proc.Kill() } catch { } }
                    $null = $proc.WaitForExit(10000)
                    $result = "timeout in ${TimeoutSec}s"
                } else {
                    Push-Location $cell
                    try { $null = python test_calc.py 2>$null; $result = if ($LASTEXITCODE -eq 0) { "pass" } else { "fail" } }
                    finally { Pop-Location }
                }
                $sw.Stop()
                $secs = [math]::Round($sw.Elapsed.TotalSeconds)
                $after = (Get-FileHash (Join-Path $cell "test_calc.py") -Algorithm SHA256).Hash
                $untouched = if ($before -eq $after) { "yes" } else { "NO" }
                # Append what the agent left behind, so a human can judge
                # whether a "pass" was the intended minimal fix.
                Add-Content -Path $log -Value @("", "== final calc.py ==", (Get-Content (Join-Path $cell "calc.py") -Raw))
                $lines += "| $route | $m | $result | $secs | $warmSecs | $untouched |"
                Write-Host "agent ${route}/${m}: $result in ${secs}s (warm-up ${warmSecs}s), test untouched: $untouched"
            }
        }
    }

    $lines += @("", "How to read this: docs/reference/COMPARE.md. One agent run per cell is an",
        "anecdote with a timestamp, not a benchmark. The bench medians are",
        "the comparable numbers; the agent cells answer 'did it do the job'.")
    $lines | Set-Content -Path $report -Encoding UTF8
    Write-Host ""
    Write-Host "Report written to $report"
} finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
