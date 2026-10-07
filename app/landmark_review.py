"""GUI-independent landmark-review checks and root-v1 eligibility."""
from __future__ import annotations

import math
import statistics
import hashlib
import json
import os
import logging
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from .performance_engine import cpu_worker_candidates, tune_workload
from .landmark_qc_geometry import pair_vector_reversal_metrics

_HUMAN_PROVENANCE = {"manual", "corrected", "corrected_by_human", "reviewed_by_human"}

def warning_landmark_ids(warning):
    values=warning.get("landmark_ids") or ()
    if not values:
        values=(warning.get("landmark_id"),warning.get("other_landmark_id"),warning.get("first_landmark_id"),warning.get("second_landmark_id"))
    return tuple(sorted({int(value) for value in values if value is not None}))

def warning_state_fingerprint(project, image_id, warning):
    """Stable fingerprint of precisely the human-reviewed final landmark states."""
    rows=project.load_landmarks(image_id)
    values=[]
    for landmark_id in warning_landmark_ids(warning):
        row=rows.get(landmark_id) or {}
        values.append({"landmark_id":landmark_id,"state":row.get("state"),"x_standardized":row.get("x_standardized"),"y_standardized":row.get("y_standardized")})
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()

def v1_training_preflight(project, **scan_options):
    """Training gate: only unresolved, unaccepted review warnings block v1."""
    result=scan_project(project, **scan_options)
    return {"eligible_image_ids":root_v1_eligible_image_ids(project),"unresolved_review_warnings":result["queue"],"review_result":result}
def root_v1_eligible_image_ids(project):
    """Return checked, non-excluded, fully manual current-schema images only."""
    eligible = []
    for image in project.catalog_rows():
        if image.get("excluded"):
            continue
        image_id = image["image_id"]
        status = project.annotation_status(image_id)
        points = project.load_landmarks(image_id)
        if not status["complete"] or not status["verified"]:
            continue
        if all((point := points.get(int(schema_row["id"]))) and (point["state"] == "missing" or point.get("provenance") in _HUMAN_PROVENANCE) for schema_row in project.schema):
            eligible.append(image_id)
    return tuple(sorted(eligible))

def structural_warnings(project, image_id, width, height, near=1e-6):
    """Return non-destructive warnings that need no cross-image reference set."""
    status = project.annotation_status(image_id)
    rows = project.load_landmarks(image_id)
    schema_ids = {int(row["id"]) for row in project.schema}
    warnings = [{"kind":"unresolved", "landmark_id":i, "message":f"Unresolved LM{i}"} for i in status["unresolved_ids"]]
    present = []
    for landmark_id, row in rows.items():
        if landmark_id not in schema_ids:
            warnings.append({"kind":"orphan", "landmark_id":landmark_id, "message":f"Orphan LM{landmark_id}"})
            continue
        if row["state"] == "missing":
            continue
        x, y = row.get("x_standardized"), row.get("y_standardized")
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (x, y)):
            warnings.append({"kind":"nonfinite", "landmark_id":landmark_id, "message":f"Non-finite LM{landmark_id}"})
            continue
        if not (0 <= x < width and 0 <= y < height):
            warnings.append({"kind":"bounds", "landmark_id":landmark_id, "message":f"Outside image LM{landmark_id}"})
        present.append((landmark_id, row))
    for index, (first_id, first) in enumerate(present):
        for second_id, second in present[index + 1:]:
            if math.hypot(first["x_standardized"]-second["x_standardized"], first["y_standardized"]-second["y_standardized"]) <= near:
                warnings.append({"kind":"duplicate", "landmark_id":first_id, "other_landmark_id":second_id, "message":f"Near-identical LM{first_id} / LM{second_id}"})
    return warnings

@dataclass(frozen=True)
class ReviewContext:
    dimensions_by_id: dict
    reference_ids: tuple
    reference_rows: dict
    profiles: dict | None
    profiles_by_image: dict


def build_review_context(project, catalog=None, min_refs=8, dimensions_by_id=None):
    """Prepare dimensions and robust human-reference profiles once per scan."""
    catalog = list(catalog if catalog is not None else project.catalog_rows())
    dimensions = dict(dimensions_by_id or {})
    if dimensions_by_id is None:
        for row in catalog:
            try: size = _standardized_dimensions(project, row["image_id"])
            except Exception: size = None
            if size: dimensions[row["image_id"]] = size
    reference_ids = tuple(root_v1_eligible_image_ids(project))
    reference_rows = {image_id: project.load_landmarks(image_id) for image_id in reference_ids}
    profiles = _profiles_from_reference_rows(project.schema, reference_ids, reference_rows, dimensions, min_refs)
    profiles_by_image = {image_id: _profiles_from_reference_rows(project.schema, tuple(i for i in reference_ids if i != image_id), reference_rows, dimensions, min_refs) for image_id in reference_ids}
    return ReviewContext(dimensions, reference_ids, reference_rows, profiles, profiles_by_image)
def _profiles_from_reference_rows(schema, reference_ids, reference_rows, dimensions, min_refs):
    usable = []
    schema_ids = [int(row["id"]) for row in schema]
    for image_id in reference_ids:
        width, height = dimensions.get(image_id, (0, 0))
        points = reference_rows.get(image_id, {})
        if not width or not height or not all(i in points and points[i].get("state") != "missing" and all(math.isfinite(points[i][key]) for key in ("x_standardized", "y_standardized")) for i in schema_ids):
            continue
        usable.append((points, width, height))
    if len(usable) < min_refs:
        return None
    profiles = {}
    for landmark_id in schema_ids:
        coordinates = [(points[landmark_id]["x_standardized"]/width, points[landmark_id]["y_standardized"]/height) for points, width, height in usable]
        centre_x = statistics.median(x for x, _ in coordinates); centre_y = statistics.median(y for _, y in coordinates)
        dispersion = max(1e-5, statistics.median(math.hypot(x-centre_x, y-centre_y) for x, y in coordinates))
        profiles[landmark_id] = (centre_x, centre_y, dispersion)
    return profiles
def _reference_profiles(project, image_id, dimensions_by_id, min_refs=8):
    """Per-landmark normalized median and robust radial MAD, leave-one-out."""
    schema_ids = [int(row["id"]) for row in project.schema]
    references = []
    for reference_id in root_v1_eligible_image_ids(project):
        if reference_id == image_id:
            continue
        width, height = dimensions_by_id.get(reference_id, (0, 0))
        points = project.load_landmarks(reference_id)
        if not width or not height or not all(i in points and points[i]["state"] != "missing" and all(math.isfinite(points[i][key]) for key in ("x_standardized","y_standardized")) for i in schema_ids):
            continue
        references.append((points, width, height))
    if len(references) < min_refs:
        return None
    profiles = {}
    for landmark_id in schema_ids:
        coordinates = [(points[landmark_id]["x_standardized"]/width, points[landmark_id]["y_standardized"]/height) for points,width,height in references]
        centre_x = statistics.median(x for x,_ in coordinates)
        centre_y = statistics.median(y for _,y in coordinates)
        dispersion = max(1e-5, statistics.median(math.hypot(x-centre_x, y-centre_y) for x,y in coordinates))
        profiles[landmark_id] = (centre_x, centre_y, dispersion)
    return profiles

def consistency_warnings(project, image_id, dimensions_by_id, min_refs=8, z=6.0, context=None):
    """Warn only against each landmark's own robust normalized distribution."""
    profiles = (context.profiles_by_image[image_id] if image_id in context.profiles_by_image else context.profiles) if context is not None else _reference_profiles(project, image_id, dimensions_by_id, min_refs)
    if not profiles or image_id not in dimensions_by_id:
        return []
    width, height = dimensions_by_id[image_id]
    rows = project.load_landmarks(image_id)
    warnings = []
    for landmark_id, (centre_x, centre_y, dispersion) in profiles.items():
        row = rows.get(landmark_id)
        if not row or row["state"] == "missing":
            continue
        x, y = row.get("x_standardized"), row.get("y_standardized")
        if not all(isinstance(value,(int,float)) and math.isfinite(value) for value in (x,y)):
            continue
        distance = math.hypot(x/width-centre_x, y/height-centre_y)
        if distance > z*dispersion:
            warnings.append({"kind":"spatial_outlier", "landmark_id":landmark_id, "message":f"Check LM{landmark_id}", "distance":distance, "dispersion":dispersion, "tolerance":z*dispersion})
    return warnings

def robust_swap_suggestions(project, image_id, dimensions_by_id, min_refs=8, context=None):
    """Suggest only a strong two-way improvement in each point's own distribution."""
    profiles = (context.profiles_by_image[image_id] if image_id in context.profiles_by_image else context.profiles) if context is not None else _reference_profiles(project, image_id, dimensions_by_id, min_refs)
    if not profiles or image_id not in dimensions_by_id:
        return []
    width, height = dimensions_by_id[image_id]
    rows = project.load_landmarks(image_id)
    suggestions = []
    def finite_present(row):
        if not row or row.get("state") == "missing":
            return False
        x, y = row.get("x_standardized"), row.get("y_standardized")
        return all(isinstance(value,(int,float)) and math.isfinite(value) for value in (x,y))
    def discrepancy(row, profile):
        return math.hypot(row["x_standardized"]/width-profile[0], row["y_standardized"]/height-profile[1]) / profile[2]
    ids = sorted(profiles)
    for index, first_id in enumerate(ids):
        first = rows.get(first_id)
        if not finite_present(first):
            continue
        for second_id in ids[index+1:]:
            second = rows.get(second_id)
            if not finite_present(second):
                continue
            own_first, own_second = discrepancy(first,profiles[first_id]), discrepancy(second,profiles[second_id])
            cross_first, cross_second = discrepancy(first,profiles[second_id]), discrepancy(second,profiles[first_id])
            if own_first>8 and own_second>8 and cross_first<3 and cross_second<3 and cross_first+cross_second < 0.35*(own_first+own_second):
                suggestions.append({"kind":"swap_suggestion", "first_landmark_id":first_id, "second_landmark_id":second_id, "message":f"Possible LM{first_id} ↔ LM{second_id}"})
    return suggestions

def review_warnings(project, image_id, width, height, dimensions_by_id=None, context=None):
    warnings = structural_warnings(project, image_id, width, height)
    if dimensions_by_id:
        warnings.extend(consistency_warnings(project, image_id, dimensions_by_id, context=context))
        warnings.extend(robust_swap_suggestions(project, image_id, dimensions_by_id, context=context))
    return warnings
def _standardized_dimensions(project, image_id):
    """Return existing cache dimensions; never loads source RAW/NEF."""
    path = project.cache_root / "standardized" / f"{image_id}.png"
    if not path.is_file():
        return None
    from PIL import Image
    with Image.open(path) as image:
        return image.size

def scan_project(project, progress=None, cancelled=None):
    """Read-only deterministic project-wide review queue, safe for a worker thread."""
    review_project = _review_snapshot(project)
    catalog = [row for row in review_project.catalog_rows() if not row.get("excluded")]
    dimensions = {row["image_id"]: _standardized_dimensions(project, row["image_id"]) for row in catalog}
    dimensions = {image_id: size for image_id, size in dimensions.items() if size}
    queue = []
    early = early_identity_warnings(project)
    use_early = 2 <= early["annotated_images"] < 8
    scanned = 0
    for row in catalog:
        if cancelled and cancelled():
            return {"cancelled": True, "scanned": scanned, "total": len(catalog), "queue": tuple()}
        image_id = row["image_id"]
        points = project.load_landmarks(image_id)
        # A completely untouched image has no annotation to review and must not
        # fill the project-wide queue with unresolved placeholders.
        if points:
            width, height = dimensions.get(image_id, (1, 1))
            warnings = structural_warnings(project, image_id, width, height)
            if image_id in dimensions:
                warnings.extend(consistency_warnings(project, image_id, dimensions))
                warnings.extend(robust_swap_suggestions(project, image_id, dimensions))
            for warning in warnings:
                warning = dict(warning)
                warning.update({"image_id": image_id, "display_name": row.get("display_name") or row.get("original_name") or image_id,
                                "index_in_locality": row.get("index_in_locality"), "severity": "warning"})
                queue.append(warning)
        scanned += 1
        if progress:
            progress(scanned, len(catalog))
    if use_early:
        for warning in early["warnings"]:
            warning = dict(warning)
            row = next(item for item in catalog if item["image_id"] == warning["image_id"])
            warning.update({"display_name": row.get("original_name") or warning["image_id"], "index_in_locality": row.get("index_in_locality")})
            queue.append(warning)
    order = {row["image_id"]: index for index, row in enumerate(catalog)}
    queue.sort(key=lambda item: (order[item["image_id"]], item.get("landmark_id", item.get("first_landmark_id", 0)), item["kind"]))
    return {"cancelled": False, "scanned": scanned, "total": len(catalog), "queue": tuple(queue), "images_needing_review": len({item["image_id"] for item in queue}), "early_cross_image": use_early, "early_annotated_images": early["annotated_images"], "statistical_reference": len(root_v1_eligible_image_ids(project)) >= 8}
# Early identity consistency: used only before a statistical Checked-reference pool exists.
def _finite_present_manual(rows, required_ids):
    return all(
        (row := rows.get(landmark_id)) and row.get("state") != "missing"
        and row.get("provenance") in _HUMAN_PROVENANCE
        and all(isinstance(row.get(key), (int, float)) and math.isfinite(row[key]) for key in ("x_standardized", "y_standardized"))
        for landmark_id in required_ids
    )

def early_manual_image_ids(project, min_landmarks=5):
    """Fully manual annotated images usable for early configuration comparisons."""
    required_ids = [int(row["id"]) for row in project.schema]
    if len(required_ids) < min_landmarks:
        return ()
    result = []
    for image in project.catalog_rows():
        if image.get("excluded"):
            continue
        rows = project.load_landmarks(image["image_id"])
        if _finite_present_manual(rows, required_ids):
            result.append(image["image_id"])
    return tuple(sorted(result))

def _similarity(source, target):
    """Least-squares 2D translation/rotation/uniform-scale source -> target."""
    if len(source) < 2:
        return None
    sx=sum(point[0] for point in source)/len(source); sy=sum(point[1] for point in source)/len(source)
    tx=sum(point[0] for point in target)/len(target); ty=sum(point[1] for point in target)/len(target)
    cross=dot=norm=0.0
    for (x,y),(u,v) in zip(source,target):
        x-=sx;y-=sy;u-=tx;v-=ty;cross+=x*v-y*u;dot+=x*u+y*v;norm+=x*x+y*y
    if norm <= 1e-12:
        return None
    scale=math.hypot(dot,cross)/norm
    cosine,sine=dot/math.hypot(dot,cross),cross/math.hypot(dot,cross)
    return sx,sy,tx,ty,scale,cosine,sine

def _apply(transform, point):
    sx,sy,tx,ty,scale,cosine,sine=transform;x,y=point[0]-sx,point[1]-sy
    return (tx+scale*(cosine*x-sine*y),ty+scale*(sine*x+cosine*y))

def _robust_alignment(source_rows, target_rows, excluded_ids):
    """Trim two largest residuals once so a few movable points cannot dominate."""
    shared=[identifier for identifier in source_rows if identifier in target_rows and identifier not in excluded_ids]
    if len(shared)<3:return None
    source=[(source_rows[i]['x_standardized'],source_rows[i]['y_standardized']) for i in shared]
    target=[(target_rows[i]['x_standardized'],target_rows[i]['y_standardized']) for i in shared]
    transform=_similarity(source,target)
    if transform is None:return None
    residuals=sorted((math.dist(_apply(transform,a),b),index) for index,(a,b) in enumerate(zip(source,target)))
    # Keep at least three alignment landmarks after trimming obvious outliers.
    if len(shared)>=5:
        keep={index for _,index in residuals[:-2]}
        transform=_similarity([source[i] for i in keep],[target[i] for i in keep]) or transform
    return transform

def _pair_vector_reversal_evidence(source_rows,target_rows,first_id,second_id):
    """Detect a conservative label swap after robust similarity alignment."""
    if not all(i in source_rows and i in target_rows for i in (first_id,second_id)):return None
    transform=_robust_alignment(source_rows,target_rows,{first_id,second_id})
    if transform is None:return None
    first=_apply(transform,(source_rows[first_id]['x_standardized'],source_rows[first_id]['y_standardized']))
    second=_apply(transform,(source_rows[second_id]['x_standardized'],source_rows[second_id]['y_standardized']))
    target_first=(target_rows[first_id]['x_standardized'],target_rows[first_id]['y_standardized'])
    target_second=(target_rows[second_id]['x_standardized'],target_rows[second_id]['y_standardized'])
    metrics=pair_vector_reversal_metrics(target_first,target_second,first,second,min_reference_length=2.0)
    if not metrics["vector_reversal"]:return None
    original_first=math.dist(first,target_first);original_second=math.dist(second,target_second)
    swapped_first=math.dist(first,target_second);swapped_second=math.dist(second,target_first)
    # A reversed vector alone is not enough: coordinated anatomical movement can
    # reverse an unrelated pair after alignment.  For an actual A<->B label
    # swap, each endpoint must independently fit the opposite identity better.
    if not (swapped_first<original_first and swapped_second<original_second):return None
    return {**metrics,"cost_original":original_first+original_second,"cost_swapped":swapped_first+swapped_second}

def _pair_swap_evidence(source_rows, target_rows, first_id, second_id):
    reversal=_pair_vector_reversal_evidence(source_rows,target_rows,first_id,second_id)
    transform=_robust_alignment(source_rows,target_rows,{first_id,second_id})
    if transform is None:return reversal
    first=_apply(transform,(source_rows[first_id]['x_standardized'],source_rows[first_id]['y_standardized']))
    second=_apply(transform,(source_rows[second_id]['x_standardized'],source_rows[second_id]['y_standardized']))
    target_first=(target_rows[first_id]['x_standardized'],target_rows[first_id]['y_standardized'])
    target_second=(target_rows[second_id]['x_standardized'],target_rows[second_id]['y_standardized'])
    original_first,original_second=math.dist(first,target_first),math.dist(second,target_second)
    swapped_first,swapped_second=math.dist(first,target_second),math.dist(second,target_first)
    original=original_first+original_second;swapped=swapped_first+swapped_second
    cross_swap=not (original <= 1e-6 or swapped >= .35*original or swapped_first >= .55*original_first or swapped_second >= .55*original_second)
    if not reversal and not cross_swap:return None
    result={"cost_original":original,"cost_swapped":swapped,"improvement":original-swapped,"cross_swap":bool(cross_swap),"vector_reversal":bool(reversal)}
    if reversal:result.update(reversal)
    return result

def batch_vector_swap_warnings(project,image_ids):
    """Find one-off pair-label reversals inside a completed manual batch.

    Each target is compared with the other available manual fish after robust
    similarity alignment excluding the tested pair. With >=3 usable fish a
    strict majority of references must vote for the reversal; with only two
    fish the result is reported as an ambiguity on both.
    """
    requested=tuple(dict.fromkeys(str(value) for value in image_ids))
    candidates=set(requested)
    manual_ids=tuple(early_manual_image_ids(project))
    if len(manual_ids)<2 or not candidates:return ()
    rows={image_id:_manual_rows(project,image_id) for image_id in manual_ids}
    schema_ids=[int(row['id']) for row in project.schema]
    warnings=[]
    for image_id in requested:
        source=rows.get(image_id) or {}
        if len(source)<5:continue
        references=[ref_id for ref_id in manual_ids if ref_id!=image_id]
        for pos,first_id in enumerate(schema_ids):
            for second_id in schema_ids[pos+1:]:
                if first_id not in source or second_id not in source:continue
                usable=0;votes=[]
                for ref_id in references:
                    target=rows.get(ref_id) or {}
                    if first_id not in target or second_id not in target:continue
                    transform=_robust_alignment(source,target,{first_id,second_id})
                    if transform is None:continue
                    usable+=1
                    evidence=_pair_vector_reversal_evidence(source,target,first_id,second_id)
                    if evidence:votes.append((ref_id,evidence))
                if not usable or not votes:continue
                accepted=(usable==1) or (len(votes)>=2 and len(votes)*2>usable)
                if not accepted:continue
                representative=min((e for _,e in votes),key=lambda item:item['pair_cos'])
                warnings.append({
                    "kind":"batch_vector_swap","image_id":image_id,
                    "landmark_id":first_id,"other_landmark_id":second_id,
                    "landmark_ids":[first_id,second_id],"severity":"advisory",
                    "message":f"Possible LM{first_id} ↔ LM{second_id} mix-up",
                    "reference_image_ids":[ref_id for ref_id,_ in votes],
                    "usable_reference_count":usable,"vote_count":len(votes),**representative,
                })
    # One warning per exact image/pair; ordering is deterministic.
    unique={}
    for warning in warnings:
        key=(warning['image_id'],tuple(warning['landmark_ids']))
        if key not in unique or warning['pair_cos']<unique[key]['pair_cos']:unique[key]=warning
    return tuple(sorted(unique.values(),key=lambda item:(item['image_id'],item['landmark_ids'][0],item['landmark_ids'][1])))

def early_identity_warnings(project):
    """Conservative pairwise identity checks for 2–7 manual configurations."""
    image_ids=early_manual_image_ids(project)
    if len(image_ids)<2:return {"available":False,"annotated_images":len(image_ids),"warnings":()}
    rows={image_id:project.load_landmarks(image_id) for image_id in image_ids};ids=[int(row['id']) for row in project.schema]
    evidence={}
    for left_index,left_id in enumerate(image_ids):
        for right_id in image_ids[left_index+1:]:
            for first_index,first_id in enumerate(ids):
                for second_id in ids[first_index+1:]:
                    # Early identity checks are deliberately conservative: a true
                    # pair-label reversal is strong evidence, while the broader
                    # cross-distance heuristic can misclassify coordinated
                    # anatomical movement as a swap before a trusted reference
                    # pool exists.
                    result=_pair_vector_reversal_evidence(rows[left_id],rows[right_id],first_id,second_id)
                    if result:evidence.setdefault((first_id,second_id),[]).append((left_id,right_id,result))
    warnings=[]
    for (first_id,second_id),pairs in evidence.items():
        if len(image_ids)==2:
            for image_id in image_ids:
                warnings.append({"kind":"early_identity_inconsistency","image_id":image_id,"landmark_id":first_id,"other_landmark_id":second_id,"severity":"advisory","message":f"LM{first_id} / LM{second_id} labeling is inconsistent between 2 images","paired_image_id":image_ids[1] if image_id==image_ids[0] else image_ids[0]})
            continue
        votes={image_id:0 for image_id in image_ids}
        for left_id,right_id,_ in pairs:votes[left_id]+=1;votes[right_id]+=1
        suspect=max(votes,key=votes.get)
        # A consensus needs the suspect to disagree with at least two other images
        # and more often than any individual reference image.
        if votes[suspect]>=2 and list(votes.values()).count(votes[suspect])==1:
            warnings.append({"kind":"early_swap_suggestion","image_id":suspect,"landmark_id":first_id,"other_landmark_id":second_id,"severity":"advisory","message":f"LM{first_id} and LM{second_id} may be swapped","pair_count":len(pairs)})
    return {"available":True,"annotated_images":len(image_ids),"warnings":tuple(warnings)}
# Gate correction: trusted semantic references are useful from the first Checked manual fish.
def _human_row(row):
    return bool(row) and row.get("provenance") in _HUMAN_PROVENANCE and row.get("state") != "missing" and all(isinstance(row.get(k),(int,float)) and math.isfinite(row[k]) for k in ("x_standardized","y_standardized"))

def _trusted_reference_ids(project):
    return root_v1_eligible_image_ids(project)

def _manual_rows(project, image_id):
    return {i:r for i,r in project.load_landmarks(image_id).items() if _human_row(r)}

def _group_score(source_rows, reference_rows, group):
    """Return every 2–4 assignment cost after alignment excluding the full group."""
    import itertools
    group=tuple(group)
    if not all(i in source_rows and i in reference_rows for i in group):return None
    transform=_robust_alignment(source_rows,reference_rows,set(group))
    if transform is None:return None
    transformed={i:_apply(transform,(source_rows[i]['x_standardized'],source_rows[i]['y_standardized'])) for i in group}
    identity=group;costs=[]
    for assignment in itertools.permutations(group):
        cost=sum(math.dist(transformed[assignment[index]],(reference_rows[target]['x_standardized'],reference_rows[target]['y_standardized'])) for index,target in enumerate(group))
        costs.append((cost,assignment))
    costs.sort(key=lambda item:(item[0],item[1]));current=next(cost for cost,assignment in costs if assignment==identity);best_cost,best=costs[0]
    ratio=(best_cost/current) if current>1e-9 else 1.0
    return {"group":group,"current_assignment_cost":current,"best_assignment_cost":best_cost,"best_permutation":best,"improvement_ratio":ratio,"accepted":best!=identity and ratio<=.40}

def trusted_identity_warnings(project, image_ids=None):
    """Conservative 2–4 local permutation suggestions against Checked manual refs.

    Candidate IDs are applied before the expensive reference/group loop so
    finite-batch and Complex-QC stage-2 work scales with the requested subset.
    """
    refs=_trusted_reference_ids(project);ids=[int(row['id']) for row in project.schema]
    requested=None if image_ids is None else {str(value) for value in image_ids}
    if not refs:return {"available":False,"reference_ids":(),"warnings":()}
    # The identity calculation is read-only but historically rebuilt the same
    # manual-row dictionaries for every image/reference/group combination.
    # Cache each image once while preserving the exact scoring and ordering.
    rows_cache={}
    def manual_rows_cached(image_id):
        if image_id not in rows_cache:
            rows_cache[image_id]=_manual_rows(project,image_id)
        return rows_cache[image_id]
    warnings=[]
    # Adjacent local groups cover anatomical neighbourhoods without factorially
    # searching the whole schema; pairs are included for ordinary swaps.
    groups=[]
    for width in (2,3,4):groups.extend(tuple(ids[start:start+width]) for start in range(len(ids)-width+1))
    for image in project.catalog_rows():
        if image.get('excluded') or image['image_id'] in refs:continue
        if requested is not None and str(image['image_id']) not in requested:continue
        source=manual_rows_cached(image['image_id'])
        for group in groups:
            scores=[]
            for ref_id in refs:
                score=_group_score(source,manual_rows_cached(ref_id),group)
                if score:scores.append((ref_id,score))
            accepted=[(ref_id,score) for ref_id,score in scores if score['accepted']]
            if not accepted:continue
            # With several trusted references demand the same best permutation
            # from a strict majority of usable comparisons.
            best=accepted[0][1]['best_permutation']
            agreeing=[(ref_id,score) for ref_id,score in accepted if score['best_permutation']==best]
            if len(refs)>1 and len(agreeing)*2<=len(scores):continue
            representative=min(agreeing,key=lambda item:item[1]['improvement_ratio'])[1]
            message=(f"LM{group[0]} and LM{group[1]} may be swapped" if len(group)==2 else f"LM{group[0]}–LM{group[-1]} may be misassigned")
            warnings.append({"kind":"trusted_reassignment","image_id":image['image_id'],"landmark_id":group[0],"landmark_ids":list(group),"severity":"advisory","message":message,"reference_image_ids":[ref_id for ref_id,_ in agreeing],**representative})
    # One smallest, strongest local explanation per image prevents nested 3/4-point variants from cluttering the queue.
    dedup={}
    for warning in warnings:
        key=warning['image_id']
        if key not in dedup or (len(warning['landmark_ids']),warning['improvement_ratio']) < (len(dedup[key]['landmark_ids']),dedup[key]['improvement_ratio']):dedup[key]=warning
    return {"available":True,"reference_ids":tuple(refs),"warnings":tuple(sorted(dedup.values(),key=lambda item:(item['image_id'],item['improvement_ratio'],len(item['landmark_ids']))))}

def early_manual_image_ids(project, min_landmarks=5):
    """Manual candidates; explicit missing is allowed and filtered per group."""
    result=[]
    for image in project.catalog_rows():
        if image.get('excluded'):continue
        if len(_manual_rows(project,image['image_id']))>=min_landmarks:result.append(image['image_id'])
    return tuple(sorted(result))

class _ReviewSnapshotProject:
    """Minimal immutable Project view used by a single read-only review scan."""
    def __init__(self, schema, catalog, points_by_image, verified, dimensions_by_id=None):
        self.schema = tuple(schema)
        self._catalog = tuple(catalog)
        self._points = points_by_image
        self._verified = verified
        self.dimensions_by_id = dict(dimensions_by_id or {})
        self._required = frozenset(int(row["id"]) for row in self.schema)

    def catalog_rows(self):
        return [dict(row) for row in self._catalog]

    def load_landmarks(self, image_id):
        return self._points.get(image_id, {})

    def annotation_status(self, image_id):
        rows = self.load_landmarks(image_id)
        present = {identifier for identifier,row in rows.items() if identifier in self._required and row.get("state") != "missing" and row.get("x_standardized") is not None and row.get("y_standardized") is not None}
        explicit_missing = {identifier for identifier,row in rows.items() if identifier in self._required and row.get("state") == "missing"}
        unresolved = self._required - present - explicit_missing
        human = {identifier for identifier in present if rows[identifier].get("provenance") in _HUMAN_PROVENANCE}
        verified = bool(self._verified.get(image_id, False))
        return {"image_id":image_id,"placed":len(present),"resolved":len(present | explicit_missing),"expected":len(self._required),"human_placed":len(human),"verified":verified,"missing":sorted(unresolved),"missing_ids":sorted(unresolved),"unresolved_ids":sorted(unresolved),"explicitly_missing_ids":sorted(explicit_missing),"extra_ids":sorted(set(rows)-self._required),"complete":not unresolved,"color":"red" if unresolved else "green" if verified else "yellow"}


def _review_snapshot(project):
    """One coordinator-only SQLite read; workers receive only plain Python data."""
    with project.transaction() as connection:
        catalog = [dict(row) for row in connection.execute("SELECT * FROM images WHERE COALESCE(active,1)=1 ORDER BY locality COLLATE NOCASE,index_in_locality,relative_path")]
        point_rows = connection.execute("SELECT * FROM landmarks").fetchall()
        review_rows = connection.execute("SELECT image_id,human_verified FROM image_review").fetchall()
        crop_rows = connection.execute("SELECT image_id,transform_json FROM crops WHERE transform_json IS NOT NULL").fetchall()
    points_by_image = {}
    display_by_abbr = {str(row["abbr"]): int(row["id"]) for row in project.schema}
    for row in point_rows:
        data = dict(row)
        display_id = display_by_abbr.get(str(data.get("landmark_abbr") or ""))
        if display_id is None:
            continue
        points_by_image.setdefault(data["image_id"], {})[display_id] = data
    verified = {row["image_id"]:bool(project.annotation_status(row["image_id"])["verified"]) for row in review_rows}
    dimensions = {}
    for row in crop_rows:
        try:
            transform = json.loads(row["transform_json"])
            width, height = int(transform["output_width"]), int(transform["output_height"])
            if width > 0 and height > 0: dimensions[str(row["image_id"])] = (width, height)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return _ReviewSnapshotProject(project.schema, catalog, points_by_image, verified, dimensions)
def adaptive_review_workers(logical_cpu_count=None):
    """Bounded portable policy: reserve one logical CPU for Tk/Windows."""
    logical = (os.cpu_count() if logical_cpu_count is None else logical_cpu_count) or 1
    return 1 if logical <= 2 else logical - 1


def _standardized_dimensions_path(path):
    from PIL import Image
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _structural_warnings_snapshot(payload):
    """Pure worker calculation: no Tk, SQLite or Project object access."""
    image_id, points, status, schema_ids, dimensions = payload
    width, height = dimensions or (1, 1)
    warnings = [{"kind":"unresolved", "landmark_id":identifier, "message":f"Unresolved LM{identifier}"} for identifier in status["unresolved_ids"]]
    present = []
    for landmark_id, row in points.items():
        if landmark_id not in schema_ids:
            warnings.append({"kind":"orphan", "landmark_id":landmark_id, "message":f"Orphan LM{landmark_id}"})
            continue
        if row.get("state") == "missing":
            continue
        x, y = row.get("x_standardized"), row.get("y_standardized")
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (x, y)):
            warnings.append({"kind":"nonfinite", "landmark_id":landmark_id, "message":f"Non-finite LM{landmark_id}"})
            continue
        if not (0 <= x < width and 0 <= y < height):
            warnings.append({"kind":"bounds", "landmark_id":landmark_id, "message":f"Outside image LM{landmark_id}"})
        present.append((landmark_id, row))
    for index, (first_id, first) in enumerate(present):
        for second_id, second in present[index + 1:]:
            if math.hypot(first["x_standardized"]-second["x_standardized"], first["y_standardized"]-second["y_standardized"]) <= 1e-6:
                warnings.append({"kind":"duplicate", "landmark_id":first_id, "other_landmark_id":second_id, "message":f"Near-identical LM{first_id} / LM{second_id}"})
    return image_id, warnings


def scan_project(project, progress=None, cancelled=None, workers=None, executor_factory=ThreadPoolExecutor, image_ids=None):
    """Read-only deterministic review scan with an adaptive bounded worker pool.

    SQLite/project reads happen in this coordinator. Workers receive only immutable
    Python snapshots and never touch Tk, SQLite or canonical project state.
    """
    import time
    started = time.perf_counter()
    review_project = _review_snapshot(project)
    all_catalog = [row for row in review_project.catalog_rows() if not row.get("excluded")]
    requested = None if image_ids is None else {str(value) for value in image_ids}
    catalog = all_catalog if requested is None else [row for row in all_catalog if str(row["image_id"]) in requested]
    logical = os.cpu_count() or 1
    worker_count = adaptive_review_workers(logical) if workers is None else max(1, int(workers))
    schema_ids = frozenset(int(row["id"]) for row in review_project.schema)
    snapshots = []
    dimension_paths = []
    dimensions_list = []
    for row in catalog:
        if cancelled and cancelled():
            return {"cancelled":True, "scanned":0, "total":len(catalog), "queue":tuple()}
        image_id = row["image_id"]
        # Keep the coordinator fully snapshot-based: no per-image SQLite reads.
        points = review_project.load_landmarks(image_id)
        snapshots.append((row, points, review_project.annotation_status(image_id)))
        dimensions_list.append(review_project.dimensions_by_id.get(image_id))
        dimension_paths.append(project.cache_root / "standardized" / f"{image_id}.png")
    for index, path in enumerate(dimension_paths):
        if dimensions_list[index] is None: dimensions_list[index] = _standardized_dimensions_path(path)
    probe_dimensions = dict(review_project.dimensions_by_id)
    probe_dimensions.update({snapshots[index][0]["image_id"]: dimensions_list[index] for index in range(len(snapshots)) if dimensions_list[index]})
    # Robust distribution checks need dimensions of the Checked reference pool
    # even when only one finite batch is being scanned.
    for reference_id in root_v1_eligible_image_ids(review_project):
        if reference_id not in probe_dimensions:
            size = _standardized_dimensions_path(project.cache_root / "standardized" / f"{reference_id}.png")
            if size: probe_dimensions[reference_id] = size
    review_context = build_review_context(review_project, all_catalog, dimensions_by_id=probe_dimensions)
    sample_payloads = [(snapshots[index][0]["image_id"], snapshots[index][1], snapshots[index][2], schema_ids, dimensions_list[index]) for index in range(min(64, len(snapshots)))]
    if workers is None and hasattr(project, "data_root") and sample_payloads:
        def probe_review(worker):
            started_probe = time.perf_counter()
            def full_score(payload):
                image_id, points, status, ids, dims = payload
                width, height = dims or (1, 1)
                return review_warnings(review_project, image_id, width, height, probe_dimensions, context=review_context)
            results = [full_score(payload) for payload in sample_payloads] if worker == 1 else None
            if worker != 1:
                with executor_factory(max_workers=worker) as probe_executor: results = list(probe_executor.map(full_score, sample_payloads))
            signature = json.dumps(results, sort_keys=True, default=str, separators=(",", ":"))
            return {"items_per_sec": len(sample_payloads) / max(time.perf_counter() - started_probe, 1e-9), "signature": signature}
        baseline_probe = probe_review(1)
        tuned = tune_workload(project, workload="landmark_project_scan", variant="v4_bulk_snapshot", candidates=cpu_worker_candidates(), probe=probe_review, safe_fallback=worker_count, equivalence_guard=lambda _c, result: result.get("signature") == baseline_probe.get("signature"))
        worker_count = int(tuned["chosen"] or worker_count)
    parallel_fallback = False
    parallel_error = None
    try:
        if worker_count == 1:
            structural = [_structural_warnings_snapshot((row["image_id"], points, status, schema_ids, dimensions_list[index])) for index,(row,points,status) in enumerate(snapshots)]
        else:
            with executor_factory(max_workers=worker_count) as executor:
                payloads = ((row["image_id"], points, status, schema_ids, dimensions_list[index]) for index,(row,points,status) in enumerate(snapshots))
                structural = list(executor.map(_structural_warnings_snapshot, payloads))
    except Exception as exc:
        # Atomic safety: discard any partial worker output and recompute serially.
        logging.getLogger(__name__).exception("Landmark Review worker pool failed; falling back to serial")
        parallel_fallback = True
        parallel_error = repr(exc)
        structural = [_structural_warnings_snapshot((row["image_id"], points, status, schema_ids, dimensions_list[index])) for index,(row,points,status) in enumerate(snapshots)]
    dimensions = {row["image_id"]: size for (row,_points,_status),size in zip(snapshots,dimensions_list) if size}
    trusted = trusted_identity_warnings(review_project, image_ids=requested)
    early = early_identity_warnings(review_project) if not trusted["available"] else {"available":False,"annotated_images":len(early_manual_image_ids(review_project)),"warnings":()}
    if requested is not None: early = {**early, "warnings": tuple(item for item in early.get("warnings",()) if str(item.get("image_id")) in requested)}
    batch_swaps=batch_vector_swap_warnings(review_project,tuple(row['image_id'] for row in catalog)) if requested is not None else ()
    queue = []
    scanned = 0
    total = len(catalog)
    throttle = max(1, total // 100)
    for index, ((row, points, _status), (_image_id, warnings)) in enumerate(zip(snapshots, structural), 1):
        if cancelled and cancelled():
            return {"cancelled":True,"scanned":scanned,"total":total,"queue":tuple()}
        image_id = row["image_id"]
        if points:
            if len(trusted["reference_ids"]) >= 8 and image_id in dimensions:
                warnings = list(warnings) + consistency_warnings(review_project,image_id,dimensions,context=review_context) + robust_swap_suggestions(review_project,image_id,dimensions,context=review_context)
            for warning in warnings:
                item = dict(warning)
                item.update({"image_id":image_id,"display_name":row.get("original_name") or image_id,"index_in_locality":row.get("index_in_locality"),"severity":item.get("severity","warning")})
                if not project.review_warning_is_accepted(image_id,item):queue.append(item)
        scanned = index
        if progress and (index == total or index % throttle == 0):
            progress(index,total)
    for warning in (trusted["warnings"] if trusted["available"] else early["warnings"]):
        item = dict(warning)
        row = next(row for row in catalog if row["image_id"] == item["image_id"])
        item.update({"display_name":row.get("original_name") or item["image_id"],"index_in_locality":row.get("index_in_locality")})
        if not project.review_warning_is_accepted(item["image_id"],item):queue.append(item)
    existing_pairs={(item.get('image_id'),tuple(warning_landmark_ids(item))) for item in queue if len(warning_landmark_ids(item))>=2}
    for warning in batch_swaps:
        item=dict(warning);pair=(item.get('image_id'),tuple(warning_landmark_ids(item)))
        if pair in existing_pairs:continue
        row=next((row for row in catalog if row["image_id"]==item["image_id"]),None)
        if row is None:continue
        item.update({"display_name":row.get("original_name") or item["image_id"],"index_in_locality":row.get("index_in_locality")})
        if not project.review_warning_is_accepted(item["image_id"],item):
            queue.append(item);existing_pairs.add(pair)
    order = {row["image_id"]:index for index,row in enumerate(catalog)}
    queue.sort(key=lambda item:(order[item["image_id"]],item.get("improvement_ratio",1),item["kind"]))
    return {"cancelled":False,"scanned":scanned,"total":total,"queue":tuple(queue),"images_needing_review":len({item["image_id"] for item in queue}),"trusted_reference_identity":trusted["available"],"trusted_reference_ids":list(trusted["reference_ids"]),"early_cross_image":early["available"],"early_annotated_images":early.get("annotated_images",len(early_manual_image_ids(review_project))),"statistical_reference":len(trusted["reference_ids"])>=8,"manual_annotations_available":len(early_manual_image_ids(review_project)),"logical_cpu_count":logical,"worker_count":worker_count,"parallel_fallback":parallel_fallback,"parallel_error":parallel_error,"elapsed_seconds":time.perf_counter()-started}
