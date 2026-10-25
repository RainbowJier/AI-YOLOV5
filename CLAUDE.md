# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows-only, Python 3.11 real-time object-detection aimbot built on a vendored YOLOv5 v7.0 codebase (rootkitorg AI-Aimbot fork with Chinese modifications). Captures the center of a game window, runs YOLOv5 inference, and moves the mouse via the Logitech driver DLL. Comments and config are bilingual (Chinese/English).

## Running

There is no build, lint, or test tooling. Each entry point is run directly:

- `python main.py` — PyTorch (torch.hub local load through `hubconf.py`); defaults to `weights/cs2/yolov5s.pt`, override with `--weights`
- `python main_onnx.py` — ONNX Runtime; provider set by `onnxChoice` in `config.py` (1=CPU, 2=DirectML/AMD, 3=CUDA/NVIDIA); defaults to `weights/sanjiaozhou/v1/320-FP16/sjz.onnx`
- `python main_tensorrt.py` — TensorRT `.engine` via `DetectMultiBackend`, NVIDIA-only, fastest; defaults to `weights/cs2/xiaozhen.engine`

Dependencies: `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` builds a Python 3.11 venv (the system Python is 3.14, which has no torch/tensorrt wheels) and installs everything, including the CUDA 12.4 torch build, `onnxruntime-gpu` and `tensorrt-cu12`. `requirements.txt` lists only the shared packages. Preprocessing uses torch, so cupy is no longer required.

Model export (`.pt` → `.onnx`/`.engine`): use the vendored `export.py`, e.g.
`python export.py --weights ./yolov5s.pt --include engine --half --imgsz 320 320 --device 0`

Runtime controls: CAPS_LOCK (key code `0x14`) toggles aiming; the quit key comes from `aaQuitKey` in `config.py` (currently `"P"`, not `q` as the README says).

## Architecture

The three entry points are thin wrappers. All shared code lives in `aimbot/`:

- `aimbot/capture.py` — `game_selection()` lists windows via `pygetwindow`, the user picks one by index, it activates the window (up to 10 retries) and starts a `bettercam` camera on a `screenShotWidth × screenShotHeight` region centered on that window (`target_fps`, `video_mode=True`, `max_buffer_len=512`). Returns `(camera, c_width, c_height)`, the crosshair position inside the capture.
- `aimbot/driver.py` — `LogitechDriver` loads `logitech.driver.dll` via ctypes. Requires Logitech GHUB or LGS to be running (`device_open() == 1`), otherwise `move()` is a silent no-op. Relative moves go through `moveR(x, y, True)`, bypassing win32 SendInput.
- `aimbot/backends/` — one detector per entry point. `TorchDetector` (`.pt` via torch.hub), `OnnxDetector` (ONNX Runtime, provider from `onnxChoice`), `TensorRTDetector` (`.engine` via `DetectMultiBackend`, FP16). Preprocessing is plain torch: one host-to-device copy, then permute, cast and normalize on GPU. No cupy.
- `aimbot/targeting.py` — `boxes_from_nms` turns NMS output into plain tuples, `select_target` picks the box closest to the crosshair, `aim_at` applies the headshot offset and the arctan smoothing (`move_smooth`, scaled by `lock_smooth`/`lock_sen`). While the left button is held the aim point drops to the box center and the move speeds up. Movement only happens while CAPS_LOCK is on and the target is within `aim_range`.
- `aimbot/loop.py` — the frame loop: grab frame, infer, aim, optional screenshot capture, CPS printout, optional OpenCV preview.

`models/`, `utils/`, `hubconf.py`, `export.py` are vendored YOLOv5 v7.0 (AGPL-3.0) — treat as upstream library code.

Key structural facts:

- NMS uses `confidence` and `iou` from `config.py` separately; previously the confidence value was passed as the IoU threshold too.
- Target selection and sorting no longer build a pandas DataFrame per frame.
- `main_tensorrt.py` filters to body classes only (`0` for CT, `2` for T) via the `CT`/`T` flags; the other two entry points keep every class.
- Headshot offset fractions differ per backend: 0.2 (torch), 0.1 (onnx), 0.32 (tensorrt).
- `export.py`'s TensorRT path uses `set_memory_pool_limit` and `build_serialized_network`, so it works on TensorRT 10 as well as 8.x.
- Weight paths default per entry point but are all overridable with `--weights`.

## Known Stale Code (gotchas)

- `config_sjz.py` still exists but nothing imports it — the former 三角洲 entry points that read it were removed.
- `main.py` needs a `.pt` checkpoint at `weights/cs2/yolov5s.pt` (or a `--weights` override); `weights/` currently only ships `.onnx` and `.engine` files, so the PyTorch entry point cannot run until a checkpoint is exported or supplied.
- The README's "Configurable Settings" section documents options (`useMask`, `headshot_mode`, `aaMovementAmp`, `aaDetectionBox`) that no longer exist; `config.py` is the source of truth.
