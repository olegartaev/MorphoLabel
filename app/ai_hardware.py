"""Read-only, dependency-free AI hardware discovery and recommendations.

Core MorphoLabel never imports an ML framework here.  CUDA availability is queried
only through the existing isolated AI runtime when it is present.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from .ai_runtime_resolver import AI_RUNTIME_INFO_TIMEOUT, resolve_ai_runtime
from .io import atomic_json_write
from .runtime_paths import app_state_dir, resource_path
from .process_utils import hidden_window_kwargs


AUTO = "auto"
MAXIMUM_SPEED = "maximum_speed"
LOW_RESOURCE = "low_resource"


@dataclass(frozen=True)
class HardwareProfile:
    cpu_model: str
    physical_cores: int | None
    logical_cores: int
    ram_bytes: int | None
    gpu_model: str | None
    gpu_vram_mib: int | None
    gpu_driver: str | None
    cuda_available: bool
    cuda_runtime: str | None
    acceleration: str
    gpu_free_mib: int | None = None

    def as_dict(self):
        return asdict(self)


def _run(command, *, input_text=None, timeout=8):
    working_dir = str(Path(command[0]).resolve().parent) if len(command)>2 and command[2]=="info" else None
    return subprocess.run(command, cwd=working_dir, input=input_text, text=True, capture_output=True, check=False, timeout=timeout, **hidden_window_kwargs())


def _ram_bytes():
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        value = MEMORYSTATUSEX(); value.dwLength = ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return int(value.ullTotalPhys)
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _physical_cores(logical, command_runner):
    if os.name == "nt":
        # Modern Windows may not provide WMIC. Count processor-core
        # relationships directly so hybrid P/E-core CPUs are detected correctly.
        try:
            size = ctypes.c_ulong(0)
            kernel = ctypes.windll.kernel32
            kernel.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
            if size.value:
                buffer = ctypes.create_string_buffer(size.value)
                if kernel.GetLogicalProcessorInformationEx(0, buffer, ctypes.byref(size)):
                    offset = count = 0
                    while offset + 8 <= size.value:
                        relationship = int.from_bytes(buffer.raw[offset:offset + 4], "little")
                        entry_size = int.from_bytes(buffer.raw[offset + 4:offset + 8], "little")
                        if entry_size < 8 or offset + entry_size > size.value:
                            break
                        count += relationship == 0
                        offset += entry_size
                    if count:
                        return count
        except (AttributeError, OSError, ValueError):
            pass
        try:
            output = command_runner(["wmic", "cpu", "get", "NumberOfCores", "/value"]).stdout
            values = [int(line.split("=", 1)[1]) for line in output.splitlines() if line.startswith("NumberOfCores=")]
            if values:
                return sum(values)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return logical


def _nvidia_gpu(command_runner):
    try:
        result = command_runner(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"])
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0 or not getattr(result, "stdout", "").strip():
        return None
    first = result.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 2:
        return None
    try:
        vram = int(float(parts[1]))
    except ValueError:
        vram = None
    try:
        free = int(float(parts[2]))
    except (ValueError, IndexError):
        free = None
    return {"model": parts[0] or None, "vram_mib": vram, "free_mib": free, "driver": parts[3] if len(parts) > 3 else None}


def _runtime_cuda_info(command_runner, runtime_python, runner_path):
    if not runtime_python.is_file() or not runner_path.is_file():
        return {}
    try:
        result = command_runner([str(runtime_python), str(runner_path), "info"], input_text="{}", timeout=AI_RUNTIME_INFO_TIMEOUT)
        if result.returncode:
            return {}
        import json
        return json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        return {}


def detect_hardware(*, command_runner=_run, runtime_python=None, runner_path=None):
    """Return a best-effort profile; unavailable hardware is reported as None."""
    runtime_python, runner_path = resolve_ai_runtime(explicit=runtime_python, runner_path=runner_path)
    logical = max(1, int(os.cpu_count() or 1))
    gpu = _nvidia_gpu(command_runner)
    runtime = _runtime_cuda_info(command_runner, runtime_python, runner_path)
    cuda = bool(runtime.get("cuda_available", False))
    if runtime.get("device") and gpu is None:
        gpu = {"model": runtime.get("device"), "vram_mib": None, "driver": None}
    return HardwareProfile(
        cpu_model=platform.processor() or platform.machine() or "Unknown",
        physical_cores=_physical_cores(logical, command_runner), logical_cores=logical,
        ram_bytes=_ram_bytes(), gpu_model=(gpu or {}).get("model"), gpu_vram_mib=(gpu or {}).get("vram_mib"),
        gpu_driver=(gpu or {}).get("driver"), cuda_available=cuda,
        cuda_runtime=runtime.get("cuda_runtime"), acceleration="CUDA" if cuda else "CPU", gpu_free_mib=(gpu or {}).get("free_mib"),
    )


def _normalise_profile(profile):
    value = str(profile or AUTO).lower().replace(" ", "_")
    if value not in {AUTO, MAXIMUM_SPEED, LOW_RESOURCE}:
        raise ValueError(f"unknown AI performance profile: {profile}")
    return value


def _recommended(profile, mode):
    profile = _normalise_profile(profile)
    use_cuda = profile != LOW_RESOURCE and mode.cuda_available
    if profile == LOW_RESOURCE:
        return {"device": "cpu", "batch_size": 1, "workers": 0, "mixed_precision": False, "pin_memory": False, "persistent_workers": False, "profile": profile}
    physical=max(1,int(mode.physical_cores or mode.logical_cores or 1))
    logical=max(1,int(mode.logical_cores or physical))
    if use_cuda:
        vram = mode.gpu_vram_mib or 0
        batch = 16 if vram >= 20_000 else 8 if vram >= 10_000 else 4 if vram >= 6_000 else 2
        if profile == MAXIMUM_SPEED:
            batch = max(batch, 8)
        # This is only the first safe guess. Workload tuning measures the real
        # optimum and may use more or fewer workers on this exact machine.
        workers=min(max(1,physical//2),8 if profile==AUTO else physical)
        return {"device": "cuda:0", "batch_size": batch, "workers": workers, "mixed_precision": True, "pin_memory": True, "persistent_workers": bool(workers), "profile": profile}
    # CPU inference/training already uses PyTorch intra-op threads. Too many
    # loader processes oversubscribe the same cores, so keep only a small I/O
    # overlap pool instead of blindly matching logical CPU count.
    workers=min(4,max(0,physical//4))
    return {"device": "cpu", "batch_size": 1, "workers": workers, "mixed_precision": False, "pin_memory": False, "persistent_workers": bool(workers), "profile": profile}


def compact_worker_candidates(hardware=None, *, include_zero=True):
    """A small measured set spanning weak laptops through many-core workstations."""
    mode=hardware or get_hardware_profile()
    physical=max(1,int(mode.physical_cores or mode.logical_cores or 1))
    logical=max(1,int(mode.logical_cores or physical))
    values=[0] if include_zero else []
    for value in (1,2,4,8,max(1,physical//2),physical,logical):
        if value<=logical and value not in values:values.append(value)
    return tuple(values)


def cuda_batch_candidates(hardware=None, *, maximum=64, minimum=1):
    """Power-of-two CUDA candidates up to a bounded real-workload ceiling."""
    mode=hardware or get_hardware_profile()
    if not mode.cuda_available:return (1,)
    maximum=max(int(minimum),int(maximum));values=[];value=max(1,int(minimum))
    # Start at one so OOM/throughput comparisons always have a safe reference.
    value=1
    while value<=maximum:
        values.append(value);value*=2
    if values[-1]!=maximum and maximum>values[-1]:values.append(maximum)
    return tuple(dict.fromkeys(values))


_HARDWARE_PROFILE = None
_MACHINE_PROFILE_FILENAME = "hardware_profile.json"


def machine_profile_path():
    return app_state_dir()/_MACHINE_PROFILE_FILENAME


def _hardware_profile_from_mapping(value):
    if not isinstance(value, dict):
        return None
    try:
        return HardwareProfile(
            cpu_model=str(value.get("cpu_model") or "Unknown"),
            physical_cores=None if value.get("physical_cores") is None else int(value.get("physical_cores")),
            logical_cores=max(1,int(value.get("logical_cores") or 1)),
            ram_bytes=None if value.get("ram_bytes") is None else int(value.get("ram_bytes")),
            gpu_model=value.get("gpu_model"),
            gpu_vram_mib=None if value.get("gpu_vram_mib") is None else int(value.get("gpu_vram_mib")),
            gpu_driver=value.get("gpu_driver"),
            cuda_available=bool(value.get("cuda_available")),
            cuda_runtime=value.get("cuda_runtime"),
            acceleration=str(value.get("acceleration") or ("CUDA" if value.get("cuda_available") else "CPU")),
            gpu_free_mib=None if value.get("gpu_free_mib") is None else int(value.get("gpu_free_mib")),
        )
    except (TypeError,ValueError):
        return None


def _read_state_json(path):
    try:
        value=json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,UnicodeDecodeError,json.JSONDecodeError):
        return {}


def persisted_hardware_profile():
    """Return the setup-qualified machine profile without probing hardware again."""
    # A successful first-run qualification is stronger than the legacy warm-cache
    # file: older builds could overwrite hardware_profile.json after a transient
    # runtime probe reported CUDA unavailable.
    setup=_read_state_json(app_state_dir()/"first_run_setup.json")
    if setup.get("status")=="PASS":
        profile=_hardware_profile_from_mapping(setup.get("hardware"))
        if profile is not None:return profile
    saved=_read_state_json(machine_profile_path())
    return _hardware_profile_from_mapping(saved.get("hardware"))


def persist_machine_profile(hardware=None):
    """Persist first-launch hardware discovery for diagnostics, never as scientific state."""
    hardware=hardware or get_hardware_profile()
    payload={
        "hardware":hardware.as_dict(),
        "training_default":get_training_config(hardware=hardware),
        "inference_default":get_inference_config(hardware=hardware),
    }
    try:atomic_json_write(machine_profile_path(),payload)
    except OSError as exc:logging.getLogger(__name__).warning("MorphoLabel hardware-profile write failed: %s",exc)
    return payload





def get_hardware_profile(*, refresh=False):
    """Use setup-qualified hardware by default; probe only when explicitly requested or absent."""
    global _HARDWARE_PROFILE
    if refresh:
        _HARDWARE_PROFILE=detect_hardware()
    elif _HARDWARE_PROFILE is None:
        _HARDWARE_PROFILE=persisted_hardware_profile() or detect_hardware()
    return _HARDWARE_PROFILE


def refresh_hardware_profile():
    """Explicit diagnostics path for a fresh hardware discovery."""
    return get_hardware_profile(refresh=True)

def get_training_config(profile=AUTO, hardware=None):
    return _recommended(profile, hardware or get_hardware_profile())


def get_inference_config(profile=AUTO, hardware=None):
    config = _recommended(profile, hardware or get_hardware_profile()).copy()
    config["batch_size"] = 1 if config["device"] == "cpu" else config["batch_size"]
    return config


def run_metadata(operation, *, profile=AUTO, hardware=None):
    """JSON-safe reproducibility record for any current or future AI run."""
    hardware = hardware or get_hardware_profile()
    config = get_training_config(profile, hardware) if operation == "training" else get_inference_config(profile, hardware)
    return {"operation": operation, "hardware": hardware.as_dict(), "selected": config}


def format_hardware_profile(hardware=None):
    hardware = hardware or get_hardware_profile()
    ram = "Unknown" if hardware.ram_bytes is None else f"{hardware.ram_bytes / 1024**3:.1f} GB"
    gpu = hardware.gpu_model or "None"
    vram = "Unknown" if hardware.gpu_vram_mib is None else f"{hardware.gpu_vram_mib / 1024:.1f} GB"
    return "\n".join(("Hardware detected:", f"CPU: {hardware.cpu_model}", f"RAM: {ram}", f"GPU: {gpu}", f"VRAM: {vram}", f"Acceleration: {hardware.acceleration}", "", "Current AI mode: Auto"))


def performance_cache_key(hardware, *, workload, model, input_size, tuning_variant="ai_auto_v2"):
    """Compatibility key delegated to the shared Performance Engine."""
    from .performance_engine import workload_tuning_key
    return workload_tuning_key(workload=workload, model=model, input_size=input_size, hardware=hardware, variant=tuning_variant)

def _performance_cache_path(project):
    from .performance_engine import PerformanceCache
    return PerformanceCache(project).path

def _load_performance_cache(project):
    from .performance_engine import PerformanceCache
    return PerformanceCache(project).read()

def _save_performance_cache(project, cache):
    from .performance_engine import PerformanceCache
    # The machine AUTO cache is an optimization, never scientific state.
    path = PerformanceCache(project).path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, cache)
    except OSError as exc:
        logging.getLogger(__name__).warning("MorphoLabel performance-cache write failed for %s: %s", path, exc)

_AUTOTUNE_DIAGNOSTIC_FILENAME = "autotune_latest.json"


def autotune_diagnostic_path():
    return app_state_dir()/"diagnostics"/"runtime"/_AUTOTUNE_DIAGNOSTIC_FILENAME


def _source_identity(path):
    try:
        path=Path(path).resolve()
        return {"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    except Exception as exc:
        return {"path":str(path),"error":f"{type(exc).__name__}: {exc}"}


def _write_autotune_diagnostic(payload):
    """Write the exact latest AUTO decision path for field diagnostics."""
    try:
        import app.performance_engine as performance_engine
        data={
            "timestamp_utc":datetime.now(timezone.utc).isoformat(),
            "pid":os.getpid(),
            "python_executable":sys.executable,
            "cwd":os.getcwd(),
            "localappdata":os.environ.get("LOCALAPPDATA"),
            "userprofile":os.environ.get("USERPROFILE"),
            "code":{
                "ai_hardware":_source_identity(__file__),
                "performance_engine":_source_identity(performance_engine.__file__),
                "landmark_training_workflow":_source_identity(Path(__file__).with_name("landmark_training_workflow.py")),
                "landmark_ai_service":_source_identity(Path(__file__).with_name("landmark_ai_service.py")),
                "rtmpose_runner":_source_identity(resource_path("ai_runtime","rtmpose_runner.py")),
            },
            **dict(payload),
        }
        # Keep diagnostics in the checkout and retain each workload's latest
        # decision independently of the shared latest event.
        targets=[autotune_diagnostic_path()]
        workload=str(data.get("workload") or "").strip().lower()
        if workload:
            targets.append(autotune_diagnostic_path().with_name(f"autotune_latest_{workload}.json"))
        for target in dict.fromkeys(targets):
            try:
                atomic_json_write(Path(target),data)
            except OSError as exc:
                logging.getLogger(__name__).warning("MorphoLabel autotune diagnostic write failed for %s: %s",target,exc)
    except Exception as exc:
        logging.getLogger(__name__).warning("MorphoLabel autotune diagnostic write failed: %s",exc)


def is_cuda_oom(error):
    text = str(error).lower()
    return "out of memory" in text or "cuda oom" in text or "cublas_status_alloc_failed" in text

def auto_performance_config(project, *, workload, model, input_size, training=False, hardware=None, probe=None, probe_configurations=False, tuning_variant=None, candidate_configurations=None, staged_worker_candidates=None, probe_many=None):
    """Compatibility AUTO wrapper backed by ``performance_engine`` only.

    Workload probes retain their existing batch-only callback contract.  They
    are measured through the shared cache, while callers without a safe probe
    receive the established conservative heuristic.
    """
    from .performance_engine import PerformanceCache, tune_workload, tune_batch_worker_workload, workload_tuning_key
    started = time.perf_counter()
    hardware = hardware or get_hardware_profile()
    base = get_training_config(hardware=hardware) if training else get_inference_config(hardware=hardware)
    variant = tuning_variant or ("landmark_training_real_v4" if workload == "landmark_training" and training else "ai_auto_v2")
    key = workload_tuning_key(workload=workload, model=model, input_size=input_size, hardware=hardware, variant=variant)
    cache = PerformanceCache(project)
    cached_before = cache.get(key)
    diagnostic_base={
        "stage":"enter",
        "workload":workload,
        "training":bool(training),
        "model":model,
        "input_size":list(input_size) if input_size is not None else None,
        "variant":variant,
        "tuning_key":key,
        "cache_path":str(cache.path),
        "cache_entry_before":cached_before,
        "hardware":hardware.as_dict(),
        "base_config":base,
        "probe_present":probe is not None,
        "probe_many_present":probe_many is not None,
        "probe_configurations":bool(probe_configurations),
        "candidate_configurations":candidate_configurations,
        "staged_worker_candidates":list(staged_worker_candidates) if staged_worker_candidates is not None else None,
    }
    _write_autotune_diagnostic(diagnostic_base)
    if not hardware.cuda_available or probe is None:
        chosen = cached_before.get("chosen") if isinstance(cached_before, dict) else None
        if isinstance(cached_before, dict) and cached_before.get("probes_succeeded") and isinstance(chosen, dict) and chosen.get("batch_size") is not None:
            result={**base, **chosen, "batch_size": max(1, int(chosen["batch_size"])), "tuning_source": "cache", "tuning_key": key,"cache_saved":True}
        else:
            result={**base, "tuning_source": "heuristic", "tuning_key": key,"cache_saved":False}
        _write_autotune_diagnostic({**diagnostic_base,"stage":"complete","return_path":"no_cuda_or_no_probe","cache_hit":result["tuning_source"]=="cache","calibration_elapsed_seconds":cached_before.get("calibration_elapsed_seconds") if result["tuning_source"]=="cache" and isinstance(cached_before,dict) else None,"lookup_elapsed_seconds":time.perf_counter()-started,"returned":result})
        return result
    # The configuration-aware training probe can safely search the full
    # bounded CUDA range. Legacy batch-only probes retain their heuristic cap.
    ceiling=32 if (hardware.cuda_available and probe_configurations) else max(1,int(base["batch_size"]))
    batches=[batch for batch in (1,2,4,8,16,32) if batch<=ceiling]
    if probe_configurations:
        if candidate_configurations is not None:
            candidates = [{**base, **dict(config), "batch_size": max(1, int(config["batch_size"])), "workers": max(0, int(config.get("workers", 0))), "persistent_workers": bool(config.get("workers", 0)), "pin_memory": bool(str(config.get("device", base.get("device", ""))).startswith("cuda"))} for config in candidate_configurations]
        else:
            from .performance_engine import cpu_worker_candidates
            worker_values = (0, *cpu_worker_candidates(hardware))
            candidates = [{**base, "batch_size": batch, "workers": workers, "persistent_workers": bool(workers), "pin_memory": bool(str(base.get("device", "")).startswith("cuda"))} for batch in batches for workers in worker_values]
    else:
        candidates = [{"batch_size": batch} for batch in batches]
    # Tune against installed VRAM, not a momentary free-memory snapshot from
    # application startup. Current contention is handled by the measured OOM
    # fallback; otherwise a transient GPU user could permanently under-tune MorphoLabel.
    budget=int((hardware.gpu_vram_mib or hardware.gpu_free_mib or 0)*.90)
    def measured(config):
        value=probe(config if probe_configurations else int(config["batch_size"]))
        result=dict(value) if isinstance(value,dict) else {}
        # New configuration-aware training probes must report the canonical
        # measured metric. Batch number is only a legacy capacity fallback.
        if not probe_configurations:
            result.setdefault("items_per_sec",float(config["batch_size"]))
        elif "items_per_sec" not in result:
            raise ValueError("configuration-aware AUTO probe did not report items_per_sec")
        return result
    def equivalent(_config,result):
        return bool(result.get("scientifically_equivalent",True)) and not (budget and result.get("peak_vram_mib",0)>budget)
    fallback={"batch_size":1}
    _write_autotune_diagnostic({**diagnostic_base,"stage":"candidates","expanded_candidates":candidates,"vram_budget_mib":budget})
    if probe_configurations and staged_worker_candidates is not None:
        grouped = (lambda configs: probe_many(configs)) if probe_many is not None else None
        tuned=tune_batch_worker_workload(project,workload=workload,model=model,input_size=input_size,variant=variant,hardware=hardware,batch_candidates=candidates,worker_candidates=staged_worker_candidates,probe=measured,safe_fallback=fallback,equivalence_guard=equivalent,probe_many=grouped)
    else:
        tuned=tune_workload(project,workload=workload,model=model,input_size=input_size,variant=variant,hardware=hardware,candidates=candidates,probe=measured,safe_fallback=fallback,equivalence_guard=equivalent)
    chosen=tuned.get("chosen") or fallback
    errors=[row.get("error") for row in tuned.get("results",()) if row.get("error")]
    source="cache" if tuned.get("cache_hit") else "probe" if tuned.get("probes_succeeded") else "fallback"
    result={**base,**chosen,"batch_size":int(chosen["batch_size"]),"tuning_source":source,"tuning_key":tuned["tuning_key"],"tuning_errors":errors[:3],"cache_saved":tuned.get("cache_saved")}
    _write_autotune_diagnostic({**diagnostic_base,"stage":"complete","expanded_candidates":candidates,"vram_budget_mib":budget,"tuned":tuned,"calibration_elapsed_seconds":tuned.get("calibration_elapsed_seconds"),"lookup_elapsed_seconds":time.perf_counter()-started if tuned.get("cache_hit") else None,"returned":result})
    return result

def record_inference_batch(project, *, workload, model, input_size, batch_size, hardware=None, validated=False, configuration=None, tuning_variant="ai_auto_v2", benchmark_rows=None, calibration_elapsed_seconds=None, attempted_batch=None):
    """Cache only measured, equivalent inference candidates and mark runtime fallback."""
    hardware=hardware or get_hardware_profile()
    base=get_inference_config(hardware=hardware)
    from .performance_engine import PerformanceCache, ENGINE_VERSION, hardware_fingerprint
    key=performance_cache_key(hardware,workload=workload,model=model,input_size=input_size,tuning_variant=tuning_variant)
    cache=PerformanceCache(project)
    if not validated:
        saved=False
        if attempted_batch is not None and int(batch_size)<int(attempted_batch):
            saved=cache.record_runtime_fallback(key,attempted_batch,batch_size)
            _write_autotune_diagnostic({"stage":"runtime_fallback","workload":workload,"model":model,"input_size":list(input_size),"variant":tuning_variant,"tuning_key":key,"cache_path":str(cache.path),"hardware":hardware.as_dict(),"attempted_batch_size":int(attempted_batch),"effective_batch_size":int(batch_size),"cache_saved":saved,"cache_entry":cache.get(key)})
        return {**base,"batch_size":max(1,int(batch_size)),"tuning_source":"runtime","tuning_key":key,"cache_saved":saved}
    results=[]
    for row in benchmark_rows or ():
        config={"batch_size":max(1,int(row.get("batch_size",1))),"prefetch_workers":row.get("prefetch_workers"),"prefetch_depth":row.get("prefetch_depth")}
        try:
            rate=float(row.get("images_per_second",0))
            equivalent=bool(row.get("scientifically_equivalent",True))
            valid=not row.get("error") and equivalent and int(row.get("effective_batch_size",config["batch_size"]))==config["batch_size"] and math.isfinite(rate) and rate>0
        except (TypeError,ValueError):
            rate=0.0;equivalent=False;valid=False
        results.append({"config":config,"valid":bool(valid),"equivalent":equivalent,"throughput":rate,"items_per_sec":rate,"elapsed_seconds":row.get("rank_seconds"),"peak_vram_mib":row.get("peak_vram_mib"),"error":row.get("error"),"measurement":dict(row)})
    valid_rows=[row for row in results if row["valid"]]
    chosen=max(valid_rows,key=lambda row:row["throughput"])["config"] if valid_rows else None
    tuned={"chosen":chosen,"metric":"items_per_sec","results":results,"probes_succeeded":bool(valid_rows),"cache_hit":False,"tuning_key":key,"engine_version":ENGINE_VERSION,"hardware_fingerprint":hardware_fingerprint(hardware),"calibration_elapsed_seconds":calibration_elapsed_seconds}
    tuned["cache_saved"]=cache.put(key,tuned) if valid_rows else False
    result={**base,**(chosen or {}),"batch_size":int(chosen["batch_size"] if chosen else 1),"tuning_source":"measured" if chosen else "fallback","tuning_key":key,"cache_saved":tuned["cache_saved"]}
    _write_autotune_diagnostic({"stage":"complete","workload":workload,"model":model,"input_size":list(input_size),"variant":tuning_variant,"tuning_key":key,"cache_path":str(cache.path),"hardware":hardware.as_dict(),"expanded_candidates":[row["config"] for row in results],"tuned":tuned,"calibration_elapsed_seconds":calibration_elapsed_seconds,"returned":result})
    return result
