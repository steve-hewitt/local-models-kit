# Windows serves, WSL drives

The intended topology: Ollama runs natively on Windows with the GPU and the
full memory pool; OpenCode runs in WSL and reaches Ollama at
`http://localhost:11434`. Never run `ollama serve` inside WSL: a WSL guest on
AMD has no ROCm device, so it would serve from the CPU and can shadow the
Windows server on port 11434.

**Model choice.** The walkthrough uses Flint in its launch examples; neither
model is a startup default. Qwen3-30B-A3B is co-equal: set
`$env:MODEL_TAG = "qwen3:30b-a3b"` on the Windows side and use `qwen-opencode`
in the verification commands. Add-on A covers Qwen.

You need Windows 11 with `winget`, WSL2 with Ubuntu, about 25 GB free for Flint
or about 45 GB for both models, and admin rights only to install WSL itself.
No account, login, or API key.

Do the parts in order. **PowerShell** means a Windows PowerShell window;
**Ubuntu** means the WSL terminal.

## Part 1: Windows side (PowerShell)

### Step 1. Allow scripts in this window

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

The default `Restricted` policy blocks every `.ps1`, including this kit's. The
`Process` scope ends when the window closes; Part 5 covers the restore.

### Step 2. Install Ollama and Git

```powershell
ollama --version
git --version
```

For whichever errors, install it, then open a new PowerShell window and re-run
Step 1:

```powershell
winget install Ollama.Ollama
winget install Git.Git
```

Ollama 0.40.8 or newer is required; Flint support landed 2026-10-21, and Qwen3
also needs a modern build.

### Step 3. Set the server environment and restart Ollama

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS","1","User")
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","131072","User")
```

Quit Ollama from the system tray, then relaunch it from the Start menu so the
server picks up both variables. `OLLAMA_MAX_LOADED_MODELS=1` is the important
one on a 64 GB machine.

### Step 4. Clone the kit

```powershell
cd ~
git clone https://github.com/steve-hewitt/local-models-kit.git
cd local-models-kit
```

### Step 5. Run the server-only setup

```powershell
.\scripts\setup.ps1 -ServerOnly
```

This pulls Flint (`ollama pull flint`, about 23 GB) and builds
`flint-opencode`. For Qwen instead, set
`$env:MODEL_TAG = "qwen3:30b-a3b"` first; it pulls about 19 GB and builds
`qwen-opencode`.

`-ServerOnly` deliberately does not install OpenCode on Windows; OpenCode runs
in WSL. It does not install the OpenCode config on Windows either. Headroom is
not a Windows-side piece here.

### Step 6. Verify natively on Windows

```powershell
ollama list
ollama show flint-opencode --parameters    # num_ctx 131072; qwen-opencode for Qwen
ollama run flint-opencode "say ready"
```

In a second PowerShell window while it runs:

```powershell
ollama ps    # CONTEXT 131072, PROCESSOR GPU, not 100% CPU
```

If it shows 100% CPU on native Windows, stop and fix that first; see
[HARDWARE.md](HARDWARE.md).

## Part 2: Let WSL reach the Windows server

### Step 1. Check WSL and Ubuntu

```powershell
wsl --list --verbose
```

If nothing is listed, install it (the one step that needs admin):

```powershell
wsl --install -d Ubuntu
```

Launch Ubuntu once from the Start menu and create your user.

### Step 2. Turn on mirrored networking

WSL2 defaults to NAT, where `localhost` inside Ubuntu means Ubuntu itself. The
kit needs mirrored networking so WSL's `localhost` reaches the Windows server.

Open the file (it works whether it exists or not):

```powershell
notepad "$env:USERPROFILE\.wslconfig"
```

If the file is empty, paste:

```ini
[wsl2]
networkingMode=mirrored
```

If it already has content, add `networkingMode=mirrored` directly under the
existing `[wsl2]` line; if there is no `[wsl2]` section, add both lines at the
end. Do not create a second `[wsl2]` section. Save and check:

```powershell
Get-Content "$env:USERPROFILE\.wslconfig"
```

Do not let Notepad save it as `.wslconfig.txt`; WSL ignores that name.

### Step 3. Restart WSL

```powershell
wsl --shutdown
wsl -d Ubuntu
```

The shutdown closes open Ubuntu windows; the second command starts Ubuntu
again with the new setting.

### Step 4. Test the bridge

```bash
curl -s http://localhost:11434/api/tags
```

Expected: JSON listing `flint:latest` and `flint-opencode:latest`. If it is
empty or refused:

1. Is the Ollama tray app running on Windows?
2. Did you run both `wsl --shutdown` and `wsl -d Ubuntu` after editing
   `.wslconfig`?
3. Does the URL answer in a Windows browser? If Windows works and WSL does
   not, mirrored networking is not in effect.

### Fallback: NAT mode with the host IP

Only if mirrored mode misbehaves on your network:

1. On Windows, set `OLLAMA_HOST=0.0.0.0:11434` as a User environment variable,
   allow TCP 11434 in Windows Firewall scoped to your local subnet, and restart
   the Ollama tray app. Ollama has no authentication; never expose it beyond
   the local network.
2. From WSL:

   ```bash
   export WIN_HOST=$(ip route show default | awk '{print $3}')
   curl -s http://$WIN_HOST:11434/api/tags
   ```

3. Gaps: the kit config's `baseURL` must be edited to
   `http://<host IP>:11434/v1`, the smoke test hardcodes localhost, and the
   Headroom proxy upstream is hardcoded to localhost too. Treat NAT as a
   workaround, not the setup.

## Part 3: WSL agent side (Ubuntu)

### Step 1. Install the tools the scripts need

```bash
sudo apt-get update
sudo apt-get install -y curl git python3
```

Do not install Ollama in WSL. No `zstd` is needed here; that belongs to a
Linux-server setup.

### Step 2. Install OpenCode in WSL

```bash
curl -fsSL https://opencode.ai/v2/install | bash
exec bash -l
opencode --version
```

This is the only OpenCode install in this topology. If an instruction asks you
to install OpenCode on Windows, it describes the all-Windows topology; ignore
it here.

### Step 3. Clone the kit in WSL

```bash
cd ~
git clone https://github.com/steve-hewitt/local-models-kit.git
cd local-models-kit
```

This is a second clone, separate from the Windows one.

### Step 4. Run the client-only setup

```bash
./scripts/setup.sh --client-only
```

This checks OpenCode, checks that the Windows server answers at
`localhost:11434`, and installs the kit config into
`~/.config/opencode/opencode.json`, backing up any existing config first. It
never pulls a model and never starts a server.

Never run plain `./scripts/setup.sh` here; it expects a local Ollama and warns
you toward serving from the guest.

### Step 5. Run the smoke test

```bash
./scripts/smoke-test.sh
```

A pass looks like:

- The server version comes from the API.
- Effective `num_ctx` for `flint-opencode:latest` (or `qwen-opencode:latest`)
  is 131072.
- The raw model round trip answers.
- Residency shows `size_vram` above 0.

Expected warnings: the WSL2 note and "Headroom proxy not running." The result
that means stop is **CPU-only** (`size_vram` 0): something other than the
Windows GPU server is answering. Check `pgrep -af ollama` in WSL; it should
print nothing.

### Step 6. Launch and run the proof task

```bash
./scripts/launch-direct.sh examples/hello-agent
```

On OpenCode 2 the script sets `OPENCODE_CONFIG_CONTENT` and launches a private
server (`--standalone`) so this session is pinned to Flint; a bare `opencode`
is unaffected. The TUI footer must name the pinned model you chose (Flint or
Qwen). If it does not, pick the right row in `/models`.

Send the prompt from `examples/hello-agent/TASK.md` verbatim:

> The tests in test_calc.py are failing. Find the bug in calc.py, fix only what is wrong, and run the tests to confirm they pass. Do not change the tests.

Then verify outside the agent:

```bash
python3 test_calc.py   # all tests passed
```

While it runs, `ollama ps` on Windows should show CONTEXT 131072 on the GPU.

### Step 7. Headroom

Headroom is optional and is not needed for the baseline. To use the compressed
paths, follow Add-on B below.

## Part 4: Qwen (the other first-class model) and Headroom

On this manual path, Qwen is an opt-in step; the installer includes it by
default. Headroom is optional everywhere. Neither is required for the direct
path.

### Add-on A: Install the Qwen model

Qwen is a Windows-side install; using it happens in WSL.

1. In PowerShell, from the Windows clone:

   ```powershell
   cd ~\local-models-kit
   $env:WITH_QWEN = "1"
   .\scripts\setup.ps1 -ServerOnly
   ```

   This pulls `qwen3:30b-a3b` and builds `qwen-opencode`.

2. Verify:

   ```powershell
   ollama list
   ollama show qwen-opencode --parameters    # num_ctx 131072
   ```

3. In Ubuntu, launch OpenCode, open `/models`, and select **Qwen3 30B A3B,
   context-pinned 128K** (`ollama/qwen-opencode:latest`). Do not select the raw
   `qwen3:30b-a3b` row; that is the unpinned base tag.

Expect:

- Switching models pauses: only one model is resident at a time.
- Neither model is a startup default. To make Qwen the startup default, edit
  `~/.config/opencode/opencode.json` and set `"model"` to
  `"ollama/qwen-opencode:latest"`, or install with
  `--set-default --no-flint`.
- Qwen thinks before answering; its reasoning counts against the 8192 output
  budget (Flint's is 32768).
- Optional proof: `MODEL_TAG=qwen3:30b-a3b ./scripts/smoke-test.sh`.

### Add-on B: Get Headroom going

Headroom is the local compression proxy between OpenCode and Ollama. All of
this runs in Ubuntu.

1. Install `uv` if needed:

   ```bash
   uv --version
   ```

   If it errors:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   exec bash -l
   ```

2. Install Headroom and verify:

   ```bash
   uv tool install --python 3.13 "headroom-ai[all]"
   headroom --version
   ```

3. Start the proxy in its own Ubuntu terminal, from the kit root, and leave it
   open:

   ```bash
   cd ~/local-models-kit
   ./scripts/start-headroom-proxy.sh
   ```

   The script sets the upstream override to
   `http://localhost:11434/v1`. Without it, requests go to OpenAI and fail with
   a 401. The first start downloads roughly 500 MB of ML models.

4. In a second Ubuntu terminal, verify:

   ```bash
   curl -s http://127.0.0.1:8787/health
   ```

5. In OpenCode, `/models` and select a row whose label ends in **via
   Headroom** (for example `headroom/flint-opencode:latest`). Direct rows go
   straight to Ollama; Headroom rows go through the proxy. Both work in the
   same session.

6. Re-run the hello-agent proof through the Headroom row. It should pass
   exactly as the direct path did, and the proxy terminal logs the request.

7. Stop with Ctrl+C in the proxy terminal.

The wrapped path, `scripts/launch-headroom.sh`, also works. Run the toggle
first: with the pieces separate, a failure tells you which piece it is in.

## Part 5: Turning it off, and putting things back

Shut down clients first, server last.

### Step 1. Exit the agent side (Ubuntu)

Quit OpenCode and close its Ubuntu terminal. Stop the Headroom proxy with
Ctrl+C if it is running.

### Step 2. Shut down WSL (PowerShell)

```powershell
wsl --shutdown
```

### Step 3. Unload the model and release the GPU (PowerShell)

```powershell
ollama stop flint-opencode:latest   # or qwen-opencode:latest
ollama ps
```

`ollama ps` should list no models. For a full stop, quit Ollama from the
system tray. Ollama also unloads an idle model after about 5 minutes.

### Step 4. Put the execution policy back (PowerShell)

If you used `-Scope Process`, close every PowerShell window that ran the
bypass. Then check a fresh window:

```powershell
Get-ExecutionPolicy
```

If you used the permanent `CurrentUser` option, restore it:

```powershell
Set-ExecutionPolicy -Scope CurrentUser Restricted
Get-ExecutionPolicy -List
```

Leave the two Ollama user environment variables in place; they are
configuration, not a loosened security setting.

## If something breaks

- `.ps1 cannot be loaded because running scripts is disabled`: re-run Step 1
  in that window; see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) item 9.
- Setup on Windows says OpenCode is missing: you ran `setup.ps1` without
  `-ServerOnly`.
- Setup in WSL offers to install Ollama: you ran `setup.sh` without
  `--client-only`.
- Part 2 test returns nothing: work the three checks in Part 2, Step 4.
- Anything else: [TROUBLESHOOTING.md](TROUBLESHOOTING.md), then bisect with
  [reference/ARCHITECTURE.md](reference/ARCHITECTURE.md#failure-bisection-order).
