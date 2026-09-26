"""Reusable, immutable-input preparation for Landmark train and inference.

This module deliberately contains no Tk or model code.  It snapshots the
current, human-final landmark state once, caches only derived file hashes, and
re-validates every cached entry before it is reused.  The immutable dataset
manifest still contains a cryptographic SHA256 for every frame.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from .io import atomic_json_write
from .landmark_frames import restore_standardized_frame
from .project_storage import schema_hash

SNAPSHOT_VERSION = 1
HASH_CACHE_VERSION = 1


def _cache_root(project):
    path = project.data_root / "ai" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_path(project):
    return _cache_root(project) / "landmark_prepared_snapshot.json"


def _hash_path(project):
    return _cache_root(project) / "landmark_standardized_hashes.json"


def _read_json(path, default):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value if isinstance(value, type(default)) else default


def _crop_fingerprint(project, image_id):
    # Keep the exact persisted crop/transform identity used by dataset checks.
    from .landmark_dataset import _crop_identity
    return _crop_identity(project, image_id)


def _labels_and_review(project, image_id, schema):
    points = project.load_landmarks(image_id)
    labels = []
    origins = {}
    for row in schema:
        landmark_id = int(row["id"])
        value = points.get(landmark_id)
        if value is None:
            raise ValueError(f"eligible landmark is absent: {image_id}/{landmark_id}")
        state = "missing" if value.get("state") == "missing" else "present"
        label = {
            "landmark_id": landmark_id,
            "state": state,
            "x": None if state == "missing" else value.get("x_standardized"),
            "y": None if state == "missing" else value.get("y_standardized"),
            "provenance": value.get("provenance"),
        }
        labels.append(label)
        if value.get("provenance") == "machine":
            origins[str(landmark_id)] = "human_accepted_unchanged_ai_final"
        elif value.get("model_id") or value.get("prediction_run_id"):
            origins[str(landmark_id)] = "human_corrected_ai_final"
        else:
            origins[str(landmark_id)] = "manual_final"
    status = project.annotation_status(image_id)
    payload = {"labels": labels, "verified": bool(status["verified"]), "color": status["color"]}
    review_fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return labels, origins, bool(status["verified"]), status["color"], review_fingerprint


def _file_signature(path):
    stat = Path(path).stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _hash_entry(path, signature, crop_fingerprint):
    return {
        "version": HASH_CACHE_VERSION,
        "path": str(Path(path)),
        "signature": signature,
        "crop_fingerprint": crop_fingerprint,
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }


def _cached_hash(project, image_id, path, signature, crop_fingerprint, cache):
    value = cache.get(str(image_id))
    if value and value.get("version") == HASH_CACHE_VERSION and value.get("path") == str(path) and value.get("signature") == signature and value.get("crop_fingerprint") == crop_fingerprint:
        return value["sha256"], False
    return None, True


def _worker_count(project, paths, hardware=None):
    """Use a bounded, cached measured file-read choice where practical."""
    # A tuning write costs more than a two/three-frame metadata pass and would
    # make tiny QA projects look slow.  The first useful parallel choice is
    # intentionally measured only for a bounded representative set.
    if len(paths) < 4:
        return 1
    try:
        from .ai_hardware import get_hardware_profile
        from .performance_engine import cpu_worker_candidates, tune_workload
        hardware = hardware or get_hardware_profile()
        cap = min(8, max(1, int(hardware.logical_cores or 1)), len(paths))
        candidates = [n for n in (1, 2, 4, 8) if n <= cap]
        sample = tuple(paths[:min(4, len(paths))])
        def probe(workers):
            import time
            started = time.perf_counter()
            def read_size(value):
                return Path(value).stat().st_size
            if workers == 1:
                for value in sample: read_size(value)
            else:
                with ThreadPoolExecutor(max_workers=int(workers)) as pool:
                    tuple(pool.map(read_size, sample))
            elapsed = max(time.perf_counter() - started, 1e-9)
            return {"items_per_sec": len(sample) / elapsed}
        result = tune_workload(project, workload="landmark_preparation", model="standardized_png", input_size=None, variant="snapshot_workers_v1", hardware=hardware, candidates=candidates, probe=probe, safe_fallback=1)
        return max(1, min(cap, int(result.get("chosen") or 1)))
    except Exception:
        return 1


def _prepare_file(image_id, frame, crop_fingerprint, cached, *, relative_path=None, force=False):
    """File-only worker: no Project/SQLite access crosses this boundary."""
    frame = Path(frame)
    signature = _file_signature(frame)
    sha, miss = _cached_hash(None, image_id, frame, signature, crop_fingerprint, cached)
    if miss or force:
        sha = hashlib.sha256(frame.read_bytes()).hexdigest()
    with Image.open(frame) as image:
        width, height = image.size
    return str(image_id), {
        "standardized_relpath": str(relative_path or frame.name),
        "standardized_width": int(width), "standardized_height": int(height),
        "standardized_sha256": sha, "standardized_signature": signature,
        "hash_cache_miss": bool(miss or force), "absolute_path": str(frame),
    }


def _source_signature(row):
    return {"file_size": row.get("file_size"), "mtime_ns": row.get("mtime_ns"), "source_sha256": row.get("source_sha256")}


def _database_fingerprints(project, image_ids):
    """One read transaction describing all mutable scientific inputs.

    This is deliberately a full-value fingerprint rather than a timestamp
    heuristic: it detects label/provenance/review/crop edits even when a file
    is restored from backup with an unchanged timestamp.  It replaces dozens
    of per-image ``load_landmarks``/``annotation_status`` transactions during
    final manifest verification.
    """
    ids = tuple(map(str, image_ids))
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    out = {image_id: {"landmarks": [], "crop": None, "review": None, "crop_review_required": None} for image_id in ids}
    # Snapshot preparation is invoked from a worker during GUI preflight.  A
    # SQLite read-only URI prevents the legacy write-capable transaction setup
    # (including journal-mode negotiation) from turning preparation into a
    # database-lock wait.
    connection = sqlite3.connect(project.path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for row in connection.execute(f"SELECT image_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,predicted_x,predicted_y,confidence,prediction_run_id,reviewed FROM landmarks WHERE image_id IN ({marks}) ORDER BY image_id,landmark_abbr", ids):
            out[str(row["image_id"])]["landmarks"].append(dict(row))
        for row in connection.execute(f"SELECT image_id,crop_json,transform_json,rotation_degrees,standardized_relpath FROM crops WHERE image_id IN ({marks})", ids):
            out[str(row["image_id"])]["crop"] = dict(row)
        for row in connection.execute(f"SELECT image_id,human_verified FROM image_review WHERE image_id IN ({marks})", ids):
            out[str(row["image_id"])]["review"] = dict(row)
        for row in connection.execute(f"SELECT image_id,value FROM image_attributes WHERE attribute_key='landmark_crop_review_required' AND image_id IN ({marks})", ids):
            out[str(row["image_id"])]["crop_review_required"] = row["value"]
    finally:
        connection.close()
    return {image_id: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest() for image_id, value in out.items()}


def _valid_cached_entry(image_id, entry, row, database_fingerprint):
    """Cheap scientific-state guard before using an in-memory/file snapshot."""
    if not entry or entry.get("image_id") != str(image_id):
        return False
    return bool(entry and entry.get("image_id") == str(image_id) and
                entry.get("database_fingerprint") == database_fingerprint and
                entry.get("source_signature") == _source_signature(row))


def prepare_training_snapshot(project, image_ids, *, hardware=None, reuse=None):
    """Return a current verified snapshot for exactly ``image_ids``.

    Database reads happen on the caller thread; independent frame restoration,
    metadata reads and cache-miss SHA256 work are bounded worker tasks.  No
    Project transaction crosses a worker boundary.
    """
    timings = {}
    started = time.perf_counter(); schema = tuple(dict(row) for row in project.schema)
    requested = tuple(map(str, image_ids))
    # Do not rebuild the complete catalogue just to prepare a finite training
    # set.  This avoids status/landmark work for unrelated photographs.
    rows = {image_id: project.catalog_row(image_id) for image_id in requested}; timings["catalog_and_status"] = time.perf_counter() - started
    prior = dict((reuse or {}).get("entries") or {})
    disk = _read_json(snapshot_path(project), {})
    prior.update(disk.get("entries") or {})
    cache = _read_json(_hash_path(project), {})
    started = time.perf_counter(); database_fingerprints = _database_fingerprints(project, requested); timings["bulk_database_fingerprint"] = time.perf_counter() - started
    base = {}
    stale = []
    for image_id in requested:
        if image_id not in rows:
            raise ValueError(f"training image is not in the active catalog: {image_id}")
        entry = prior.get(image_id)
        if _valid_cached_entry(image_id, entry, rows[image_id], database_fingerprints[image_id]):
            base[image_id] = dict(entry)
        else:
            labels, origins, verified, color, review = _labels_and_review(project, image_id, schema)
            base[image_id] = {"image_id": image_id, "sample_id": rows[image_id].get("sample_id"), "locality": rows[image_id].get("locality"), "labels": labels, "training_label_origins": origins, "human_verified": verified, "qc_color": color, "human_review_fingerprint": review, "source_signature": _source_signature(rows[image_id]), "crop_transform_sha256": _crop_fingerprint(project, image_id), "database_fingerprint": database_fingerprints[image_id]}
            stale.append(image_id)
    # Restore a missing derived frame on the caller thread.  Project uses one
    # SQLite connection per transaction, so workers intentionally receive only
    # plain paths and never access Project state.
    started = time.perf_counter()
    for image_id in requested:
        frame, _ = restore_standardized_frame(project, image_id)
        base[image_id]["absolute_path"] = str(frame)
    timings["frame_restore"] = time.perf_counter() - started
    # Even valid database entries must verify their derived frame signature.
    paths = []
    for image_id in requested:
        entry = base[image_id]
        old = entry.get("absolute_path") or (project.data_root / entry.get("standardized_relpath", ""))
        paths.append(Path(old))
    workers = _worker_count(project, [path for path in paths if path.exists()], hardware)
    def file_task(image_id):
        frame=Path(base[image_id]["absolute_path"])
        return _prepare_file(image_id, frame, base[image_id]["crop_transform_sha256"], cache, relative_path=frame.relative_to(project.data_root).as_posix())
    started = time.perf_counter()
    if workers > 1 and len(requested) > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="simm-landmark-prepare") as pool:
            prepared = tuple(pool.map(file_task, requested))
    else:
        prepared = tuple(file_task(image_id) for image_id in requested)
    timings["file_metadata_and_hash"] = time.perf_counter() - started
    for image_id, file_info in prepared:
        miss = file_info.pop("hash_cache_miss")
        base[image_id].update(file_info)
        cache[image_id] = {"version": HASH_CACHE_VERSION, "path": file_info["absolute_path"], "signature": file_info["standardized_signature"], "crop_fingerprint": base[image_id]["crop_transform_sha256"], "sha256": file_info["standardized_sha256"]}
        if miss:
            stale.append(image_id)
    for entry in base.values():
        entry.pop("absolute_path", None)
    result = {"format_version": SNAPSHOT_VERSION, "schema_sha256": schema_hash(project.schema_path), "image_ids": list(requested), "entries": base, "workers": workers, "timings_seconds": timings}
    atomic_json_write(_hash_path(project), cache)
    atomic_json_write(snapshot_path(project), result)
    return result


def standardized_metadata(project, image_id):
    """Return a verified canonical frame path/dimensions/hash for inference."""
    image_id = str(image_id)
    crop_fingerprint = _crop_fingerprint(project, image_id)
    frame, _ = restore_standardized_frame(project, image_id)
    frame = Path(frame)
    signature = _file_signature(frame)
    cache = _read_json(_hash_path(project), {})
    digest, miss = _cached_hash(project, image_id, frame, signature, crop_fingerprint, cache)
    if miss:
        digest = hashlib.sha256(frame.read_bytes()).hexdigest()
        cache[image_id] = {"version": HASH_CACHE_VERSION, "path": str(frame), "signature": signature, "crop_fingerprint": crop_fingerprint, "sha256": digest}
        atomic_json_write(_hash_path(project), cache)
    with Image.open(frame) as image:
        width, height = image.size
    return frame, {"standardized_width": int(width), "standardized_height": int(height), "standardized_sha256": digest, "standardized_signature": signature, "crop_transform_sha256": crop_fingerprint}


def prepare_inference_metadata(project, image_ids, *, hardware=None):
    """Prepare canonical request metadata with no model or label work.

    Crop records are resolved on the caller thread; the independent PNG
    metadata/hash reads run in bounded workers.  This is safe for projects
    using SQLite DELETE journal mode and retains exact image-ID order.
    """
    ids = tuple(map(str, image_ids))
    cache = _read_json(_hash_path(project), {})
    frames = {}
    for image_id in ids:
        crop = _crop_fingerprint(project, image_id)
        frame, _ = restore_standardized_frame(project, image_id)
        frames[image_id] = (Path(frame), crop)
    workers = _worker_count(project, [item[0] for item in frames.values()], hardware)
    def task(image_id):
        frame, crop = frames[image_id]
        return _prepare_file(image_id, frame, crop, cache, relative_path=frame.relative_to(project.data_root).as_posix())
    if workers > 1 and len(ids) > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="simm-inference-prepare") as pool:
            values = tuple(pool.map(task, ids))
    else:
        values = tuple(task(image_id) for image_id in ids)
    result = {}
    for image_id, value in values:
        value.pop("hash_cache_miss", None)
        frame = Path(value.pop("absolute_path"))
        cache[image_id] = {"version": HASH_CACHE_VERSION, "path": str(frame), "signature": value["standardized_signature"], "crop_fingerprint": frames[image_id][1], "sha256": value["standardized_sha256"]}
        result[image_id] = {"path": frame, **value}
    atomic_json_write(_hash_path(project), cache)
    return result
