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
.\.venv\Scripts\python.exe app-cs2\main.py --weights app-cs2\weights\10w-v5-320-16.engine
```

不传 `--weights` 时默认就是上面这个引擎。自己训练/转换的模型看 [TRAINING.md](TRAINING.md) 和 [EXPORT.md](EXPORT.md)。权重可以是 YOLOv5 或 YOLOv11（ultralytics）训出来的，两者的输出格式不同，运行时按张量形状自动识别，不需要任何开关。

## 3. 选窗口

启动后终端列出所有有标题的窗口，输入序号回车。程序会尝试激活该窗口（最多 10 次，每次等 3 秒）；若窗口最小化会自动还原并**等待就绪**（最多约 30 秒，期间提示“请点一下游戏窗口”），然后截取窗口中心 `screenShotWidth × screenShotHeight`（默认 320×320）的区域开始推理。选完后加载模型并弹出调参工作台。

## 4. 操作

| 按键 | 作用 |
| --- | --- |
| **Caps Lock** | 开/关瞄准。启动时是关的 |
| **↑ / ↓** | 运行中实时调节锁定垂直位置 `lock_y`（每次 0.02，终端打印当前值；0=框顶 0.2=头 0.5=中心 1=框底），调好把值写回 config.py |
| **P**（`aaQuitKey`） | 退出 |

瞄准逻辑：选离准星最近的框，距离不超过 `aim_range` 才动；垂直锁定位置由 `lock_y` 决定（↑/↓ 热键可调）；按住左键（开火）时吸附加速。详见 `app-cs2/config.py` 的注释和根 README。

## 5. 性能与调优

每帧热路径（GPU 模式）：bettercam 采集 → 帧写入锁页内存，一次异步上传到常驻显存缓冲 → 引擎直读 → GPU 把预测归约成 top-64 定长候选切片 → 一次回传 → host 上做阈值、队伍过滤、NMS、选目标。全程无逐帧分配、无多余设备同步。

| 想要 | 改哪里 |
| --- | --- |
| 抬高 CPS 上限 | `config.py` 的 `target_fps`——CPS 封顶等于采集帧率，游戏 144Hz 就填 144 |
| 实战再省 1-3ms/帧 | 调参面板「运行」Tab 里关掉「实时画面」（内嵌预览，实时生效），或 `config.py` 的 `visuals = False` |
| 摇鼠更稳 | `config.py` 的 `dll_timer_ms = 1`（默认已开） |
| 换推理引擎 | 直接换 `--weights` 后缀：`.engine` > `.onnx`(CUDA) > `.pt` |
| 只打一方 | `config.py` 的 `CT` / `T`（host 端过滤，所有后端生效） |
| 只打头 / 只打身体 | 调参面板「目标」页的「识别身体」「识别头部」开关（实时生效），或 `config.py` 的 `aim_body` / `aim_head` |
| 锁定更快/更柔 | `config.py` 的 `move_rate`（有效值 = move_rate × 2.6/s；默认 8 柔，25 快） |
| 锁定点高低 | 运行中按 ↑/↓，或改 `lock_y`（0=框顶 0.2=头 0.5=中心 1=框底） |

诊断看终端每秒打印的 CPS：**CPS ≈ `target_fps` 说明瓶颈在采集供给而不是推理**，此时继续优化推理没有意义，调大 `target_fps` 才有用。

## 6. 视频检测（离线）

用和实时完全相同的后端跑一个视频文件，检查模型效果：

```powershell
.\.venv\Scripts\python.exe app-cs2\detect.py --source mp4\你的视频.mp4 --conf 0.75
```

- 后端按 `--weights` 后缀选择、ONNX 引擎由 `onnxChoice` 决定，和 `main.py` 完全一致（4 = OpenVINO 核显/NPU 自动，最快）
- 视角是**整帧 letterbox**（看全画面），不是实战的中心 320 裁剪——适合检查模型，不代表实战视场
- 产物：视频同目录 `<名字>_detected.mp4` + 少量 `*_det_*.png` 快照，终端打印速度统计
- `--vid-stride 3` 每 3 帧取 1 帧加速；`--weights` 可换 `.pt` / `.engine`

## 常见问题

- **鼠标完全不动。** 看用的是哪个驱动（`config.py` 的 `mouse_driver`）：`dll` 用仓库自带的 `app-cs2/native/mouse_driver.dll`，报 `DLL file not found` 说明文件缺失，按 docs/DRIVER.md 重编或换 `logitech`；`logitech` 需要 GHUB / LGS 在运行且接了罗技设备，否则报 `GHUB or LGS driver not found`。两种驱动都先确认 Caps Lock 已开、目标在 `aim_range` 内。
- **选不中游戏窗口。** Windows 的 SetForegroundWindow 限制。提示重试时手动切到游戏再等它试完。
- **ONNX 报没有对应 Provider。** `onnxChoice=3` 需要 `onnxruntime-gpu`（1.23），`2` 需要 `onnxruntime-directml`。装了哪个就选哪个。
- **engine 加载失败。** 引擎和 GPU 架构绑定，换卡要用 `.pt` 重新导出（见 EXPORT.md）。
- **CPS 很低。** 先确认没有顶到采集上限：CPS ≈ `target_fps` 时调大它才有用。然后优先换 `.engine`；确认截取区域是 320×320 且模型导出尺寸一致。
