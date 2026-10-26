# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows-only, Python 3.11 real-time object-detection aimbot built on a vendored YOLOv5 v7.0 codebase. Captures the center of a game window, runs YOLOv5 or YOLOv11 (ultralytics) inference — the two layouts coexist — and moves the mouse via the Logitech driver DLL. Comments and config are bilingual (Chinese/English).

## Layout

Two trees that do not import each other:

- `app-cs2/` — the runtime. Single entry `app-cs2/main.py`; the backend follows the weight suffix (`.pt` torch, `.onnx` onnxruntime, `.engine` tensorrt). `app-cs2/detect.py` runs offline video detection on those same backends (letterbox whole-frame view; `config.onnxChoice` drives the engine). `app-cs2/aimbot/` holds capture, driver, preprocess, nms, targeting, loop, engine loader and backends. `app-cs2/config.py` is the only runtime config.
- `train/` — full YOLOv5 v7.0 training stack: `train.py`, `val.py`, `export.py`, `models/`, `utils/`, `data/`. Kept from upstream plus local patches listed below. YOLOv11 is trained with the `ultralytics` package instead (see docs/TRAINING.md §5) and exported with `train/export_yolo11.py`.
- `weights/` — exported models. `docs/` — RUN / TRAINING / EXPORT guides (Chinese).

The only cross-tree dependency: `app-cs2/aimbot/backends/torch_backend.py` puts `train/` on `sys.path` while a `.pt` checkpoint unpickles (the checkpoint references `models.yolo` classes); nothing else crosses.

## Running

`powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` builds a Python 3.11 venv (system Python is 3.14, no torch/tensorrt wheels) with torch 2.11 cu128, onnxruntime-gpu 1.23 (last CUDA 12 build; 1.24+ needs CUDA 13 and cannot share the process), tensorrt-cu12 11, plus `requirements.txt` and `train/requirements.txt`.

- `.\.venv\Scripts\python.exe app-cs2\main.py --weights weights\cs2\xiaozhen.engine` — default when `--weights` is omitted
- `.onnx` provider comes from `onnxChoice` in `app-cs2/config.py` (1=CPU, 2=DirectML, 3=CUDA, 4=OpenVINO AUTO — Intel iGPU/NPU/CPU, fastest without NVIDIA; ORT pins 8 intra-op threads on CPU)
- Training: see `docs/TRAINING.md`; export pt→onnx→engine: `docs/EXPORT.md`

Runtime controls: CAPS_LOCK (`0x14`) toggles aiming; quit key is `aaQuitKey` in `app-cs2/config.py` (`P`).

## Runtime architecture (app-cs2/)

- `capture.py` — window picker (titled windows only), up to 10 activate retries, bettercam on the centered `screenShotWidth × screenShotHeight` region, RGB, `max_buffer_len=64`. Returns `(camera, cx, cy)`.
- `driver.py` — `logitech.driver.dll` via ctypes, argtypes set once; needs GHUB/LGS running or moves are no-ops.
- `preprocess.py` — one HtoD copy, permute/cast/normalize on GPU; CPU path writes BCHW directly into a preallocated array.
- `nms.py` — single-frame class-agnostic NMS, no sort, no time check. Returns one `(n, 6)` tensor. Accepts both output layouts — YOLOv5 `(1, anchors, 5+nc)` with objectness and YOLOv8/11 `(1, 4+nc, anchors)` without — auto-detected by shape.
- `backends/` — `base.Detector` shared; `OnnxDetector` uses IO binding on CUDA with a reused output buffer and pins ORT to 8 intra-op threads on the CPU provider (default oversubscribes: 35 ms → 4–16 ms); `TensorRTDetector` drives `aimbot/engine.py`; `TorchDetector` loads `.pt` directly (no torch.hub; v11 checkpoints need the `ultralytics` package installed to unpickle; CPU path caps `torch.set_num_threads(8)`).
- `targeting.py` — `pick` selects the closest box on the tensor and transfers that one row; `aim_at` gates on CapsLock + `aim_range`, applies headshot offset (torch 0.2 / onnx 0.1 / tensorrt 0.32) and arctan smoothing; left button drops the aim point to the box center and speeds the move 3.0/2.6.
- `loop.py` — grab → infer → aim → optional save/preview/CPS.
- `engine.py` — TensorRT engine loader speaking both the 8.x binding API and the 10/11 tensor API (`num_io_tensors`, `set_tensor_address`, `execute_async_v3` + stream sync).

## Local patches in train/ (do not revert)

- `torch.load(..., weights_only=False)` everywhere (torch 2.x default breaks these checkpoints).
- `utils/general.py`: self-contained `check_requirements` (check-only, no auto-install; the fork used to `pip install ultralytics` at import time). Treats a bare string as a package name, `.txt`/Path as a file.
- `utils/plots.py` and `utils/loggers/` restored from upstream v7.0 — the fork had swapped in versions that import `ultralytics`.
- `models/yolo.py`: `check_anchor_order` inlined, `feature_visualization` hook removed.
- `export.py`: ONNX opset 17 for TRT≥8; `NetworkDefinitionCreationFlag.EXPLICIT_BATCH` only on 8.x (enum member removed in 10/11); `set_memory_pool_limit` + `build_serialized_network` for TRT 10/11 with 8.x fallbacks.

## Known gotchas

- `.engine` files are GPU-architecture-bound; TensorRT 11 still deserializes 8.x/10 engines.
- `confidence` in `app-cs2/config.py` (0.75) is tuned for YOLOv5's obj×cls scores. YOLOv11 confidences are raw class probabilities (higher for the same detection) — retune, start around 0.45–0.55.
- YOLOv11 checkpoints must keep the class order 0=CT body, 1=CT head, 2=T body, 3=T head — `config.CT`/`config.T` pick the team on every backend (both on or both off = all classes).
- `train.py` auto-downloads weights/datasets on first use (coco128 smoke test in TRAINING.md).
- `app-cs2/main.py` chdirs to the repo root so `weights/` paths resolve from anywhere.
