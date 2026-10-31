"""Frame to model input, without the copies the old backends did per frame.

The capture is already 320x320, so there is no letterbox. The CUDA path
uploads the raw buffer once and does the channel swap, the cast and the
/255 on the device. The CPU path stays in numpy because DirectML and the
CPU provider want a host array.

CudaUploader is the allocation-free CUDA path: bettercam hands out pageable
arrays, which CUDA can only copy synchronously, so each frame is first
staged into one reused pinned buffer. From there the HtoD is a true async
copy into one reused device buffer, where the cast and the /255 run.
"""

import numpy as np
import torch

_SCALE = 1.0 / 255.0

# Scratch for the host path: multiply into a contiguous HWC float buffer
# first (SIMD-friendly), then transpose-copy into the NCHW array. Writing
# the scaled values straight through the transposed NCHW view touches a
# new cache line per element -- measured 2.5 ms/frame (fp16) vs 1.3/0.3
# for these two passes.
_hwc = None
_hwc_key = None


class CudaUploader:
    """Reused pinned -> device upload for fixed-size frames.

    upload(frame) returns the persistent CUDA input tensor (BCHW, scaled).
    Downstream work must be enqueued on the same stream the copy went to
    (the torch default stream), which keeps every reuse ordered. A CUDA
    event stops the host from rewriting the pinned buffer while the
    previous HtoD is still in flight.
    """

    def __init__(self, half=True):
        self.half = half
        self._pinned = None
        self._hwc = None  # cached HWC view of the pinned buffer
        self._gpu = None
        self._copied = torch.cuda.Event()

    def upload(self, frame):
        if self._gpu is None:
            h, w, _ = frame.shape
            self._pinned = torch.empty((1, 3, h, w), dtype=torch.uint8, pin_memory=True)
            self._hwc = self._pinned[0].permute(1, 2, 0).numpy()
            self._gpu = torch.empty(self._pinned.shape,
                                    dtype=torch.float16 if self.half else torch.float32,
                                    device='cuda')
        self._copied.synchronize()
        # HWC view into the pinned BCHW buffer; numpy writes through strides.
        np.copyto(self._hwc, frame[:, :, :3])
        self._gpu.copy_(self._pinned, non_blocking=True)
        self._copied.record()
        return self._gpu.mul_(_SCALE)


def frame_to_numpy(frame, half, out=None):
    """HWC uint8 capture -> BCHW float array, contiguous, for host providers.

    Pass out= to reuse one preallocated array across frames.
    """
    if frame.shape[2] == 4:
        frame = frame[:, :, :3]
    if out is None:
        out = np.empty((1, 3, frame.shape[0], frame.shape[1]),
                       np.float16 if half else np.float32)
    global _hwc, _hwc_key
    key = (frame.shape[0], frame.shape[1], out.dtype)
    if _hwc_key != key:
        _hwc = np.empty(frame.shape, out.dtype)
        _hwc_key = key
    np.multiply(frame, _SCALE, out=_hwc, casting='unsafe')
    out[0] = _hwc.transpose(2, 0, 1)
    return out
