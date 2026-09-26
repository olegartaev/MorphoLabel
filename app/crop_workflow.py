"""Reusable, UI-independent application of a reviewed crop transform."""
from __future__ import annotations
from PIL import Image
from .transforms import Transform
from .png_atomic import atomic_save_png
from .gui_crop_debug import log
from .landmark_frames import write_standardized_frame_manifest


def previous_transform(project, image_id, base, standard_path):
    """Return a provable prior frame, or ``None`` for legacy-frame reconciliation."""
    rows = project.load_landmarks(image_id).values()
    needs_transform = any((row.get("x_standardized") is not None and row.get("y_standardized") is not None) or (row.get("predicted_x") is not None and row.get("predicted_y") is not None) for row in rows)
    if not needs_transform:
        return None
    crop = project.crop_record(image_id) or {}
    stored = crop.get("transform_json")
    if stored:
        return Transform(**stored)
    bounds = crop.get("crop_json")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        left, top, right, bottom = (round(float(value)) for value in bounds)
        if right > left and bottom > top:
            return Transform(base.width, base.height, float(crop.get("rotation_degrees") or 0), base.width / 2, base.height / 2, left, top, right - left, bottom - top)
    if standard_path.exists():
        with Image.open(standard_path) as standard:
            if standard.size == (base.width, base.height):
                return Transform(base.width, base.height, 0, base.width / 2, base.height / 2, 0, 0, base.width, base.height)
    # A legacy row can contain points but no scientifically provable frame.  The
    # Project save authority archives and invalidates those finals; Crop itself
    # must remain usable rather than presenting a routine modal dead-end.
    return None


def reviewed_crop_change(project, image_id, base, bounds, angle, standard_path):
    """Describe a proposed reviewed Crop frame without mutating project state."""
    old_transform = previous_transform(project, image_id, base, standard_path)
    crop = tuple(round(float(value)) for value in bounds)
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError("Crop must have a positive width and height.")
    new_transform = Transform(
        base.width, base.height, float(angle), base.width / 2, base.height / 2,
        crop[0], crop[1], crop[2] - crop[0], crop[3] - crop[1],
    )
    had_landmarks = bool(project.load_landmarks(image_id))
    return {
        "crop": crop,
        "old_transform": old_transform,
        "new_transform": new_transform,
        "had_landmarks": had_landmarks,
        "frame_changed": old_transform is None or old_transform != new_transform,
    }


def apply_reviewed_crop(project, image_id, base, bounds, angle, standard_path, source_path):
    """Persist the same reversible reviewed crop used by the established editor."""
    change = reviewed_crop_change(project, image_id, base, bounds, angle, standard_path)
    old_transform = change["old_transform"]
    new_transform = change["new_transform"]
    crop = change["crop"]
    rotated = base.rotate(float(angle), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255))
    master = rotated.crop(crop)
    atomic_save_png(master, standard_path, image_id)
    had_landmarks = change["had_landmarks"]
    frame_changed = change["frame_changed"]
    saved = project.save_reviewed_crop(image_id, {
        "developed_full_relpath": f"cache/developed/{image_id}.png",
        "standardized_relpath": f"cache/standardized/{image_id}.png",
        "crop_bounds": list(crop), "rotation_degrees": float(angle),
        "transform": new_transform.__dict__, "normalization_status": "PASS", "source_sha256": None,
    }, previous_frame_proven=old_transform is not None)
    write_standardized_frame_manifest(project, image_id, project.crop_record(image_id), target=standard_path)
    remap = {"present_before": 0, "present_after": 0, "outside_count": 0}
    if had_landmarks and old_transform is not None and frame_changed:
        # Preserve biological positions through the crop-frame change:
        # old standardized -> original -> new standardized. The Project remap
        # authority clears Checked state and leaves the image requiring review.
        remap = project.remap_landmarks_for_transform(image_id, old_transform, new_transform)
    return {
        **remap,
        "review_required": project.landmark_crop_review_required(image_id),
        "legacy_landmarks_invalidated": bool(saved.get("legacy_landmarks_invalidated")),
        "landmarks_remapped": bool(had_landmarks and old_transform is not None and frame_changed),
    }
