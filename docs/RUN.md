# 如何启动项目

运行时代码全部在 `app-cs2/`，一个入口 `app-cs2/main.py`，后端按权重文件后缀自动选择：

| `--weights` 后缀 | 后端 | 适用机器 |
| --- | --- | --- |
| `.pt` | PyTorch 2.11 | 任意，有 CUDA 时走 FP16 |
| `.onnx` | ONNX Runtime 1.23 | CPU / AMD / NVIDIA（`onnxChoice` 决定） |
| `.engine` | TensorRT 11 | 仅 NVIDIA，最快 |

## 1. 装环境（一次性）

Windows，需要 Python 3.11（脚本会用 uv 自动装，系统 3.14 没有 torch/TensorRT 的 wheel）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

脚本创建 `.venv/`，装齐运行和训练两套依赖，CUDA 全家对齐到 12（torch 2.11 cu128、onnxruntime-gpu 1.23、tensorrt-cu12 11）。

不跑 NVIDIA 路径的话，可以跳过脚本最后一组，只装 `requirements.txt`，并把 `app-cs2/config.py` 的 `onnxChoice` 改成 `1`（CPU）、`2`（AMD）或 `4`（Intel OpenVINO，核显/NPU/CPU 自动挑，无 NVIDIA 独显时最快）。

## 2. 启动

```powershell
.\.venv\Scripts\python.exe app-cs2\main.py --weights weights\cs2\xiaozhen.engine
```

不传 `--weights` 时默认就是上面这个引擎。其它选择：

```powershell
.\.venv\Scripts\python.exe app-cs2\main.py --weights weights\sanjiaozhou\v1\320-FP16\sjz.onnx
.\.venv\Scripts\python.exe app-cs2\main.py --weights weights\sanjiaozhou\v2\320-FP16\sjz_yolov5.pt
```

自己训练/转换的模型看 [TRAINING.md](TRAINING.md) 和 [EXPORT.md](EXPORT.md)。权重可以是 YOLOv5 或 YOLOv11（ultralytics）训出来的，两者的输出格式不同，运行时按张量形状自动识别，不需要任何开关。

## 3. 选窗口

启动后终端列出所有有标题的窗口，输入序号回车。程序会尝试激活该窗口（最多 10 次，每次等 3 秒），然后截取窗口中心 `screenShotWidth × screenShotHeight`（默认 320×320）的区域开始推理。

## 4. 操作

| 按键 | 作用 |
| --- | --- |
| **Caps Lock** | 开/关瞄准。启动时是关的 |
| **P**（`aaQuitKey`） | 退出 |
| `visuals = True` 时预览窗口里按 `q` | 退出 |

瞄准逻辑：选离准星最近的框，距离不超过 `aim_range` 才动；未开火瞄头部偏移点，按住左键时瞄框中心并加速。详见 `app-cs2/config.py` 的注释和根 README。

## 常见问题

- **鼠标完全不动。** 罗技 GHUB / LGS 没在运行，或 `logitech.driver.dll` 没加载成功（启动时会打印 `GHUB or LGS driver not found`）。确认 Caps Lock 已开、目标在 `aim_range` 内。
- **选不中游戏窗口。** Windows 的 SetForegroundWindow 限制。提示重试时手动切到游戏再等它试完。
- **ONNX 报没有对应 Provider。** `onnxChoice=3` 需要 `onnxruntime-gpu`（1.23），`2` 需要 `onnxruntime-directml`。装了哪个就选哪个。
- **engine 加载失败。** 引擎和 GPU 架构绑定，换卡要用 `.pt` 重新导出（见 EXPORT.md）。
- **CPS 很低。** 优先换 `.engine`；确认截取区域是 320×320 且模型导出尺寸一致。
