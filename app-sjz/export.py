"""把 YOLO_DeltaForce 的 .pt 权重导出为 .onnx 和 .engine。

    .\\.venv\\Scripts\\python.exe app-sjz\\export.py
    .\\.venv\\Scripts\\python.exe app-sjz\\export.py --imgsz 640 --no-engine

pt 来自 github.com/advent259141/YOLO_DeltaForce 的
runs/detect/delta_force_v4/weights/best.pt（YOLOv8n, nc=2, 0=body 1=head）。

onnx 走 ultralytics 导出（opset 12、静态 shape）：fp32 版给 onnxruntime/
OpenVINO 后端，fp16 版给 TensorRT。engine 不走 ultralytics（其 FP16 路径
强制依赖 nvidia-modelopt），改用 TensorRT Python API：TRT 11 删掉了
BuilderFlag.FP16，FP16 由 STRONGLY_TYPED 网络解析 fp16 onnx 实现。
engine 绑定本机 GPU，换卡需重跑。产物与 pt 同目录：
    delta_force_v4.onnx (fp32) / delta_force_v4.fp16.onnx / delta_force_v4.engine
"""

import argparse
import os
import shutil
import sys

_APP = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_APP)
sys.path.insert(0, _APP)
os.chdir(_ROOT)

WEIGHTS = os.path.join(_APP, 'weights', 'delta_force_v4.pt')


def _export_onnx(weights, imgsz, half):
    from ultralytics import YOLO
    onnx_path = YOLO(weights).export(
        format='onnx', imgsz=imgsz, opset=12, simplify=True,
        dynamic=False, half=half, device=0)
    return onnx_path


def export_onnx(weights, imgsz):
    """fp16 first (renamed away), then fp32 left in place for the runtime."""
    half_path = _export_onnx(weights, imgsz, half=True)
    fp16_path = os.path.join(os.path.dirname(half_path),
                             os.path.splitext(os.path.basename(weights))[0] + '.fp16.onnx')
    if os.path.abspath(half_path) != os.path.abspath(fp16_path):
        shutil.move(half_path, fp16_path)
    print('[export] onnx fp16 -> {}'.format(fp16_path))
    fp32_path = _export_onnx(weights, imgsz, half=False)
    print('[export] onnx fp32 -> {}'.format(fp32_path))
    return fp32_path, fp16_path


def build_engine(onnx_path, engine_path=None, workspace_gb=2):
    """TensorRT engine from a static-shape ONNX, via the builder API.

    STRONGLY_TYPED keeps the onnx's own dtypes: feed it the fp16 export
    and the whole graph runs in half precision.
    """
    import tensorrt as trt

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
    parser = trt.OnnxParser(network, logger)
    with open(onnx_path, 'rb') as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                print('[trt] {}'.format(parser.get_error(i)))
            raise RuntimeError('ONNX parse failed: {}'.format(onnx_path))

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE,
                                 workspace_gb << 30)
    serialized = builder.build_serialized_network(network, config)
    if serialized is None:
        raise RuntimeError('TensorRT build failed for {}'.format(onnx_path))

    if engine_path is None:
        engine_path = os.path.join(
            os.path.dirname(os.path.abspath(onnx_path)), 'delta_force_v4.engine')
    with open(engine_path, 'wb') as f:
        f.write(serialized)
    print('[export] engine -> {}'.format(engine_path))

    # Round-trip: deserialize and report the I/O tensors it locked in.
    runtime = trt.Runtime(logger)
    with open(engine_path, 'rb') as f:
        engine = runtime.deserialize_cuda_engine(f.read())
    for i in range(engine.num_io_tensors):
        name = engine.get_tensor_name(i)
        mode = 'in ' if engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT else 'out'
        print('[trt] {} {} {} {}'.format(mode, name,
              engine.get_tensor_dtype(name), engine.get_tensor_shape(name)))
    return engine_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', default=WEIGHTS, help='source .pt')
    parser.add_argument('--imgsz', type=int, default=640,
                        help='model input size; must match config.screenShot*')
    parser.add_argument('--onnx', default=None,
                        help='skip the pt step, build the engine from this onnx')
    parser.add_argument('--no-engine', action='store_true',
                        help='only build the onnx')
    args = parser.parse_args()

    if args.onnx:
        build_engine(args.onnx)
    else:
        if not os.path.isfile(args.weights):
            raise SystemExit('weights not found: {}'.format(args.weights))
        _fp32, fp16 = export_onnx(args.weights, args.imgsz)
        if not args.no_engine:
            build_engine(fp16)


if __name__ == '__main__':
    main()
