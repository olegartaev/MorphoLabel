"""One-time setup contract for installed MorphoLabel builds."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .io import atomic_json_write
from .runtime_paths import app_state_dir, is_frozen
from .version import __version__

SETUP_CONTRACT_VERSION=1
_STATE_FILE="first_run_setup.json"


def setup_state_path():
    return app_state_dir(create=True)/_STATE_FILE


def read_setup_state():
    path=setup_state_path()
    if not path.is_file():return {}
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,UnicodeDecodeError,json.JSONDecodeError):
        return {}


def first_run_setup_required():
    """Only public frozen installs perform automatic first-run setup."""
    if not is_frozen():return False
    state=read_setup_state()
    if state.get("status")!="PASS" or int(state.get("setup_contract_version",0) or 0)!=SETUP_CONTRACT_VERSION:
        return True
    runtime=Path(str(state.get("runtime_python") or ""))
    bootstrap=Path(str(state.get("bootstrap_checkpoint") or ""))
    return not runtime.is_file() or not bootstrap.is_file()


def _progress(callback,stage,detail):
    if callback:callback(str(stage),str(detail))


def run_first_run_setup(*,progress=None):
    """Prepare the complete optional AI stack and qualify this machine.

    The expensive work is GUI-independent so callers can always run it on a
    worker thread. Real workload auto-tuning remains project-specific.
    """
    from .ai_delivery import ensure_ai_runtime
    from .ai_hardware import persist_machine_profile, refresh_hardware_profile
    from .self_test import run_ai_self_test

    _progress(progress,"AI COMPONENT","Checking the managed AI runtime…")
    runtime,_runner=ensure_ai_runtime(progress=progress)

    _progress(progress,"HARDWARE","Detecting CPU, RAM, GPU, VRAM and CUDA…")
    hardware=refresh_hardware_profile()
    defaults=persist_machine_profile(hardware)

    _progress(progress,"AI CHECK","Running a real prediction and short training test…")
    ai_test=run_ai_self_test(require_cuda=False,include_training=True,progress=progress)
    training=ai_test.get("training_smoke") or {}
    if ai_test.get("status")!="PASS" or int(ai_test.get("landmarks") or 0)<=0:
        raise RuntimeError("AI inference qualification did not pass")
    if training.get("status")!="trained":
        raise RuntimeError("AI training qualification did not produce a checkpoint")

    payload={
        "setup_contract_version":SETUP_CONTRACT_VERSION,
        "status":"PASS",
        "app_version":__version__,
        "completed_at":datetime.now(timezone.utc).isoformat(),
        "runtime_python":str(runtime),
        "bootstrap_checkpoint":str(ai_test.get("bootstrap_checkpoint") or ""),
        "hardware":hardware.as_dict(),
        "recommended_defaults":{
            "inference":defaults.get("inference_default"),
            "training":defaults.get("training_default"),
        },
        "ai_self_test":{
            "status":ai_test.get("status"),
            "device":ai_test.get("device"),
            "cuda_available":bool(ai_test.get("cuda_available")),
            "cuda_device_name":ai_test.get("cuda_device_name"),
            "landmarks":ai_test.get("landmarks"),
            "training_smoke":training,
            "bootstrap_sha256":ai_test.get("bootstrap_sha256"),
        },
        "optimization_note":"Safe machine defaults are stored now; workload-specific batch/worker tuning is measured later on real project images.",
    }
    atomic_json_write(setup_state_path(),payload)
    _progress(progress,"READY","First-time setup completed.")
    return payload
