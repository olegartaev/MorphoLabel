"""Conservative provisional standardization: no mirroring, no anatomy inference."""
from dataclasses import asdict
from pathlib import Path
import hashlib
from .io import atomic_json_write
from .paths import sample_work, require_relative
from .transforms import Transform
from .manifest import sha256

def image_id(source: Path) -> str:
    # In project mode SQLite is the sole authority for image identity.
    try:
        from .project_runtime import active_project
        project = active_project()
        if project is not None:
            candidate = Path(source)
            try:
                rel = candidate.resolve().relative_to(project.source_root.resolve()).as_posix()
            except ValueError:
                rel = str(candidate).replace("\\", "/")
            with project.transaction() as conn:
                row = conn.execute("SELECT image_id FROM images WHERE relative_path=?", (rel,)).fetchone()
            if row is not None:
                return str(row[0])
    except Exception:
        # Keep legacy startup usable before a project context is opened.
        pass
    return hashlib.sha256(require_relative(source).encode()).hexdigest()[:16]

def decode(source: Path):
    from PIL import Image
    if source.suffix.lower() == ".nef":
        import rawpy
        with rawpy.imread(str(source)) as raw:
            array = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
        return Image.fromarray(array)
    with Image.open(source) as image:
        return image.convert("RGB")

def provisional_standardize(source: Path) -> dict:
    """Write a lossless full-frame master marked REVIEW pending human normalization."""
    image = decode(source)
    sample_id = source.parent.name; identifier = image_id(source)
    out = sample_work(sample_id); standardized = out / "standardized" / f"{identifier}.png"
    standardized.parent.mkdir(parents=True, exist_ok=True)
    image.save(standardized, format="PNG", compress_level=6)
    transform = Transform(image.width, image.height, 0.0, image.width / 2, image.height / 2, 0, 0, image.width, image.height)
    metadata = {"image_id": identifier, "source_relpath": require_relative(source), "source_sha256": sha256(source),
                "standardized_relpath": require_relative(standardized), "normalization_status": "REVIEW",
                "normalization_note": "Conservative full-frame provisional master; human crop/orientation review required.",
                "transform": asdict(transform), "interpolation": "none", "mirrored": False,
                "software_version": "0.1.0"}
    atomic_json_write(out / "metadata" / f"{identifier}.json", metadata)
    return metadata

def preview(source: Path, target: Path, max_size=(1000, 700)) -> Path:
    image = decode(source); image.thumbnail(max_size)
    target.parent.mkdir(parents=True, exist_ok=True); image.save(target, format="PNG")
    return target


