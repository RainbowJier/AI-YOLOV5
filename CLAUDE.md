# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows-only, Python 3.11 real-time object-detection aimbot built on a vendored YOLOv5 v7.0 codebase (rootkitorg AI-Aimbot fork with Chinese modifications). Captures the center of a game window, runs YOLOv5 inference, and moves the mouse via the Logitech driver DLL. Comments and config are bilingual (Chinese/English).

## Running

There is no build, lint, or test tooling. Each entry point is run directly:

- `python main.py` — PyTorch (torch.hub local load), slowest
- `python main_onnx.py` — ONNX Runtime (provider set by `onnxChoice` in config)
- `python main_tensorrt.py` — TensorRT `.engine`, NVIDIA-only, fastest
- `main_onnx_sjz.py` / `main_tensorrt_sanjiaozhou.py` — "三角洲" (Delta Force) variants that read `config_sjz.py` instead of `config.py`

Dependencies: `pip install -r requirements.txt`, plus torch (CUDA 11.8 build per README), and per entry point: `pynput`, `onnxruntime`/`onnxruntime-gpu` + `cupy-cuda11x` (onnx), or `tensorrt` (engine). A `.venv` exists in the project root.

Model export (`.pt` → `.onnx`/`.engine`): use the vendored `export.py`, e.g.
`python export.py --weights ./yolov5s.pt --include engine --half --imgsz 320 320 --device 0`

Runtime controls: CAPS_LOCK (key code `0x14`) toggles aiming; the quit key comes from `aaQuitKey` in the config file (currently `"P"`, not `q` as the README says).

## Architecture

Every entry point follows the same pipeline, duplicated (not shared) across the `main_*.py` files:

1. **Window selection** — `gameSelection.py` lists all windows, user picks one by index, activates it, and creates a `bettercam` camera capturing a `screenShotWidth × screenShotHeight` region centered on that window. Returns `(camera, cWidth, cHeight, region)` where cWidth/cHeight are the capture-region center (the crosshair position).
2. **Mouse driver** — each entry point loads `logitech.driver.dll` via ctypes at import time. Requires Logitech GHUB or LGS to be running (`device_open() == 1`), otherwise all `Logitech.mouse.move()` calls are silent no-ops. Relative moves go through `driver.moveR(x, y, True)`; this bypasses win32 SendInput, which some anti-cheat platforms block.
3. **Inference + targeting loop** — grab frame → normalize (half precision when CUDA) → model → `non_max_suppression` (vendored `utils/general.py`) → build a pandas DataFrame of normalized xywh targets → sort by distance from capture center → nearest target wins → compute headshot offset (fraction of box height) → move mouse only while CAPS_LOCK is on and (in some variants) only when within `aim_range` pixels of center.

Key structural facts:

- `models/`, `utils/`, `hubconf.py`, `export.py` are vendored YOLOv5 v7.0 — treat as upstream library code; project-specific logic lives in the `main_*.py` files, `config.py`/`config_sjz.py`, and `gameSelection.py`.
- All entry points patch `pathlib.PosixPath = pathlib.WindowsPath` at import so locally-loaded `.pt` checkpoints (saved on Posix) deserialize on Windows.
- Model classes: `0` = CT body, `1` = CT head, `2` = T body, `3` = T head (class list comes from the checkpoint; NMS `classes` filter is `[0, 1, 2, 3]`). The `CT`/`T` flags in `config.py` filter which team is targeted in `main_tensorrt.py`.
- TensorRT variants preprocess on GPU with `cupy` before handing a numpy array to torch.
- Mouse smoothing: `main_tensorrt*.py` use `moveSmooth()` (arctan-based curve scaled by `lock_smooth`/`lock_sen`); `main.py` instead fires several scaled-down moves per frame (1.1× down to 0.5×).

## Known Stale Code (gotchas)

- `main.py` is out of sync with `config.py`: it imports `useMask`, `maskWidth`, `maskHeight`, `headshot_mode` (and `maskSide` mid-loop), which `config.py` no longer defines, and unpacks 3 values from `gameSelection()` which now returns 4. It will fail before the main loop until fixed. The other entry points work with the current configs.
- Weight paths are hardcoded per entry point:
  - `main.py` → `weights/CS2-2/yolov5s.pt` (path does not currently exist under `weights/`)
  - `main_onnx.py` / `main_onnx_sjz.py` → `weights/sanjiaozhou/v1/320-FP16/sjz.onnx`
  - `main_tensorrt.py` → `weights/cs2/xiaozhen.engine`
  - `main_tensorrt_sanjiaozhou.py` → `weights/sanjiaozhou/v2/320-FP16/sjz_yolov5.engine`
- `capture_screen()` in `main_onnx.py` saves training screenshots to a hardcoded absolute path (`C:\Users\30218\Desktop\SJZ\train/`); the copy in `main_tensorrt.py` saves to `images/`. Only invoked when `capture` is enabled and left mouse is held.
- `requirements.txt` is incomplete: it omits `pynput`, `torch`, `onnxruntime*`, and `cupy` which the entry points import.
