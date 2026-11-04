"""Small schema-driven family helpers for X-ray training method calibration.

Only groups declared dependent in the scientific scheme are kept together.
No fish-specific structural names or legacy model-selection code belongs here.
"""
from __future__ import annotations

from .xray_schema import compatible_reference_roles


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


