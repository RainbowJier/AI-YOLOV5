# Environment for both app-cs2/ (runtime) and train/ (training). The repo targets
# Python 3.11; the system Python here is 3.14, which torch and TensorRT do not
# ship wheels for, so this builds a dedicated 3.11 venv with uv.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Then:
#   .\.venv\Scripts\python.exe app-cs2\main.py --weights weights\cs2\xiaozhen.engine
#   .\.venv\Scripts\python.exe train\train.py --data coco128.yaml --img 320

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found, installing..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
}

uv python install 3.11
uv venv --python 3.11 .venv

# One CUDA generation for the whole process: torch 2.11 cu128 and
# onnxruntime-gpu 1.23 both sit on CUDA 12. onnxruntime-gpu 1.24+ moved to
# CUDA 13 and cannot share a process with this torch, so it is pinned below 1.24.
uv pip install --python .venv torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Shared runtime packages (app-cs2/) and training packages (train/).
uv pip install --python .venv -r requirements.txt -r train\requirements.txt

# NVIDIA-only extras: .onnx with onnxChoice = 3, and .engine on TensorRT 11.
# tensorrt-cu12 11 still deserializes 8.x engines, so existing weights keep working.
uv pip install --python .venv "onnxruntime-gpu>=1.23,<1.24" "tensorrt-cu12>=11,<12" cuda-python

Write-Host ""
Write-Host "Done. Run:"
Write-Host "  .\.venv\Scripts\python.exe app-cs2\main.py --weights weights\cs2\xiaozhen.engine"
