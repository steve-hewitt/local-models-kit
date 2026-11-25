# ComfyUI in the kit

The kit installs and manages ComfyUI, the image generation program, next to
the Ollama stack. ComfyUI is part of the default install: a plain `install`
includes everything here. Leave it out with `--no-comfyui`.

What the kit manages: the official ComfyUI Windows portable AMD build v0.46.0
with the Z-Image-Turbo model set, run natively on Windows. The manager
downloads and verifies everything itself.

## Target hardware

See [docs/HARDWARE.md](HARDWARE.md) for the canonical spec. ComfyUI needs:

- Ryzen AI Max 395 (Strix Halo), Radeon 8060S, 64 GB unified memory, Windows 11.
- GPU/shared-memory allocation: 48 GB in the reference setup, leaving 16 GB as
  system RAM. ComfyUI with Z-Image-Turbo peaks at 23 GB of VRAM and about 43
  seconds per 1024 by 1024 image. A loaded Flint or Qwen plus its 128K KV cache
  is the same size class, so the two stacks do not fit at once. The `switch`
  verb unloads one side before starting the other.
- Free disk: at least 35 GB on the ComfyUI drive.

## What gets installed

Default root: `C:\ComfyUI`; override with `--comfy-root DIR`.

- The archive lands in `C:\ComfyUI\downloads\` and extracts to
  `C:\ComfyUI\ComfyUI_windows_portable\`. The launcher is `run_amd_gpu.bat` in
  that folder.
- Models go into the program's own model folders:

| File | Folder under `ComfyUI\models\` | Size |
| --- | --- | --- |
| `z_image_turbo_bf16.safetensors` | `diffusion_models\` | 12,309,866,400 bytes |
| `qwen_3_4b.safetensors` | `text_encoders\` | 8,044,982,048 bytes |
| `ae.safetensors` | `vae\` | 335,304,388 bytes |

Sources: the portable from the official Comfy-Org/ComfyUI GitHub release
v0.46.0; the three model files from the Comfy-Org/z_image_turbo repo on Hugging
Face. Every download is streamed to a temporary file, and its size and SHA-256
are verified before it is moved into place. A file that fails verification is
deleted, never installed.

Extraction note: the portable is a `.7z` archive and Python's standard library
cannot read those, so the manager uses the `tar.exe` that ships with Windows 11
(bsdtar reads `.7z`). If `tar.exe` is missing, the step stops and says so.

## Install

Run on Windows in PowerShell, from the folder where you cloned the kit:

```
.\local-models-kit.exe install
```

Or from source, with Python 3 on the Windows PATH:

```
python installer\manager\local_models_kit_manager.py install
```

ComfyUI is included by default along with Flint and Qwen. `--no-comfyui`
leaves it out; `--with-comfyui` is the way back in when recorded state has it
out. Add `--comfy-root D:\ComfyUI` to put the portable somewhere else.

The ComfyUI steps run after the Ollama steps:

- **C1, portable:** downloads and verifies the archive, extracts it, and
  records the version, hash, and installed directories. The check is the
  launcher's presence plus the recorded pin.
- **C2, models:** downloads each of the three files directly into its model
  folder and verifies size and SHA-256. Each file is its own download.
- **C3, GPU check:** starts ComfyUI and polls `/system_stats`. Passes only when
  a Radeon device reports at least 16 GB of VRAM. A CPU-only device, an empty
  list, or a small carve-out fails, with the reason printed.
- **C4, generation smoke:** posts the kit's Z-Image-Turbo workflow to
  `/prompt`, polls `/history`, and requires a real output image. The workflow
  is the official Comfy-Org template converted to API format and embedded in
  the manager. Seconds and peak VRAM are recorded in state.

Preflight adds two ComfyUI blockers when ComfyUI is included: disk space at the
ComfyUI root, and port 8188 not held by something else. ComfyUI answers at
`http://127.0.0.1:8188`.

## Manual fallback

If you cannot use the installer, download the portable v0.46.0 from
Comfy-Org/ComfyUI and the three files from Comfy-Org/z_image_turbo on Hugging
Face, place them in the folders above, and verify the sizes. The installer path
is the supported one; the manual flow is a fallback.

## Switching between Ollama and ComfyUI

One GPU allocation, two stacks that each want most of it. The `switch` verb
hands it over and verifies both sides:

```
local-models-kit switch comfy
local-models-kit switch ollama
```

- `switch comfy`: unloads every Ollama model, verifies `/api/ps` is empty,
  starts ComfyUI, and verifies the GPU is visible. If a model refuses to
  unload, the switch stops there.
- `switch ollama`: frees ComfyUI's models, stops its processes (scoped to the
  portable's own path), verifies port 8188 is quiet, restarts the Ollama tray,
  and verifies `/api/version` answers.

Closing the browser tab does not unload anything; use `switch`.

## Doctor

`local-models-kit doctor` adds four rows when ComfyUI is installed:

- **C1 comfy install** and **C2 comfy models:** recorded pins and files agree.
- **C3 comfy server:** not launched is PASS (ComfyUI is on-demand); running on
  the GPU is PASS; CPU-only or a foreign process on 8188 is FAIL.
- **VRAM conflict:** WARN when an Ollama model is loaded and ComfyUI reports at
  least 1 GB of VRAM in use. The fix is `switch`.

## Repair

`local-models-kit repair` re-downloads a missing or wrong-size model file,
re-extracts a missing portable (or re-downloads the archive), relaunches a
stopped server for the gates, and re-runs a generation smoke whose record is
gone.

## Uninstall

Uninstall stops the ComfyUI server first, then follows the keep-by-default
rule:

- Default: the portable tree and models are kept, with their size printed.
- `--remove-comfyui-models`: deletes the three Z-Image-Turbo files.
- `--remove-comfyui`: removes the tree and archive only when no unrecorded
  user files (outputs, extra models, custom nodes) are present. User files are
  never deleted; the manager lists what it left.

## Troubleshooting

- **GPU check fails, CPU-only:** check the GPU/shared-memory allocation first,
  then the AMD driver, then run the launcher by hand and read its log.
- **Port 8188 busy:** something else holds it, or an old ComfyUI is running.
  `switch ollama` stops the kit's copy; the manager will not kill an unrelated
  process.
- **Model download failed or mismatched:** run `repair`.
- **SmartScreen on the EXE:** the downloaded copy is unsigned. Build locally to
  avoid the download mark.
- **Window closed but VRAM still held:** `switch ollama` is the reliable off
  switch.

Validation: [docs/reference/VALIDATION.md](reference/VALIDATION.md).
