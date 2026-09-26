"""Small installation-integrity test used by CI and support diagnostics."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from .extensions.builtins import backend_registry, module_registry
from .runtime_paths import app_state_dir, resource_path
from .version import __version__
def run_self_test():
    import cv2
    import numpy
    import PIL
    import rawpy
    state = app_state_dir(create=True)
    with tempfile.NamedTemporaryFile(prefix="morpholabel-self-test-", suffix=".tmp", dir=state, delete=False) as handle:
        probe = Path(handle.name)
        handle.write(b"ok")
    probe.unlink(missing_ok=True)
    runner = resource_path("ai_runtime", "rtmpose_runner.py")
    if not runner.is_file():
        raise RuntimeError(f"packaged AI runner resource is missing: {runner}")
    modules = module_registry()
    backends = backend_registry()
    if not modules.get("landmarks"):
        raise RuntimeError("built-in landmarks module is unavailable")
    if not backends.get("rtmpose"):
        raise RuntimeError("built-in RTMPose backend is unavailable")
    return {"status":"PASS","version":__version__,"app_state":str(state),"runner":str(runner),
            "modules":[item.module_id for item in modules.all()],"backends":[item.backend_id for item in backends.all()],
            "dependencies":{"Pillow":getattr(PIL,"__version__","unknown"),"NumPy":getattr(numpy,"__version__","unknown"),
                            "OpenCV":getattr(cv2,"__version__","unknown"),"rawpy":getattr(rawpy,"__version__","unknown")}}
def print_self_test():
    print(json.dumps(run_self_test(), indent=2, sort_keys=True))
