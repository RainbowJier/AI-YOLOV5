"""运行时唯一配置 / the only runtime config. 改完保存重跑即可。

Each knob is documented where it sits; sections follow the frame's journey:
capture -> inference -> target -> aim -> mouse -> UI.
"""

# ============ 截取 / Capture ============

# 截取游戏窗口中心的正方形区域。必须和导出模型时的 --imgsz 一致。
# Square region captured around the window center; must match the
# exported model's --imgsz.
screenShotWidth = 320
screenShotHeight = 320

# 采集节流帧率，CPS 的上限由它决定（推理再快也不会超过采集供给）。
# 想要更高 CPS / 更新鲜的画面，提到游戏的刷新率（如 144）。
# Capture pacing -- the CPS ceiling. Raise it to the game's refresh rate
# for fresher frames and a higher ceiling (costs some capture CPU).
target_fps = 60

# ============ 推理后端 / Inference backend ============

# 仅 .onnx 权重生效：
#   1 - CPU        2 - AMD (DirectML)        3 - NVIDIA (CUDA)
#   4 - Intel OpenVINO（核显/NPU/CPU 自动挑，无 NVIDIA 独显时最快；
#       注意核显同时在渲染桌面/游戏时会有算力争夺）
onnxChoice = 3

# onnxChoice = 4 时 OpenVINO 用的设备：
#   'AUTO' 自动挑（通常落在核显）；也可固定 'GPU' / 'NPU' / 'CPU'
ov_device = 'NPU'  # 打游戏时用 NPU：游戏渲染占核显，NPU 是独立单元互不抢

# 置信度阈值。v5 语义 = objectness × 类别分数；v11 是裸类别分数（数值普遍
# 偏高），换 v11 权重后从这里重调，建议 0.45-0.55 起试。
# Confidence threshold. v5: obj*cls score; v11: raw class score (higher
# for the same detection) -- retune from ~0.5 when switching to v11.
confidence = 0.75

# NMS 的 IoU 阈值 / IoU threshold for non-max suppression
iou = 0.45

# ============ 目标类别 / Target classes ============

# 0=CT身体 1=CT头 2=T身体 3=T头。两队都开（或都关）= 所有类别都参与竞争。
# 组合示例：只打 T 就 CT = False, T = True。
CT = True
T = True

# ============ 瞄准 / Aim ============

# 目标中心离准星超过这个像素数就不瞄 / max box distance to the crosshair, px
aim_range = 50

# 选目标时优先离准星最近的框；关掉则永远取置信度最高的第一行。
# Prefer the closest box to the crosshair; off = first (top-score) row.
centerOfScreen = True

# 鼠标平滑系数，越大越柔，最低 1.0 / move smoothing, higher = softer, min 1.0
lock_smooth = 4

# 灵敏度系数：桌面试用 1；游戏里调成游戏内灵敏度 / sensitivity scale
lock_sen = 1

# ============ 鼠标驱动 / Mouse driver ============

#   'dll'       自建 native/mouse_driver.dll（C 里直接 SendInput，带小数位移
#               累积，最省开销；编译见 docs/DRIVER.md）
#   'logitech'  罗技驱动，需 GHUB/LGS 在运行且有罗技设备
mouse_driver = "dll"

# 仅 mouse_driver = "dll" 生效：进程多媒体定时器精度（毫秒）。
# 0 = 不改；1 = 更细的调度间隔，摇鼠更稳，代价是略高 CPU/耗电。
dll_timer_ms = 1

# ============ 界面与诊断 / UI & diagnostics ============

# 终端每秒打印一次每秒修正数 / print corrections-per-second once a second
cpsDisplay = True

# 预览窗口，每两帧渲染一次（每口约 1-3ms）；实战建议关掉。
# Preview window, rendered every 2nd frame (~1-3 ms per draw); turn off
# for real play.
visuals = True

# 按住左键时把截取帧存进 images/（采集训练数据用）。
# Save the capture while the left button is held (dataset collection).
capture = False

# 退出键 / quit key
aaQuitKey = "P"
