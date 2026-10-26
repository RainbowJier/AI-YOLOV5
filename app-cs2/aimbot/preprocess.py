"""Frame to model input, without the copies the old backends did per frame.

The capture is already 320x320, so there is no letterbox. The CUDA path
uploads the raw buffer once and does the channel swap, the cast and the
/255 on the device. The CPU path stays in numpy because DirectML and the
CPU provider want a host array.
"""

import numpy as np
import torch

_SCALE = 1.0 / 255.0


def frame_to_cuda(frame, half):
    """HWC uint8 capture -> BCHW float tensor on the current CUDA device."""
    im = torch.from_numpy(frame)
    if im.shape[2] == 4:
        im = im[:, :, :3]
    im = im.permute(2, 0, 1).unsqueeze(0)
    im = im.to('cuda', non_blocking=True)
    return (im.half() if half else im.float()).mul_(_SCALE)


def frame_to_numpy(frame, half):
    """HWC uint8 capture -> BCHW float array, contiguous, for host providers."""
    if frame.shape[2] == 4:
        frame = frame[:, :, :3]
    im = np.empty((1, 3, frame.shape[0], frame.shape[1]),
                  np.float16 if half else np.float32)
    np.multiply(frame, _SCALE, out=im[0].transpose(1, 2, 0), casting='unsafe')
    return im
