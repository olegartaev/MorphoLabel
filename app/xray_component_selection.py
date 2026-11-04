"""Select X-ray structure sources without changing scientific annotations or model weights.

The *entire anatomical family* is routed together: reference roles on an ordered
series must not be detached from the model producing that series. Selection uses
paired human-verified specimens, not per-model training loss.
"""
from __future__ import annotations

from itertools import combinations

from .xray_schema import compatible_reference_roles

MAX_EXHAUSTIVE_FAMILIES = 8


def structure_families(scheme):
    """Partition schema structures, grouping dependent roles with their base series."""
    structures = list(scheme.get("structures") or ())
    ids = [str(item["id"]) for item in structures]
    parent = {ident: ident for ident in ids}

    def find(ident):
        while parent[ident] != ident:
            ident = parent[ident]
        return ident

    def union(left, right):
        if left in parent and right in parent:
            parent[find(right)] = find(left)

    for structure in structures:
        if not structure.get("repeated"):
            continue
        base = str(structure["id"])
        for role in compatible_reference_roles(scheme, base):
            union(base, str(role["id"]))
    groups = {}
    for ident in ids:
        groups.setdefault(find(ident), []).append(ident)
    return tuple(tuple(group) for group in groups.values())


def validated_routes(scheme, model_id, routes, registered_ids):
    """Return a complete, scientifically consistent structure-to-model mapping."""
    families = structure_families(scheme)
    active = str(model_id)
    known = set(registered_ids)
    if active not in known:
        raise ValueError("Active X-ray model is missing.")
    if not isinstance(routes, dict):
        raise ValueError("Invalid component source mapping.")
    legal = {ident for family in families for ident in family}
    if set(routes) - legal:
        raise ValueError("Component source mapping contains unknown structures.")
    result = {ident: str(routes.get(ident) or active) for ident in legal}
    if any(value not in known for value in result.values()):
        raise ValueError("Component source model is missing.")
    for family in families:
        if len({result[ident] for ident in family}) != 1:
            raise ValueError("Dependent anatomical markers must use the same model.")
    return result


def combine_marker_rows(scheme, sources, assignments):
    """Combine complete output families, without interpolating or inventing points."""
    legal = {str(item["id"]) for item in scheme.get("structures") or ()}
    if set(assignments) != legal:
        raise ValueError("Incomplete structure routing.")
    if any(model_id not in sources for model_id in assignments.values()):
        raise ValueError("Prediction is missing from a source model.")
    merged = []
    for ident in (str(item["id"]) for item in scheme.get("structures") or ()):
        source = assignments[ident]
        merged.extend(dict(point) for point in sources[source]
                      if str(point.get("structure_id") or "") == ident)
    return merged


def choose_routed_components(scheme, baseline_id, candidate_id, cases,
                             predictions, evaluate, baseline_routes=None, check=None):
    """Pick a safe combination on a shared cohort.

    cases: read-only human/crop/visibility records for exactly the same specimens.
    predictions: {model_id: {specimen_id: predicted marker rows}}.
    check(old_report, candidate_report): validated acceptance gate.
    No model is activated or stored here.
    """
    baseline_id = str(baseline_id)
    candidate_id = str(candidate_id)
    families = structure_families(scheme)
    routes = validated_routes(scheme, baseline_id, baseline_routes or {}, predictions)
    case_ids = [str(item.get("specimen_id") or "") for item in cases]
    if not cases or len(set(case_ids)) != len(case_ids) or not all(case_ids):
        raise ValueError("Cannot compare duplicate or unidentified specimens.")
    for model_id, by_case in predictions.items():
        if set(by_case) != set(case_ids):
            raise ValueError("All models must predict exactly the same verified specimens.")

    def compare(assignments):
        prepared = []
        for case in cases:
            sid = str(case["specimen_id"])
            selected = {model_id: predictions[model_id][sid] for model_id in set(assignments.values())}
            prepared.append({**case, "predicted": combine_marker_rows(scheme, selected, assignments)})
        return evaluate(scheme, prepared)

    baseline_report = compare(routes)
    check = check or (lambda old, new: (False, "No model promotion gate supplied."))
    choices = []
    family_count = len(families)
    if family_count <= MAX_EXHAUSTIVE_FAMILIES:
        for count in range(1, family_count + 1):
            choices.extend(combinations(range(family_count), count))
    else:
        choices = [(i,) for i in range(family_count)]
        choices.append(tuple(range(family_count)))
    best = None
    for indices in choices:
        trial = dict(routes)
        for index in indices:
            for ident in families[index]:
                trial[ident] = candidate_id
        if trial == routes:
            continue
        report = compare(trial)
        accepted, reason = check(baseline_report, report)
        if not accepted:
            continue
        summary = report["summary"]
        gains = int(summary["all_traits_correct_specimens"]) - int(
            baseline_report["summary"]["all_traits_correct_specimens"])
        changed_families = sum(1 for family in families
                               if trial[family[0]] != routes[family[0]])
        score = (gains, -changed_families)
        if best is None or score > best["score"]:
            best = {"routes": trial, "report": report, "score": score, "reason": reason}
    if best is None:
        return {"accepted": False, "routes": routes, "report": baseline_report,
                "reason": "No verified improvement from combining structure sources."}
    return {"accepted": True, "routes": best["routes"], "report": best["report"],
            "reason": best["reason"]}
