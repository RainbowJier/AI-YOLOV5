# AI-AIMBOT-YOLOV5

Windows 实时目标检测自瞄。截取游戏窗口中心区域，YOLOv5 推理，罗技驱动 DLL 做相对鼠标移动。在 [rootkitorg AI-Aimbot](https://github.com/rootkitorg/AI-Aimbot) 基础上重构，推理栈升级为 torch 2.11（CUDA 12.8）/ ONNX Runtime 1.23 / TensorRT 11。

仓库分成两个互不依赖的目录：

```
app/     运行时。入口 app/main.py，后端按权重后缀选择（.pt / .onnx / .engine）
train/   训练与格式转换。YOLOv5 v7.0 完整训练栈，train.py / val.py / export.py
weights/ 已导出的模型
docs/    RUN.md 启动 · TRAINING.md 训练 · EXPORT.md 格式转换
```

## 快速开始

```powershell
# 1. 装环境（Python 3.11 venv + CUDA 12 全家：torch 2.11 / ort-gpu 1.23 / tensorrt-cu12 11）
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 2. 跑起来（默认 weights\cs2\xiaozhen.engine，TensorRT，最快）
.\.venv\Scripts\python.exe app\main.py
```

| 文档 | 内容 |
| --- | --- |
| [docs/RUN.md](docs/RUN.md) | 如何启动项目：环境、命令、窗口选择、按键、排障 |
| [docs/TRAINING.md](docs/TRAINING.md) | 如何训练：数据集、类别约定、训练命令、产物 |
| [docs/EXPORT.md](docs/EXPORT.md) | pt 格式转换：pt → onnx → engine（TensorRT 11） |

## 性能

- 一个入口，按后缀选后端，`.engine` 默认。
- ONNX CUDA 路径用 IO Binding：输入输出都留在显存，输出缓冲复用，不再每帧两次整帧拷贝。
- TensorRT 引擎读取器兼容 8.x / 10 / 11 的 API，旧引擎直接用。
- NMS 面向单帧小目标数重写：类别无关、无排序、无时间检查；类别过滤张量只建一次。
- 选目标在张量上完成，只有中选那一行回到 CPU。
- bettercam 采集区域 RGB 输出、缓冲 64 帧，存图与预览共用同一帧。

## 瞄准行为

- 类别：`0` CT 身体，`1` CT 头，`2` T 身体，`3` T 头。`CT`/`T` 开关只作用于 `.engine`。
- 选离准星最近的框，距离不超过 `aim_range`（默认 50 像素）才移动。
- 未开火瞄头部偏移点（各后端比例：torch 0.2 / onnx 0.1 / tensorrt 0.32）；按住左键瞄框中心并加速 3.0/2.6。
- 位移经 `atan` 平滑，`lock_smooth` 越大越慢，`lock_sen` 是灵敏度系数。

配置全部在 `app/config.py`，改完重跑即生效。

## 仓库里的权重

| 文件 | 格式 |
| --- | --- |
| `weights/cs2/xiaozhen.engine` | TensorRT，默认 |
| `weights/cs2/10w-v5-32-fp16.engine` | TensorRT |
| `weights/cs2/10w-v5-320-16.onnx` | ONNX |
| `weights/cs2/best.onnx` | ONNX |
| `weights/sanjiaozhou/v1/320-FP16/sjz.onnx` | ONNX FP16 |
| `weights/sanjiaozhou/v2/320-FP16/sjz_yolov5.onnx` | ONNX FP16 |
| `weights/sanjiaozhou/v2/320-FP16/sjz_yolov5.engine` | TensorRT |
| `weights/sanjiaozhou/v2/320-FP16/sjz_yolov5.pt` | PyTorch |

## 硬性要求

- Windows + 罗技 GHUB 或 LGS 常驻（否则鼠标移动是空操作）。
- NVIDIA 路径需要 CUDA 12.8 驱动；`.engine` 与 GPU 架构绑定，换卡重新导出。
- ONNX Runtime 固定 1.23：1.24 起改绑 CUDA 13，不能和这套 torch 共进程。

## 许可

本仓库以 [GNU GPL v3](LICENSE) 发布。`train/` 下的 YOLOv5 v7.0 代码原许可为 AGPL-3.0。
