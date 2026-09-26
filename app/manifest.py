import csv
import hashlib
import json
import platform
import subprocess
from collections import Counter
from pathlib import Path
from .io import atomic_json_write
from .paths import ORIGINALS, REPORTS, require_relative

SUPPORTED = {".nef", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def image_dimensions(path: Path) -> tuple[int | None, int | None, str | None]:
    try:
        from PIL import Image
        with Image.open(path) as image:
            return image.width, image.height, None
    except Exception as exc:
        return None, None, str(exc)

def scan() -> list[dict]:
    rows = []
    for path in sorted(ORIGINALS.rglob("*")):
        if not path.is_file(): continue
        width, height, error = image_dimensions(path)
        rows.append({"sample_id": path.parent.name, "source_relpath": require_relative(path),
                     "filename": path.name, "extension": path.suffix.lower(), "bytes": path.stat().st_size,
                     "sha256": sha256(path), "width": width, "height": height,
                     "read_error": error, "supported": path.suffix.lower() in SUPPORTED})
    return rows

def write_manifest() -> list[dict]:
    rows = scan(); REPORTS.mkdir(exist_ok=True)
    fields = list(rows[0]) if rows else ["sample_id"]
    with (REPORTS / "source_manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    hashes = Counter(row["sha256"] for row in rows)
    summary = {"sample_folders": len({row["sample_id"] for row in rows}), "images": len(rows),
               "formats": dict(Counter(row["extension"] for row in rows)),
               "duplicates_by_hash": sum(count - 1 for count in hashes.values() if count > 1),
               "dimension_capability": "Pillow unavailable or does not decode RAW" if all(r["width"] is None for r in rows) else "available",
               "unreadable": [row["source_relpath"] for row in rows if row["read_error"]],
               "note": "Source files were scanned read-only; no source file was changed."}
    atomic_json_write(REPORTS / "source_audit.json", summary)
    return rows

def environment_report() -> dict:
    def command(cmd):
        try: return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=15).strip()
        except Exception as exc: return f"unavailable: {exc}"
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "git": command(["git", "--version"]), "nvidia_smi": command(["nvidia-smi"]),
              "ollama": command(["ollama", "list"])}
    atomic_json_write(REPORTS / "environment.json", report)
    return report
