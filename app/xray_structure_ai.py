"""Training, prediction and portable packages for X-ray structure markers."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import random
import zipfile

import numpy as np
from PIL import Image

from .ai_delivery import ensure_ai_runtime
from .ai_hardware import get_hardware_profile, get_inference_config, get_training_config, is_cuda_oom
from .process_utils import hidden_window_kwargs
from .runtime_paths import resource_path
from .xray_crop import oriented_crop
from .xray_schema import compatible_reference_roles

STRUCTURE_BACKEND = "resnet18_heatmap_v1"
MODEL_PACKAGE_FORMAT = "morpholabel-xray-structure-model-v1"
INPUT_SIZE = (768, 256)
MIN_STRUCTURE_TRAINING_SPECIMENS = 8
MIN_STRUCTURE_TRAINING_PLATES = 3
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class XRayStructureAIError(RuntimeError):
    pass


class XRayStructurePackageError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def structure_schema_contract(scheme):
    structures = []
    compatibility = {}
    for item in scheme.get("structures") or ():
        sid = str(item["id"])
        structures.append({
            "id": sid,
            "repeated": bool(item.get("repeated")),
            "annotation": str(item.get("annotation") or "point"),
            "required": bool(item.get("required", True)),
        })
        compatibility[sid] = [str(role["id"]) for role in compatible_reference_roles(scheme, sid)]
    return {"structures": structures, "role_compatibility": compatibility}


def structure_schema_digest(scheme):
    return hashlib.sha256(_canonical(structure_schema_contract(scheme)).encode("utf-8")).hexdigest()


def structure_performance_settings(hardware=None):
    hardware = hardware or get_hardware_profile()
    training = get_training_config(hardware=hardware)
    inference = get_inference_config(hardware=hardware).copy()
    inference["mixed_precision"] = False
    return {"hardware": hardware.as_dict(), "training": training, "inference": inference}


def _run(runtime, mode, payload, timeout):
    runner = resource_path("ai_runtime", "xray_structure_runner.py")
    if not runner.is_file():
        raise XRayStructureAIError(f"X-ray structure runner is unavailable: {runner}")
    result = subprocess.run(
        [str(runtime), str(runner), str(mode)],
        input=json.dumps(payload), text=True, capture_output=True, check=False, timeout=timeout,
        **hidden_window_kwargs(),
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise XRayStructureAIError(f"X-ray structure {mode} failed: {detail[-5000:]}")
    try:
        return json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
    except (ValueError, StopIteration) as exc:
        raise XRayStructureAIError("X-ray structure runner returned invalid JSON") from exc


def _display_ready(image):
    array = np.asarray(image)
    if array.ndim == 3:
        array = array[..., :3].astype(np.float32).mean(axis=2)
    else:
        array = array.astype(np.float32)
    finite = array[np.isfinite(array)]
    if not finite.size:
        return Image.new("RGB", image.size, (0, 0, 0))
    lo, hi = np.percentile(finite, (0.5, 99.5))
    if hi <= lo:
        scaled = np.zeros(array.shape, dtype=np.uint8)
    else:
        scaled = np.clip((array - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)
    return Image.fromarray(scaled, "L").convert("RGB")


def _verified_truth(project):
    rows = []
    for row in project.structure_specimens(1):
        run = project.annotation_run(row["specimen_id"], 1, "human", False)
        if not run or str(run.get("status") or "") != "verified":
            continue
        annotations = project.effective_annotations(row["specimen_id"], 1, "human")
        rows.append({
            "specimen_id": str(row["specimen_id"]),
            "image_id": str(row["image_id"]),
            "points": [
                {
                    "structure_id": str(point["structure_id"]),
                    "x": float(point["x"]),
                    "y": float(point["y"]),
                }
                for point in annotations
            ],
        })
    return rows


def _split_by_plate(rows, seed):
    plate_ids = sorted({row["image_id"] for row in rows})
    if len(plate_ids) < MIN_STRUCTURE_TRAINING_PLATES:
        raise ValueError(
            f"Need at least {MIN_STRUCTURE_TRAINING_PLATES} source X-ray plates with verified structures before training."
        )
    rng = random.Random(int(seed)); rng.shuffle(plate_ids)
    val_n = max(1, min(len(plate_ids) - 1, round(len(plate_ids) * 0.20)))
    val_ids = set(plate_ids[:val_n])
    split = {}
    for row in rows:
        split[row["specimen_id"]] = "val" if row["image_id"] in val_ids else "train"
    return split


def prepare_structure_training_dataset(project, workspace_root, seed=42):
    truth = _verified_truth(project)
    if len(truth) < MIN_STRUCTURE_TRAINING_SPECIMENS:
        raise ValueError(
            f"Need at least {MIN_STRUCTURE_TRAINING_SPECIMENS} human-verified specimens before structure training. "
            "A larger diverse set is recommended for a useful model."
        )
    split = _split_by_plate(truth, seed)
    root = Path(workspace_root) / "structure_dataset"
    images = root / "images"; images.mkdir(parents=True, exist_ok=True)
    groups = {"train": [], "val": []}
    membership = []
    digest_rows = []
    by_id = {str(item["id"]): item for item in project.scheme.get("structures") or ()}
    structures = [
        {
            "id": sid,
            "name": str(item.get("name") or sid),
            "repeated": bool(item.get("repeated")),
        }
        for sid, item in by_id.items()
    ]
    if not structures:
        raise ValueError("The active X-ray trait scheme has no structures to learn.")
    for index, row in enumerate(truth, 1):
        specimen = project.specimen(row["specimen_id"])
        with Image.open(project.source_image_path(row["image_id"])) as source:
            source.load()
            crop = oriented_crop(source.copy(), specimen["crop"], project.orientation_policy)
        prepared = _display_ready(crop)
        filename = f"{index:06d}.png"
        target = images / filename
        prepared.save(target, format="PNG")
        group = split[row["specimen_id"]]
        points = [
            point for point in row["points"]
            if point["structure_id"] in by_id
        ]
        groups[group].append({
            "specimen_id": row["specimen_id"],
            "image_id": row["image_id"],
            "path": str(target),
            "points": points,
        })
        membership.append({"specimen_id": row["specimen_id"], "image_id": row["image_id"], "split": group})
        digest_rows.append({
            "specimen_id": row["specimen_id"], "image_id": row["image_id"], "split": group,
            "points": [
                {
                    "structure_id": point["structure_id"],
                    "x": round(float(point["x"]), 8),
                    "y": round(float(point["y"]), 8),
                }
                for point in points
            ],
        })
    if not groups["train"] or not groups["val"]:
        raise ValueError("Structure training requires non-empty train and validation groups.")
    train_plates = {row["image_id"] for row in groups["train"]}
    val_plates = {row["image_id"] for row in groups["val"]}
    if train_plates & val_plates:
        raise RuntimeError("Source-plate leakage detected between structure train and validation splits.")
    manifest = {
        "format_version": 1,
        "backend": STRUCTURE_BACKEND,
        "input_size": list(INPUT_SIZE),
        "schema_digest": structure_schema_digest(project.scheme),
        "structures": structures,
        "train": groups["train"],
        "val": groups["val"],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    dataset_hash = hashlib.sha256(_canonical({
        "schema_digest": manifest["schema_digest"],
        "rows": sorted(digest_rows, key=lambda item: item["specimen_id"]),
    }).encode("utf-8")).hexdigest()
    return {
        "root": root, "manifest": manifest_path, "schema_digest": manifest["schema_digest"],
        "dataset_hash": dataset_hash, "membership": membership,
        "training_specimens": len(groups["train"]), "validation_specimens": len(groups["val"]),
        "training_plates": len(train_plates), "validation_plates": len(val_plates),
    }


def train_structure_model(project, seed=42, epochs=60, progress=None):
    runtime, _ = ensure_ai_runtime(project=project, progress=progress)
    model_id = project.next_structure_model_id()
    parent = project.active_structure_model()
    schema_digest = structure_schema_digest(project.scheme)
    if parent and str(parent.get("schema_digest") or "") != schema_digest:
        raise XRayStructureAIError("The active structure model is incompatible with the current X-ray structure scheme.")
    performance = structure_performance_settings()
    settings = performance["training"]
    target = project.models_root / model_id
    if target.exists():
        raise XRayStructureAIError(f"Model folder already exists: {target}")
    with tempfile.TemporaryDirectory(prefix=f"morpholabel_xray_structure_{model_id}_") as scratch_name:
        scratch = Path(scratch_name)
        dataset = prepare_structure_training_dataset(project, scratch, seed=seed)
        if progress:
            progress(
                "STRUCTURE TRAINING",
                f"Learning {len(project.scheme.get('structures') or ())} marker types from "
                f"{len(dataset['membership'])} verified specimens…",
            )
        initial = ""
        if parent:
            initial_path = project.root / str(parent["path"])
            if not initial_path.is_file():
                raise XRayStructureAIError("The active parent structure model checkpoint is missing.")
            initial = str(initial_path)
        base_batch = max(1, int(settings.get("batch_size") or 2))
        attempts = []
        value = base_batch
        while value >= 1:
            if value not in attempts:
                attempts.append(value)
            if value == 1:
                break
            value = max(1, value // 2)
        result = None
        used_batch = None
        for attempt_index, batch_size in enumerate(attempts):
            payload = {
                "manifest": str(dataset["manifest"]),
                "work_dir": str(scratch / f"work_b{batch_size}"),
                "initial_checkpoint": initial,
                "device": settings["device"],
                "batch_size": batch_size,
                "workers": int(settings.get("workers") or 0),
                "mixed_precision": bool(settings.get("mixed_precision")),
                "pin_memory": bool(settings.get("pin_memory")),
                "persistent_workers": bool(settings.get("persistent_workers")),
                "epochs": int(epochs),
                "seed": int(seed),
            }
            try:
                result = _run(runtime, "train", payload, 10800)
                used_batch = batch_size
                break
            except Exception as exc:
                if not is_cuda_oom(exc) or attempt_index == len(attempts) - 1:
                    raise
                if progress:
                    progress(
                        "AUTO PERFORMANCE",
                        f"GPU memory limit at batch {batch_size}; retrying with batch {attempts[attempt_index + 1]}…",
                    )
        if not result or used_batch is None:
            raise XRayStructureAIError("Structure training did not produce a model.")
        checkpoint = Path(result["checkpoint"])
        metadata = Path(result["metadata"])
        if not checkpoint.is_file() or not metadata.is_file():
            raise XRayStructureAIError("Structure training finished without portable model artifacts.")
        try:
            model_meta = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise XRayStructureAIError("Structure model metadata is invalid.") from exc
        model_meta.update({
            "model_id": model_id,
            "schema_digest": schema_digest,
            "dataset_hash": dataset["dataset_hash"],
            "parent_model_id": (parent or {}).get("model_id"),
            "training_specimens": dataset["training_specimens"],
            "validation_specimens": dataset["validation_specimens"],
            "training_plates": dataset["training_plates"],
            "validation_plates": dataset["validation_plates"],
        })
        metadata.write_text(json.dumps(model_meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        staging = target.with_name(target.name + ".training")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        shutil.copy2(checkpoint, staging / "model.pth")
        shutil.copy2(metadata, staging / "model.json")
        staging.replace(target)
        metrics = {
            "backend": STRUCTURE_BACKEND,
            "schema_digest": schema_digest,
            "dataset_hash": dataset["dataset_hash"],
            "batch_size": used_batch,
            "device": settings["device"],
            "initialization": (parent or {}).get("model_id") or "imagenet_resnet18",
            "training_plates": dataset["training_plates"],
            "validation_plates": dataset["validation_plates"],
            **dict(result.get("metrics") or {}),
        }
        project.register_structure_model(
            model_id,
            str((target / "model.pth").relative_to(project.root)),
            str((target / "model.json").relative_to(project.root)),
            (parent or {}).get("model_id"),
            schema_digest,
            STRUCTURE_BACKEND,
            metrics,
            dataset["membership"],
            training_specimen_count=dataset["training_specimens"],
            validation_specimen_count=dataset["validation_specimens"],
            activate=True,
        )
    return {
        "trained": True, "model_id": model_id, "metrics": metrics,
        "training_specimens": dataset["training_specimens"],
        "validation_specimens": dataset["validation_specimens"],
        "training_plates": dataset["training_plates"],
        "validation_plates": dataset["validation_plates"],
    }


def _prediction_image(project, specimen_id, target):
    specimen = project.specimen(specimen_id)
    with Image.open(project.source_image_path(specimen["image_id"])) as source:
        source.load()
        crop = oriented_crop(source.copy(), specimen["crop"], project.orientation_policy)
    prepared = _display_ready(crop)
    target.parent.mkdir(parents=True, exist_ok=True)
    prepared.save(target, format="PNG")
    return target


def _flatten_prediction(groups):
    rows = []
    for group in groups or ():
        sid = str(group.get("structure_id") or "")
        for point in group.get("points") or ():
            rows.append({
                "structure_id": sid,
                "x": float(point["x"]), "y": float(point["y"]),
                "score": float(point.get("score") or 0.0),
            })
    return rows


def predict_structures(project, specimen_ids=None, count=None, cancel=None, progress=None, model=None):
    model = model or project.active_structure_model()
    if not model:
        raise XRayStructureAIError("Train or import an X-ray structure model before prediction.")
    current_digest = structure_schema_digest(project.scheme)
    if str(model.get("schema_digest") or "") != current_digest:
        raise XRayStructureAIError("The active structure model is incompatible with the current X-ray structure scheme.")
    candidates = list(project.structure_prediction_candidate_ids())
    if specimen_ids is not None:
        allowed = set(candidates)
        ids = [str(value) for value in specimen_ids if str(value) in allowed]
    else:
        ids = project.select_structure_prediction_ids(
            len(candidates) if count is None else max(1, int(count))
        )
    if not ids:
        return {"success": [], "failures": [], "model_id": model["model_id"]}
    runtime, _ = ensure_ai_runtime(project=project, progress=progress)
    settings = structure_performance_settings()["inference"]
    checkpoint = project.root / str(model["path"])
    metadata = project.root / str(model["metadata_path"])
    if not checkpoint.is_file() or not metadata.is_file():
        raise XRayStructureAIError("The active structure model artifact is incomplete.")
    success = []
    failures = []
    with tempfile.TemporaryDirectory(prefix="morpholabel_xray_structure_predict_") as scratch_name:
        scratch = Path(scratch_name)
        prepared = []
        for index, specimen_id in enumerate(ids, 1):
            if cancel is not None and cancel.is_set():
                break
            try:
                path = _prediction_image(project, specimen_id, scratch / f"{index:06d}.png")
                prepared.append((specimen_id, path))
            except Exception as exc:
                failures.append({"specimen_id": specimen_id, "reason": str(exc)})
        batch_size = max(1, int(settings.get("batch_size") or 1))
        index = 0
        while index < len(prepared):
            if cancel is not None and cancel.is_set():
                break
            chunk = prepared[index:index + batch_size]
            payload = {
                "metadata": str(metadata), "checkpoint": str(checkpoint),
                "images": [str(path) for _sid, path in chunk],
                "device": settings["device"],
            }
            try:
                result = _run(runtime, "predict_many", payload, max(900, 180 * len(chunk)))
            except Exception as exc:
                if is_cuda_oom(exc) and batch_size > 1:
                    batch_size = max(1, batch_size // 2)
                    if progress:
                        progress(index, len(prepared), f"GPU memory limit; retrying with batch {batch_size}")
                    continue
                for specimen_id, _path in chunk:
                    failures.append({"specimen_id": specimen_id, "reason": str(exc)})
                index += len(chunk)
                continue
            returned = list(result.get("results") or ())
            for offset, (specimen_id, _path) in enumerate(chunk):
                try:
                    if offset >= len(returned):
                        raise RuntimeError("Structure model returned an incomplete prediction batch.")
                    points = _flatten_prediction(returned[offset].get("structures") or ())
                    saved = project.seed_structure_predictions(specimen_id, points, model["model_id"])
                    success.append({"specimen_id": specimen_id, "saved": saved})
                except Exception as exc:
                    failures.append({"specimen_id": specimen_id, "reason": str(exc)})
                if progress:
                    progress(index + offset + 1, len(prepared), specimen_id)
            index += len(chunk)
    return {
        "success": success, "failures": failures, "model_id": model["model_id"],
        "inference_batch_size": batch_size,
    }


def _safe_model_json(path):
    try:
        source = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XRayStructurePackageError("Structure model metadata is invalid.") from exc
    allowed = {
        "format_version", "backend", "input_size", "output_stride", "structures", "preprocessing",
        "thresholds", "validation", "epochs_completed", "model_id", "schema_digest",
        "dataset_hash", "parent_model_id", "training_specimens", "validation_specimens",
        "training_plates", "validation_plates",
    }
    return {key: source[key] for key in allowed if key in source}


def export_structure_model_package(project, target, model_id=None):
    model = next(
        (item for item in project.structure_models() if item["model_id"] == str(model_id)),
        None,
    ) if model_id else project.active_structure_model()
    if not model:
        raise XRayStructurePackageError("No X-ray structure model is selected.")
    checkpoint = project.root / str(model["path"])
    metadata = project.root / str(model["metadata_path"])
    if not checkpoint.is_file() or not metadata.is_file():
        raise XRayStructurePackageError("Structure model artifact is incomplete.")
    safe_meta = _safe_model_json(metadata)
    safe_meta["model_id"] = str(model["model_id"])
    safe_meta["schema_digest"] = str(model["schema_digest"])
    meta_bytes = json.dumps(safe_meta, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    checkpoint_bytes = checkpoint.read_bytes()
    files = {
        "artifacts/model.pth": checkpoint_bytes,
        "artifacts/model.json": meta_bytes,
    }
    metrics = dict(model.get("metrics") or {})
    safe_metrics = {
        key: value for key, value in metrics.items()
        if key not in {"training_membership", "validation_membership"} and not str(key).endswith("_path")
    }
    manifest = {
        "package_format": MODEL_PACKAGE_FORMAT,
        "model_id": str(model["model_id"]),
        "backend": str(model.get("backend") or STRUCTURE_BACKEND),
        "schema_digest": str(model["schema_digest"]),
        "training_statistics": {
            "training_specimen_count": int(model.get("training_specimen_count") or 0),
            "validation_specimen_count": int(model.get("validation_specimen_count") or 0),
            "metrics": safe_metrics,
        },
        "files": {name: _sha256_bytes(data) for name, data in files.items()},
    }
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return target


def import_structure_model_package(project, source):
    source = Path(source)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise XRayStructurePackageError("The selected structure model package is not a valid ZIP file.") from exc
    with archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise XRayStructurePackageError("Structure model package manifest is invalid.") from exc
        if manifest.get("package_format") != MODEL_PACKAGE_FORMAT:
            raise XRayStructurePackageError("Unsupported X-ray structure model package format.")
        if str(manifest.get("backend") or "") != STRUCTURE_BACKEND:
            raise XRayStructurePackageError("This package uses an unsupported X-ray structure backend.")
        current_digest = structure_schema_digest(project.scheme)
        if str(manifest.get("schema_digest") or "") != current_digest:
            raise XRayStructurePackageError(
                "This structure model was trained for a different X-ray structure scheme."
            )
        expected = dict(manifest.get("files") or {})
        if set(expected) != {"artifacts/model.pth", "artifacts/model.json"}:
            raise XRayStructurePackageError("Structure model package has an unexpected artifact set.")
        payload = {}
        for name, digest in expected.items():
            if ".." in Path(name).parts or not name.startswith("artifacts/"):
                raise XRayStructurePackageError(f"Unsafe package path: {name}")
            try:
                data = archive.read(name)
            except KeyError as exc:
                raise XRayStructurePackageError(f"Missing package artifact: {name}") from exc
            if _sha256_bytes(data) != str(digest):
                raise XRayStructurePackageError(f"Checksum mismatch: {name}")
            payload[name] = data
        try:
            metadata = json.loads(payload["artifacts/model.json"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise XRayStructurePackageError("Imported structure model metadata is invalid.") from exc
        if str(metadata.get("schema_digest") or "") != current_digest:
            raise XRayStructurePackageError("Imported model metadata does not match the current structure scheme.")
        original = str(manifest.get("model_id") or "imported_structure_model")
        if not _SAFE_ID.fullmatch(original):
            raise XRayStructurePackageError("Imported structure model ID is unsafe.")
        existing = {item["model_id"] for item in project.structure_models()}
        local = original
        counter = 2
        while local in existing or (project.models_root / local).exists():
            local = f"imported_{original}_{counter}"
            counter += 1
        destination = project.models_root / local
        staging = destination.with_name(destination.name + ".importing")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            (staging / "model.pth").write_bytes(payload["artifacts/model.pth"])
            metadata["model_id"] = local
            metadata["imported_from_model_id"] = original
            (staging / "model.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            staging.replace(destination)
            stats = dict(manifest.get("training_statistics") or {})
            metrics = dict(stats.get("metrics") or {})
            metrics.update({
                "origin": "imported",
                "original_model_id": original,
                "portable_package_format": MODEL_PACKAGE_FORMAT,
            })
            project.register_structure_model(
                local,
                str((destination / "model.pth").relative_to(project.root)),
                str((destination / "model.json").relative_to(project.root)),
                None,
                current_digest,
                STRUCTURE_BACKEND,
                metrics,
                (),
                training_specimen_count=int(stats.get("training_specimen_count") or 0),
                validation_specimen_count=int(stats.get("validation_specimen_count") or 0),
                activate=False,
            )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            if destination.exists():
                shutil.rmtree(destination)
            raise
    return local
