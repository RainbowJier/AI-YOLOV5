"""Shared runtime for the three entry points.

main.py / main_onnx.py / main_tensorrt.py used to duplicate the whole
pipeline. Everything they have in common now lives here:

- driver   : Logitech GHUB/LGS relative mouse driver
- capture  : window selection + bettercam region capture
- targeting: detection filtering, target selection, mouse movement
- loop     : the per-frame loop (capture -> infer -> aim -> stats)

Each entry point only supplies a Detector implementation.
"""
