# Portion of screen to be captured (This forms a square/rectangle around the center of screen)
# 设置图片截取的大小
screenShotHeight = 320
screenShotWidth = 320

# ONNX ONLY - Choose 1 of the 4 below
# 1 - CPU
# 2 - AMD
# 3 - NVIDIA
# 4 - Intel OpenVINO（核显/NPU/CPU 自动挑，无 NVIDIA 独显时最快；
#     注意核显同时在渲染桌面/游戏时会有算力争夺）
onnxChoice = 4
#
CT = True
T = True
# # #
# CT = True
# T = False
# #
# CT = False
# T = True

# aim range
aim_range = 50
# capture the screen while clicking left button
# 鼠标平滑，最低1.0
lock_smooth = 4

capture = False

# fps
target_fps = 110

# lock幅度系数；若在桌面试用请调成1，在游戏中(csgo)则为灵敏度
lock_sen = 1

# Person Class Confidence
confidence = 0.75

# IoU threshold for non-max suppression
iou = 0.45

# What key to press to quit and shutdown the autoaim
aaQuitKey = "P"

# Displays the Corrections per second in the terminal
cpsDisplay = True

# Smarter selection of people
centerOfScreen = True

#########
# 是否开启可视化窗口
#########
# Set to True if you want to get the visuals
visuals = True
