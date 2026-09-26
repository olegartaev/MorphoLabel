"""Split a managed AI ZIP into GitHub-Release-sized assets and write its delivery manifest."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

DEFAULT_MAX_PART_BYTES = 1_900_000_000
MANIFEST_NAME = "MorphoLabel-AI-Windows-x64.json"


def _sha256_stream(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_release_assets(component_dir: Path, app_version: str, *, max_part_bytes=DEFAULT_MAX_PART_BYTES):
    component_dir = Path(component_dir)
    build = json.loads((component_dir / "AI_BUILD_INFO.json").read_text(encoding="utf-8"))
    archive = component_dir / str(build["archive"])
    if not archive.is_file():
        raise RuntimeError(f"AI archive is missing: {archive}")
    archive_bytes = int(build["archive_bytes"])
    archive_sha256 = str(build["archive_sha256"]).lower()
    if archive.stat().st_size != archive_bytes:
        raise RuntimeError("AI archive size does not match AI_BUILD_INFO.json")
    if _sha256_stream(archive) != archive_sha256:
        raise RuntimeError("AI archive SHA256 does not match AI_BUILD_INFO.json")
    if int(max_part_bytes) <= 0 or int(max_part_bytes) >= 2 * 1024**3:
        raise RuntimeError("release part size must be positive and below 2 GiB")

    output = component_dir / "release-assets"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    parts = []
    full_digest = hashlib.sha256()
    total = 0
    index = 1
    with archive.open("rb") as source:
        while total < archive_bytes:
            name = f"{archive.name}.part{index:02d}"
            target = output / name
            part_digest = hashlib.sha256()
            part_bytes = 0
            with target.open("wb") as destination:
                while part_bytes < max_part_bytes:
                    block = source.read(min(1024 * 1024, max_part_bytes - part_bytes))
                    if not block:
                        break
                    destination.write(block)
                    part_digest.update(block)
                    full_digest.update(block)
                    part_bytes += len(block)
                    total += len(block)
            if part_bytes <= 0:
                raise RuntimeError("AI release splitting produced an empty part")
            parts.append({
                "name": name,
                "bytes": part_bytes,
                "sha256": part_digest.hexdigest(),
            })
            index += 1

    if total != archive_bytes or full_digest.hexdigest() != archive_sha256:
        raise RuntimeError("AI release parts do not reconstruct the original archive")

    manifest = {
        "format_version": 1,
        "app_version": str(app_version),
        "component_version": str(build["component_manifest"]["component_version"]),
        "platform": str(build["component_manifest"]["platform"]),
        "archive_name": archive.name,
        "archive_sha256": archive_sha256,
        "archive_bytes": archive_bytes,
        "installed_bytes": int(build["installed_bytes"]),
        "parts": parts,
    }
    (output / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest, output


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: build_ai_release_assets.py COMPONENT_DIR APP_VERSION [MAX_PART_BYTES]")
    maximum = int(sys.argv[3]) if len(sys.argv) == 4 else DEFAULT_MAX_PART_BYTES
    manifest, folder = build_release_assets(Path(sys.argv[1]), sys.argv[2], max_part_bytes=maximum)
    print(json.dumps({"release_assets": str(folder), **manifest}, indent=2))
