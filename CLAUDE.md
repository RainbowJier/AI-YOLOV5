# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows-only, Python 3.11 real-time object-detection aimbot built on a vendored YOLOv5 v7.0 codebase. Captures the center of a game window, runs YOLOv5 or YOLOv11 (ultralytics) inference — the two layouts coexist — and moves the mouse via the Logitech driver DLL. Comments and config are bilingual (Chinese/English).

## Layout

Two trees that do not import each other:

- `app-cs2/` — the runtime. Single entry `app-cs2/main.py`; the backend follows the weight suffix (`.pt` torch, `.onnx` onnxruntime, `.engine` tensorrt). `app-cs2/detect.py` runs offline video detection on those same backends (letterbox whole-frame view; `config.onnxChoice` drives the engine). `app-cs2/aimbot/` holds capture, driver, preprocess, nms, targeting, loop, the feed slot, engine loader, backends and the tuner UI. `app-cs2/config.py` is the only runtime config. `app-cs2/weights/` holds the exported models (a locally built `.engine` plus its `.onnx` source).
- `train/` — full YOLOv5 v7.0 training stack: `train.py`, `val.py`, `export.py`, `models/`, `utils/`, `data/`. Kept from upstream plus local patches listed below. YOLOv11 is trained with the `ultralytics` package instead (see docs/TRAINING.md §5) and exported with `train/export_yolo11.py`.
- `app-cs2/weights/` — exported models. `docs/` — RUN / TRAINING / EXPORT guides (Chinese).

The only cross-tree dependency: `app-cs2/aimbot/backends/torch_backend.py` puts `train/` on `sys.path` while a `.pt` checkpoint unpickles (the checkpoint references `models.yolo` classes); nothing else crosses.

## Running

`powershell -ExecutionPolicy Bypass -File scripts\setup.ps1` builds a Python 3.11 venv (system Python is 3.14, no torch/tensorrt wheels) with torch 2.11 cu128, onnxruntime-gpu 1.23 (last CUDA 12 build; 1.24+ needs CUDA 13 and cannot share the process), tensorrt-cu12 11, plus `requirements.txt` and `train/requirements.txt`.

- `.\.venv\Scripts\python.exe app-cs2\main.py --weights app-cs2\weights\10w-v5-320-16.engine` — default when `--weights` is omitted
- `.onnx` provider comes from `onnxChoice` in `app-cs2/config.py` (1=CPU, 2=DirectML, 3=CUDA, 4=OpenVINO AUTO — Intel iGPU/NPU/CPU, fastest without NVIDIA; ORT pins 8 intra-op threads on CPU)
- Training: see `docs/TRAINING.md`; export pt→onnx→engine: `docs/EXPORT.md`

Runtime controls: CAPS_LOCK (`0x14`) toggles aiming; quit key is `aaQuitKey` in `app-cs2/config.py` (`P`).

## Runtime architecture (app-cs2/)

- `capture.py` — window picking stays in the console (`game_selection()` prints every titled window from `list_windows()` and reads an index); `open_window(window)` activates it (up to 10 retries), waits until it is restored and its centre is on the primary screen (auto-restore for minimized windows, ~30 s readiness loop), clamps the centered `screenShotWidth × screenShotHeight` region into the primary screen, then starts bettercam (RGB, `max_buffer_len=64`). Returns `(camera, cx, cy)`.
- `driver.py` — pluggable mouse drivers, picked by `mouse_driver` in config: `dll` (default; `native/mouse_driver.dll` vendored prebuilt — rebuild per docs/DRIVER.md after changing `native/mouse_driver.c`, SendInput in C with sub-pixel remainder accumulation and an optional `dll_timer_ms` timer-resolution bump — see docs/DRIVER.md) or `logitech` (`native/logitech.driver.dll` via ctypes; needs GHUB/LGS running or moves are no-ops). `DllDriver` exposes `close()`; `main.py` calls it on exit.
- `preprocess.py` — `CudaUploader`: one pinned staging buffer + one persistent device input, single async HtoD, cast + /255 on the GPU (an event guards the pinned buffer from in-flight rewrites); host providers write into a preallocated feed array.
- `nms.py` — single-frame NMS in two halves: the device reduces the prediction to a fixed top-64 slab (mul/max/topk/gather, no data-dependent shapes, no sync), one D2H moves the slab, then threshold + class filter + class-agnostic greedy NMS run on the host. Returns one `(n, 6)` cpu tensor. Accepts both output layouts — YOLOv5 `(1, anchors, 5+nc)` with objectness and YOLOv8/11 `(1, 4+nc, anchors)` without — auto-detected by shape.
- `backends/` — `base.Detector` shared; `load_detector()` in this package's `__init__` is the one suffix-driven factory, shared by `main.py` and `detect.py` (modules import lazily); `OnnxDetector` uses IO binding on CUDA with a reused output buffer and pins ORT to 8 intra-op threads on the CPU provider (default oversubscribes: 35 ms → 4–16 ms); `TensorRTDetector` drives `aimbot/engine.py`; `TorchDetector` loads `.pt` directly (no torch.hub; v11 checkpoints need the `ultralytics` package installed to unpickle; CPU path caps `torch.set_num_threads(8)`).
- `targeting.py` — `pick` transfers the NMS slab to the host once; the team filter and the closest-box scan run in numpy; `aim_at` gates on CapsLock + `aim_range`; with `aim_while_firing=False` the snap also pauses while LMB is held (mouse rests, the tracker stays warm, aiming resumes on release). Vertical lock point = `config.lock_y` fraction of the box from its top (hotkey-tunable: loop.py reads ↑/↓ and nudges it at runtime). Movement (v3.1): EMA-tracked target (`track_tau`); world-velocity lead reconstructed from observed deltas + own injected moves but **noise-gated** (`lead_min_speed` — the lead is exactly zero below the gate, so a standing target gets zero feed-forward); radial deadband (`deadband_px`, hard zero inside); an **error-space critically damped spring** (semi-implicit, unconditionally stable; `move_rate` × backend `speed` = omega, ×3.0/2.6 while LMB held; the spring integrates only the freshly OBSERVED error each frame — no position is ever simulated, so the loop is closed on reality: a dead view or wrong `lock_sen` slows convergence but can never stall the output, the v3.0 bug); tanh soft cap (`max_move_speed`); px→dots output scaling (`lock_sen`). Sticky box selection with 35% hysteresis stops head/body flip-flop. Still shaking → raise `deadband_px` then `lead_min_speed`; see docs/MOVEMENT_ALGORITHM.md. `scripts/sim_movement.py` simulates the core against a closed-loop view model (incl. dead-view and half-sensitivity regressions) without the game.
- `loop.py` — grab → infer → aim → optional save / embedded preview: when `config.visuals` (read live; the tuner switch flips it mid-run) the loop draws the boxes (cv2, imported lazily) and publishes the drawn frame to `aimbot/feed.py`, a latest-wins slot the tuner UI drains at ~12 fps — no OpenCV window, no cross-thread Tk calls. Dataset PNG saves run on a queue worker; quit drains it.
- `feed.py` — single-slot frame handoff aim loop → tuner UI (producer `publish`, consumer `take`; private copies because bettercam frames are ring-buffer views).
- `tuner.py` — runtime tuning UI (CustomTkinter, own daemon thread), opened by main.py after the console window pick. Fixed-DPI-safe two-column workbench: embedded live feed on the left, segmented `手感`/`目标`/`运行` tabs on the right, and a sticky save footer. Slider commits are coalesced (~24ms) and the mouse wheel is disabled panel-wide (drag sliders / scrollbar only); Entry Enter/Escape and field errors are explicit; hidden windows lower polling; save runs off the Tk callback and reports through a queue. Sliders/toggles write `config` live; `refresh()` re-derives targeting's import-time constants and pushes `confidence` into the loaded backend; `save()` regex-writes values back into config.py atomically, preserving comments/line endings.
- `engine.py` — TensorRT engine loader speaking both the 8.x binding API and the 10/11 tensor API (`num_io_tensors`, `set_tensor_address` cached once, `execute_async_v3`, no per-frame sync — the NMS slab copy is the sync point).

## Local patches in train/ (do not revert)

- `torch.load(..., weights_only=False)` everywhere (torch 2.x default breaks these checkpoints).
- `utils/general.py`: self-contained `check_requirements` (check-only, no auto-install; the fork used to `pip install ultralytics` at import time). Treats a bare string as a package name, `.txt`/Path as a file.
- `utils/plots.py` and `utils/loggers/` restored from upstream v7.0 — the fork had swapped in versions that import `ultralytics`.
- `models/yolo.py`: `check_anchor_order` inlined, `feature_visualization` hook removed.
- `export.py`: ONNX opset 17 for TRT≥8; `NetworkDefinitionCreationFlag.EXPLICIT_BATCH` only on 8.x (enum member removed in 10/11); `set_memory_pool_limit` + `build_serialized_network` for TRT 10/11 with 8.x fallbacks.

## Known gotchas

- `.engine` files are bound to the building GPU's architecture AND TensorRT version. The former `weights` engines were built elsewhere (old TRT, sm50/70/80 kernels, no sm86) and all failed to deserialize in TRT 11 ("old deserialization call on a newer plan file") — they were deleted; rebuild from the `.onnx` with `train/export.py --include engine --half`.
- `confidence` in `app-cs2/config.py` (0.75) is tuned for YOLOv5's obj×cls scores. YOLOv11 confidences are raw class probabilities (higher for the same detection) — retune, start around 0.45–0.55.
- YOLOv11 checkpoints must keep the class order 0=CT body, 1=CT head, 2=T body, 3=T head — `config.CT`/`config.T` pick the team on every backend (both on or both off = all classes).
- `train.py` auto-downloads weights/datasets on first use (coco128 smoke test in TRAINING.md).
- `app-cs2/main.py` chdirs to the repo root so `weights` paths resolve from anywhere.
