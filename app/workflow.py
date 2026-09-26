"""Scientific record, queue, split, and report operations for Block 1.

This module never creates biological coordinates.  Its only synthetic values are
accepted through explicit test fixtures outside the project data tree.
"""
from __future__ import annotations
import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from .io import atomic_json_write, read_json
from .paths import ORIGINALS, REPORTS, WORK, require_relative
from .landmark_ids import landmark_id, record_key,number_from_id
from .project_runtime import active_project, rows as project_rows, record as project_record, save as project_save

def stable_image_id(source_relpath: str) -> str:
    return hashlib.sha256(source_relpath.encode("utf-8")).hexdigest()[:16]

def image_catalog() -> list[dict]:
    active = project_rows()
    if active is not None: return active
    rows = []
    for source in sorted(ORIGINALS.rglob("*")):
        if source.is_file() and source.suffix.lower() in {".nef", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            rel = require_relative(source)
            rows.append({"image_id": stable_image_id(rel), "sample_id": source.parent.name, "source_relpath": rel})
    return rows

def select_seed_queue(target: int = 100, seed: int = 20260814, max_samples: int = 50) -> dict:
    """Round-robin sample selection prevents consecutive-specimen bias."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in image_catalog(): grouped[row["sample_id"]].append(row)
    rng = random.Random(seed)
    samples = sorted(grouped); rng.shuffle(samples); samples = samples[:max_samples]
    for images in grouped.values(): rng.shuffle(images)
    queue = []; round_no = 0
    while len(queue) < min(target, sum(len(grouped[s]) for s in samples)):
        added = False
        for sample in samples:
            if round_no < len(grouped[sample]) and len(queue) < target:
                queue.append(grouped[sample][round_no]); added = True
        if not added: break
        round_no += 1
    result = {"kind": "manual_seed_queue", "seed": seed, "target": target,
              "created_at": datetime.now(timezone.utc).isoformat(), "images": queue}
    atomic_json_write(REPORTS / "manual_seed_queue.json", result)
    return result

def make_sample_split(seed: int = 20260814, train_fraction=.70, validation_fraction=.15) -> dict:
    samples = sorted({row["sample_id"] for row in image_catalog()})
    rng = random.Random(seed); rng.shuffle(samples)
    train_end = round(len(samples) * train_fraction); valid_end = train_end + round(len(samples) * validation_fraction)
    result = {"kind":"sample_level_split", "seed":seed, "train":sorted(samples[:train_end]),
              "validation":sorted(samples[train_end:valid_end]), "permanent_test":sorted(samples[valid_end:])}
    atomic_json_write(REPORTS / "sample_split.json", result)
    return result

def assert_no_split_leakage(split: dict) -> None:
    groups = [set(split[k]) for k in ("train", "validation", "permanent_test")]
    if any(a & b for i, a in enumerate(groups) for b in groups[i + 1:]):
        raise ValueError("Sample-level split leakage detected")

def landmark_json_path(sample_id: str, image_id: str) -> Path:
    return WORK / sample_id / "landmarks" / f"{image_id}.json"

def new_record(image: dict, profile_id: str, profile_version: str, source_sha256: str | None = None) -> dict:
    return {"sample_id":image["sample_id"], "image_id":image["image_id"], "source_relpath":image["source_relpath"],
            "source_sha256":source_sha256, "profile_id":profile_id, "profile_version":profile_version,
            "points":{}, "software_version":"0.2.0"}

def save_record(record: dict) -> None:
    project = active_project()
    if project is not None:
        project_save(project, record); return
    record = dict(record); record["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json_write(landmark_json_path(record["sample_id"], record["image_id"]), record)

def load_record(image: dict, profile_id: str, profile_version: str) -> dict:
    project = active_project()
    if project is not None:
        stored = project_record(project, image)
        stored.update({"profile_id":profile_id,"profile_version":profile_version}); return stored
    return read_json(landmark_json_path(image["sample_id"], image["image_id"]), new_record(image, profile_id, profile_version))

def set_human_point(record: dict, number: int, code: str, x: float | None, y: float | None, corrected=False) -> dict:
    point = {"landmark_id":landmark_id(number), "point_number":number, "point_code":code, "state":"missing" if x is None else ("corrected" if corrected else "manual"),
             "x_standardized":x, "y_standardized":y, "final_x":x, "final_y":y,
             "reviewed":True, "provenance":"corrected_by_human" if corrected else "manual", "timestamp":datetime.now(timezone.utc).isoformat()}
    points = record.setdefault("points", {})
    key = record_key(points, number)
    old = points.get(key)
    # Preserve the immutable machine reference across every later human edit,
    # not only the first auto -> corrected transition.
    if old and any(old.get(key) is not None for key in ("predicted_x","predicted_y","confidence","model_id","prediction_run_id")):
        point.update({"predicted_x":old.get("predicted_x"), "predicted_y":old.get("predicted_y"),
                      "confidence":old.get("confidence"), "model_id":old.get("model_id"), "prediction_run_id":old.get("prediction_run_id")})
    points[key] = point
    return record

def export_landmarks_csv() -> Path:
    rows = []
    for path in WORK.glob("*/landmarks/*.json"):
        record = read_json(path, {})
        for point in record.get("points", {}).values(): rows.append({**{k:record.get(k) for k in ("sample_id","image_id","source_relpath","source_sha256","profile_id","profile_version")}, **point})
    REPORTS.mkdir(exist_ok=True); destination = REPORTS / "landmarks.csv"
    columns = ["sample_id","image_id","source_relpath","source_sha256","profile_id","profile_version","point_number","point_code","state","x_standardized","y_standardized","predicted_x","predicted_y","final_x","final_y","confidence","model_id","reviewed","timestamp"]
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
    return destination

def correction_report(records: list[dict]) -> dict:
    distances = []; by_point: dict[str, list[float]] = defaultdict(list)
    total = corrected = 0
    for record in records:
        for point in record.get("points", {}).values():
            if point.get("reviewed") and point.get("state") != "missing":
                total += 1
                if point.get("predicted_x") is not None and point.get("final_x") is not None:
                    distance = ((point["predicted_x"]-point["final_x"])**2+(point["predicted_y"]-point["final_y"])**2)**.5
                    distances.append(distance); by_point[point["point_code"]].append(distance)
                    if distance > 0: corrected += 1
    result = {"landmarks_reviewed":total, "landmarks_corrected":corrected,
              "median_correction_px":median(distances) if distances else None,
              "p95_correction_px":sorted(distances)[max(0, int(len(distances)*.95)-1)] if distances else None,
              "max_correction_px":max(distances) if distances else None,
              "per_landmark_median_px":{key:median(value) for key,value in by_point.items()},
              "status":"MORE HUMAN-REVIEW DATA REQUIRED" if not distances else "STABLE — MORE VALIDATION NEEDED"}
    atomic_json_write(REPORTS / "latest_review_report.json", result)
    return result





