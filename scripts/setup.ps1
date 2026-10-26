# Environment for both app-cs2/ (runtime) and train/ (training). The repo targets
# Python 3.11; the system Python here is 3.14, which torch and TensorRT do not
# ship wheels for, so this builds a dedicated 3.11 venv with uv.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Then:
#   .\.venv\Scripts\python.exe app-cs2\main.py --weights app-cs2\weights\10w-v5-320-16.engine
#   .\.venv\Scripts\python.exe train\train.py --data coco128.yaml --img 320
#
# 本机（2026-10-26）：D 盘已满，装不下 ~7GB 的 torch。.venv 是指向
# C:\venv\ai-aimbot-yolov5\.venv 的目录联接，实体在 C 盘（与 uv 缓存同盘，
# 硬链接安装几乎不占额外空间）。重装依赖用：
#   uv pip install --python C:\venv\ai-aimbot-yolov5\.venv ...
# 不要删除项目里的 .venv 联接本身。

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
#
# 国内镜像（换回官方源：PyPI 去掉 --index-url；torch 改回
# uv pip install --python .venv torch torchvision --index-url https://download.pytorch.org/whl/cu128）：
#   $pypi       清华 TUNA，PyPI 全量
#   torch 系直接钉阿里云 cu128 轮子的完整 URL——阿里云的目录页 uv 解析不稳定，
#   当索引用时会静默回落到 TUNA 装成 CPU 版（踩过：2.14.1+cpu）；钉 URL 无歧义。
$Tuna = 'https://pypi.tuna.tsinghua.edu.cn/simple'

uv pip install --python .venv --index-url $Tuna `
    'https://mirrors.aliyun.com/pytorch-wheels/cu128/torch-2.11.0%2Bcu128-cp311-cp311-win_amd64.whl' `
    'https://mirrors.aliyun.com/pytorch-wheels/cu128/torchvision-0.26.0%2Bcu128-cp311-cp311-win_amd64.whl'

# Shared runtime packages (app-cs2/) and training packages (train/).
uv pip install --python .venv --index-url $Tuna -r requirements.txt -r train\requirements.txt

# NVIDIA-only extras: .onnx with onnxChoice = 3, and .engine on TensorRT 11.
# .engine binds to the building GPU arch and TRT version; rebuild from the
# .onnx per docs/EXPORT.md when either changes.
uv pip install --python .venv --index-url $Tuna "onnxruntime-gpu>=1.23,<1.24" "tensorrt-cu12>=11,<12" cuda-python

Write-Host ""
Write-Host "Done. Run:"
Write-Host "  .\.venv\Scripts\python.exe app-cs2\main.py --weights app-cs2\weights\10w-v5-320-16.engine"
