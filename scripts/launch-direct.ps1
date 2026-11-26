# Baseline launch: OpenCode straight to Ollama, no Headroom.
# Always prove this path first. Usage: .\scripts\launch-direct.ps1 [project folder]
#
# The model must be the context-pinned variant
# (ollama/flint-opencode:latest). The base flint:latest tag carries
# no num_ctx, so Ollama serves it at the 4096 default and truncates
# OpenCode's prompt; that was the first hands-on run's main failure
# (2026-10-24).
#
# How the model gets selected depends on the OpenCode line. This
# script pins only the session it launches; a bare `opencode` is
# unaffected.
#   - OpenCode 1: the top-level -m flag exists, so this script passes
#     it explicitly.
#   - OpenCode 2: the top-level -m flag is gone ("Unrecognized flag:
#     -m in command opencode"), and there is no root --model either.
#     The script sets OPENCODE_CONFIG_CONTENT with a {"model": ...}
#     snippet and passes --standalone. Verified on 2.0.26, 2026-11-26:
#     with --standalone the TUI footer names the pinned Flint; without
#     it the shared background service ignores the env snippet.
# (`opencode run` still accepts -m/--model on both lines; the compare
# harness is unaffected.)
#
# OLLAMA_CONTEXT_LENGTH is set below for one case only: an Ollama
# server started from THIS shell reads it at startup. The usual Windows
# tray service never sees this shell's environment, so do not expect
# this variable to resize anything on its own. Use the pinned variant.
param([string]$ProjectDir = ".")
$env:OLLAMA_CONTEXT_LENGTH = if ($env:NUM_CTX) { $env:NUM_CTX } else { "131072" }
Set-Location $ProjectDir
$Model = "ollama/flint-opencode:latest"
Write-Host "Direct path: OpenCode -> Ollama (localhost:11434), model $Model (context pinned at 131072)."
$verRaw = (opencode --version) -join " "
$major = $null
if ($verRaw -match "(\d+)\.\d+\.\d+") { $major = $Matches[1] }
if ($major -eq "1") {
    Write-Host "OpenCode 1: passing -m $Model explicitly (the v1 top-level flag)."
    Write-Host "Kit launches pin the model for this session only; bare opencode is unaffected."
    Write-Host "In the TUI, /models should show the row labeled 'Flint 40B, context-pinned 128K' ($Model)."
    Write-Host "Do not pick a raw flint:latest row if an older installed config shows one: it is the unpinned base tag."
    opencode -m $Model
} elseif ($major -eq "2") {
    Write-Host "OpenCode 2: pinning this session with OPENCODE_CONFIG_CONTENT and --standalone."
    Write-Host "Kit launches pin the model for this session only; bare opencode is unaffected."
    Write-Host "The TUI footer must name 'Flint 40B, context-pinned 128K' ($Model)."
    Write-Host "A raw flint:latest row may appear in the picker; do not pick it, it is the unpinned base tag."
    $env:OPENCODE_CONFIG_CONTENT = "{`"model`":`"$Model`"}"
    opencode --standalone
} else {
    Write-Host "WARNING: could not parse an OpenCode version from 'opencode --version' (got '$verRaw')." -ForegroundColor Yellow
    Write-Host "Launching without a model pin. In the TUI, verify with /models that the live model is"
    Write-Host "$Model (picker label 'Flint 40B, context-pinned 128K') before doing agent work; if it is"
    Write-Host "not selected, switch to that labeled row there. Bare opencode is unaffected by this script."
    opencode
}
