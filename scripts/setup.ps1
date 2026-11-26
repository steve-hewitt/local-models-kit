# Setup for local-models-kit on Windows.
# Run from the repo root:  .\scripts\setup.ps1
# Design rule: check first, install only what is missing, never overwrite
# an existing OpenCode config without a timestamped backup.
#
# -ServerOnly is for the "Windows serves, WSL drives" topology
# (docs/WSL.md): this side only installs and prepares Ollama and the
# models. OpenCode lives in WSL there, so ServerOnly skips the OpenCode
# check and the Windows OpenCode config install entirely. Without the
# switch this script sets up the all-Windows topology, where OpenCode
# does run on Windows.

param([switch]$ServerOnly)

$ErrorActionPreference = "Stop"
$KitRoot = Split-Path -Parent $PSScriptRoot
$ModelTag = if ($env:MODEL_TAG) { $env:MODEL_TAG } else { "flint" }
# The prefix picks the family's Modelfile (for its parameters) and the
# variant's default name. The variant itself is always built FROM the
# tag that was pulled: the shipped Modelfiles hardcode a FROM line for
# the family default, so building from one directly would pull and pin
# that default even when MODEL_TAG names another tag in the family.
if ($ModelTag -like "qwen*") {
    $Modelfile = "models/Modelfile.qwen-opencode"; $DefaultCustom = "qwen-opencode"
} elseif ($ModelTag -like "flint*") {
    $Modelfile = "models/Modelfile.flint-opencode"; $DefaultCustom = "flint-opencode"
} else {
    $Modelfile = $null; $DefaultCustom = $null
}
$CustomTag = if ($env:CUSTOM_MODEL_TAG) { $env:CUSTOM_MODEL_TAG } else { $DefaultCustom }
# Context pins. 131072 (128K) is the kit default since 2026-11-09
# (the old 32768 default was unusable for agent work; 128K is
# the floor). NUM_CTX sets the primary model's pin and can go up to
# 262144 for Flint. Qwen keeps its own pin: 131072 is Qwen3-30B-A3B's
# documented YaRN ceiling, so raising NUM_CTX never drags Qwen past
# what the model supports. Both values are baked into the built
# variants and into the installed config below.
$NumCtx = if ($env:NUM_CTX) { $env:NUM_CTX } else { "131072" }
$QwenNumCtx = if ($env:QWEN_NUM_CTX) { $env:QWEN_NUM_CTX } else { "131072" }
$MinOllama = [version]"0.40.8"

# $ErrorActionPreference = "Stop" does not stop on a native command's
# nonzero exit code. Check $LASTEXITCODE after every ollama call instead.
function CheckNative($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed with exit code $LASTEXITCODE" }
}

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# Build a context-pinned variant FROM the tag that was pulled, taking the
# parameters from the family Modelfile. The Modelfile's own FROM line
# names the family default tag, so it is rewritten into a temp copy.
function BuildVariant($Name, $FromTag, $Template, $Ctx) {
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        (Get-Content (Join-Path $KitRoot $Template)) -replace '^FROM .*', "FROM $FromTag" -replace '^PARAMETER num_ctx .*', "PARAMETER num_ctx $Ctx" | Set-Content $tmp
        Write-Host "Building context-pinned variant $Name from $FromTag (context $Ctx, parameters from $Template)..."
        ollama create $Name -f $tmp
        CheckNative "ollama create $Name"
    } finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}

Write-Host "== local-models-kit setup ==" -ForegroundColor Cyan

# --- Ollama ---------------------------------------------------------------
if (-not (Have "ollama")) {
    Write-Host "Ollama not found. Install it with:" -ForegroundColor Yellow
    Write-Host "  winget install Ollama.Ollama"
    Write-Host "or download it from https://ollama.com/download"
    throw "Install Ollama, open a new terminal, and re-run this script."
}
$ollamaVersionRaw = (ollama --version) -join " "
Write-Host "Ollama: $ollamaVersionRaw"
if ($ollamaVersionRaw -match "(\d+\.\d+\.\d+)") {
    $found = [version]$Matches[1]
    if ($found -lt $MinOllama) {
        Write-Host "WARNING: Ollama $found is older than $MinOllama (2026-10-21)." -ForegroundColor Yellow
        Write-Host "Flint support landed 2026-10-21. Update Ollama before debugging any model load failure."
    }
}

# --- OpenCode -------------------------------------------------------------
if ($ServerOnly) {
    Write-Host "ServerOnly: skipping the OpenCode check and install."
    Write-Host "In this topology OpenCode runs in WSL, not on Windows."
    Write-Host "Do not install OpenCode for Windows for this setup."
} elseif (-not (Have "opencode")) {
    Write-Host "OpenCode not found. Install options:" -ForegroundColor Yellow
    Write-Host "  npm install -g @opencode/cli"
    Write-Host "  or see https://opencode.ai for the current Windows installer"
    throw "Install OpenCode, open a new terminal, and re-run this script."
} else {
    Write-Host "OpenCode: $((opencode --version) -join ' ')"
}

# --- Headroom -------------------------------------------------------------
$env:HEADROOM_TELEMETRY = "off"
$env:HEADROOM_BEACON = "off"
$env:DO_NOT_TRACK = "1"
# Headroom is optional: only the headroom paths need it. The direct
# path (the baseline this kit tells you to prove first) must not be
# blocked by a missing optional layer.
if ($ServerOnly) {
    Write-Host "ServerOnly: Headroom is not a Windows-side piece in this topology;"
    Write-Host "when you use it, it runs in WSL next to OpenCode. Skipping its check."
} elseif (-not (Have "headroom")) {
    Write-Host "WARNING: Headroom not found; continuing without it." -ForegroundColor Yellow
    Write-Host "The direct path will work. Install Headroom later for the"
    Write-Host "compressed paths. Preferred install (isolated env, needs uv):"
    Write-Host '  uv tool install --python 3.13 "headroom-ai[all]"'
    Write-Host "Fallback:"
    Write-Host '  pip install "headroom-ai[all]"'
} else {
    Write-Host "Headroom: installed (telemetry forced off by this kit)"
}

# --- Model ----------------------------------------------------------------
Write-Host "Pulling model $ModelTag (about 23 GB for flint, one-time)..."
ollama pull $ModelTag
CheckNative "ollama pull $ModelTag"

$BuiltName = $null
$BuiltFrom = $null
if ($Modelfile) {
    $PrimaryCtx = if ($ModelTag -like "qwen*") { $QwenNumCtx } else { $NumCtx }
    BuildVariant $CustomTag $ModelTag $Modelfile $PrimaryCtx
    $BuiltName = $CustomTag
    $BuiltFrom = $ModelTag
} else {
    Write-Host "No context-pinned variant ships for $ModelTag; skipping that build."
    Write-Host "The model itself is pulled and declared models still work; context"
    Write-Host "then follows Ollama's runtime default instead of the kit's pin."
}

# --- Optional Qwen model ----------------------------------------------------
if ($env:WITH_QWEN -eq "1") {
    $QwenTag = if ($env:QWEN_TAG) { $env:QWEN_TAG } else { "qwen3:30b-a3b" }
    $QwenCustom = if ($env:QWEN_CUSTOM_TAG) { $env:QWEN_CUSTOM_TAG } else { "qwen-opencode" }
    Write-Host "Pulling optional model $QwenTag (about 19 GB, one-time)..."
    ollama pull $QwenTag
    CheckNative "ollama pull $QwenTag"
    if ($BuiltName -eq $QwenCustom -and $BuiltFrom -eq $QwenTag) {
        Write-Host "Variant $QwenCustom was already built from $QwenTag above; skipping the duplicate build."
    } else {
        BuildVariant $QwenCustom $QwenTag "models/Modelfile.qwen-opencode" $QwenNumCtx
    }
}

# --- OpenCode config ------------------------------------------------------
# Merge only the kit's two provider blocks into an existing config. The
# installed context limits and picker labels are written from NUM_CTX /
# QWEN_NUM_CTX, so OpenCode budgets against the variants built above.
# The repo config stays the 131072 template; substitution happens only
# in the installed copy. No top-level model is written unless
# KIT_SET_DEFAULT=1.
function CtxLabel($n) {
    if (([int]$n % 1024) -eq 0) { return "$([int]$n / 1024)K" } else { return "$n" }
}
function InstallConfig($Dest) {
    $cfg = Get-Content "$KitRoot\config\opencode.json" -Raw | ConvertFrom-Json
    foreach ($pname in $cfg.provider.PSObject.Properties.Name) {
        foreach ($key in $cfg.provider.$pname.models.PSObject.Properties.Name) {
            $ctx = if ($key -like "qwen*") { [int]$QwenNumCtx } else { [int]$NumCtx }
            $cfg.provider.$pname.models.$key.limit.context = $ctx
            $cfg.provider.$pname.models.$key.name = $cfg.provider.$pname.models.$key.name -replace "128K", (CtxLabel $ctx)
        }
    }
    if (Test-Path $Dest) {
        try {
            $existing = Get-Content $Dest -Raw | ConvertFrom-Json
        } catch {
            throw "cannot safely merge ${Dest}: $($_.Exception.Message); left untouched"
        }
        if ($existing -isnot [System.Management.Automation.PSCustomObject]) {
            throw "cannot safely merge ${Dest}: top level is not a JSON object"
        }
    } else {
        $existing = [pscustomobject]@{ '$schema' = $cfg.'$schema' }
    }
    if (-not $existing.PSObject.Properties["provider"]) {
        $existing | Add-Member -MemberType NoteProperty -Name provider -Value ([pscustomobject]@{})
    }
    if ($existing.provider -isnot [System.Management.Automation.PSCustomObject]) {
        throw "cannot safely merge ${Dest}: provider is not a JSON object"
    }
    foreach ($pname in @("ollama", "headroom")) {
        $existing.provider | Add-Member -MemberType NoteProperty -Name $pname -Value $cfg.provider.$pname -Force
    }
    if ($env:KIT_SET_DEFAULT -eq "1") {
        if ($BuiltName -in @("flint-opencode", "qwen-opencode")) {
            $existing | Add-Member -MemberType NoteProperty -Name model -Value "ollama/${BuiltName}:latest" -Force
        } else {
            Write-Warning "KIT_SET_DEFAULT=1 but no standard pinned variant was built; no model field was written."
        }
    }
    ($existing | ConvertTo-Json -Depth 20) | Set-Content $Dest
    Write-Host "Kit provider blocks merged into $Dest (Flint context $NumCtx, Qwen context $QwenNumCtx)"
}
# ServerOnly skips this too: the config belongs to the OpenCode side,
# which in that topology is the WSL home directory, not Windows.
if ($ServerOnly) {
    Write-Host "ServerOnly: skipping the Windows OpenCode config install."
    Write-Host "The WSL side installs the kit config in Part 3 of docs/WSL.md."
} else {
$ConfigDir = Join-Path $env:USERPROFILE ".config\opencode"
$ConfigPath = Join-Path $ConfigDir "opencode.json"
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
if (Test-Path $ConfigPath) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$ConfigPath.bak-$stamp"
    Copy-Item $ConfigPath $backup
    Write-Host "Existing OpenCode config backed up to $backup"
}
InstallConfig $ConfigPath
}

Write-Host ""
Write-Host "Ollama service environment (one-time, recommended on the 64 GB target):"
Write-Host "the pinned variants fix the context per model, but OLLAMA_MAX_LOADED_MODELS=1"
Write-Host "still belongs in the Ollama server environment. A variable exported in this"
Write-Host "shell does not reach the already-running tray service. On Windows, set it as"
Write-Host "a user environment variable (Settings > Environment variables, or"
Write-Host '[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","User"))'
Write-Host "and restart the Ollama tray app. OLLAMA_CONTEXT_LENGTH=$NumCtx is a fallback for"
Write-Host "unpinned tags only; the kit's *-opencode variants pin context themselves."
Write-Host ""
if ($ServerOnly) {
    Write-Host "Server setup done. Next, still on Windows:" -ForegroundColor Green
    Write-Host "  ollama show flint-opencode --parameters   (must show num_ctx $NumCtx)"
    Write-Host "  ollama run flint-opencode `"say ready`""
    Write-Host "  ollama ps   (in a second window, while the model is loaded:"
    Write-Host "               CONTEXT $NumCtx, PROCESSOR not 100% CPU)"
    Write-Host "Then continue with Part 2 of docs\WSL.md (networking and WSL)."
} else {
    Write-Host "Setup done. Next:" -ForegroundColor Green
    Write-Host "  .\scripts\smoke-test.ps1"
    Write-Host "  .\scripts\launch-direct.ps1     (baseline)"
    Write-Host "  .\scripts\launch-headroom.ps1   (full stack, needs Headroom)"
}
