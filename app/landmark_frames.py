"""Canonical cropped frames for landmarking and landmark training.

The persisted crop transform is the scientific frame identity. A PNG beneath
``cache/standardized`` is only a derived cache and can be restored without
changing any crop or landmark record.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
from datetime import datetime
from PIL import Image

from .normalization_pipeline import develop_full
from .png_atomic import atomic_save_png
from .io import atomic_json_write, read_json
from .transforms import Transform


class LandmarkFrameError(ValueError):
    pass


def _relative_path(project, value, default):
    """Resolve current and legacy persisted project-relative cache paths.

    Current records are relative to project.data_root. Older records may
    already include the project_data prefix; joining those to data_root would
    incorrectly produce project_data/project_data.
    """
    value = Path(str(value or default))
    if value.is_absolute():
        return value
    data_root = Path(project.data_root)
    if value.parts and value.parts[0].casefold() == data_root.name.casefold():
        return Path(project.root) / value
    return data_root / value


def crop_frame_record(project, image_id):
    """Return a validated persisted crop record, otherwise ``None``.

    This intentionally never infers a crop from a developed image.
    """
    crop = project.crop_record(image_id)
    if not crop:
        return None
    bounds = crop.get("crop_json")
    transform = crop.get("transform_json")
    if not isinstance(bounds, list) or len(bounds) != 4 or not isinstance(transform, dict):
        return None
    try:
        left, top, right, bottom = (float(value) for value in bounds)
        parsed = Transform(**transform)
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top or parsed.output_width <= 0 or parsed.output_height <= 0:
        return None
    source = project.image_path(image_id)
    developed = _relative_path(project, crop.get("developed_relpath"), f"cache/developed/{image_id}.png")
    standardized = _relative_path(project, crop.get("standardized_relpath"), f"cache/standardized/{image_id}.png")
    # A persisted standardized crop is already a valid canonical landmark
    # frame. Do not demand the source/developed cache again just to display it.
    if not (source and source.is_file()) and not developed.is_file() and not standardized.is_file():
        return None
    return crop


def standardized_frame_path(project, image_id, crop=None):
    crop = crop or crop_frame_record(project, image_id)
    if not crop:
        return None
    return _relative_path(project, crop.get("standardized_relpath"), f"cache/standardized/{image_id}.png")


def _standardized_manifest_path(target):
    return Path(target).with_name(Path(target).name + ".frame.json")


def _crop_geometry_sha256(crop):
    payload = {
        "crop_json": crop.get("crop_json"),
        "transform_json": crop.get("transform_json"),
        "rotation_degrees": crop.get("rotation_degrees"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _developed_signature(path):
    path = Path(path)
    if not path.is_file():
        return None
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(getattr(stat, "st_mtime_ns", round(stat.st_mtime * 1_000_000_000)))}


def write_standardized_frame_manifest(project, image_id, crop=None, *, target=None, developed=None):
    crop = crop or crop_frame_record(project, image_id)
    if not crop:
        return None
    target = Path(target or standardized_frame_path(project, image_id, crop))
    developed = Path(developed or _relative_path(project, crop.get("developed_relpath"), f"cache/developed/{image_id}.png"))
    if not target.is_file():
        return None
    transform = Transform(**crop["transform_json"])
    payload = {
        "format_version": 1,
        "image_id": str(image_id),
        "geometry_sha256": _crop_geometry_sha256(crop),
        "developed": _developed_signature(developed),
        "standardized_size": [int(transform.output_width), int(transform.output_height)],
    }
    atomic_json_write(_standardized_manifest_path(target), payload)
    return payload


def _standardized_cache_matches(project, image_id, crop, target, developed):
    target = Path(target)
    if not target.is_file():
        return False
    try:
        transform = Transform(**crop["transform_json"])
        with Image.open(target) as image:
            if image.size != (int(transform.output_width), int(transform.output_height)):
                return False
    except (OSError, TypeError, ValueError):
        return False
    try:
        manifest = read_json(_standardized_manifest_path(target), None)
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        return False
    if manifest.get("geometry_sha256") != _crop_geometry_sha256(crop):
        return False
    current_developed = _developed_signature(developed)
    if current_developed is not None and manifest.get("developed") != current_developed:
        return False
    return True


def _crop_updated_timestamp(crop):
    value=crop.get("updated_at")
    if not value:return None
    try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
    except (TypeError,ValueError,OverflowError):return None


def _legacy_standardized_can_be_adopted(crop,target):
    """Adopt a pre-manifest standardized frame only when it is not older than its persisted Crop."""
    target=Path(target)
    if not _legacy_standardized_size_matches(crop,target):return False
    crop_timestamp=_crop_updated_timestamp(crop)
    if crop_timestamp is None:return False
    try:return target.stat().st_mtime+1.0>=crop_timestamp
    except OSError:return False


def _legacy_standardized_size_matches(crop,target):
    target=Path(target)
    if not target.is_file():return False
    try:
        transform=Transform(**crop["transform_json"])
        with Image.open(target) as image:
            return image.size==(int(transform.output_width),int(transform.output_height))
    except (OSError,TypeError,ValueError):
        return False


def restore_standardized_frame(project, image_id, crop=None):
    """Return a cache that is proven to match the persisted Crop frame, rebuilding stale caches."""
    crop = crop or crop_frame_record(project, image_id)
    if not crop:
        raise LandmarkFrameError("Crop required before landmarking")
    target = standardized_frame_path(project, image_id, crop)
    developed = _relative_path(project, crop.get("developed_relpath"), f"cache/developed/{image_id}.png")
    manifest_path=_standardized_manifest_path(target)
    if _standardized_cache_matches(project, image_id, crop, target, developed):
        return target, False
    # One-way migration for valid old projects: if no manifest existed yet,
    # the standardized PNG is the right size and was written no earlier than
    # the current persisted Crop, it already represents that Crop. Trust it
    # and attach the new fingerprint instead of reopening a huge developed/RAW image.
    if not manifest_path.exists() and _legacy_standardized_can_be_adopted(crop,target):
        write_standardized_frame_manifest(project,image_id,crop,target=target,developed=developed)
        return target, False
    if not developed.is_file():
        # Legacy projects may retain only the canonical standardized PNG.
        # Do not re-decode a large RAW/NEF merely because the new manifest
        # did not exist when that frame was created. Exact transform size is
        # sufficient for this one-way migration when no developed source is
        # available to perform the stricter geometry check.
        if _legacy_standardized_size_matches(crop,target):
            write_standardized_frame_manifest(project,image_id,crop,target=target,developed=developed)
            return target, False
        source = project.image_path(image_id)
        if not source:
            raise LandmarkFrameError("Crop required before landmarking")
        develop_full(source, project=project, image_id_value=image_id)
    if not developed.is_file():
        raise LandmarkFrameError("Crop required before landmarking")
    bounds = tuple(round(float(value)) for value in crop["crop_json"])
    transform = Transform(**crop["transform_json"])
    with Image.open(developed) as source:
        base = source.convert("RGB")
        if (base.width, base.height) != (transform.original_width, transform.original_height):
            raise LandmarkFrameError("Persisted crop source dimensions no longer match")
        rotated = base.rotate(float(transform.rotation_degrees), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255))
        frame = rotated.crop(bounds)
    if frame.size != (transform.output_width, transform.output_height):
        raise LandmarkFrameError("Persisted crop transform dimensions do not match")
    atomic_save_png(frame, target, image_id)
    write_standardized_frame_manifest(project, image_id, crop, target=target, developed=developed)
    return target, True


def landmark_prediction_frame_ready(project, image_id):
    """Whether AI may predict in the current persisted final Crop frame.

    A pending landmark_crop_review_required flag means the Crop changed and the
    downstream landmarks need refresh/review. It must not make that already
    human-confirmed Crop unusable for the AI refresh that can repair them.
    """
    crop = crop_frame_record(project, image_id)
    return bool(
        crop
        and crop.get("provenance") in {"manual", "ai_accepted", "ai_corrected"}
        and crop.get("human_verified")
    )


def landmark_frame_ready(project, image_id, *, require_final_crop=True):
    crop = crop_frame_record(project, image_id)
    if not crop:
        return False
    if require_final_crop and not landmark_prediction_frame_ready(project, image_id):
        return False
    return not project.landmark_crop_review_required(image_id)
