"""Small fixtures for the current MorphoLabel persistence contracts."""

from hashlib import sha256
from pathlib import Path

from PIL import Image

from app.transforms import Transform


def make_reviewed_crop(project, image_id, width=80, height=60):
    """Materialize a valid standardized frame and reviewed canonical Crop."""
    developed = project.cache_root / "developed" / f"{image_id}.png"
    standardized = project.cache_root / "standardized" / f"{image_id}.png"
    developed.parent.mkdir(parents=True, exist_ok=True)
    standardized.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (32, 48, 64)).save(developed)
    Image.new("RGB", (width, height), (32, 48, 64)).save(standardized)
    transform = Transform(
        original_width=width,
        original_height=height,
        rotation_degrees=0.0,
        center_x=width / 2,
        center_y=height / 2,
        crop_left=0.0,
        crop_top=0.0,
        output_width=width,
        output_height=height,
    )
    crop = {
        "crop_bounds": [0, 0, width, height],
        "transform": transform.__dict__,
        "rotation_degrees": 0.0,
        "normalization_status": "PASS",
        "developed_full_relpath": f"cache/developed/{image_id}.png",
        "standardized_relpath": f"cache/standardized/{image_id}.png",
        "source_sha256": sha256(developed.read_bytes()).hexdigest(),
    }
    project.save_reviewed_crop(image_id, crop, previous_frame_proven=True)
    return crop
