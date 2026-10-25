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
        self.provider = _PROVIDERS[onnxChoice]

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.enable_mem_pattern = True
        self.session = ort.InferenceSession(weights, sess_options=options, providers=[self.provider])

        meta = self.session.get_inputs()[0]
        self.input_name = meta.name
        self.half = meta.type == "tensor(float16)"
        self.io = self.session.io_binding() if self.cuda else None
        self._out = None
        print("模型的tensor：", meta.type)
        print("模型的shape：", meta.shape)

    def infer(self, frame):
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
