#!/usr/bin/env python3
"""Read-only comparison of heuristic, RTMDet, and predefined hybrid geometries."""
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
EXPECTED_BRANCH = "diagnostics/xray-hybrid-benchmark-20261001"
IOU_TRUTH = 0.30
IOU_RECALL = 0.50
METHODS = ("HEURISTIC", "RTMDET", "HYBRID_A", "HYBRID_B", "HYBRID_C")


def fingerprint(path: Path) -> dict:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], text=True, capture_output=True, check=True).stdout.strip()


def area(poly) -> float:
    return abs(float(cv2.contourArea(np.asarray(poly, np.float32).reshape((-1, 1, 2)))))


def intersection(left, right) -> float:
    try:
        value, _ = cv2.intersectConvexConvex(
            np.asarray(left, np.float32).reshape((-1, 1, 2)),
            np.asarray(right, np.float32).reshape((-1, 1, 2)),
        )
        return max(0.0, float(value))
    except cv2.error:
        return 0.0


def corners(item) -> list[list[float]]:
    raw = item.corners if hasattr(item, "corners") else item["corners"]
    return [[float(x), float(y)] for x, y in raw]


def iou_matrix(left, right):
    left_areas = [area(poly) for poly in left]
    right_areas = [area(poly) for poly in right]
    matrix = []
    for li, lpoly in enumerate(left):
        row = []
        for ri, rpoly in enumerate(right):
            inter = intersection(lpoly, rpoly)
            union = left_areas[li] + right_areas[ri] - inter
            row.append(inter / union if union > 0 else 0.0)
        matrix.append(row)
    return matrix


def greedy_iou(matrix, threshold):
    pairs = [(matrix[i][j], i, j) for i in range(len(matrix))
             for j in range(len(matrix[i])) if matrix[i][j] >= threshold]
    pairs.sort(key=lambda value: (-value[0], value[1], value[2]))
    used_left, used_right, result = set(), set(), []
    for score, i, j in pairs:
        if i not in used_left and j not in used_right:
            result.append((i, j, float(score)))
            used_left.add(i)
            used_right.add(j)
    return result


def proposal_center(proposal):
    return float(proposal.center_x), float(proposal.center_y)


def hybrid_pairs(h, r, matrix, rule):
    candidates = []
    for hi, hp in enumerate(h):
        hx, hy = proposal_center(hp)
        for ri, rp in enumerate(r):
            score = matrix[hi][ri]
            agreed = score >= rule["iou"]
            if rule["center_fallback"] and not agreed:
                polygon = np.asarray(corners(rp), np.float32).reshape((-1, 1, 2))
                inside = cv2.pointPolygonTest(polygon, (hx, hy), False) >= 0
                rx, ry = proposal_center(rp)
                diagonal = math.hypot(float(rp.length), float(rp.width))
                agreed = inside and math.hypot(hx - rx, hy - ry) <= 0.35 * diagonal
            if agreed:
                candidates.append((float(score), hi, ri))
    candidates.sort(key=lambda value: (-value[0], value[1], value[2]))
    used_h, used_r, pairs = set(), set(), []
    for score, hi, ri in candidates:
        if hi not in used_h and ri not in used_r:
            pairs.append((hi, ri, score))
            used_h.add(hi)
            used_r.add(ri)
    return pairs, used_h, used_r


def metrics(truth, prediction, seconds):
    matrix = iou_matrix(truth, prediction)
    pred_areas = [area(poly) for poly in prediction]
    truth_areas = [area(poly) for poly in truth]
    matches30 = greedy_iou(matrix, IOU_TRUTH)
    matches50 = greedy_iou(matrix, IOU_RECALL)
    by_truth = {i: j for i, j, _ in matches30}
    coverage = [intersection(truth[i], prediction[by_truth[i]]) / truth_areas[i]
                if i in by_truth and truth_areas[i] > 0 else 0.0
                for i in range(len(truth))]
    ratios = [pred_areas[j] / truth_areas[i] for i, j, _ in matches30 if truth_areas[i] > 0]
    matched_ious = [score for _, _, score in matches30]
    return {
        "truth_count": len(truth), "predicted_count": len(prediction),
        "exact_count": len(truth) == len(prediction),
        "misses": len(truth) - len(matches30), "extras": len(prediction) - len(matches30),
        "recall_iou_0_30": len(matches30) / len(truth) if truth else None,
        "recall_iou_0_50": len(matches50) / len(truth) if truth else None,
        "mean_polygon_iou": statistics.mean(matched_ious) if matched_ious else None,
        "mean_gt_coverage": statistics.mean(coverage) if coverage else None,
        "coverage_ge_0_95_percent": 100 * sum(x >= 0.95 for x in coverage) / len(coverage) if coverage else None,
        "median_predicted_area_over_gt_area": statistics.median(ratios) if ratios else None,
        "seconds_per_plate": float(seconds), "_iou_values": matched_ious,
        "_coverage_values": coverage, "_area_ratios": ratios,
        "_matches30": matches30,
    }


def aggregate(rows, method):
    values = [row["metrics"][method] for row in rows]
    truth_n = sum(item["truth_count"] for item in values)
    ious = [x for item in values for x in item["_iou_values"]]
    coverages = [x for item in values for x in item["_coverage_values"]]
    ratios = [x for item in values for x in item["_area_ratios"]]
    matched30 = sum(item["truth_count"] - item["misses"] for item in values)
    matched50 = sum(len(greedy_iou(iou_matrix(row["truth"], row["predictions"][method]), IOU_RECALL))
                    for row in rows)
    return {
        "plate_count": len(values), "truth_count": truth_n,
        "predicted_count": sum(item["predicted_count"] for item in values),
        "exact_count_plates": sum(item["exact_count"] for item in values),
        "misses": sum(item["misses"] for item in values), "extras": sum(item["extras"] for item in values),
        "recall_iou_0_30": matched30 / truth_n if truth_n else None,
        "recall_iou_0_50": matched50 / truth_n if truth_n else None,
        "mean_polygon_iou": statistics.mean(ious) if ious else None,
        "mean_gt_coverage": statistics.mean(coverages) if coverages else None,
        "coverage_ge_0_95_percent": 100 * sum(x >= .95 for x in coverages) / len(coverages) if coverages else None,
        "median_predicted_area_over_gt_area": statistics.median(ratios) if ratios else None,
        "median_seconds_per_plate": statistics.median(item["seconds_per_plate"] for item in values),
    }


def read_truth(db_path, project_root):
    connection = sqlite3.connect("file:" + db_path.as_posix() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    try:
        meta = dict(connection.execute("SELECT key,value FROM meta"))
        source_root = Path(meta["source"]).resolve(strict=True)
        images = list(connection.execute(
            "SELECT image_id,relative_path,excluded,crop_reviewed FROM source_images "
            "ORDER BY lower(relative_path),image_id"))
        specimens = list(connection.execute(
            "SELECT image_id,crop_json,excluded,crop_status FROM specimens"))
        model_row = connection.execute(
            "SELECT path,config_path FROM xray_crop_models WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if model_row is None:
            raise RuntimeError("Active X-ray detector model is unavailable")
        model = dict(model_row)
        membership = {row[0] for row in connection.execute(
            "SELECT image_id FROM xray_crop_training_membership WHERE model_id=("
            "SELECT model_id FROM xray_crop_models WHERE active=1 ORDER BY created_at DESC LIMIT 1)")}
        from app.xray_crop import crop_corners
        gt = {}
        for row in images:
            if row["crop_reviewed"]:
                gt[row["image_id"]] = []
        for item in specimens:
            if item["image_id"] not in gt or item["excluded"] or item["crop_status"] != "confirmed":
                continue
            crop = json.loads(item["crop_json"] or "{}")
            poly = crop.get("corners")
            if not poly or len(poly) < 3:
                keys = ("center_x", "center_y", "length", "width", "angle_degrees")
                if not all(key in crop for key in keys):
                    raise RuntimeError("A confirmed crop lacks usable polygon coordinates")
                poly = crop_corners(*(crop[key] for key in keys))
            gt[item["image_id"]].append([[float(x), float(y)] for x, y in poly])
        plates = []
        for row in images:
            if not row["crop_reviewed"]:
                continue
            source_path = (source_root / Path(row["relative_path"])).resolve(strict=True)
            if not source_path.is_relative_to(source_root):
                raise RuntimeError("A reviewed source image resolves outside the declared source tree")
            plates.append({"plate_id": f"plate_{len(plates) + 1:03d}", "source_path": source_path,
                           "image_id": row["image_id"], "truth": gt[row["image_id"]],
                           "split": "SEEN" if row["image_id"] in membership else "UNSEEN"})
        checkpoint = (project_root / model["path"]).resolve(strict=True)
        config = (project_root / model["config_path"]).resolve(strict=True)
        return plates, checkpoint, config
    finally:
        connection.close()


def run(args):
    repo = Path(__file__).resolve().parents[2]
    project_root = Path(args.project_root).resolve(strict=True)
    db_path = project_root / "xray_project.sqlite3"
    before = fingerprint(db_path)
    if git("branch", "--show-current") != EXPECTED_BRANCH or git("rev-parse", "HEAD") != EXPECTED_HEAD:
        raise RuntimeError("Diagnostic branch or source HEAD does not match the required baseline")
    dirty = [line for line in git("status", "--porcelain").splitlines()
             if "diagnostics/xray_hybrid_benchmark_20261001/" not in line.replace("\\", "/")]
    if dirty:
        raise RuntimeError("Checkout must be clean before the benchmark starts")

    plates, checkpoint, config = read_truth(db_path, project_root)
    if not plates:
        raise RuntimeError("No human-confirmed plates were found")
    from app.xray_crop import detect_specimens, display_preview, proposals_from_detector_boxes
    from app.xray_detector import detector_performance_settings
    from app.ai_delivery import ensure_ai_runtime

    heuristic_time, heuristic = {}, {}
    for row in plates:
        started = time.perf_counter()
        proposals = detect_specimens(row["source_path"])
        heuristic_time[row["image_id"]] = time.perf_counter() - started
        heuristic[row["image_id"]] = proposals

    settings = detector_performance_settings()["inference"]
    runtime, _ = ensure_ai_runtime()
    runner = repo / "ai_runtime" / "xray_detector_runner.py"
    detector = {}
    with tempfile.TemporaryDirectory(prefix="morpholabel_xray_hybrid_") as scratch:
        scratch = Path(scratch)
        image_paths, scales, preview_times = [], {}, {}
        for row in plates:
            started = time.perf_counter()
            preview, scale, _size = display_preview(row["source_path"], max_dim=1800)
            target = scratch / f"{row['plate_id']}.png"
            preview.convert("RGB").save(target, format="PNG")
            image_paths.append(str(target))
            scales[row["image_id"]] = scale
            preview_times[row["image_id"]] = time.perf_counter() - started
        payload = {"config": str(config), "checkpoint": str(checkpoint), "images": image_paths,
                   "device": str(settings.get("device") or "cuda:0"),
                   "mixed_precision": False, "score_threshold": 0.25}
        started = time.perf_counter()
        completed = subprocess.run([str(runtime), str(runner), "predict_many"], input=json.dumps(payload),
                                   text=True, capture_output=True, check=False,
                                   timeout=max(600, 120 * len(plates)))
        runner_seconds = time.perf_counter() - started
        if completed.returncode:
            message = (completed.stderr or completed.stdout or "managed predict_many failed")
            message = message.replace(str(project_root), "<PROJECT>").replace(str(checkpoint), "<MODEL>").replace(str(config), "<CONFIG>")
            raise RuntimeError(f"Managed RTMDet predict_many failed ({completed.returncode}): {message[-4000:]}")
        output = json.loads(next(line for line in reversed(completed.stdout.splitlines()) if line.strip()))
        predictions = output.get("results") or []
        if len(predictions) != len(plates):
            raise RuntimeError("Managed RTMDet runner returned an unexpected result count")
        for row, result in zip(plates, predictions):
            if result.get("error"):
                raise RuntimeError("Managed RTMDet inference returned a per-image error")
            boxes = []
            for item in result.get("detections") or []:
                bbox = item.get("bbox") or []
                if len(bbox) == 4:
                    boxes.append({"bbox": [float(x) / scales[row["image_id"]] for x in bbox],
                                  "score": float(item.get("score", 0.0))})
            started = time.perf_counter()
            detector[row["image_id"]] = proposals_from_detector_boxes(row["source_path"], boxes)
            conversion_time = time.perf_counter() - started
            row["rtmdet_seconds"] = preview_times[row["image_id"]] + runner_seconds / len(plates) + conversion_time

    rules = {
        "HYBRID_A": {"iou": .30, "center_fallback": True,
                     "description": "polygon IoU >= 0.30 OR heuristic center inside RTMDet polygon and center distance <= 0.35 RTMDet crop diagonal"},
        "HYBRID_B": {"iou": .20, "center_fallback": False,
                     "description": "polygon IoU >= 0.20"},
        "HYBRID_C": {"iou": .40, "center_fallback": False,
                     "description": "polygon IoU >= 0.40"},
    }
    for row in plates:
        image_id = row["image_id"]
        hs, rs = heuristic[image_id], detector[image_id]
        hpolys, rpolys = [corners(p) for p in hs], [corners(p) for p in rs]
        pair_iou = iou_matrix(hpolys, rpolys)
        merge_times = {}
        row["predictions"] = {"HEURISTIC": hpolys, "RTMDET": rpolys}
        row["diagnostics"] = {}
        for method, rule in rules.items():
            started = time.perf_counter()
            pairs, used_h, used_r = hybrid_pairs(hs, rs, pair_iou, rule)
            final_polys = [hpolys[hi] for hi, _ri, _score in pairs]
            final_polys.extend(rpolys[ri] for ri in range(len(rs)) if ri not in used_r)
            only_r = [ri for ri in range(len(rs)) if ri not in used_r]
            only_h = [hi for hi in range(len(hs)) if hi not in used_h]
            merge_times[method] = time.perf_counter() - started
            row["predictions"][method] = final_polys
            row["diagnostics"][method] = {
                "geometry_from_heuristic": len(pairs), "rtmdet_only_review": len(only_r),
                "heuristic_only_rejected": len(only_h),
                "rtmdet_only_false_or_extra_iou_0_30": None,
                "agreement_pairs": len(pairs),
            }
        row["metrics"] = {}
        row["metrics"]["HEURISTIC"] = metrics(row["truth"], hpolys, heuristic_time[image_id])
        row["metrics"]["RTMDET"] = metrics(row["truth"], rpolys, row["rtmdet_seconds"])
        for method in rules:
            elapsed = heuristic_time[image_id] + row["rtmdet_seconds"] + merge_times[method]
            row["metrics"][method] = metrics(row["truth"], row["predictions"][method], elapsed)
            agreed_count = row["diagnostics"][method]["agreement_pairs"]
            matched_review = sum(pred_index >= agreed_count
                                 for _truth_index, pred_index, _score in row["metrics"][method]["_matches30"])
            row["diagnostics"][method]["rtmdet_only_false_or_extra_iou_0_30"] = (
                row["diagnostics"][method]["rtmdet_only_review"] - matched_review)

    groups = {"ALL": plates, "SEEN": [p for p in plates if p["split"] == "SEEN"],
              "UNSEEN": [p for p in plates if p["split"] == "UNSEEN"]}
    aggregates = {group: {method: aggregate(rows, method) for method in METHODS}
                  for group, rows in groups.items()}
    diag_aggregates = {group: {method: {
        key: sum(row["diagnostics"][method][key] for row in rows)
        for key in ("geometry_from_heuristic", "rtmdet_only_review", "heuristic_only_rejected",
                    "rtmdet_only_false_or_extra_iou_0_30")}
    for method in rules} for group, rows in groups.items()}

    per_plate = []
    for row in plates:
        per_plate.append({"plate": row["plate_id"], "split": row["split"],
                          "truth_count": len(row["truth"]),
                          "metrics": {method: {key: value for key, value in row["metrics"][method].items()
                                               if not key.startswith("_")} for method in METHODS},
                          "hybrid_diagnostics": row["diagnostics"]})

    after = fingerprint(db_path)
    if before != after:
        raise RuntimeError("SQLite fingerprint changed during benchmark")
    result = {
        "repository": {"source_head": EXPECTED_HEAD, "diagnostic_branch": EXPECTED_BRANCH},
        "method_definitions": {
            "HEURISTIC": "app.xray_crop.detect_specimens oriented proposals",
            "RTMDET": "managed-runtime predict_many proposals; score threshold 0.25",
            **{method: {"agreement": rule["description"],
                        "agreed_existence": "RTMDet", "agreed_geometry": "heuristic",
                        "agreed_confidence": "high", "unpaired_rtmdet": "retained with RTMDet geometry, confidence=review, QC=detector_disagreement",
                        "unpaired_heuristic": "rejected from final hybrid; diagnostic only"}
               for method, rule in rules.items()},
        },
        "pairing": "one-to-one greedy candidate assignment, descending polygon IoU with deterministic index tie-break; each hybrid evaluated independently",
        "ground_truth_matching": "one-to-one greedy highest polygon IoU; primary IoU >= 0.30; recall also at IoU >= 0.50",
        "sqlite_fingerprint_before": before, "sqlite_fingerprint_after": after,
        "sqlite_unchanged": True,
        "source_plate_count": len({p["image_id"] for p in plates}),
        "confirmed_plate_count": len(plates), "confirmed_specimen_count": sum(len(p["truth"]) for p in plates),
        "seen_plate_count": len(groups["SEEN"]), "unseen_plate_count": len(groups["UNSEEN"]),
        "rtmdet_model_files_available": True,
        "aggregates": aggregates, "hybrid_diagnostic_counts": diag_aggregates,
        "per_plate": per_plate,
    }
    for row in per_plate:
        for method in METHODS:
            row["metrics"][method].pop("_matches30", None)
    out = Path(__file__).resolve().parent
    (out / "benchmark.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    write_report(result, out / "report.txt")
    print(json.dumps({"confirmed_plates": len(plates), "confirmed_specimens": result["confirmed_specimen_count"],
                      "seen_plates": len(groups["SEEN"]), "unseen_plates": len(groups["UNSEEN"]),
                      "sqlite_unchanged": True, "methods": list(METHODS)}, sort_keys=True))


def fmt(value, digits=3, suffix=""):
    return "n/a" if value is None else f"{value:.{digits}f}{suffix}"


def write_report(data, path):
    lines = ["MorphoLabel X-ray Hybrid Benchmark — read-only diagnostic",
             f"Feature source HEAD: {data['repository']['source_head']}",
             f"Diagnostic branch: {data['repository']['diagnostic_branch']}",
             f"Confirmed plates: {data['confirmed_plate_count']} (SEEN {data['seen_plate_count']}, UNSEEN {data['unseen_plate_count']})",
             f"Confirmed specimens: {data['confirmed_specimen_count']}",
             f"SQLite unchanged: YES; size={data['sqlite_fingerprint_before']['size_bytes']} bytes; mtime_ns={data['sqlite_fingerprint_before']['mtime_ns']}; SHA256={data['sqlite_fingerprint_before']['sha256']}",
             "", "Metrics — ALL", "method | truth | predicted | exact plates | misses | extras | recall@.30 | recall@.50 | mean IoU | mean coverage | coverage>=.95% | median area ratio | median sec/plate"]
    for method in METHODS:
        item = data["aggregates"]["ALL"][method]
        lines.append(f"{method} | {item['truth_count']} | {item['predicted_count']} | {item['exact_count_plates']} | {item['misses']} | {item['extras']} | {fmt(item['recall_iou_0_30'])} | {fmt(item['recall_iou_0_50'])} | {fmt(item['mean_polygon_iou'])} | {fmt(item['mean_gt_coverage'])} | {fmt(item['coverage_ge_0_95_percent'], 1, '%')} | {fmt(item['median_predicted_area_over_gt_area'])} | {fmt(item['median_seconds_per_plate'])}")
    for group in ("SEEN", "UNSEEN"):
        lines.extend(["", f"Metrics — {group}", "method | plates | truth | predicted | exact plates | misses | extras | recall@.30 | recall@.50 | mean IoU | mean coverage | coverage>=.95% | median area ratio | median sec/plate"])
        for method in METHODS:
            item = data["aggregates"][group][method]
            lines.append(f"{method} | {item['plate_count']} | {item['truth_count']} | {item['predicted_count']} | {item['exact_count_plates']} | {item['misses']} | {item['extras']} | {fmt(item['recall_iou_0_30'])} | {fmt(item['recall_iou_0_50'])} | {fmt(item['mean_polygon_iou'])} | {fmt(item['mean_gt_coverage'])} | {fmt(item['coverage_ge_0_95_percent'], 1, '%')} | {fmt(item['median_predicted_area_over_gt_area'])} | {fmt(item['median_seconds_per_plate'])}")
    lines.extend(["", "Hybrid source/review diagnostics (count)", "split | hybrid | heuristic geometry (agreed) | RTMDet-only review retained | heuristic-only rejected | RTMDet-only false/extras @ IoU .30"])
    for group in ("ALL", "SEEN", "UNSEEN"):
        for method in ("HYBRID_A", "HYBRID_B", "HYBRID_C"):
            item = data["hybrid_diagnostic_counts"][group][method]
            lines.append(f"{group} | {method} | {item['geometry_from_heuristic']} | {item['rtmdet_only_review']} | {item['heuristic_only_rejected']} | {item['rtmdet_only_false_or_extra_iou_0_30']}")
    lines.extend(["", "Agreement rules", *[f"{method}: {data['method_definitions'][method]['agreement']}" for method in ("HYBRID_A", "HYBRID_B", "HYBRID_C")],
                  "Timing for each hybrid includes heuristic detection + RTMDet preview/inference/conversion + merge.",
                  "Ground truth and detector matching use deterministic one-to-one greedy polygon-IoU matching."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Local project folder; never written into outputs")
    run(parser.parse_args())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
