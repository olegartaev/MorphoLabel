"""Installation-integrity tests used by CI and support diagnostics."""
from __future__ import annotations

import json
import math
import subprocess
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
    return {
        "status": "PASS",
        "version": __version__,
        "app_state": str(state),
        "runner": str(runner),
        "modules": [item.module_id for item in modules.all()],
        "backends": [item.backend_id for item in backends.all()],
        "dependencies": {
            "Pillow": getattr(PIL, "__version__", "unknown"),
            "NumPy": getattr(numpy, "__version__", "unknown"),
            "OpenCV": getattr(cv2, "__version__", "unknown"),
            "rawpy": getattr(rawpy, "__version__", "unknown"),
        },
    }


def run_ai_self_test(*, require_cuda=False, progress=None):
    """Exercise the same managed runtime/bootstrap path used by the GUI."""
    from PIL import Image

    from .ai_runtime_resolver import validate_ai_runtime
    from .landmark_bootstrap import resolve_landmark_bootstrap

    bootstrap = resolve_landmark_bootstrap(None, progress_callback=progress)
    runner = resource_path("ai_runtime", "rtmpose_runner.py")
    info = validate_ai_runtime(
        bootstrap.runtime_python,
        runner,
        require_cuda=require_cuda,
        timeout=30,
    )
    device = "cuda:0" if info.get("cuda_available") else "cpu"
    if require_cuda and device == "cpu":
        raise RuntimeError("CUDA was required but the managed AI runtime reported no CUDA device")

    state = app_state_dir(create=True)
    with tempfile.TemporaryDirectory(prefix="morpholabel-ai-self-test-", dir=state) as folder:
        image_path = Path(folder) / "probe.png"
        Image.new("RGB", (320, 180), (128, 128, 128)).save(image_path)
        request = {
            "image_id": "ai-self-test",
            "image_path": str(image_path),
            "schema_sha256": "ai-self-test",
            "model_id": "official-ap10k-self-test",
            "config_path": str(bootstrap.config_path),
            "checkpoint_path": str(bootstrap.checkpoint_path),
            "input_size": [256, 256],
            "device": device,
            "simm_landmark_ids": list(range(1, 18)),
        }
        result = subprocess.run(
            [str(bootstrap.runtime_python), str(runner), "predict"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
        if result.returncode:
            raise RuntimeError(
                f"AI prediction self-test failed (return code {result.returncode}): {result.stderr}"
            )
        try:
            prediction = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
        except (ValueError, StopIteration) as exc:
            raise RuntimeError("AI prediction self-test returned invalid JSON") from exc
        landmarks = prediction.get("landmarks") or []
        if len(landmarks) != 17:
            raise RuntimeError(f"AI prediction self-test returned {len(landmarks)} landmarks instead of 17")
        for point in landmarks:
            if not all(math.isfinite(float(point[key])) for key in ("x", "y", "confidence")):
                raise RuntimeError("AI prediction self-test returned non-finite landmark output")

    return {
        "status": "PASS",
        "version": __version__,
        "runtime_python": str(bootstrap.runtime_python),
        "bootstrap_config": str(bootstrap.config_path),
        "bootstrap_checkpoint": str(bootstrap.checkpoint_path),
        "bootstrap_sha256": bootstrap.checksum,
        "device": device,
        "cuda_available": bool(info.get("cuda_available")),
        "cuda_device_name": info.get("device"),
        "cuda_version": info.get("cuda_runtime"),
        "torch": info.get("torch"),
        "torchvision": info.get("torchvision"),
        "mmengine": info.get("mmengine"),
        "mmcv": info.get("mmcv"),
        "mmpose": info.get("mmpose"),
        "numpy": info.get("numpy"),
        "opencv": info.get("opencv"),
        "landmarks": 17,
    }


def print_self_test():
    print(json.dumps(run_self_test(), indent=2, sort_keys=True))


def print_ai_self_test(*, require_cuda=False, progress=None):
    print(json.dumps(
        run_ai_self_test(require_cuda=require_cuda, progress=progress),
        indent=2,
        sort_keys=True,
    ))
