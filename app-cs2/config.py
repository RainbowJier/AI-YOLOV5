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
target_fps = 50

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
CT = False
T = True

# 只识别头部 / 身体（在队伍过滤之上再筛部位；调参面板「目标」页有开关，
# 实时生效）：两个都开 = 全部；只开一个 = 只瞄该部位；两个都关 = 不瞄任何目标。
# Head/body part filter on top of the team filter (live switches in the
# tuner panel): both on = everything; one on = that part only;
# both off = nothing gets aimed at.
aim_body = False
aim_head = True

# ============ 瞄准 / Aim ============

# 目标中心离准星超过这个像素数就不瞄 / max box distance to the crosshair, px
aim_range = 40

# 吸附范围（px）：0 = 关（全程同强度）；>0 = 吸附强度随距离线性衰减，
# 越近吸得越狠、到范围边界衰减为 0（之外不瞄）。建议不大于触发半径。
# 面板「目标」页可实时调。
# Aim falloff radius (px): 0 = off (uniform strength); >0 = the snap
# scales down linearly with distance, reaching zero at the edge.
# Keep it within aim_range. Live slider in the tuner panel.
aim_falloff = 5

# 选目标时优先离准星最近的框；关掉则永远取置信度最高的第一行。
# Prefer the closest box to the crosshair; off = first (top-score) row.
centerOfScreen = True

# 锁定点在目标框内的垂直位置：0=框顶 · 0.2=头部 · 0.5=中心 · 1=框底。
# 运行中按 ↑/↓ 实时调节（每次 0.02，终端打印当前值），调好把值写回这里。
# Vertical lock point inside the target box (0=top, 1=bottom).
lock_y = 0.05

# 鼠标平滑系数（原版算法）：越大越柔、跟得越慢，最低 1.0。调参面板「目标」页可实时调。
# Move smoothing, higher = softer/slower, min 1.0 (original algorithm).
lock_smooth = 6

# 灵敏度换算：输出鼠标 dots = 像素位移 ÷ lock_sen。桌面试用 1；
# 游戏里填游戏灵敏度相对桌面的倍数（如 1.25），填对后收敛手感与桌面一致。
# Mouse dots = px move / lock_sen (game sensitivity scale).
lock_sen = 1.25

# 按住左键（开火）时：瞄点落到框中心，吸附加速 3.0/2.6×（原版行为）。
# Left button held: aim at the box centre, 3.0/2.6x faster (original).

# 开火时是否继续吸附（CapsLock 开启时生效）：
#   True  = 是：开火（按住左键）时照常吸附
#   False = 否：开火时不吸附，松开左键后恢复吸附
# 调参面板里也有这个开关。
# Keep aiming while firing (LMB held), with CapsLock on: True = keep
# snapping; False = the mouse rests while firing and resumes after
# release. Also a panel switch.
aim_while_firing = True

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
visuals = False

# 按住左键时把截取帧存进 images/（采集训练数据用）。
# Save the capture while the left button is held (dataset collection).
capture = False

# 退出键 / quit key
aaQuitKey = "P"
