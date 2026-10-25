# Environment for the aimbot. The repo targets Python 3.11; the system Python
# here is 3.14, which torch/tensorrt do not ship wheels for, so this builds a
# dedicated 3.11 venv with uv.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Then run with:
#   .\.venv\Scripts\python.exe main_tensorrt.py

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found, installing..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
}

uv python install 3.11
uv venv --python 3.11 .venv

# PyTorch with CUDA 12.4. CPU-only fallback: drop the --index-url.
uv pip install --python .venv torch torchvision --index-url https://download.pytorch.org/whl/cu124

uv pip install --python .venv -r requirements.txt

# NVIDIA-only extras used by main_onnx.py (onnxChoice=3) and main_tensorrt.py.
uv pip install --python .venv onnxruntime-gpu tensorrt-cu12 cuda-python

Write-Host ""
Write-Host "Done. Run: .\.venv\Scripts\python.exe main_tensorrt.py"
