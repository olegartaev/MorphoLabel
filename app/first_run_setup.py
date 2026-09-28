"""One-time setup contract for installed MorphoLabel builds."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .io import atomic_json_write
from .runtime_paths import app_state_dir, is_frozen
from .version import __version__

SETUP_CONTRACT_VERSION=2
_STATE_FILE="first_run_setup.json"
_STATUS_PASS="PASS"
_STATUS_DEFERRED="DEFERRED"
_STATUS_PENDING="PENDING"

def setup_state_path(): return app_state_dir(create=True)/_STATE_FILE

def read_setup_state():
    path=setup_state_path()
    if not path.is_file():return {}
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,UnicodeDecodeError,json.JSONDecodeError): return {}

def _current_contract(state): return int(state.get("setup_contract_version",0) or 0)==SETUP_CONTRACT_VERSION

def ai_setup_complete():
    state=read_setup_state()
    if state.get("status")!=_STATUS_PASS:return False
    runtime=Path(str(state.get("runtime_python") or ""))
    bootstrap=Path(str(state.get("bootstrap_checkpoint") or ""))
    return runtime.is_file() and bootstrap.is_file()

def ai_setup_deferred():
    state=read_setup_state()
    return _current_contract(state) and state.get("status")==_STATUS_DEFERRED

def ai_download_consent_granted():
    state=read_setup_state()
    return _current_contract(state) and bool(state.get("download_consent"))

def first_run_setup_required():
    if not is_frozen():return False
    return not (ai_setup_complete() or ai_setup_deferred())

def defer_first_run_setup():
    atomic_json_write(setup_state_path(),{
        "setup_contract_version":SETUP_CONTRACT_VERSION,"status":_STATUS_DEFERRED,
        "app_version":__version__,"download_consent":False,
        "deferred_at":datetime.now(timezone.utc).isoformat(),
    })

def _record_download_consent():
    state=read_setup_state()
    state.update({
        "setup_contract_version":SETUP_CONTRACT_VERSION,"status":_STATUS_PENDING,
        "app_version":__version__,"download_consent":True,
        "consent_at":datetime.now(timezone.utc).isoformat(),
    })
    atomic_json_write(setup_state_path(),state)

def _progress(callback,stage,detail):
    if callback:callback(str(stage),str(detail))

def run_first_run_setup(*,progress=None):
    """Install AI support after the user explicitly starts this action."""
    _record_download_consent()
    from .ai_delivery import ensure_ai_runtime
    from .ai_hardware import persist_machine_profile, refresh_hardware_profile
    from .self_test import run_ai_self_test
    from .landmark_bootstrap import resolve_landmark_bootstrap
    _progress(progress,"AI ENGINE","Checking Python 3.11.9 / PyTorch 2.1.0 / MMPose 1.3.2…")
    runtime,_runner=ensure_ai_runtime(progress=progress)
    _progress(progress,"PRETRAINED MODEL","Checking RTMPose-M AP-10K…")
    bootstrap=resolve_landmark_bootstrap(None,progress_callback=progress)
    _progress(progress,"HARDWARE","Checking CPU, GPU and CUDA support…")
    hardware=refresh_hardware_profile();defaults=persist_machine_profile(hardware)
    _progress(progress,"HARDWARE","Hardware check complete.")
    _progress(progress,"AI TEST","Preparing prediction and training checks…")
    ai_test=run_ai_self_test(require_cuda=False,include_training=True,progress=progress,bootstrap=bootstrap)
    training=ai_test.get("training_smoke") or {}
    if ai_test.get("status")!="PASS" or int(ai_test.get("landmarks") or 0)<=0: raise RuntimeError("AI inference qualification did not pass")
    if training.get("status")!="trained": raise RuntimeError("AI training qualification did not produce a checkpoint")
    payload={
        "setup_contract_version":SETUP_CONTRACT_VERSION,"status":_STATUS_PASS,"app_version":__version__,
        "download_consent":True,"completed_at":datetime.now(timezone.utc).isoformat(),
        "runtime_python":str(runtime),"bootstrap_checkpoint":str(ai_test.get("bootstrap_checkpoint") or ""),
        "hardware":hardware.as_dict(),
        "recommended_defaults":{"inference":defaults.get("inference_default"),"training":defaults.get("training_default")},
        "ai_self_test":{"status":ai_test.get("status"),"device":ai_test.get("device"),"cuda_available":bool(ai_test.get("cuda_available")),
                        "cuda_device_name":ai_test.get("cuda_device_name"),"landmarks":ai_test.get("landmarks"),
                        "training_smoke":training,"bootstrap_sha256":ai_test.get("bootstrap_sha256")},
        "optimization_note":"Safe machine defaults are stored now; workload-specific batch/worker tuning is measured later on real project images.",
    }
    atomic_json_write(setup_state_path(),payload);_progress(progress,"READY","First-time AI setup completed.");return payload
