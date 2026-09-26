"""Thin GUI-independent coordinator over the existing immutable RTMPose pipeline."""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

from .ai_batch import active_backend, backend_for_model, BatchError
from .landmark_bootstrap import resolve_landmark_bootstrap
from .ai_hardware import auto_performance_config, get_hardware_profile, get_training_config, compact_worker_candidates, cuda_batch_candidates
from .landmark_dataset import create_dataset, deterministic_splits, v2_human_final_eligible_image_ids
from .rtmpose_dataset import export_coco, generate_smoke_config
from .io import atomic_json_write
from .landmark_frames import restore_standardized_frame
from .project_storage import schema_hash, landmark_model_schema_compatible
from .rtmpose_backend import RTMPoseBackend, RTMPoseModelSpec, train_project, pending_finalization_artifact, _finalize_trained_artifact
from .landmark_preparation import prepare_training_snapshot, snapshot_path


class LandmarkTrainingPreparationError(ValueError):
    pass


@dataclass(frozen=True)
class LandmarkTrainingPlan:
    model_id: str
    dataset_id: str
    parent_model_id: str | None
    image_ids: tuple[str, ...]
    splits: dict
    seed: int
    training_settings: dict


def _next_model_id(project):
    with project.transaction() as connection:
        identifiers = [row[0] for row in connection.execute("SELECT model_id FROM models WHERE kind='landmark'")]
    versions = [int(match.group(1)) for value in identifiers if (match := re.fullmatch(r"rtmpose_v(\d+)", str(value)))]
    artifacts = Path(project.data_root) / "ai" / "models"
    if artifacts.is_dir():
        versions.extend(int(match.group(1)) for path in artifacts.iterdir() if path.is_dir() and (match := re.fullmatch(r"rtmpose_v(\d+)", path.name)))
    return f"rtmpose_v{max(versions, default=0) + 1:03d}"


def _verify_first_model_bootstrap(plan):
    if plan.parent_model_id is not None:
        return
    info = plan.training_settings.get("bootstrap") or {}
    config_path = Path(info.get("config_path") or "")
    checkpoint_path = Path(info.get("checkpoint_path") or "")
    expected_checksum = str(info.get("checksum") or "")
    if not config_path.is_file() or not checkpoint_path.is_file() or not expected_checksum:
        raise LandmarkTrainingPreparationError("first-model bootstrap assets are unavailable after confirmation")
    actual_checksum = __import__("hashlib").sha256(checkpoint_path.read_bytes()).hexdigest()
    if actual_checksum != expected_checksum:
        raise LandmarkTrainingPreparationError("first-model bootstrap checkpoint changed after confirmation")

def _prepare_training_probe_assets(project, image_ids, splits, backend, *, seed, prepared_snapshot=None):
    """Create a disposable, current-data MMPose probe under the AI cache."""
    import hashlib
    schema = tuple(dict(row) for row in project.schema)
    digest = schema_hash(project.schema_path)
    identity = hashlib.sha256((digest + ":" + ",".join(sorted(map(str, image_ids))) + ":" + str(seed)).encode("utf-8")).hexdigest()[:20]
    root = project.data_root / "ai" / "cache" / "training_probe" / identity
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    images = []
    split_by_id = {str(image_id): name for name, values in splits.items() for image_id in values}
    # Preflight already made this exact current-state snapshot.  Probe export
    # only adapts it to COCO; it must not repeat image restoration, hash reads
    # or landmark/database reads.
    prepared = prepared_snapshot if isinstance(prepared_snapshot, dict) else prepare_training_snapshot(project, image_ids, reuse=prepared_snapshot)
    for image_id in image_ids:
        entry = prepared["entries"][str(image_id)]
        images.append({"image_id": str(image_id), "split": split_by_id[str(image_id)], "standardized_relpath": entry["standardized_relpath"], "standardized_width": entry["standardized_width"], "standardized_height": entry["standardized_height"], "landmarks": entry["labels"]})
    manifest = {"format_version": 1, "dataset_id": f"training_probe_{identity}", "schema_sha256": digest, "schema_landmarks": [{"landmark_id": int(row["id"]), "abbr": row["abbr"]} for row in schema], "images": images}
    atomic_json_write(manifest_path, manifest)
    train_coco = root / "train.coco.json"
    val_coco = root / "val.coco.json"
    export_coco(manifest_path, train_coco, splits=("train",))
    export_coco(manifest_path, val_coco, splits=("validation",))
    return {"root": root, "manifest": manifest_path, "train_coco": train_coco, "val_coco": val_coco}
def available_training_parents(project):
 """Compatible registered landmark artifacts usable as an explicit training parent."""
 models=[]
 with project.transaction() as connection: rows=connection.execute("SELECT * FROM models WHERE kind='landmark' ORDER BY model_id").fetchall()
 for row in rows:
  model=dict(row)
  if not landmark_model_schema_compatible(project,model):continue
  try:model,_backend=backend_for_model(project,str(model["model_id"]),model=model)
  except Exception:continue
  models.append(model)
 return tuple(models)

def _architecture_tuning_identity(backend, landmark_count):
 """Stable tuning identity: architecture, not immutable checkpoint version."""
 import hashlib
 config=Path(backend.spec.config_path)
 try:
  # Generated SIMM configs deliberately differ in dataset paths, epochs and
  # checkpoint references.  Those are not model architecture.  Fingerprint
  # only structural MMPose declarations, while input size/runtime/hardware
  # remain separate cache-key fields.
  import re
  text=config.read_text(encoding="utf-8")
  fields=re.findall(r"(?:type|arch|deepen_factor|widen_factor|in_channels|out_channels|simcc_split_ratio)\s*=\s*([^,\n]+)",text)
  config_digest=hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()[:16]
 except OSError: config_digest=config.name
 return f"rtmpose_arch_v2:{config.name}:{config_digest}:landmarks={int(landmark_count)}"
def prepare_landmark_training(project, *, parent_model_id=None, seed=None, experimental_photometric_augmentation=False, batch_size=None, epochs=210, progress_callback=None):
    """Read-only preflight; no dataset/model artifact is created until Start."""
    def progress(stage, detail):
        if progress_callback:
            progress_callback(stage, detail)
    progress("MODEL", "Resolving selected training parent...")
    parent = project.model_metadata(parent_model_id) if parent_model_id else project.active_model_readonly("landmark")
    bootstrap = None
    if parent:
        parent, backend = backend_for_model(project, parent["model_id"], model=parent) if parent_model_id else active_backend(project)
        progress("MODEL", "Active model resolved; checking schema compatibility...")
    else:
        bootstrap = resolve_landmark_bootstrap(project)
        backend = RTMPoseBackend(RTMPoseModelSpec("bootstrap", schema_hash(project.schema_path), bootstrap.config_path, bootstrap.checkpoint_path, bootstrap.input_size))
        progress("MODEL", "First-model bootstrap resolved.")
    import time
    timings = {}
    progress("TRAINING IMAGES", "Scanning eligible human-verified images...")
    started = time.perf_counter()
    image_ids = tuple(v2_human_final_eligible_image_ids(project))
    timings["eligible_query"] = time.perf_counter() - started
    progress("TRAINING IMAGES", f"Eligible count: {len(image_ids)}")
    if len(image_ids) < 2:
        raise LandmarkTrainingPreparationError("at least two human-verified training images are required")
    if parent and not landmark_model_schema_compatible(project, parent):
        raise LandmarkTrainingPreparationError("active model landmark identities/order do not match current landmark schema")
    seed = int(seed if seed is not None else datetime.now(timezone.utc).strftime("%Y%m%d"))
    validation_count = max(1, min(len(image_ids) - 1, round(len(image_ids) * .15)))
    splits = deterministic_splits(project, split_counts={"train": len(image_ids) - validation_count, "validation": validation_count, "test": 0}, seed=seed, eligibility_mode="v2_human_final")
    model_id = _next_model_id(project)
    progress("HARDWARE", "Detecting CPU, GPU, VRAM and CUDA...")
    hardware = get_hardware_profile()
    progress("HARDWARE", f"GPU: {hardware.gpu_model or 'CPU'}; CUDA: {hardware.cuda_available}")
    progress("PREPARING TRAINING IMAGES", "Verifying standardized frames, labels and immutable hashes...")
    started = time.perf_counter()
    try: prepared = prepare_training_snapshot(project, image_ids, hardware=hardware)
    except Exception as exc: raise LandmarkTrainingPreparationError(f"canonical cropped frame is unavailable: {exc}") from exc
    timings["prepared_snapshot"] = time.perf_counter() - started
    progress("TRAINING IMAGES", f"Dataset-ready count: {len(image_ids)}")
    # Cache hits should not export COCO/build a probe config. Create those
    # disposable assets only when a real benchmark actually starts.
    timings["probe_assets"] = 0.0
    probe_assets = None
    probe_config_ready = False
    def ensure_probe_config(config):
        nonlocal probe_config_ready, probe_assets
        if not probe_config_ready:
            started = time.perf_counter()
            probe_assets = _prepare_training_probe_assets(project, image_ids, splits, backend, seed=seed, prepared_snapshot=prepared)
            probe_config_path = probe_assets["root"] / "config_probe.py"
            generate_smoke_config(
                probe_assets["manifest"], data_root=project.data_root,
                train_coco=probe_assets["train_coco"], val_coco=probe_assets["val_coco"],
                output_path=probe_config_path, base_config=backend.spec.config_path,
                base_checkpoint=backend.spec.checkpoint_path, batch_size=1,
                workers=0, mixed_precision=bool(config.get("mixed_precision")),
                device=str(config.get("device", backend.spec.device)), pin_memory=bool(config.get("pin_memory")),
                persistent_workers=False, max_epochs=1, checkpoint_interval=1,
                max_keep_ckpts=1, input_size=backend.spec.input_size,
            )
            timings["probe_assets"] = time.perf_counter() - started
            probe_config_ready = True
        return probe_assets["root"] / "config_probe.py"
    def probe(config):
        batch = int(config["batch_size"])
        workers = int(config.get("workers", 0))
        config_path = ensure_probe_config(config)
        progress("AUTO PERFORMANCE", f"Testing batch {batch}, workers {workers} on current cropped training images…")
        return backend._invoke("probe", {"config_path": str(config_path), "batch_size": batch, "workers": workers,
                                          "iterations": 4, "samples": 48,
                                          "mixed_precision": bool(config.get("mixed_precision")), "pin_memory": bool(config.get("pin_memory")), "persistent_workers": bool(config.get("persistent_workers")), "device": str(config.get("device", "cuda:0"))})
    def probe_many(configs):
        configs=tuple(dict(config) for config in configs)
        if not configs:return ()
        config_path=ensure_probe_config(configs[0])
        progress("CALIBRATING TRAINING", f"First run only — testing 0/{len(configs)} settings…")
        return backend.benchmark_training_configurations(
            config_path, configs, samples=24,
            mixed_precision=bool(configs[0].get("mixed_precision")),
            device=str(configs[0].get("device", backend.spec.device)),
            progress_callback=lambda done, total: progress("CALIBRATING TRAINING", f"Testing {done}/{total} settings…"),
        )
    # Tune a bounded GPU batch set first, then vary workers only around the
    # two fastest safe batches. Grouped probes keep model/runtime startup out
    # of each candidate measurement.
    baseline_settings = get_training_config(hardware=hardware)
    baseline = int(baseline_settings["batch_size"])
    train_count=max(1,len(splits.get("train") or ()))
    # Keep at least ~4 optimiser steps per epoch when possible.  This avoids
    # "maximising GPU load" by silently turning a small scientific dataset
    # into one giant batch, while still allowing large workstations to use 64.
    quality_ceiling=max(1,min(64,train_count//4))
    batch_values=cuda_batch_candidates(hardware,maximum=quality_ceiling) if hardware.cuda_available else (1,)
    if baseline not in batch_values and baseline<=quality_ceiling:
        batch_values=tuple(sorted(set(batch_values+(baseline,))))
    # Measure a compact span from no workers through the machine's physical/logical
    # capacity.  AUTO keeps only a few representative counts, so first use is
    # short but a 32-core workstation is not treated like a 4-core laptop.
    recommended=int(baseline_settings.get("workers",0))
    physical=max(1,int(hardware.physical_cores or hardware.logical_cores or 1))
    logical=max(1,int(hardware.logical_cores or physical))
    # Windows worker-process startup is costly and persistent workers amortize
    # it across the full training run. Measure a compact steady-state range.
    if physical<=2:
        worker_values=tuple(range(0,physical+1))
    else:
        worker_values=(0,2,min(4,physical))
    # First measure batch throughput with workers=0. The Performance Engine
    # then tests this compact worker set only on the two fastest safe batches.
    tuning_candidates=[{"batch_size":batch,"workers":0} for batch in batch_values]
    progress("AI RUNTIME", "Checking Python, runner, torch, MMPose/MMEngine and CUDA...")
    started = time.perf_counter()
    architecture = _architecture_tuning_identity(backend, len(project.schema))
    selected = dict(auto_performance_config(project, workload="landmark_training", model=architecture, input_size=tuple(backend.spec.input_size), training=True, hardware=hardware, probe=probe if batch_size is None and hardware.cuda_available and hasattr(backend, "_invoke") else None, probe_many=probe_many if batch_size is None and hardware.cuda_available and hasattr(backend, "benchmark_training_configurations") else None, probe_configurations=batch_size is None, candidate_configurations=tuning_candidates if batch_size is None else None, staged_worker_candidates=worker_values if batch_size is None else None, tuning_variant="landmark_training_architecture_v12:" + architecture))
    timings["auto_performance"] = time.perf_counter() - started
    if selected.get("tuning_source") == "cache":
        progress("AUTO PERFORMANCE", "Using cached settings for this machine.")
    elif selected.get("tuning_source") == "probe":
        saved = "Cache saved." if selected.get("cache_saved") else "Cache could not be saved; calibration may repeat next time."
        progress("AUTO PERFORMANCE", f"Selected batch {selected['batch_size']}, workers {selected['workers']}. {saved}")
    if batch_size is not None: selected["batch_size"]=int(batch_size)
    issue=("; "+str((selected.get("tuning_errors") or [""])[0])) if selected.get("tuning_source")=="fallback" else ""
    progress("TRAINING PLAN", f"Auto selected: {selected.get('device')}, batch {selected.get('batch_size')}, workers {selected.get('workers')}, AMP {'on' if selected.get('mixed_precision') else 'off'}, source {selected.get('tuning_source','heuristic')}{issue}")
    selected.update({"photometric_augmentation":bool(experimental_photometric_augmentation),"max_epochs":int(epochs),"input_size":list(backend.spec.input_size),"persistent_workers": bool(selected["workers"] > 0), "pin_memory": bool(str(selected["device"]).startswith("cuda")), "hardware": hardware.as_dict()})
    attempt = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    selected.update({"bootstrap": None if bootstrap is None else {"config_path":str(bootstrap.config_path),"checkpoint_path":str(bootstrap.checkpoint_path),"checksum":bootstrap.checksum},"prepared_snapshot_path":str(snapshot_path(project)),"prepared_snapshot_workers":prepared.get("workers"),"preparation_timings_seconds":timings,"architecture_tuning_identity":architecture})
    return LandmarkTrainingPlan(model_id, f"{model_id}_engineering_{seed}_{attempt}", parent["model_id"] if parent else None, image_ids, splits, seed, selected)


def _verify_first_model_loadable(project, plan):
    """Load one immutable first-model prediction before making it active."""
    from .landmark_ai_service import LandmarkAIService
    _model, backend = backend_for_model(project, plan.model_id)
    request = LandmarkAIService(project, backend)._request(plan.image_ids[0])
    prediction = backend.predict(request)
    expected_ids = [int(row["id"]) for row in request.schema]
    if prediction.model_id != plan.model_id or [point.landmark_id for point in prediction.landmarks] != expected_ids:
        raise LandmarkTrainingPreparationError("first-model load verification returned a different landmark schema")
    import math
    if not all(math.isfinite(point.x) and math.isfinite(point.y) and (point.confidence is None or math.isfinite(point.confidence)) for point in prediction.landmarks):
        raise LandmarkTrainingPreparationError("first-model load verification returned non-finite predictions")

def resume_pending_finalization(project, progress_callback=None):
    pending = pending_finalization_artifact(project)
    if not pending:
        return None
    artifact, state = pending
    try:
        _, base = active_backend(project)
        backend = RTMPoseBackend(RTMPoseModelSpec(state["model_id"], schema_hash(project.schema_path), base.spec.config_path, base.spec.checkpoint_path, base.spec.input_size, state.get("device", base.spec.device)))
    except BatchError:
        info = (state.get("settings") or {}).get("bootstrap") or {}
        config_path = Path(info.get("config_path") or "")
        checkpoint_path = Path(info.get("checkpoint_path") or "")
        if not config_path.is_file() or not checkpoint_path.is_file():
            raise LandmarkTrainingPreparationError("unfinished first-model finalization has no verified bootstrap assets")
        backend = RTMPoseBackend(RTMPoseModelSpec(state["model_id"], schema_hash(project.schema_path), config_path, checkpoint_path, tuple((state.get("settings") or {}).get("input_size") or (512, 256)), state.get("device", "cuda:0")))
    return _finalize_trained_artifact(project, artifact, backend, state, progress_callback)
def run_landmark_training(project, plan, *, progress_callback=None):
    """Create the existing immutable snapshot, then call the existing training entry point."""
    resumed = resume_pending_finalization(project, progress_callback)
    if resumed is not None:
        return resumed
    _verify_first_model_bootstrap(plan)
    # Hardware was already detected during preflight and is process-cached;
    # passing it prevents final manifest verification from launching a second
    # runtime-discovery subprocess merely to choose bounded file workers.
    from .ai_hardware import get_hardware_profile
    create_dataset(project, dataset_id=plan.dataset_id, splits=plan.splits, seed=plan.seed,
                   eligibility_mode="v2_human_final", prepared_snapshot=plan.training_settings.get("prepared_snapshot_path"),
                   hardware=get_hardware_profile())
    if plan.parent_model_id is None:
        info=plan.training_settings.get("bootstrap") or {}; backend=RTMPoseBackend(RTMPoseModelSpec(plan.model_id, schema_hash(project.schema_path), Path(info["config_path"]), Path(info["checkpoint_path"]), tuple(plan.training_settings.get("input_size",(512,256))), plan.training_settings["device"]))
        parent=None; old_backend=None
    else:
        parent, old_backend = backend_for_model(project, plan.parent_model_id) if (project.active_model_readonly("landmark") or {}).get("model_id") != plan.parent_model_id else active_backend(project)
        if parent["model_id"] != plan.parent_model_id: raise LandmarkTrainingPreparationError("selected parent landmark model changed after confirmation")
    settings = dict(plan.training_settings, max_epochs=int(plan.training_settings.get("max_epochs", 210)))
    settings.setdefault("checkpoint_interval", 10)
    settings.setdefault("max_keep_ckpts", 21)
    settings.setdefault("smoke", False)
    backend = backend if plan.parent_model_id is None else RTMPoseBackend(RTMPoseModelSpec(plan.model_id, schema_hash(project.schema_path), old_backend.spec.config_path, old_backend.spec.checkpoint_path, old_backend.spec.input_size, settings["device"]))
    # A verified first model is immediately usable; later candidates retain explicit activation policy.
    result = train_project(project, plan.dataset_id, backend, parent_model_id=plan.parent_model_id, settings=settings) if progress_callback is None else train_project(project, plan.dataset_id, backend, parent_model_id=plan.parent_model_id, settings=settings, progress_callback=progress_callback)
    if plan.parent_model_id is None:
        registered = project.model_metadata(plan.model_id)
        checkpoint = Path((registered or {}).get("path") or "")
        checkpoint = project.data_root / checkpoint / "best_engineering_validation.pth"
        if registered and checkpoint.is_file():
            _verify_first_model_loadable(project, plan)
            activate_landmark_model(project, plan.model_id)
    return result


def activate_landmark_model(project, model_id):
    project.set_active_model("landmark", model_id)


def validation_metrics(model):
    metrics = model.get("engineering_validation") or model.get("result", {}).get("engineering_validation") or {}
    result = model.get("result", {})
    return {key: metrics.get(key) for key in ("median_error_percent", "p90_error_percent", "p95_error_percent")} | {"best_epoch": model.get("best_epoch", result.get("best_epoch")), "ema_used": model.get("ema_used", result.get("ema_used"))}
