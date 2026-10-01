#!/usr/bin/env python3
"""Read-only X-ray crop benchmark; emits only anonymous diagnostic metrics."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np


EXPECTED_HEAD = "9c78fa9f54a6c9f8b163bc8e3b3ddbe146691f28"
EXPECTED_BRANCH = "feature/xray-traits-foundation"
GT_MATCH_THRESHOLD = 0.30
HIGH_MATCH_THRESHOLD = 0.50
CODE_FILES = (
    "app/xray_crop.py",
    "app/xray_detector.py",
    "app/xray_project.py",
    "ai_runtime/xray_detector_runner.py",
)
SAFE_MODEL_METRIC_KEYS = {
    "backend", "epochs", "device", "train_plates", "val_plates", "training_plates",
    "training_specimens", "initialization", "batch_size", "workers", "mixed_precision",
    "precision", "loss", "coco/bbox_mAP", "coco/bbox_mAP_50", "coco/bbox_mAP_75",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def open_db_readonly(path: Path) -> sqlite3.Connection:
    uri = "file:" + path.as_posix() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection


def safe_metrics(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    out = {}
    for key in sorted(SAFE_MODEL_METRIC_KEYS):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) or item is None:
            if not isinstance(item, float) or math.isfinite(item):
                out[key] = item
    return out


def polygon_area(corners) -> float:
    points = np.asarray(corners, dtype=np.float32).reshape((-1, 1, 2))
    return abs(float(cv2.contourArea(points)))


def polygon_intersection_area(left, right) -> float:
    a = np.asarray(left, dtype=np.float32).reshape((-1, 1, 2))
    b = np.asarray(right, dtype=np.float32).reshape((-1, 1, 2))
    try:
        area, _ = cv2.intersectConvexConvex(a, b)
        return max(0.0, float(area))
    except cv2.error:
        return 0.0


def proposal_corners(proposal) -> list[list[float]]:
    if hasattr(proposal, "corners"):
        raw = proposal.corners
    elif hasattr(proposal, "to_dict"):
        raw = proposal.to_dict().get("corners")
    else:
        raw = proposal.get("corners")
    return [[float(point[0]), float(point[1])] for point in raw]


def crop_record_corners(crop: dict) -> list[list[float]]:
    corners = crop.get("corners")
    if corners and len(corners) >= 3:
        return [[float(point[0]), float(point[1])] for point in corners]
    from app.xray_crop import crop_corners

    required = ("center_x", "center_y", "length", "width", "angle_degrees")
    if all(key in crop for key in required):
        return [[float(x), float(y)] for x, y in crop_corners(*(crop[key] for key in required))]
    raise ValueError("A confirmed crop has no usable polygon geometry")


def greedy_matches(ious: list[list[float]], threshold: float) -> list[tuple[int, int, float]]:
    candidates = [
        (float(ious[truth_i][pred_i]), truth_i, pred_i)
        for truth_i in range(len(ious))
        for pred_i in range(len(ious[truth_i]))
        if ious[truth_i][pred_i] >= threshold
    ]
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_truth, used_pred, matches = set(), set(), []
    for iou, truth_i, pred_i in candidates:
        if truth_i in used_truth or pred_i in used_pred:
            continue
        used_truth.add(truth_i)
        used_pred.add(pred_i)
        matches.append((truth_i, pred_i, iou))
    return matches


def plate_metrics(truth: list[list[list[float]]], predictions: list[list[list[float]]], seconds: float) -> dict:
    truth_areas = [polygon_area(poly) for poly in truth]
    pred_areas = [polygon_area(poly) for poly in predictions]
    ious, intersections = [], []
    for gt_poly, gt_area in zip(truth, truth_areas):
        iou_row, intersection_row = [], []
        for pred_poly, pred_area in zip(predictions, pred_areas):
            intersection = polygon_intersection_area(gt_poly, pred_poly)
            union = gt_area + pred_area - intersection
            intersection_row.append(intersection)
            iou_row.append(intersection / union if union > 0 else 0.0)
        ious.append(iou_row)
        intersections.append(intersection_row)

    matches30 = greedy_matches(ious, GT_MATCH_THRESHOLD)
    matches50 = greedy_matches(ious, HIGH_MATCH_THRESHOLD)
    assigned = {truth_i: pred_i for truth_i, pred_i, _ in matches30}
    coverage = [
        intersections[i][assigned[i]] / truth_areas[i]
        if i in assigned and truth_areas[i] > 0 else 0.0
        for i in range(len(truth))
    ]
    area_ratios = [
        pred_areas[pred_i] / truth_areas[truth_i]
        for truth_i, pred_i, _ in matches30
        if truth_areas[truth_i] > 0
    ]
    matched_ious = [item[2] for item in matches30]
    return {
        "truth_specimen_count": len(truth),
        "predicted_specimen_count": len(predictions),
        "count_exact": len(truth) == len(predictions),
        "unmatched_truth": len(truth) - len(matches30),
        "extra_predictions": len(predictions) - len(matches30),
        "recall_iou_0_30": len(matches30) / len(truth) if truth else None,
        "recall_iou_0_50": len(matches50) / len(truth) if truth else None,
        "mean_matched_polygon_iou": statistics.mean(matched_ious) if matched_ious else None,
        "median_matched_polygon_iou": statistics.median(matched_ious) if matched_ious else None,
        "mean_gt_coverage": statistics.mean(coverage) if coverage else None,
        "gt_coverage_ge_0_95_percent": 100.0 * sum(value >= 0.95 for value in coverage) / len(coverage) if coverage else None,
        "median_predicted_area_over_gt_area": statistics.median(area_ratios) if area_ratios else None,
        "processing_seconds_per_plate": float(seconds),
        "matched_at_iou_0_30": len(matches30),
        "matched_at_iou_0_50": len(matches50),
        "_matched_iou_values": matched_ious,
        "_coverage_values": coverage,
        "_area_ratio_values": area_ratios,
    }


def aggregate(plates: list[dict], method_key: str) -> dict:
    rows = [row[method_key] for row in plates if row.get(method_key) is not None]
    if not rows:
        return {"plate_count": 0}
    truth_n = sum(row["truth_specimen_count"] for row in rows)
    matched30 = sum(row["matched_at_iou_0_30"] for row in rows)
    matched50 = sum(row["matched_at_iou_0_50"] for row in rows)
    coverage_values = [value for row in rows for value in row["_coverage_values"]]
    matched_iou_values = [value for row in rows for value in row["_matched_iou_values"]]
    area_ratios = [value for row in rows for value in row["_area_ratio_values"]]
    return {
        "plate_count": len(rows),
        "truth_specimen_count": truth_n,
        "predicted_specimen_count": sum(row["predicted_specimen_count"] for row in rows),
        "count_exact_plates": sum(row["count_exact"] for row in rows),
        "unmatched_truth": sum(row["unmatched_truth"] for row in rows),
        "extra_predictions": sum(row["extra_predictions"] for row in rows),
        "recall_iou_0_30": matched30 / truth_n if truth_n else None,
        "recall_iou_0_50": matched50 / truth_n if truth_n else None,
        "mean_matched_polygon_iou": statistics.mean(matched_iou_values) if matched_iou_values else None,
        "median_matched_polygon_iou": statistics.median(matched_iou_values) if matched_iou_values else None,
        "mean_gt_coverage": statistics.mean(coverage_values) if coverage_values else None,
        "gt_coverage_ge_0_95_percent": 100.0 * sum(value >= 0.95 for value in coverage_values) / len(coverage_values) if coverage_values else None,
        "median_predicted_area_over_gt_area": statistics.median(area_ratios) if area_ratios else None,
        "median_processing_seconds_per_plate": statistics.median(row["processing_seconds_per_plate"] for row in rows),
    }


def read_project(db_path: Path) -> tuple[dict, list[dict], dict | None, set[str]]:
    connection = open_db_readonly(db_path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"meta", "source_images", "specimens", "xray_crop_models", "xray_crop_training_membership"}
        missing = required - tables
        if missing:
            raise RuntimeError("X-ray project database lacks required tables")
        meta = dict(connection.execute("SELECT key,value FROM meta"))
        source_root = Path(meta.get("source", ""))
        image_rows = [dict(row) for row in connection.execute(
            "SELECT image_id,relative_path,excluded,crop_reviewed FROM source_images ORDER BY lower(relative_path),image_id"
        )]
        specimen_rows = [dict(row) for row in connection.execute(
            "SELECT image_id,crop_json,excluded,crop_status FROM specimens"
        )]
        active_row = connection.execute(
            "SELECT model_id,created_at,path,config_path,parent_model_id,metrics_json,training_plate_count,training_specimen_count "
            "FROM xray_crop_models WHERE active=1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        active = dict(active_row) if active_row else None
        membership = set()
        if active:
            membership = {row[0] for row in connection.execute(
                "SELECT image_id FROM xray_crop_training_membership WHERE model_id=?", (active["model_id"],)
            )}
        gt_by_id = {row["image_id"]: [] for row in image_rows if row["crop_reviewed"]}
        from app.xray_crop import crop_corners

        for item in specimen_rows:
            if item["image_id"] not in gt_by_id or item["excluded"] or item["crop_status"] != "confirmed":
                continue
            crop = json.loads(item["crop_json"] or "{}")
            corners = crop.get("corners")
            if not corners or len(corners) < 3:
                keys = ("center_x", "center_y", "length", "width", "angle_degrees")
                if not all(key in crop for key in keys):
                    raise RuntimeError("A confirmed crop lacks usable polygon coordinates")
                corners = crop_corners(*(crop[key] for key in keys))
            gt_by_id[item["image_id"]].append([[float(x), float(y)] for x, y in corners])
        plate_rows = []
        for index, row in enumerate(image_rows, 1):
            if not row["crop_reviewed"]:
                continue
            relative = Path(row["relative_path"])
            source_path = (source_root / relative).resolve(strict=True)
            if not source_path.is_relative_to(source_root.resolve(strict=True)):
                raise RuntimeError(f"Anonymous plate {index:03d} resolves outside the project source tree")
            plate_rows.append({
                "internal_image_id": row["image_id"],
                "plate_id": f"plate_{len(plate_rows) + 1:03d}",
                "source_path": source_path,
                "truth": gt_by_id[row["image_id"]],
                "split": "SEEN" if row["image_id"] in membership else "UNSEEN",
            })
        return {"source_root_exists": source_root.is_dir(), "source_plate_count": len(image_rows)}, plate_rows, active, membership
    finally:
        connection.close()


def benchmark(args) -> dict:
    repo = Path(__file__).resolve().parents[2]
    project_root = Path(args.project_root).resolve(strict=True)
    db_path = project_root / "xray_project.sqlite3"
    if not db_path.is_file():
        raise FileNotFoundError("Selected project has no xray_project.sqlite3")
    before = file_fingerprint(db_path)
    branch = git_output(repo, "branch", "--show-current")
    head = git_output(repo, "rev-parse", "HEAD")
    source_status = git_output(repo, "status", "--porcelain")
    package_rel = Path(__file__).resolve().parent.relative_to(repo.resolve()).as_posix() + "/"
    filtered_status = "\n".join(
        line for line in source_status.splitlines()
        if package_rel not in line.replace("\\", "/")
    )
    code_hashes = {name: sha256_file(repo / name) for name in CODE_FILES}
    project_info, plate_rows, active, membership = read_project(db_path)

    from app.xray_crop import detect_specimens, display_preview, proposals_from_detector_boxes
    from app.xray_detector import detector_performance_settings
    from app.ai_delivery import ensure_ai_runtime

    performance = detector_performance_settings()
    inference_settings = performance["inference"]
    heuristic_metrics = {}
    for row in plate_rows:
        started = time.perf_counter()
        proposals = detect_specimens(row["source_path"])
        seconds = time.perf_counter() - started
        predicted = [proposal_corners(proposal) for proposal in proposals]
        heuristic_metrics[row["internal_image_id"]] = plate_metrics(row["truth"], predicted, seconds)

    active_available = False
    active_summary = None
    rtm_metrics = {}
    if active:
        checkpoint = (project_root / active["path"]).resolve()
        config = (project_root / active["config_path"]).resolve()
        active_available = checkpoint.is_file() and config.is_file() and bool(plate_rows)
        metrics = safe_metrics(active.get("metrics_json", "{}"))
        active_summary = {
            "model_id": active["model_id"],
            "parent_model_id": active["parent_model_id"],
            "created_at": active["created_at"],
            "training_plate_count": int(active["training_plate_count"]),
            "training_specimen_count": int(active["training_specimen_count"]),
            "membership_plate_count": len(membership),
            "metrics": metrics,
            "files_available": active_available,
        }
    if active_available:
        runtime, _ = ensure_ai_runtime()
        runner = repo / "ai_runtime" / "xray_detector_runner.py"
        with tempfile.TemporaryDirectory(prefix="morpholabel_xray_benchmark_") as temporary:
            temporary_root = Path(temporary)
            preview_paths, scales, preview_seconds = [], {}, {}
            for row in plate_rows:
                started = time.perf_counter()
                preview, scale, _original_size = display_preview(row["source_path"], max_dim=1800)
                preview_path = temporary_root / f"{row['plate_id']}.png"
                preview.convert("RGB").save(preview_path, format="PNG")
                preview_paths.append(str(preview_path))
                scales[row["internal_image_id"]] = scale
                preview_seconds[row["internal_image_id"]] = time.perf_counter() - started

            payload = {
                "config": str(config),
                "checkpoint": str(checkpoint),
                "images": preview_paths,
                "device": str(inference_settings.get("device") or "cuda:0"),
                "mixed_precision": False,
                "score_threshold": 0.25,
            }
            started = time.perf_counter()
            result = subprocess.run(
                [str(runtime), str(runner), "predict_many"],
                input=json.dumps(payload), text=True, capture_output=True, check=False,
                timeout=max(600, 120 * len(plate_rows)),
            )
            runner_seconds = time.perf_counter() - started
            if result.returncode:
                # Preserve diagnostic value without leaking local paths.
                error = (result.stderr or result.stdout or "managed runner failed").replace(str(project_root), "<PROJECT>")
                raise RuntimeError(f"Read-only RTMDet runner failed ({result.returncode}): {error[-4000:]}")
            response = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
            outputs = response.get("results") or []
            if len(outputs) != len(plate_rows):
                raise RuntimeError("Managed RTMDet runner returned an unexpected number of plate results")
            for row, output in zip(plate_rows, outputs):
                image_id = row["internal_image_id"]
                scale = scales[image_id]
                boxes = []
                for detection in output.get("detections") or []:
                    bbox = detection.get("bbox") or []
                    if len(bbox) == 4:
                        boxes.append({
                            "bbox": [float(value) / scale for value in bbox],
                            "score": float(detection.get("score", 0.0)),
                        })
                started = time.perf_counter()
                proposals = proposals_from_detector_boxes(row["source_path"], boxes)
                conversion_seconds = time.perf_counter() - started
                per_plate_seconds = preview_seconds[image_id] + runner_seconds / len(plate_rows) + conversion_seconds
                rtm_metrics[image_id] = plate_metrics(
                    row["truth"], [proposal_corners(proposal) for proposal in proposals], per_plate_seconds
                )

    for row in plate_rows:
        row["heuristic"] = heuristic_metrics[row["internal_image_id"]]
        row["rtmdet"] = rtm_metrics.get(row["internal_image_id"])
        row.pop("internal_image_id")
        row.pop("source_path")

    categories = {
        "ALL": plate_rows,
        "SEEN": [row for row in plate_rows if row["split"] == "SEEN"],
        "UNSEEN": [row for row in plate_rows if row["split"] == "UNSEEN"],
    }
    aggregates = {
        group: {
            "heuristic": aggregate(rows, "heuristic"),
            "rtmdet": aggregate(rows, "rtmdet") if active_available else None,
        }
        for group, rows in categories.items()
    }
    paired = [row for row in plate_rows if row["rtmdet"] is not None]
    comparisons = None
    if paired:
        coverage_delta = [
            (row["heuristic"]["mean_gt_coverage"] or 0.0) - (row["rtmdet"]["mean_gt_coverage"] or 0.0)
            for row in paired
        ]
        comparisons = {
            "plates_heuristic_better_gt_coverage": sum(value > 1e-12 for value in coverage_delta),
            "plates_rtmdet_better_gt_coverage": sum(value < -1e-12 for value in coverage_delta),
            "plates_tied_gt_coverage": sum(abs(value) <= 1e-12 for value in coverage_delta),
            "plates_heuristic_exact_specimen_count": sum(row["heuristic"]["count_exact"] for row in paired),
            "plates_rtmdet_exact_specimen_count": sum(row["rtmdet"]["count_exact"] for row in paired),
            "heuristic_total_missed": sum(row["heuristic"]["unmatched_truth"] for row in paired),
            "rtmdet_total_missed": sum(row["rtmdet"]["unmatched_truth"] for row in paired),
            "heuristic_total_extras": sum(row["heuristic"]["extra_predictions"] for row in paired),
            "rtmdet_total_extras": sum(row["rtmdet"]["extra_predictions"] for row in paired),
            "heuristic_median_seconds_per_plate": statistics.median(row["heuristic"]["processing_seconds_per_plate"] for row in paired),
            "rtmdet_median_seconds_per_plate": statistics.median(row["rtmdet"]["processing_seconds_per_plate"] for row in paired),
        }

    # Internal per-specimen values are needed for exact pooled aggregates but are
    # omitted from the published anonymous per-plate summaries.
    for row in plate_rows:
        for method in ("heuristic", "rtmdet"):
            if row.get(method) is not None:
                for key in ("_matched_iou_values", "_coverage_values", "_area_ratio_values"):
                    row[method].pop(key, None)

    after = file_fingerprint(db_path)
    db_unchanged = before == after
    if not db_unchanged:
        raise RuntimeError("Project SQLite fingerprint changed during the read-only benchmark")
    status_text = "clean" if not filtered_status else filtered_status
    result = {
        "repository": {
            "branch": branch,
            "head": head,
            "expected_head": EXPECTED_HEAD,
            "feature_source_status": status_text,
            "source_code_sha256": code_hashes,
        },
        "project_found": True,
        "project_database_fingerprint_before": before,
        "project_database_fingerprint_after": after,
        "project_database_unchanged": db_unchanged,
        "source_plate_count": project_info["source_plate_count"],
        "confirmed_plate_count": len(plate_rows),
        "confirmed_specimen_count": sum(len(row["truth"]) for row in read_project(db_path)[1]),
        "active_model_available": active_available,
        "active_model": active_summary,
        "seen_plate_count": sum(row["split"] == "SEEN" for row in plate_rows),
        "unseen_plate_count": sum(row["split"] == "UNSEEN" for row in plate_rows),
        "holdout_status": "NO INDEPENDENT HOLDOUT" if not any(row["split"] == "UNSEEN" for row in plate_rows) else "independent unseen plates present",
        "matching_method": "deterministic greedy highest polygon IoU; primary one-to-one assignment threshold IoU >= 0.30; recall also computed at IoU >= 0.50",
        "aggregates": aggregates,
        "comparison": comparisons,
        "per_plate": plate_rows,
    }
    output_dir = Path(__file__).resolve().parent
    (output_dir / "benchmark.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    write_report(result, output_dir / "report.txt")
    return result


def fmt(value, digits=3):
    return "n/a" if value is None else f"{value:.{digits}f}"


def write_report(data: dict, target: Path) -> None:
    all_data = data["aggregates"]["ALL"]
    heuristic, rtm = all_data["heuristic"], all_data["rtmdet"]
    lines = [
        "MorphoLabel X-ray Crop Read-only Benchmark",
        f"Repository branch: {data['repository']['branch']}",
        f"Repository HEAD: {data['repository']['head']}",
        f"Repository status (excluding this diagnostic package): {data['repository']['feature_source_status']}",
        f"Source plates: {data['source_plate_count']}",
        f"Human-confirmed plates: {data['confirmed_plate_count']}",
        f"Human-confirmed specimens: {data['confirmed_specimen_count']}",
        f"Active model available: {'YES' if data['active_model_available'] else 'NO'}",
    ]
    model = data.get("active_model")
    if model:
        lines.extend([
            f"Active model id: {model['model_id']}",
            f"Model parent: {model['parent_model_id'] or 'none'}",
            f"Model created: {model['created_at']}",
            f"Model training membership: {model['membership_plate_count']} plates",
            f"SEEN / UNSEEN: {data['seen_plate_count']} / {data['unseen_plate_count']}",
        ])
    if data["holdout_status"] == "NO INDEPENDENT HOLDOUT":
        lines.append("NO INDEPENDENT HOLDOUT")
    lines.extend([
        "",
        "Aggregate metrics — ALL confirmed plates",
        f"HEURISTIC: truth={heuristic.get('truth_specimen_count')}; predicted={heuristic.get('predicted_specimen_count')}; recall@0.30={fmt(heuristic.get('recall_iou_0_30'))}; recall@0.50={fmt(heuristic.get('recall_iou_0_50'))}; mean IoU={fmt(heuristic.get('mean_matched_polygon_iou'))}; mean GT coverage={fmt(heuristic.get('mean_gt_coverage'))}; coverage>=0.95={fmt(heuristic.get('gt_coverage_ge_0_95_percent'), 1)}%; median area ratio={fmt(heuristic.get('median_predicted_area_over_gt_area'))}; median seconds/plate={fmt(heuristic.get('median_processing_seconds_per_plate'))}",
    ])
    if rtm:
        lines.append(f"RTMDET: truth={rtm.get('truth_specimen_count')}; predicted={rtm.get('predicted_specimen_count')}; recall@0.30={fmt(rtm.get('recall_iou_0_30'))}; recall@0.50={fmt(rtm.get('recall_iou_0_50'))}; mean IoU={fmt(rtm.get('mean_matched_polygon_iou'))}; mean GT coverage={fmt(rtm.get('mean_gt_coverage'))}; coverage>=0.95={fmt(rtm.get('gt_coverage_ge_0_95_percent'), 1)}%; median area ratio={fmt(rtm.get('median_predicted_area_over_gt_area'))}; median seconds/plate={fmt(rtm.get('median_processing_seconds_per_plate'))}")
    else:
        lines.append("RTMDET: ACTIVE MODEL AVAILABLE: NO")
    comparison = data.get("comparison")
    if comparison:
        lines.extend([
            "",
            "Plate counts and timings",
            f"Heuristic better / RTMDet better / ties by mean GT coverage: {comparison['plates_heuristic_better_gt_coverage']} / {comparison['plates_rtmdet_better_gt_coverage']} / {comparison['plates_tied_gt_coverage']}",
            f"Exact specimen count — heuristic / RTMDet: {comparison['plates_heuristic_exact_specimen_count']} / {comparison['plates_rtmdet_exact_specimen_count']}",
            f"Total missed — heuristic / RTMDet: {comparison['heuristic_total_missed']} / {comparison['rtmdet_total_missed']}",
            f"Total extras — heuristic / RTMDet: {comparison['heuristic_total_extras']} / {comparison['rtmdet_total_extras']}",
            f"Median seconds/plate — heuristic / RTMDet: {fmt(comparison['heuristic_median_seconds_per_plate'])} / {fmt(comparison['rtmdet_median_seconds_per_plate'])}",
        ])
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Local project directory; never copied into outputs")
    args = parser.parse_args()
    result = benchmark(args)
    print(json.dumps({
        "project_found": result["project_found"],
        "source_plate_count": result["source_plate_count"],
        "confirmed_plate_count": result["confirmed_plate_count"],
        "confirmed_specimen_count": result["confirmed_specimen_count"],
        "active_model_available": result["active_model_available"],
        "seen_plate_count": result["seen_plate_count"],
        "unseen_plate_count": result["unseen_plate_count"],
        "project_database_unchanged": result["project_database_unchanged"],
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
