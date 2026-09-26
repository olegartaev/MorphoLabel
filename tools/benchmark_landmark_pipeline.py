"""Bounded wall-clock benchmark for the Landmark preparation/inference path.

Run only against a disposable project copy.  It does not train or persist any
predictions; it creates one immutable dataset manifest to measure the same
final snapshot path used by training.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai_batch import active_backend
from app.ai_hardware import get_hardware_profile
from app.landmark_ai_service import LandmarkAIService
from app.landmark_dataset import create_dataset, v2_human_final_eligible_image_ids
from app.landmark_preparation import prepare_inference_metadata, prepare_training_snapshot
from app.project_storage import Project


def timed(values, name, callback):
    started = time.perf_counter(); result = callback(); elapsed = time.perf_counter() - started
    values[name] = elapsed
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--images", type=int, default=8)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    project = Project.open(args.project)
    timings = {}
    ids = timed(timings, "eligible_query", lambda: tuple(v2_human_final_eligible_image_ids(project)))
    ids = ids[:max(2, min(int(args.images), len(ids)))]
    if len(ids) < 2:
        raise SystemExit("fewer than two eligible Landmark images")
    hardware = timed(timings, "hardware_detection", get_hardware_profile)
    snapshot = timed(timings, "prepared_snapshot", lambda: prepare_training_snapshot(project, ids, hardware=hardware))
    splits = {"train": ids[:-1], "validation": ids[-1:], "test": ()}
    dataset_id = "benchmark_" + uuid.uuid4().hex
    manifest = timed(timings, "immutable_dataset_and_coco", lambda: create_dataset(project, dataset_id=dataset_id, splits=splits, seed=20260915, eligibility_mode="v2_human_final", prepared_snapshot=snapshot))
    report = {"project": str(project.root), "image_count": len(ids), "image_ids": list(ids), "timings_seconds": timings, "snapshot_stage_timings_seconds": snapshot.get("timings_seconds", {}), "snapshot_workers": snapshot.get("workers"), "dataset_id": dataset_id, "inference": None}
    try:
        _model, backend = active_backend(project)
        service = LandmarkAIService(project, backend)
        metadata = timed(timings, "inference_request_preparation", lambda: prepare_inference_metadata(project, ids))
        requests = [service._request(image_id, metadata=metadata[image_id]) for image_id in ids]
        predictions = timed(timings, "bulk_rank_inference", lambda: backend.predict_readonly_many(requests))
        report["inference"] = {"model_id": backend.model_id, "returned": len(predictions), "images_per_second": len(predictions) / max(timings["bulk_rank_inference"], 1e-9), "batch_size": getattr(backend, "last_rank_batch_size", None)}
    except Exception as exc:
        report["inference"] = {"error": f"{type(exc).__name__}: {exc}"}
    report["timings_seconds"] = timings
    report["total_seconds"] = sum(timings.values())
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
