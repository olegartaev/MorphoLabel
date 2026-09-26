"""Read-only ensemble QC for final landmark annotations.

Complex QC ranks suspicious final annotations; it never treats a statistical
outlier as an error and never changes canonical landmark data.
"""
from __future__ import annotations

from collections import defaultdict
import math
import os
import statistics

MIN_REFERENCE = 8
MIN_GM_REFERENCE = 10
ROBUST_Z = 4.5
GM_DISTANCE = 3.5


def _finite_point(row):
    if not row or row.get("state") == "missing":
        return None
    x, y = row.get("x_standardized"), row.get("y_standardized")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (x, y)):
        return None
    return float(x), float(y)


def _robust_stat(values):
    values = [float(value) for value in values]
    if len(values) < MIN_REFERENCE:
        return None
    centre = statistics.median(values)
    mad = statistics.median(abs(value - centre) for value in values)
    scale = 1.4826 * mad
    tolerance = max(1e-12, abs(centre) * 1e-9)
    return centre, scale if scale > tolerance else 0.0, tolerance, len(values)


def _robust_z(value, stat):
    if stat is None:
        return None
    centre, scale, tolerance, _count = stat
    distance = abs(float(value) - centre)
    if scale > 0:
        return distance / scale
    return 0.0 if distance <= tolerance else 8.0


def _reference_stats(feature_by_image, group_by_image):
    global_values = defaultdict(list)
    grouped_values = defaultdict(lambda: defaultdict(list))
    for image_id, features in feature_by_image.items():
        group = group_by_image.get(image_id, "")
        for key, value in features.items():
            if not math.isfinite(float(value)):
                continue
            global_values[key].append(float(value))
            if group:
                grouped_values[group][key].append(float(value))
    global_stats = {key: _robust_stat(values) for key, values in global_values.items()}
    group_stats = {
        group: {key: _robust_stat(values) for key, values in values_by_key.items()}
        for group, values_by_key in grouped_values.items()
    }
    return global_stats, group_stats


def _stat_for(image_id, key, group_by_image, global_stats, group_stats):
    group = group_by_image.get(image_id, "")
    return (group_stats.get(group) or {}).get(key) or global_stats.get(key)


def _shape_ids(schema):
    gm = [int(row["id"]) for row in schema if str(row.get("role") or "BOTH").upper() in {"GM", "BOTH"}]
    return tuple(gm if len(gm) >= 4 else [int(row["id"]) for row in schema])


def _shape_features(records, shape_ids):
    """Scale/rotation/translation-invariant pair distances normalized by centroid size."""
    features = {}
    for image_id, record in records.items():
        points = record["points"]
        coords = {}
        for ident in shape_ids:
            value = _finite_point(points.get(ident))
            if value is None:
                coords = {}
                break
            coords[ident] = value
        if len(coords) != len(shape_ids) or len(coords) < 3:
            continue
        cx = sum(x for x, _ in coords.values()) / len(coords)
        cy = sum(y for _, y in coords.values()) / len(coords)
        centroid_size = math.sqrt(sum((x - cx) ** 2 + (y - cy) ** 2 for x, y in coords.values()))
        if centroid_size <= 0:
            continue
        row = {}
        ordered = list(shape_ids)
        for index, first in enumerate(ordered):
            x1, y1 = coords[first]
            for second in ordered[index + 1:]:
                x2, y2 = coords[second]
                row[(first, second)] = math.hypot(x1 - x2, y1 - y2) / centroid_size
        features[image_id] = row
    return features


def _distance_signals(records, shape_ids, group_by_image, reference_ids=()):
    features = _shape_features(records, shape_ids)
    references = {image_id:features[image_id] for image_id in reference_ids if image_id in features}
    baseline = references if len(references) >= MIN_REFERENCE else features
    global_stats, group_stats = _reference_stats(baseline, group_by_image)
    output = {}
    for image_id, row in features.items():
        extremes = []
        landmark_hits = defaultdict(list)
        for pair, value in row.items():
            z = _robust_z(value, _stat_for(image_id, pair, group_by_image, global_stats, group_stats))
            if z is None or z < ROBUST_Z:
                continue
            extremes.append((z, pair))
            for ident in pair:
                landmark_hits[int(ident)].append(z)
        if not extremes:
            continue
        extremes.sort(reverse=True)
        max_z = extremes[0][0]
        suspects = sorted(
            ((max(values), len(values), ident) for ident, values in landmark_hits.items()
             if len(values) >= 2 or max(values) >= 7.0),
            reverse=True,
        )
        if len(extremes) < 2 and max_z < 7.0:
            continue
        landmark_ids = [ident for _z, _count, ident in suspects[:3]]
        if not landmark_ids:
            landmark_ids = list(extremes[0][1])
        top = suspects[0] if suspects else (max_z, 1, landmark_ids[0])
        output[image_id] = {
            "family": "distance",
            "label": "Distance geometry",
            "score": float(max_z + min(3, len(extremes) - 1) * 0.35),
            "landmark_ids": landmark_ids,
            "message": f"Distance geometry: LM{top[2]} is involved in {top[1]} extreme distance(s) (max {max_z:.1f} robust SD).",
            "strong_local": bool(top[1] >= 3 and max_z >= 6.0),
            "extreme_pairs": len(extremes),
        }
    return output, {"used": bool(global_stats), "reference_images": len(baseline), "candidate_images": len(features), "landmarks": len(shape_ids)}


def _active_measurements_readonly(project):
    from .measurements import schema_path, load_measurements
    path = schema_path(project)
    if not path.is_file():
        return []
    return [row for row in load_measurements(project) if row.get("use")]


def _measurement_features(records, definitions):
    if len(definitions) < 2:
        return {}
    output = {}
    for image_id, record in records.items():
        points = record["points"]
        raw = {}
        complete = True
        for definition in definitions:
            first = _finite_point(points.get(int(definition["point1"])))
            second = _finite_point(points.get(int(definition["point2"])))
            if first is None or second is None:
                complete = False
                break
            distance = math.dist(first, second)
            if distance <= 0:
                complete = False
                break
            raw[str(definition["abbr"])] = distance
        if not complete or len(raw) < 2:
            continue
        log_mean = sum(math.log(value) for value in raw.values()) / len(raw)
        output[image_id] = {key: math.log(value) - log_mean for key, value in raw.items()}
    return output


def _measurement_signals(records, definitions, group_by_image, reference_ids=()):
    features = _measurement_features(records, definitions)
    references = {image_id:features[image_id] for image_id in reference_ids if image_id in features}
    baseline = references if len(references) >= MIN_REFERENCE else features
    global_stats, group_stats = _reference_stats(baseline, group_by_image)
    endpoints = {str(row["abbr"]): (int(row["point1"]), int(row["point2"])) for row in definitions}
    output = {}
    for image_id, row in features.items():
        outliers = []
        for key, value in row.items():
            z = _robust_z(value, _stat_for(image_id, key, group_by_image, global_stats, group_stats))
            if z is not None and z >= 4.0:
                outliers.append((z, key))
        if not outliers:
            continue
        outliers.sort(reverse=True)
        max_z = outliers[0][0]
        top_names = [key for _z, key in outliers[:3]]
        ids = []
        for key in top_names:
            ids.extend(endpoints.get(key, ()))
        output[image_id] = {
            "family": "measurements",
            "label": "Measurements",
            "score": float(max_z + min(2, len(outliers) - 1) * 0.25),
            "landmark_ids": list(dict.fromkeys(ids))[:6],
            "message": f"Measurement proportions: {', '.join(top_names)} ({max_z:.1f} robust SD at the strongest value).",
            "measurement_abbrs": top_names,
        }
    return output, {
        "used": bool(global_stats) and len(definitions) >= 2,
        "reference_images": len(baseline),
        "candidate_images": len(features),
        "definitions": len(definitions),
    }


def _normalise_shape(array, np):
    centred = array - array.mean(axis=0, keepdims=True)
    size = float(np.sqrt((centred * centred).sum()))
    return centred / size if size > 0 else None


def _align_to(array, target, np):
    cross = array.T @ target
    u, _s, vt = np.linalg.svd(cross, full_matrices=False)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    return array @ rotation


def _gpa(stack, np):
    aligned = []
    for array in stack:
        value = _normalise_shape(array, np)
        if value is None:
            return None
        aligned.append(value)
    aligned = np.stack(aligned)
    mean = _normalise_shape(aligned[0], np)
    for _ in range(12):
        aligned = np.stack([_align_to(array, mean, np) for array in aligned])
        new_mean = _normalise_shape(aligned.mean(axis=0), np)
        if new_mean is None:
            return None
        if float(np.sqrt(((new_mean - mean) ** 2).sum())) < 1e-9:
            mean = new_mean
            break
        mean = new_mean
    return np.stack([_align_to(array, mean, np) for array in aligned])


def _robust_z_vector(values, np):
    centre = float(np.median(values))
    mad = float(np.median(np.abs(values - centre)))
    scale = 1.4826 * mad
    tolerance = max(1e-12, abs(centre) * 1e-9)
    if scale > tolerance:
        return np.abs(values - centre) / scale
    return np.where(np.abs(values - centre) <= tolerance, 0.0, 8.0)


def _gm_group_scores(image_ids, shape_by_image, shape_ids, np):
    if len(image_ids) < MIN_GM_REFERENCE:
        return {}
    stack = np.stack([shape_by_image[image_id] for image_id in image_ids])
    aligned = _gpa(stack, np)
    if aligned is None:
        return {}
    flat = aligned.reshape(len(image_ids), -1)
    centred = flat - flat.mean(axis=0, keepdims=True)
    try:
        _u, singular, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:
        return {}
    if not len(singular) or float(singular[0]) <= 1e-12:
        return {}
    variance = singular * singular
    positive = [index for index, value in enumerate(variance) if float(value) > float(variance[0]) * 1e-10]
    max_components = min(8, len(image_ids) - 2, len(positive))
    if max_components < 1:
        return {}
    total = float(variance[positive].sum())
    cumulative = 0.0
    k = 0
    for index in positive[:max_components]:
        cumulative += float(variance[index])
        k += 1
        if total > 0 and cumulative / total >= 0.95 and k >= min(2, max_components):
            break
    scores = centred @ vt[:k].T
    z_columns = np.column_stack([_robust_z_vector(scores[:, col], np) for col in range(k)])
    distances = np.sqrt((z_columns * z_columns).mean(axis=1))
    template = np.median(aligned, axis=0)
    residuals = np.sqrt(((aligned - template[None, :, :]) ** 2).sum(axis=2))
    residual_z = np.column_stack([_robust_z_vector(residuals[:, col], np) for col in range(residuals.shape[1])])
    output = {}
    for index, image_id in enumerate(image_ids):
        pca_distance = float(distances[index])
        local = [(float(residual_z[index, col]), int(shape_ids[col])) for col in range(len(shape_ids))]
        local.sort(reverse=True)
        local_max = local[0][0] if local else 0.0
        if pca_distance < GM_DISTANCE and local_max < 5.0:
            continue
        suspects = [ident for z, ident in local if z >= 4.0][:3]
        if not suspects and local:
            suspects = [local[0][1]]
        output[image_id] = {
            "family": "gm",
            "label": "GM PCA",
            "score": float(max(pca_distance, local_max)),
            "landmark_ids": suspects,
            "message": f"GM shape outlier: PCA distance {pca_distance:.1f}; strongest local residual {local_max:.1f} robust SD.",
            "pca_distance": pca_distance,
            "local_residual_z": local_max,
            "components": int(k),
        }
    return output


def _gm_signals(records, shape_ids, group_by_image):
    try:
        import numpy as np
    except ImportError:
        return {}, {"used": False, "reference_images": 0, "landmarks": len(shape_ids), "reason": "NumPy is not available"}
    shape_by_image = {}
    for image_id, record in records.items():
        coords = []
        for ident in shape_ids:
            value = _finite_point(record["points"].get(ident))
            if value is None:
                coords = []
                break
            coords.append(value)
        if len(coords) == len(shape_ids) and len(coords) >= 4:
            shape_by_image[image_id] = np.asarray(coords, dtype=float)
    if len(shape_by_image) < MIN_GM_REFERENCE:
        return {}, {"used": False, "reference_images": len(shape_by_image), "landmarks": len(shape_ids), "reason": f"Need at least {MIN_GM_REFERENCE} complete final images"}
    global_scores = _gm_group_scores(list(shape_by_image), shape_by_image, shape_ids, np)
    by_group = defaultdict(list)
    for image_id in shape_by_image:
        group = group_by_image.get(image_id, "")
        if group:
            by_group[group].append(image_id)
    output = dict(global_scores)
    local_groups = 0
    for _group, ids in by_group.items():
        if len(ids) < MIN_GM_REFERENCE:
            continue
        local = _gm_group_scores(ids, shape_by_image, shape_ids, np)
        for image_id in ids:
            if image_id in local:
                output[image_id] = local[image_id]
            else:
                output.pop(image_id, None)
        local_groups += 1
    return output, {
        "used": True,
        "reference_images": len(shape_by_image),
        "landmarks": len(shape_ids),
        "local_groups": local_groups,
    }


def _basic_structural_signals(records, schema_ids):
    """Cheap per-image checks for every annotated fish, using already-loaded state.

    Missing frame dimensions are not an annotation error: they only make the
    bounds sub-check unavailable.  Complex QC must never flag a fish merely
    because optional frame metadata is absent.
    """
    output = {}
    dimensions_missing = 0
    for image_id, record in records.items():
        status = record.get("status") or {}
        points = record["points"]
        dimensions = record.get("dimensions")
        warnings = []
        landmark_ids = []
        unresolved = [int(value) for value in status.get("unresolved_ids") or ()]
        if unresolved:
            landmark_ids.extend(unresolved)
            warnings.append(f"{len(unresolved)} unresolved landmark(s)")
        present = []
        width = height = None
        if dimensions:
            width, height = dimensions
        for landmark_id, row in points.items():
            if int(landmark_id) not in schema_ids:
                landmark_ids.append(int(landmark_id))
                warnings.append(f"orphan LM{landmark_id}")
                continue
            if row.get("state") == "missing":
                continue
            x, y = row.get("x_standardized"), row.get("y_standardized")
            if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (x, y)):
                landmark_ids.append(int(landmark_id));warnings.append(f"non-finite LM{landmark_id}");continue
            if width and height and not (0 <= x < width and 0 <= y < height):
                landmark_ids.append(int(landmark_id));warnings.append(f"outside frame LM{landmark_id}")
            present.append((int(landmark_id), float(x), float(y)))
        for index, (first_id, x1, y1) in enumerate(present):
            for second_id, x2, y2 in present[index + 1:]:
                if math.hypot(x1-x2, y1-y2) <= 1e-6:
                    landmark_ids.extend((first_id, second_id));warnings.append(f"duplicate LM{first_id}/LM{second_id}")
        if not dimensions:
            dimensions_missing += 1
        if warnings:
            output[image_id] = {
                "family": "basic",
                "label": "Geometry",
                "score": 10.0,
                "landmark_ids": list(dict.fromkeys(landmark_ids))[:8],
                "message": "Geometry: " + "; ".join(warnings[:4]),
                "hard": True,
            }
    return output, {"used": True, "issues": len(output), "dimensions_missing": dimensions_missing}


def _existing_qc_signals(project, records, candidate_ids, progress=None):
    """Run the older expensive identity checks only on fast-stage candidates."""
    from .landmark_review import scan_project, warning_landmark_ids
    candidate_ids=tuple(str(value) for value in candidate_ids if str(value) in records)
    if not candidate_ids:
        return {}, {"used":False,"issues":0,"warnings":0,"candidate_images":0,"worker_count":0}
    result=scan_project(
        project,
        image_ids=candidate_ids,
        workers=1,
        progress=(lambda done,total: progress("Checking identity on candidates",done,total)) if progress else None,
    )
    grouped=defaultdict(list)
    keep_kinds={
        "unresolved","orphan","nonfinite","bounds","duplicate",
        "swap_suggestion","batch_vector_swap","early_swap_suggestion",
        "early_identity_inconsistency","trusted_reassignment",
        "trusted_identity_inconsistency","group_reassignment_suggestion",
    }
    for warning in result.get("queue") or ():
        image_id=str(warning.get("image_id") or "")
        kind=str(warning.get("kind") or "")
        if image_id not in records or kind not in keep_kinds:
            continue
        grouped[image_id].append(warning)
    output={}
    hard_kinds={"unresolved","orphan","nonfinite","bounds","duplicate"}
    for image_id,warnings in grouped.items():
        ids=[]
        for warning in warnings:
            ids.extend(warning_landmark_ids(warning))
        labels=[str(item.get("message") or item.get("kind") or "Check landmarks") for item in warnings[:3]]
        hard=any(str(item.get("kind") or "") in hard_kinds for item in warnings)
        output[image_id]={
            "family":"established",
            "label":"Identity",
            "score":10.0 if hard else min(8.0,5.0+0.5*len(warnings)),
            "landmark_ids":list(dict.fromkeys(int(value) for value in ids)),
            "message":"Identity check: "+"; ".join(labels),
            "hard":hard,
            "warning_count":len(warnings),
        }
    return output, {
        "used":True,
        "issues":len(output),
        "warnings":sum(len(values) for values in grouped.values()),
        "candidate_images":len(candidate_ids),
        "worker_count":result.get("worker_count"),
    }

def _abbr_map(project):
    return {int(row["id"]): str(row.get("abbr") or row["id"]) for row in project.schema}


def _issue_from_signals(record, signals, abbrs):
    families = {signal["family"] for signal in signals}
    landmark_ids = []
    for signal in signals:
        landmark_ids.extend(int(value) for value in signal.get("landmark_ids") or ())
    landmark_ids = list(dict.fromkeys(landmark_ids))[:8]
    risk = sum(min(10.0, float(signal.get("score") or 0.0)) for signal in signals)
    high = (
        any(signal.get("hard") for signal in signals)
        or any(signal.get("strong_local") for signal in signals)
        or len(families) >= 2
        or any(float(signal.get("score") or 0.0) >= 7.0 for signal in signals)
    )
    labels = [label for family, label in (
        ("basic", "Geometry"),
        ("established", "Identity"),
        ("distance", "Distance"),
        ("measurements", "Measurements"),
        ("gm", "GM PCA"),
    ) if family in families]
    suspect = ", ".join(abbrs.get(ident, str(ident)) for ident in landmark_ids[:4])
    message = " + ".join(labels)
    if suspect:
        message += f"; inspect {suspect}"
    return {
        "image_id": record["image_id"],
        "display_name": record["display_name"],
        "kind": "complex_qc",
        "severity": "high" if high else "warning",
        "priority": "High" if high else "Review",
        "risk_score": round(risk, 3),
        "landmark_ids": landmark_ids,
        "message": message,
        "details": " | ".join(signal["message"] for signal in signals),
        "signals": [dict(signal) for signal in signals],
        "locality": record.get("group") or "",
    }


def scan_complex_qc(project, progress=None, cancelled=None):
    """Scan every complete non-excluded annotation; return one ranked human-review queue.

    Incomplete landmark sets stay in the normal annotation workflow.  Fast
    invariant checks run on every complete annotation.  The expensive legacy
    identity search is a bounded second stage for the strongest fast-stage
    candidates only.  Every annotation participates in the scan, but only
    unresolved statistical/structural warnings enter the human review queue.
    """
    from .landmark_review import _review_snapshot

    catalog = [row for row in project.catalog_rows() if not row.get("excluded")]
    snapshot = _review_snapshot(project)
    records = {}
    total = len(catalog)
    for index, row in enumerate(catalog, start=1):
        if cancelled and cancelled():
            return {"cancelled":True,"scanned":len(records),"queue":tuple(),"flagged":0,"high":0,"review_total":0,"methods":{}}
        image_id = str(row["image_id"])
        points = snapshot.load_landmarks(image_id)
        if points:
            status = snapshot.annotation_status(image_id)
            if not status.get("complete"):
                if progress and (index == total or index % 50 == 0):
                    progress("Reading complete annotations", index, total)
                continue
            records[image_id] = {
                "image_id":image_id,
                "display_name":row.get("display_name") or row.get("original_name") or image_id,
                "group":row.get("locality") or row.get("sample_id") or "",
                "points":points,
                "status":status,
                "dimensions":snapshot.dimensions_by_id.get(image_id),
                "checked":bool(row.get("human_verified")) and bool(status.get("complete")),
            }
        if progress and (index == total or index % 50 == 0):
            progress("Reading annotated images", index, total)

    if not records:
        return {
            "cancelled":False,"scanned":0,"queue":tuple(),"flagged":0,"high":0,"review_total":0,
            "methods":{
                "basic":{"used":False,"issues":0},
                "established":{"used":False,"issues":0,"warnings":0,"candidate_images":0},
                "distance":{"used":False,"reference_images":0,"candidate_images":0,"landmarks":0},
                "measurements":{"used":False,"reference_images":0,"candidate_images":0,"definitions":0},
                "gm":{"used":False,"reference_images":0,"landmarks":0,"reason":"No annotated images"},
            },
        }

    group_by_image={image_id:record["group"] for image_id,record in records.items()}
    reference_ids=tuple(
        image_id for image_id,record in records.items()
        if record["checked"] and record["status"].get("complete")
    )
    shape_ids=_shape_ids(project.schema)
    schema_ids=frozenset(int(row["id"]) for row in project.schema)

    progress and progress("Checking geometry",0,len(records))
    basic,basic_meta=_basic_structural_signals(records,schema_ids)

    progress and progress("Checking distance geometry",0,len(records))
    distance,distance_meta=_distance_signals(records,shape_ids,group_by_image,reference_ids=reference_ids)

    definitions=_active_measurements_readonly(project)
    progress and progress("Checking measurements",0,len(records))
    measurements,measurement_meta=_measurement_signals(records,definitions,group_by_image,reference_ids=reference_ids)

    progress and progress("Running GM PCA",0,len(records))
    gm,gm_meta=_gm_signals(records,shape_ids,group_by_image)

    by_image=defaultdict(list)
    for mapping in (basic,distance,measurements,gm):
        for image_id,signal in mapping.items():
            by_image[image_id].append(signal)

    # The old permutation search is scientifically useful but was measured at
    # ~145 s for this project.  Use it only to refine the strongest candidates.
    ranked_candidates=sorted(
        by_image,
        key=lambda image_id:(
            0 if any(item.get("hard") for item in by_image[image_id]) else 1,
            -sum(min(10.0,float(item.get("score") or 0.0)) for item in by_image[image_id]),
            image_id,
        ),
    )
    logical=os.cpu_count() or 1
    stage2_budget=max(8,min(32,logical))
    stage2_ids=tuple(ranked_candidates[:stage2_budget])
    progress and progress("Checking identity on candidates",0,len(stage2_ids))
    established,established_meta=_existing_qc_signals(project,records,stage2_ids,progress=progress)
    established_meta["budget"]=stage2_budget
    established_meta["fast_candidates"]=len(ranked_candidates)
    for image_id,signal in established.items():
        by_image[image_id].append(signal)

    abbrs=_abbr_map(project)
    queue=[]
    for image_id,record in records.items():
        signals=by_image.get(image_id,[])
        if not signals:
            continue
        issue=_issue_from_signals(record,signals,abbrs)
        try:accepted=project.review_warning_is_accepted(image_id,issue)
        except Exception:accepted=False
        if not accepted:queue.append(issue)

    priority={"High":0,"Review":1}
    queue.sort(key=lambda item:(priority.get(item.get("priority"),9),-float(item.get("risk_score") or 0.0),item.get("display_name") or "",item["image_id"]))
    high=sum(item.get("priority")=="High" for item in queue)
    return {
        "cancelled":False,
        "scanned":len(records),
        "reference_images":len(reference_ids),
        "flagged":len(queue),
        "high":high,
        "review_total":len(queue),
        "queue":tuple(queue),
        "methods":{
            "basic":basic_meta,
            "established":established_meta,
            "distance":distance_meta,
            "measurements":measurement_meta,
            "gm":gm_meta,
        },
    }
