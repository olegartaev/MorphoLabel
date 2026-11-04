"""Conservative automatic model promotion using common, untouched source plates.

This policy does not claim independent generalisation from repeatedly examined
validation plates. It never uses machine proposals as reference annotations.
"""
from __future__ import annotations

import math

MIN_COMMON_SPECIMENS = 12
MIN_COMMON_PLATES = 3


def common_validation_specimens(project, previous, candidate):
    """Return common verified validation IDs, excluding training plates of all ancestors."""
    if not previous or not candidate or previous.get("schema_digest") != candidate.get("schema_digest"):
        return (), "Models use different scientific schemes."
    by_id = {item["model_id"]: item for item in project.structure_models()}
    models_to_check = set()
    for root in (previous, candidate):
        seen = set()
        model = root
        while model:
            ident = str(model["model_id"])
            if ident in seen:
                return (), "Invalid model ancestry."
            seen.add(ident)
            models_to_check.add(ident)
            parent_id = model.get("parent_model_id")
            if parent_id and parent_id not in by_id:
                return (), "Model ancestry is incomplete."
            model = by_id.get(parent_id) if parent_id else None
    memberships = {}
    training_plates = set()
    for model_id in models_to_check:
        entries = project.structure_model_membership(model_id)
        if not entries:
            return (), "Training history is not sufficient for fair comparison."
        memberships[model_id] = entries
        for entry in entries:
            if entry["split"] == "train":
                try:
                    training_plates.add(project.specimen(entry["specimen_id"])["image_id"])
                except (KeyError, ValueError):
                    return (), "Training specimen metadata is missing."
    old_val = {str(x["specimen_id"]) for x in memberships[previous["model_id"]] if x["split"] == "val"}
    new_val = {str(x["specimen_id"]) for x in memberships[candidate["model_id"]] if x["split"] == "val"}
    safe = []
    plate_ids = set()
    for specimen_id in sorted(old_val & new_val):
        try:
            plate = project.specimen(specimen_id)["image_id"]
            run = project.annotation_run(specimen_id, 1, "human", False)
        except (KeyError, ValueError):
            continue
        if plate in training_plates or not run or run.get("status") != "verified":
            continue
        safe.append(specimen_id)
        plate_ids.add(plate)
    if len(safe) < MIN_COMMON_SPECIMENS or len(plate_ids) < MIN_COMMON_PLATES:
        return (), "Not enough shared, human-verified validation plates."
    return tuple(safe), ""


def _numeric(value):
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def choose_better_model(previous_report, candidate_report):
    """Strict paired gate: improve fully correct specimens without degrading any scored trait."""
    before = previous_report.get("summary") or {}
    after = candidate_report.get("summary") or {}
    if (previous_report.get("failures") or candidate_report.get("failures")
            or before.get("prediction_failures") or after.get("prediction_failures")
            or before.get("skipped_not_verified") or after.get("skipped_not_verified")):
        return False, "Model comparison was incomplete."
    n = before.get("all_traits_evaluable_specimens")
    if not isinstance(n, int) or n < MIN_COMMON_SPECIMENS or n != after.get("all_traits_evaluable_specimens"):
        return False, "Not enough comparable complete trait results."
    old_correct = before.get("all_traits_correct_specimens")
    new_correct = after.get("all_traits_correct_specimens")
    if not isinstance(old_correct, int) or not isinstance(new_correct, int):
        return False, "Complete trait scores are missing."
    improvement = new_correct - old_correct
    if improvement < max(2, math.ceil(n * .05)):
        return False, "No sufficiently clear improvement across complete specimens."
    old_traits = {row["trait_id"]: row for row in previous_report.get("traits") or ()}
    new_traits = {row["trait_id"]: row for row in candidate_report.get("traits") or ()}
    if not old_traits or set(old_traits) != set(new_traits):
        return False, "Cannot compare all scientific traits."
    for ident, old in old_traits.items():
        new = new_traits[ident]
        if old.get("evaluated") != new.get("evaluated"):
            return False, "Trait evaluation groups do not match."
        if old.get("correct") is not None:
            if new.get("correct") is None or int(new["correct"]) < int(old["correct"]):
                return False, "At least one scientific trait became less accurate."
        elif old.get("mae") is not None:
            if not _numeric(new.get("mae")) or float(new["mae"]) > float(old["mae"]):
                return False, "A continuous scientific trait became less accurate."
    old_structures = {row["structure_id"]: row for row in previous_report.get("structures") or ()}
    new_structures = {row["structure_id"]: row for row in candidate_report.get("structures") or ()}
    if not old_structures or set(old_structures) != set(new_structures):
        return False, "Cannot compare all marker types."
    for ident, old in old_structures.items():
        new = new_structures[ident]
        if old.get("n") != new.get("n"):
            return False, "Marker evaluation groups do not match."
        for metric, allowance, lower_is_better in (
            ("count_mae", 0.0, True),
            ("localization_median_diag", 0.003, True),
            ("localization_p95_diag", 0.005, True),
            ("role_accuracy", 0.0, False),
            ("f1", 0.02, False),
        ):
            previous = old.get(metric)
            current = new.get(metric)
            if previous is None:
                continue
            if not _numeric(previous) or not _numeric(current):
                return False, "A previously measured marker quality metric is missing."
            if lower_is_better and float(current) > float(previous) + allowance + 1e-12:
                return False, "Marker geometry or count accuracy became worse."
            if not lower_is_better and float(current) < float(previous) - allowance - 1e-12:
                return False, "Marker geometry or count accuracy became worse."
    return True, "Better on shared validation images without measured trait regressions."
