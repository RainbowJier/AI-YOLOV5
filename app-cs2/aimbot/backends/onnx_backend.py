"""ONNX Runtime backend. Provider comes from onnxChoice in config.py."""

import onnxruntime as ort
import torch

from aimbot.backends.base import Detector
from aimbot.nms import nms
from aimbot.preprocess import frame_to_cuda, frame_to_numpy
from config import confidence, iou, onnxChoice

_PROVIDERS = {1: "CPUExecutionProvider", 2: "DmlExecutionProvider", 3: "CUDAExecutionProvider"}


class OnnxDetector(Detector):
    def __init__(self, weights, mouse, headshot_fraction=0.1, speed=2.6):
        super().__init__(mouse, headshot_fraction, speed)
        self.cuda = onnxChoice == 3
        self.provider = _PROVIDERS.get(onnxChoice)  # None on the OpenVINO path
        self.ov_request = None

        if onnxChoice == 4:
            # Intel OpenVINO: AUTO picks the Arc iGPU / NPU / CPU. Fastest by
            # far on Meteor Lake (1.3 ms on the iGPU vs 4.3 ms tuned ORT CPU).
            import openvino as ov
            core = ov.Core()
            compiled = core.compile_model(weights, 'AUTO', {'PERFORMANCE_HINT': 'LATENCY'})
            # 'AUTO' picks a device per model; pin 'GPU' or 'NPU' to force the
            # Arc iGPU / NPU when the game does not run on the iGPU.
            self.ov_request = compiled.create_infer_request()
            self.input_name = compiled.inputs[0].any_name
            self.half = 'float16' in str(compiled.inputs[0].element_type)
            print('OpenVINO devices:', core.get_available_devices())
            return

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.enable_mem_pattern = True
        if self.provider == "CPUExecutionProvider":
            # The default thread pool oversubscribes a tiny 320 model: 18
            # threads measured 35 ms on this CPU, 8 threads measured 16 ms.
            options.intra_op_num_threads = 8
            options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(weights, sess_options=options, providers=[self.provider])

        meta = self.session.get_inputs()[0]
        self.input_name = meta.name
        self.half = meta.type == "tensor(float16)"
        self.io = self.session.io_binding() if self.cuda else None
        self._out = None
        print("模型的tensor：", meta.type)
        print("模型的shape：", meta.shape)

    def infer(self, frame):
        if self.ov_request is not None:
            feed = frame_to_numpy(frame, self.half)
            out = next(iter(self.ov_request.infer({self.input_name: feed}).values()))
            return nms(torch.from_numpy(out), confidence, iou, max_det=3)
        if self.cuda:
            im = frame_to_cuda(frame, self.half)
            out = self._bound(im)
        else:
            feed = frame_to_numpy(frame, self.half)
            out = torch.from_numpy(self.session.run(None, {self.input_name: feed})[0])
        return nms(out, confidence, iou, max_det=3)

    def _bound(self, im):
        """Feed the CUDA tensor straight in. The output buffer is reused."""
        if self._out is None or self._out.dtype != im.dtype:
            self._out = torch.empty(self.session.get_outputs()[0].shape, dtype=im.dtype, device=im.device)
        binding = self.io
        binding.bind_input(self.input_name, 'cuda', 0, _ort_type(im.dtype),
                           tuple(im.shape), im.data_ptr())
        binding.bind_output(self.session.get_outputs()[0].name, 'cuda', 0, _ort_type(im.dtype),
                            tuple(self._out.shape), self._out.data_ptr())
        self.session.run_with_iobinding(binding)
        return self._out


def _ort_type(dtype):
    return ort.TensorType.float16 if dtype == torch.float16 else ort.TensorType.float32
