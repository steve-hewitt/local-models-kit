# Baseline launch: OpenCode straight to Ollama, no Headroom.
# Always prove this path first. Usage: .\scripts\launch-direct.ps1 [project folder]
#
# The model must be the context-pinned variant
# (ollama/flint-opencode:latest). The base flint:latest tag carries
# no num_ctx, so Ollama serves it at the 4096 default and truncates
# OpenCode's prompt; that was the first hands-on run's main failure
# (2026-10-24).
#
# How the model gets selected depends on the OpenCode line (verified
# hands-on against the real OpenCode 2.2.6 binary, 2026-11-07):
#   - OpenCode 1: the top-level -m flag exists, so this script passes
#     it explicitly as belt-and-suspenders over the config default.
#   - OpenCode 2: the top-level -m flag is gone ("Unrecognized flag:
#     -m in command opencode"), and there is no top-level --model in
#     the root command either. An interactive v2 session takes its
#     model from the installed config default, which kit setup sets
#     to the same pinned variant (verified: a bare v2 launch with the
#     kit config and a reachable server opens on the pinned Flint
#     model). So on v2 this script launches bare and tells you to
#     check the TUI footer, which names the live model; /models
#     switches it if it ever differs.
# (`opencode run` still accepts -m/--model on both lines, verified in
# the v2.2.6 `run --help`; the compare harness is unaffected.)
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
    Write-Host "In the TUI, /models should show the row labeled 'Flint 40B, context-pinned 128K' ($Model)."
    Write-Host "Do not pick a raw flint:latest row if an older installed config shows one: it is the unpinned base tag."
    opencode -m $Model
} elseif ($major -eq "2") {
    Write-Host "OpenCode 2: v2 has no top-level model flag; the session model is the config default"
    Write-Host "installed by setup, which is $Model. Check the TUI footer: it must name the pinned Flint"
    Write-Host "model. If it names anything else, switch with /models by selecting the row labeled"
    Write-Host "'Flint 40B, context-pinned 128K'. A raw flint:latest row may appear in the picker"
    Write-Host "despite the whitelist; do not pick it, it is the unpinned base tag."
    opencode
} else {
    Write-Host "WARNING: could not parse an OpenCode version from 'opencode --version' (got '$verRaw')." -ForegroundColor Yellow
    Write-Host "Launching without a model flag. In the TUI, verify with /models that the live model is"
    Write-Host "$Model (picker label 'Flint 40B, context-pinned 128K') before doing agent work; if it is"
    Write-Host "not selected, switch to that labeled row there."
    opencode
}
