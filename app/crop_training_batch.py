"""Reproducible selection and cache preparation for sequential crop correction."""
from __future__ import annotations

import random
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .io import atomic_json_write
from .gui_crop_debug import dump_threads, error, log


class CropBatchDiagnostics:
    """Low-volume batch lifecycle diagnostics with independent hang watchdogs."""
    def __init__(self, batch_id, *, requested_count, selected_rows, active_model_id, watchdog_seconds=10, log_fn=log, error_fn=error, dump_threads_fn=dump_threads):
        self.batch_id = str(batch_id); self.requested_count = int(requested_count); self.active_model_id = active_model_id
        self.watchdog_seconds = float(watchdog_seconds); self._log = log_fn; self._error = error_fn; self._dump_threads = dump_threads_fn
        self._lock = threading.Lock(); self._timers = {}
        selected = [(row.get("image_id"), row.get("relative_path") or row.get("original_name")) for row in selected_rows]
        self.event("crop_batch_start", "START", detail=f"requested_count={self.requested_count} selected_count={len(selected)} active_crop_model_id={active_model_id} selected_images={selected}")

    def _detail(self, detail="", **context):
        values = {"batch_id": self.batch_id, **{key: value for key, value in context.items() if value is not None}}
        prefix = " ".join(f"{key}={value}" for key, value in values.items())
        return f"{prefix} {detail}".strip()

    def event(self, name, state="END", *, image_id="GLOBAL", path="", detail="", **context):
        self._log(image_id, name, state, path=path, detail=self._detail(detail, **context))

    def begin(self, operation, *, image_id="GLOBAL", path="", detail="", **context):
        key = (operation, str(image_id), context.get("batch_index"))
        self.event(operation, "START", image_id=image_id, path=path, detail=detail, **context)
        timer = threading.Timer(self.watchdog_seconds, self._watchdog, args=(key, operation, image_id, path, detail, context))
        timer.daemon = True
        with self._lock:
            previous = self._timers.pop(key, None)
            if previous: previous.cancel()
            self._timers[key] = timer
        timer.start()
        return key

    def end(self, operation, *, image_id="GLOBAL", path="", detail="", **context):
        key = (operation, str(image_id), context.get("batch_index"))
        with self._lock:
            timer = self._timers.pop(key, None)
        if timer: timer.cancel()
        self.event(operation, "END", image_id=image_id, path=path, detail=detail, **context)

    def failure(self, operation, exc, *, image_id="GLOBAL", path="", **context):
        self.end(operation, image_id=image_id, path=path, detail=f"failure={exc!r}", **context)
        self._error(image_id, operation, path, exc)

    def _watchdog(self, key, operation, image_id, path, detail, context):
        with self._lock:
            if key not in self._timers: return
        self.event("crop_batch_watchdog", "WARNING", image_id=image_id, path=path, detail=f"active_operation={operation} {detail}", **context)
        self._dump_threads(image_id, f"crop_batch_watchdog batch_id={self.batch_id} operation={operation}")

    def close(self):
        with self._lock:
            timers = tuple(self._timers.values()); self._timers.clear()
        for timer in timers: timer.cancel()


def _human_corrected_crop_ids(project):
    with project.transaction() as connection:
        return {row[0] for row in connection.execute("SELECT image_id FROM crops WHERE human_verified=1 AND provenance IN ('manual','ai_accepted','ai_corrected')")}


def crop_editor_input_ready(project, image_id):
    """Return whether the current Project crop editor can load its developed PNG."""
    from PIL import Image

    path = project.cache_root / "developed" / f"{image_id}.png"
    try:
        with Image.open(path) as image:
            image.verify()
    except (FileNotFoundError, OSError):
        return False
    return True


def crop_preparation_input_ready(project, row):
    """An editor-ready cache or an available source can be prepared for editing."""
    image_id = row["image_id"]
    if crop_editor_input_ready(project, image_id):
        return True
    source = project.image_path(image_id)
    return bool(source and Path(source).is_file())


def select_crop_training_images(project, count, seed):
    """Select unused, non-excluded, prep-capable images round-robin by locality."""
    if int(count) < 1:
        raise ValueError("number of images must be at least 1")
    used_ids = _human_corrected_crop_ids(project)
    candidates = [
        row for row in project.catalog_rows()
        if not row.get("excluded")
        and row["image_id"] not in used_ids
        and crop_preparation_input_ready(project, row)
    ]
    return _select_round_robin_by_locality(candidates, count, seed)


def _select_round_robin_by_locality(rows, count, seed):
    """Deterministic shuffled locality round-robin used by Crop batches."""
    groups = {}
    randomizer = random.Random(int(seed))
    for row in rows:
        locality = row.get("locality") or row.get("sample_id") or ""
        groups.setdefault(locality, []).append(row)
    for values in groups.values():
        randomizer.shuffle(values)
    localities = list(groups)
    randomizer.shuffle(localities)
    selected = []
    while localities and len(selected) < int(count):
        for locality in tuple(localities):
            if len(selected) >= int(count):
                break
            selected.append(groups[locality].pop())
            if not groups[locality]:
                localities.remove(locality)
    return tuple(selected)


def select_crop_prediction_images(project, count, seed):
    """Select an unseen finite Crop prediction batch without catalogue bias."""
    if int(count) < 1:
        raise ValueError("number of images must be at least 1")
    eligible_ids, _protected = project.crop_auto_candidates()
    rows_by_id = {row["image_id"]: row for row in project.catalog_rows()}
    rows = [rows_by_id[image_id] for image_id in eligible_ids if image_id in rows_by_id]
    return _select_round_robin_by_locality(rows, count, seed)


def create_crop_prediction_batch(project, count, seed=None):
    """Persist the exact representative finite prediction selection for review."""
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    seed = int(seed)
    rows = select_crop_prediction_images(project, count, seed)
    batch_id = "crop_prediction_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    path = project.data_root / "crop_prediction_batches" / batch_id / "selection.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    payload = {
        "batch_id": batch_id, "seed": seed, "created_at": datetime.now(timezone.utc).isoformat(),
        "selected_images": [{"image_id": row["image_id"], "locality": row.get("locality"), "original_name": row.get("original_name")} for row in rows],
    }
    atomic_json_write(path, payload)
    return payload, path

def prepare_crop_training_images(project, rows, progress=None, ensure_developed=None, prepare_proposal=None, diagnostics=None, cancel=None, config=None):
    """Prepare the whole training batch before editing begins.

    Each image has independent cache/proposal work, so it is performed through
    the established bounded executor. Project/UI writes remain serialized.
    """
    if ensure_developed is None:
        from .developed_cache_v2 import ensure as ensure_developed
    if prepare_proposal is None:
        from .normalization_pipeline import prepare_crop_result
        prepare_proposal = lambda source, image_id: prepare_crop_result(source, project=project, force=True, image_id_value=image_id)
    from .crop_parallel import auto_config, bounded_map
    from .project_runtime import scoped_project
    prepared, skipped, proposal_failures, proposals = [], [], [], {}
    total = len(rows)
    def prepare(row):
        # Context variables do not cross executor threads. The established cache
        # layer still consults this scoped project for portable relative paths.
        with scoped_project(project):
            image_id = row["image_id"]; source = project.image_path(image_id); cache_path = project.cache_root / "developed" / f"{image_id}.png"
            if not crop_editor_input_ready(project, image_id):
                if not source or not Path(source).is_file(): raise FileNotFoundError("source image is unavailable")
                ensure_developed(Path(source))
            if not crop_editor_input_ready(project, image_id): raise RuntimeError("developed cache was not created")
            if not source or not Path(source).is_file():
                return {"image_id": image_id, "source": source, "cache_path": cache_path, "proposal": None, "proposal_failure": "source image unavailable for crop inference; editor uses full-image fallback"}
            try:
                log(image_id, "crop_batch_proposal", "START", path=str(source), detail="inference_called=true source=normalization_pipeline")
                try: proposal = prepare_proposal(Path(source), image_id)
                except TypeError: proposal = prepare_proposal(Path(source))
                log(image_id, "crop_batch_proposal", "END", path=str(source), detail=f"inference_called=true proposal_crop={proposal.get('crop_bounds') if isinstance(proposal, dict) else 'unknown'}")
                return {"image_id": image_id, "source": source, "cache_path": cache_path, "proposal": proposal, "proposal_failure": None}
            except Exception as exc:
                error(image_id, "crop_batch_proposal", str(source), exc)
                return {"image_id": image_id, "source": source, "cache_path": cache_path, "proposal": None, "proposal_failure": str(exc) or type(exc).__name__}
    config = config or auto_config(project, workload="crop_training_batch_prepare")
    for index, (row, item, failure) in enumerate(bounded_map(rows, prepare, cancel=cancel, config=config), 1):
        image_id = row["image_id"]; source = project.image_path(image_id); cache_path = project.cache_root / "developed" / f"{image_id}.png"; reason = None
        if diagnostics: diagnostics.begin("crop_batch_prepare_image", image_id=image_id, path=str(source or cache_path), batch_index=index, batch_total=total, detail=f"source_path={source} developed_path={cache_path}")
        if failure is not None:
            reason = str(failure) or type(failure).__name__; skipped.append({"image_id": image_id, "reason": reason})
            if diagnostics: diagnostics.failure("crop_batch_prepare_image", failure, image_id=image_id, path=str(source or cache_path), batch_index=index, batch_total=total)
        else:
            prepared.append(image_id)
            if item.get("proposal_failure"):
                reason = item["proposal_failure"]; proposal_failures.append({"image_id": image_id, "reason": reason})
            elif isinstance(item.get("proposal"), dict) and item["proposal"].get("crop_bounds"): proposals[image_id] = item["proposal"]["crop_bounds"]
            if diagnostics: diagnostics.end("crop_batch_prepare_image", image_id=image_id, path=str(source or cache_path), batch_index=index, batch_total=total, detail=f"result=prepared proposal_failure={bool(item.get('proposal_failure'))}")
        if progress is not None: progress(index, total, image_id, reason)
    return {"selected": total, "prepared_ids": tuple(prepared), "skipped": tuple(skipped), "proposal_failures": tuple(proposal_failures), "proposals": proposals}

def create_crop_training_batch(project, count, seed=None):
    """Persist the deterministic selection without modifying source images or crops."""
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    seed = int(seed)
    rows = select_crop_training_images(project, count, seed)
    batch_id = "crop_training_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    path = project.data_root / "crop_training_batches" / batch_id / "selection.json"
    path.parent.mkdir(parents=True, exist_ok=False)
    payload = {
        "batch_id": batch_id, "seed": seed, "created_at": datetime.now(timezone.utc).isoformat(),
        "selected_images": [{"image_id": row["image_id"], "locality": row.get("locality"), "original_name": row.get("original_name")} for row in rows],
    }
    atomic_json_write(path, payload)
    return payload, path
