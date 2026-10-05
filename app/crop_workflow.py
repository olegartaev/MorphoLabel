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
        import math
        try:
            transform=Transform(**stored)
            if transform.version=="affine_crop_v1" and (transform.original_width,transform.original_height)==base.size and min(transform.output_width,transform.output_height)>0 and all(math.isfinite(float(v)) for v in (transform.rotation_degrees,transform.center_x,transform.center_y,transform.crop_left,transform.crop_top)):
                return transform
        except (ValueError,TypeError):pass
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
    new_transform = change["new_transform"]
    crop = change["crop"]
    rotated = base.rotate(float(angle), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255))
    master = rotated.crop(crop)
    saved = project.save_reviewed_crop(image_id, {
        "developed_full_relpath": f"cache/developed/{image_id}.png",
        "standardized_relpath": f"cache/standardized/{image_id}.png",
        "crop_bounds": list(crop), "rotation_degrees": float(angle),
        "transform": new_transform.__dict__, "normalization_status": "PASS", "source_sha256": None,
    })
    atomic_save_png(master, standard_path, image_id)
    write_standardized_frame_manifest(project, image_id, project.crop_record(image_id), target=standard_path)
    return {
        "present_before":0,"present_after":0,"outside_count":0,**saved,
        "review_required": project.landmark_crop_review_required(image_id),
        "legacy_landmarks_invalidated": bool(saved.get("legacy_landmarks_invalidated")),
        "landmarks_remapped": bool(saved.get("landmarks_remapped")),
    }
