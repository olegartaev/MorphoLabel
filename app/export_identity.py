"""Shared identity fields for scientific export rows.

Values are projected from persisted catalogue fields only. Missing source
metadata stays empty; identifiers are never inferred from filenames.
"""

IDENTITY_FIELDS = (
    "specimen_id",
    "image_id",
    "sample_id",
    "locality",
    "filename",
    "source_relative_path",
)


def export_identity(row):
    """Return the canonical export identity for a Landmark catalogue row."""
    row = row or {}
    return {
        "specimen_id": row.get("specimen_id") or "",
        "image_id": row.get("image_id") or "",
        "sample_id": row.get("sample_id") or "",
        "locality": row.get("locality") or "",
        "filename": row.get("original_name") or "",
        "source_relative_path": row.get("relative_path") or "",
    }


def companion_path(target):
    """Return the standalone identity sidecar path for an export file."""
    from pathlib import Path

    target = Path(target)
    return target.with_name(f"{target.stem}_specimens.csv")


def write_specimen_crosswalk(target, rows, exported_ids):
    """Write only included records, keyed by the exact external-format ID."""
    import csv
    from pathlib import Path

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    identity_fields = ("exported_id", "image_id", "specimen_id", "sample_id",
                       "locality", "filename", "source_relative_path")
    by_image = {str(row.get("image_id") or ""): row for row in rows}
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=identity_fields, lineterminator="\n")
        writer.writeheader()
        for image_id, exported_id in exported_ids:
            row = by_image.get(str(image_id))
            if row is None:
                continue
            writer.writerow({"exported_id": exported_id, **export_identity(row)})
    return target
