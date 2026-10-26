"""Inference backends. The weight file's suffix picks one; each module is
imported lazily so choosing .engine never loads onnxruntime, and so on."""

_MODULES = {
    '.pt': ('aimbot.backends.torch_backend', 'TorchDetector'),
    '.onnx': ('aimbot.backends.onnx_backend', 'OnnxDetector'),
    '.engine': ('aimbot.backends.tensorrt_backend', 'TensorRTDetector'),
}


def load_detector(weights, mouse):
    """Build the detector matching the weight file's suffix.

    Shared by app-cs2/main.py (live) and app-cs2/detect.py (offline).
    """
    import os
    suffix = os.path.splitext(weights)[1].lower()
    try:
        module_name, class_name = _MODULES[suffix]
    except KeyError:
        raise SystemExit(
            'unsupported weights {}: expected .pt, .onnx or .engine'.format(weights))
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)(weights, mouse)
