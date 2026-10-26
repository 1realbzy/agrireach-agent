"""Offline test startup, including speech subprocesses (PYTHONPATH=tests:src).

Disable optional ONNX diagnostics before loading speech models. This module is
test-only and is not installed with the application.
"""
import os
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["OTEL_SDK_DISABLED"] = "true"
try:
    import onnxruntime
except ImportError:
    pass
else:
    onnxruntime.disable_telemetry_events()
