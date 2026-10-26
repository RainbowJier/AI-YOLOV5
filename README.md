# AI-AIMBOT-YOLOV5

Windows 实时目标检测自瞄：截取游戏窗口中心 320×320 区域，YOLOv5 / YOLOv11 推理，鼠标驱动注入相对位移。在 [rootkitorg AI-Aimbot](https://github.com/rootkitorg/AI-Aimbot) 基础上重构——运行时收敛为单入口 `app-cs2/`，推理栈升级到 torch 2.11（CUDA 12.8）/ ONNX Runtime 1.23 / TensorRT 11，GPU 热路径做到每帧零分配、只有一次设备同步。

## 仓库结构

```
app-cs2/     运行时。唯一入口 main.py（后端按权重后缀自动选择）；detect.py 离线视频检测
  aimbot/    采集 / 鼠标驱动 / 上传 / NMS / 选目标 / 主循环 / TensorRT 引擎加载 / 推理后端
  native/    鼠标驱动：mouse_driver.c/.dll（默认）、logitech.driver.dll（可选）
train/       YOLOv5 v7.0 完整训练栈（train.py / val.py / export.py）；v11 用 ultralytics 训，export_yolo11.py 导出
weights/     已导出的模型
docs/        RUN 启动 · TRAINING 训练 · EXPORT 格式转换 · DRIVER 鼠标驱动
scripts/     setup.ps1 一键环境 · build_dll.ps1 驱动编译
```

两个目录互不依赖：`train/` 只在 `.pt` 反序列化的瞬间被 `torch_backend.py` 挂上 `sys.path`（checkpoint 引用 `models.yolo` 类），其余时候完全隔离。

## 快速开始

```powershell
# 1. 装环境（一次性）：Python 3.11 venv + CUDA 12 全家
#    torch 2.11 cu128 / onnxruntime-gpu 1.23 / tensorrt-cu12 11，已内置国内镜像源
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 2. 跑起来（默认 weights\cs2\xiaozhen.engine，TensorRT FP16，最快）
.\.venv\Scripts\python.exe app-cs2\main.py

# 3.（可选）编译自建鼠标驱动 DLL，需要 MSVC Build Tools
powershell -ExecutionPolicy Bypass -File scripts\build_dll.ps1
```

启动后终端列出所有有标题的窗口，输入序号回车，程序激活该窗口并开始截取推理。

| 按键 | 作用 |
| --- | --- |
| **Caps Lock** | 开 / 关瞄准（启动时是关的） |
| **P** | 退出（`aaQuitKey`） |
| 预览窗口里 **q** | 退出（`visuals = True` 时） |

## 后端与权重

| `--weights` 后缀 | 后端 | 适用 |
| --- | --- | --- |
| `.engine` | TensorRT 11 | 仅 NVIDIA，**最快**，默认 |
| `.onnx` | ONNX Runtime | 由 `onnxChoice` 决定：`1` CPU · `2` AMD/DirectML · `3` NVIDIA/CUDA · `4` Intel OpenVINO（核显/NPU/CPU 自动，无 N 卡时最快） |
| `.pt` | PyTorch | 任意机器，有 CUDA 时走 FP16 |

仓库自带：

| 文件 | 格式 |
| --- | --- |
| `weights/cs2/xiaozhen.engine` | TensorRT，默认 |
| `weights/cs2/10w-v5-320-fp16.engine` | TensorRT FP16 |
| `weights/cs2/10w-v5-320-16.onnx` | ONNX FP16 |
| `weights/sanjiaozhou/v1/320-FP16/sjz.onnx` | ONNX FP16 |
| `weights/sanjiaozhou/v2/320-FP16/sjz_yolov5.{onnx,engine,pt}` | ONNX / TensorRT / PyTorch |

YOLOv5 和 YOLOv11 的输出布局不同（v5 带 objectness，v8/11 不带），运行时按张量形状自动识别，不需要任何开关。

## 性能设计

每帧热路径（GPU 模式）：

```
bettercam 采集
  → 帧写入锁页内存，一次异步 HtoD 到常驻显存缓冲（零逐帧分配）
  → 推理引擎直读该缓冲（TRT 张量地址只设一次，无每帧全流同步）
  → GPU 把预测归约成 top-64 定长候选切片（无数据依赖形状、无同步）
  → 整片一次回传（全帧唯一的设备同步点）
  → host 上做阈值、队伍过滤、贪心 NMS、选目标（≤64 行，纯 numpy）
```

- ONNX CUDA 路径：IO Binding 输入输出常驻显存，输出缓冲复用，与 torch 共享 CUDA 流。
- OpenVINO 路径：设备可选（核显 / NPU / CPU），打游戏用 NPU 不和游戏抢核显。
- 预览窗口每两帧渲染一次；实战 `visuals = False` 整体关闭。

**CPS 上限 = `target_fps`（采集帧率）**。实测 CPS 贴着 60 的时候，瓶颈在采集供给不在推理，把 `target_fps` 提到游戏刷新率才是有效优化。调优速查见 [docs/RUN.md](docs/RUN.md) 第 5 节。

## 瞄准行为

- 类别：`0` CT 身体 · `1` CT 头 · `2` T 身体 · `3` T 头。`config.CT` / `config.T` 在 host 端过滤，作用于所有后端（都开或都关 = 全类别竞争）。
- 选离准星最近的框，距离不超过 `aim_range`（默认 50 px）才动；关掉 `centerOfScreen` 则永远取置信度最高的一行。
- 未开火瞄头部偏移点（各后端比例：torch 0.2 / onnx 0.1 / tensorrt 0.32）；按住左键瞄框中心并加速 3.0/2.6。
- 位移经 `atan` 阻尼平滑：`lock_smooth` 越大越柔（最低 1.0），`lock_sen` 是灵敏度系数（游戏内填游戏灵敏度）。

全部配置集中在 `app-cs2/config.py`，按「截取 → 推理 → 类别 → 瞄准 → 鼠标 → 界面」分节，每个旋钮带双语注释，改完重跑即生效。

## 训练与转换

```powershell
# 训练（YOLOv5；v11 用 .venv\Scripts\yolo.exe，见 TRAINING.md 第 5 节）
.\.venv\Scripts\python.exe train\train.py --data mygame.yaml --weights yolov5s.pt --img 320 --batch 32 --epochs 100 --device 0

# 导出：pt → onnx / engine（TensorRT 11），v5 与 v11 各有入口
.\.venv\Scripts\python.exe train\export.py       --weights best.pt --include engine --half --imgsz 320 320 --device 0
.\.venv\Scripts\python.exe train\export_yolo11.py --weights best.pt --include onnx engine --imgsz 320 --half --device 0
```

注意：`--imgsz` 必须和 `config.py` 的截取区域一致（默认 320）；`.engine` 与 GPU 架构和 TensorRT 大版本绑定，换卡要重导；v11 的置信度语义和 v5 不同，换权重后把 `confidence` 从 0.45–0.55 重调。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/RUN.md](docs/RUN.md) | 启动：环境、命令、窗口选择、按键、性能调优、排障 |
| [docs/TRAINING.md](docs/TRAINING.md) | 训练：数据集、类别约定、YOLOv5 / YOLOv11 训练命令 |
| [docs/EXPORT.md](docs/EXPORT.md) | 格式转换：pt → onnx → engine，v5 / v11 双入口 |
| [docs/DRIVER.md](docs/DRIVER.md) | 自建鼠标驱动 DLL：为什么快、编译、排查 |

## 硬性要求

- Windows；Python 3.11 由 `scripts/setup.ps1` 经 uv 自动安装（系统 Python 3.14 没有 torch/TensorRT 的 wheel）。
- NVIDIA 路径需要 CUDA 12.8 驱动；无 N 卡用 `onnxChoice = 4`（Intel OpenVINO）或 `1`（CPU）。
- ONNX Runtime 固定 1.23：1.24 起改绑 CUDA 13，不能和这套 torch 共进程。
- 鼠标：默认 `dll` 驱动免厂商软件（SendInput 在 C 里，带小数位移累积）；罗技设备可选 GHUB/LGS 驱动。

## 许可

本仓库以 [GNU GPL v3](LICENSE) 发布。`train/` 下的 YOLOv5 v7.0 代码原许可为 AGPL-3.0。
