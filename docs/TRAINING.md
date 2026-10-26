# 如何训练

训练代码在 `train/`，来自 YOLOv5 v7.0，入口是 `train/train.py`。所有命令都在仓库根目录执行，用安装脚本建好的虚拟环境（见 [RUN.md](RUN.md) 第 1 步）。

```powershell
.\.venv\Scripts\python.exe train\train.py --data coco128.yaml --weights yolov5s.pt --img 320 --epochs 3
```

第一次跑会自动下载 `yolov5s.pt` 预训练权重和 coco128 示例数据集（约 200MB）。这条命令用来确认环境能训练，跑通后再换自己的数据。

## 1. 准备数据集

YOLO 格式：每张图一个同名 `.txt` 标签，每行 `class x_center y_center width height`，坐标归一化到 0-1。

```
datasets/mygame/
  images/
    train/   *.jpg
    val/     *.jpg
  labels/
    train/   *.txt
    val/     *.txt
```

CS2 模型的类别约定（`app-cs2/` 运行时按这个读）：

| id | 类别 |
| --- | --- |
| 0 | CT 身体 |
| 1 | CT 头 |
| 2 | T 身体 |
| 3 | T 头 |

## 2. 写数据集描述文件

新建 `train/data/mygame.yaml`：

```yaml
path: D:/datasets/mygame    # 数据集根目录（绝对路径最稳）
train: images/train
val: images/val
nc: 4
names: ['ct-body', 'ct-head', 't-body', 't-head']
```

仓库里 `train/data/coco128.yaml` 是现成的例子。

## 3. 训练

```powershell
.\.venv\Scripts\python.exe train\train.py `
  --data mygame.yaml `
  --weights yolov5s.pt `
  --img 320 --batch 32 --epochs 100 `
  --device 0
```

- `--img 320`：`app-cs2/config.py` 的截取区域是 320×320，训练和推理保持同尺寸效果最好。
- `--weights yolov5s.pt`：从预训练权重微调（推荐）。从零训练改为 `--weights '' --cfg yolov5s.yaml`。
- `--device 0` 指定第一块 GPU，多卡用 `--device 0,1`。
- 显存不够先降 `--batch`，或 `--batch -1` 自动探测。

产物在 `train/runs/train/exp*/weights/`：`best.pt` 是验证集最优，`last.pt` 是最后一轮。中断后加 `--resume train/runs/train/exp/weights/last.pt` 续训。

## 4. 交付给运行时

`best.pt` 可以直接用（`app-cs2/main.py --weights best.pt`，走 PyTorch 后端），但要在实战帧率里跑，先按 [EXPORT.md](EXPORT.md) 转成 `.onnx` 或 `.engine`，速度差距是数倍到数十倍。

## 5. 用 YOLOv11 训练

YOLOv5 流程照旧可用；想换 YOLOv11（ultralytics，精度更高、小目标更好），数据集和 `mygame.yaml` 完全复用，**类别顺序必须保持 0=CT身体 1=CT头 2=T身体 3=T头**（运行时按 id 过滤）：

```powershell
.\.venv\Scripts\yolo.exe detect train model=yolo11s.pt data=train/data/mygame.yaml imgsz=320 batch=32 epochs=100 device=0
```

- 预训练 `yolo11s.pt` 首跑会自动下载；网络慢就手动下载后放到仓库根目录，`model=` 写本地路径。
- 档位选择：`yolo11n.pt` 比 yolov5s 更快且精度更高（拉 CPS 用）；`yolo11s.pt` 对标 yolov5s（精度优先用）。
- 产物在 `runs/detect/train*/weights/best.pt`，按 [EXPORT.md](EXPORT.md) 第 4 节导出（v11 不能用 `train/export.py`）。
- v11 没有 objectness 分数，置信度语义不同，训完把 `app-cs2/config.py` 的 `confidence` 从 `0.45`–`0.55` 起重新调。

## 常见问题

- **自动下载权重/数据集很慢或失败。** 手动下载后放进 `train/` 目录，或把 `--weights` 写成本地路径。
- **`nc` 不一致报错。** `mygame.yaml` 的 `nc` 必须等于标注里的类别数；改类别数要重新标注或映射。
- **TensorBoard 看曲线。** `tensorboard --logdir train/runs/train`（需要 `tensorboard` 包，已在依赖里）。
