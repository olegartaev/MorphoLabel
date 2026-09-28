"""Bounded retention for disposable full-resolution developed image cache."""
from __future__ import annotations
from pathlib import Path

DEVELOPED_HIGH_WATER_BYTES = 4 * 1024**3
DEVELOPED_TARGET_BYTES = 3 * 1024**3
DEVELOPED_RECENT_KEEP = 32


def prune_developed_cache(project, *, high_bytes=DEVELOPED_HIGH_WATER_BYTES,
                          target_bytes=DEVELOPED_TARGET_BYTES,
                          keep_recent=DEVELOPED_RECENT_KEEP, max_removals=None):
    """Remove only reproducible developed PNGs for verified crops with available sources.

    Standardized landmark frames, SQLite state, crop transforms, model artifacts,
    QC and correction history are never touched.  Recent verified crops are kept
    hot for fast re-editing.  A missing developed PNG is rebuilt on demand.
    """
    developed = Path(project.cache_root) / "developed"
    if not developed.is_dir():
        return {"removed_files": 0, "removed_bytes": 0, "before_bytes": 0, "after_bytes": 0}

    files = {path.stem: path for path in developed.glob("*.png") if path.is_file()}
    sizes = {}
    total = 0
    for image_id, path in files.items():
        try:
            size = int(path.stat().st_size)
        except OSError:
            continue
        sizes[image_id] = size
        total += size
    before = total
    if total <= int(high_bytes):
        return {"removed_files": 0, "removed_bytes": 0, "before_bytes": before, "after_bytes": total}

    with project.transaction() as connection:
        rows = connection.execute("""
SELECT cr.image_id,COALESCE(cr.reviewed_at,cr.updated_at) AS reviewed_at,
       i.relative_path,i.source_available
FROM crops cr
JOIN images i ON i.image_id=cr.image_id
WHERE COALESCE(cr.human_verified,0)=1
  AND cr.provenance IN ('manual','ai_accepted','ai_corrected')
ORDER BY COALESCE(cr.reviewed_at,cr.updated_at) DESC,cr.image_id
""").fetchall()

    hot = {str(row["image_id"]) for row in rows[:max(0, int(keep_recent))]}
    candidates = [row for row in reversed(rows) if str(row["image_id"]) not in hot]
    removed_files = 0
    removed_bytes = 0
    for row in candidates:
        if total <= int(target_bytes):
            break
        if max_removals is not None and removed_files >= int(max_removals):
            break
        image_id = str(row["image_id"])
        path = files.get(image_id)
        if path is None or image_id not in sizes or not bool(row["source_available"]):
            continue
        source = Path(project.source_root) / str(row["relative_path"])
        if not source.is_file():
            continue
        size = sizes[image_id]
        try:
            path.unlink()
            metadata = Path(project.cache_root) / "metadata" / f"{image_id}.developed.json"
            metadata.unlink(missing_ok=True)
        except OSError:
            continue
        total -= size
        removed_bytes += size
        removed_files += 1

    return {"removed_files": removed_files, "removed_bytes": removed_bytes,
            "before_bytes": before, "after_bytes": total}
