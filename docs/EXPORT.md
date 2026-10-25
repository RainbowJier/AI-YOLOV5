# pt 格式转换

把训练出的 `.pt` 转成 `.onnx` 和 `.engine`（TensorRT 11），供 `app/main.py` 按 GPU 选最快后端。转换脚本在 `train/export.py`，命令都在仓库根目录执行，NVIDIA 路径需要 CUDA 可用（`--device 0`）。

```
.pt  --include onnx-->  .onnx   ONNX Runtime，CPU / AMD / NVIDIA
.pt  --include engine--> .engine  TensorRT 11，仅 NVIDIA，最快
```

## 1. pt → onnx

```powershell
.\.venv\Scripts\python.exe train\export.py `
  --weights train\runs\train\exp\weights\best.pt `
  --include onnx --half --imgsz 320 320 --device 0
```

- `--half`：FP16，体积和耗时减半，`onnxChoice=3`（CUDA）直接受益。
- `--imgsz 320 320`：和 `app/config.py` 的截取区域一致，导出即最终输入尺寸。
- `--simplify`：可选，用 onnx-simplifier 化简图结构。
- 产物与源文件同目录同名：`best.onnx`。

ONNX Runtime 的执行器由 `app/config.py` 的 `onnxChoice` 决定：`1` CPU、`2` DirectML（AMD）、`3` CUDA（NVIDIA）。

## 2. onnx → engine（TensorRT 11）

```powershell
.\.venv\Scripts\python.exe train\export.py `
  --weights train\runs\train\exp\weights\best.pt `
  --include engine --half --imgsz 320 320 --device 0
```

这一步内部先导出 ONNX 再编译引擎，两条路一次完成，不需要分开跑。也可以直接拿现成的 `.onnx` 转引擎：把 `--weights` 指向那个 `.onnx` 即可。

构建引擎可能要十几分钟，进度条像卡住是正常现象。产物：`best.engine`。

要点：

- `.engine` 与导出它的 GPU 架构和 TensorRT 大版本绑定。换显卡后要用 `.pt` 在新机器上重新 `--include engine`。
- TensorRT 11 可以直接反序列化 8.x / 10 导出的旧引擎，所以 `weights/` 里已有的 `.engine` 不用重转。
- 需要动态 batch 时加 `--dynamic --batch 4`（运行时固定 batch 1，一般用不上）。

## 3. 验证

```powershell
.\.venv\Scripts\python.exe app\main.py --weights train\runs\train\exp\weights\best.engine
```

启动后先看终端打印的输入/输出 shape 是否是 `1×3×320×320`，进对局看 CPS 和命中是否正常。ONNX 同理，把后缀换掉即可，后端按后缀自动选择。

## 常见问题

- **`tensorrt` 导入失败。** 确认装的是 `tensorrt-cu12`（脚本已装），且 `pip list` 里版本是 10.x 或 11.x。
- **构建引擎报显存不足。** 关掉占显存的程序再跑；或去掉 `--half` 用 FP32（更慢但省一半）。
- **engine 在别的机器上加载失败。** 正常，重新导出。`.onnx` 和 `.pt` 跨机器通用。
