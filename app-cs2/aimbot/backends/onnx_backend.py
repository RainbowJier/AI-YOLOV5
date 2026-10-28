"""ONNX Runtime backend. Provider comes from onnxChoice in config.py."""

import numpy as np
import onnxruntime as ort
import torch

from aimbot.backends.base import Detector
from aimbot.nms import nms
from aimbot.preprocess import CudaUploader, frame_to_numpy
from config import confidence, iou, onnxChoice, ov_device

_PROVIDERS = {1: "CPUExecutionProvider", 2: "DmlExecutionProvider", 3: "CUDAExecutionProvider"}


class OnnxDetector(Detector):
    def __init__(self, weights, mouse, speed=2.6):
        super().__init__(mouse, speed)
        self.cuda = onnxChoice == 3
        self.provider = _PROVIDERS.get(onnxChoice)  # None on the OpenVINO path
        self.ov_request = None
        self.shared_stream = False
        self._feed = None

        if onnxChoice == 4:
            # Intel OpenVINO: ov_device picks the Arc iGPU / NPU / CPU. Fastest
            # by far on Meteor Lake (1.3 ms on the iGPU vs 4.3 ms tuned ORT CPU).
            import openvino as ov
            core = ov.Core()
            compiled = core.compile_model(weights, ov_device, {'PERFORMANCE_HINT': 'LATENCY'})
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

        if self.provider == "CUDAExecutionProvider":
            cuda_opts = {
                'device_id': 0,
                # EXHAUSTIVE benchmarks every conv algo on the first frames;
                # HEURISTIC picks immediately and lands within a few percent.
                'cudnn_conv_algo_search': 'HEURISTIC',
            }
            # Run on torch's stream so upload, inference and NMS serialize
            # with no sync in between (onnxruntime >= 1.15).
            shared = dict(cuda_opts,
                          has_user_compute_stream='1',
                          user_compute_stream=str(torch.cuda.current_stream().cuda_stream))
            try:
                self.session = ort.InferenceSession(
                    weights, sess_options=options, providers=[(self.provider, shared)])
                self.shared_stream = True
            except Exception:
                self.session = ort.InferenceSession(
                    weights, sess_options=options, providers=[(self.provider, cuda_opts)])

            self.uploader = CudaUploader()
        else:
            self.session = ort.InferenceSession(
                weights, sess_options=options, providers=[self.provider])

        meta = self.session.get_inputs()[0]
        self.input_name = meta.name
        self.half = meta.type == "tensor(float16)"
        if self.cuda:
            self.uploader.half = self.half
        self.io = self.session.io_binding() if self.cuda else None
        self._out = None
        print("模型的tensor：", meta.type)
        print("模型的shape：", meta.shape)

    def infer(self, frame):
        if self.ov_request is not None:
            out = next(iter(self.ov_request.infer(
                {self.input_name: self._host_feed(frame)}).values()))
            out = torch.from_numpy(out)
        elif self.cuda:
            out = self._bound(self.uploader.upload(frame))
        else:
            out = torch.from_numpy(self.session.run(
                None, {self.input_name: self._host_feed(frame)})[0])
        return nms(out, confidence, iou, max_det=3)

    def _host_feed(self, frame):
        """Preallocated normalized input; frames write into the same array."""
        if self._feed is None or self._feed.shape[2] != frame.shape[0]:
            h, w, _ = frame.shape
            self._feed = np.empty((1, 3, h, w),
                                  np.float16 if self.half else np.float32)
        return frame_to_numpy(frame, self.half, self._feed)

    def _bound(self, im):
        """Feed the persistent CUDA input straight in. Output buffer reused."""
        if self._out is None or self._out.dtype != im.dtype:
            meta = self.session.get_outputs()[0]
            self._out = torch.empty(meta.shape, dtype=im.dtype, device=im.device)
            self.io.bind_output(meta.name, 'cuda', 0, _ort_type(im.dtype),
                                tuple(self._out.shape), self._out.data_ptr())
        self.io.bind_input(self.input_name, 'cuda', 0, _ort_type(im.dtype),
                           tuple(im.shape), im.data_ptr())
        self.session.run_with_iobinding(self.io)
        if not self.shared_stream:
            # ORT ran on its own stream; the NMS below reads its output.
            torch.cuda.current_stream().synchronize()
        return self._out


def _ort_type(dtype):
    # ORT >=1.23 has no ort.TensorType; bind_input/bind_output take dtype strings.
    return 'float16' if dtype == torch.float16 else 'float32'
