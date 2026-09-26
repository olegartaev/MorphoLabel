"""Generate third-party notices from the exact managed AI interpreter."""
from __future__ import annotations

import importlib.metadata as metadata
import shutil
import sys
from pathlib import Path

LICENSE_WORDS = ("license", "copying", "notice", "copyright")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def license_files(dist):
    found = []
    seen = set()
    for item in dist.files or ():
        path_text = str(item).replace("\\", "/")
        leaf = Path(path_text).name.casefold()
        if "/licenses/" not in path_text.casefold() and not any(word in leaf for word in LICENSE_WORDS):
            continue
        source = Path(dist.locate_file(item))
        if source.is_file():
            key = str(source.resolve()).casefold()
            if key not in seen:
                seen.add(key)
                found.append(source)
    return found


def generate(component_root: Path):
    component_root = Path(component_root)
    licenses_root = component_root / "licenses"
    if licenses_root.exists():
        shutil.rmtree(licenses_root)
    licenses_root.mkdir(parents=True)

    lines = [
        "MorphoLabel managed AI third-party notices",
        "=========================================",
        "",
        "Generated at build time from the exact installed Python distributions.",
        "Copied license/notice files under licenses/ are the authoritative bundled texts.",
        "",
    ]

    python_sources = []
    for root in {Path(sys.base_prefix), Path(sys.prefix)}:
        for pattern in ("LICENSE.txt", "LICENSE", "LICENSE*"):
            for path in root.glob(pattern):
                if path.is_file() and path not in python_sources:
                    python_sources.append(path)
    if not python_sources:
        raise RuntimeError("Python redistribution license was not found")
    python_dir = licenses_root / "Python"
    python_dir.mkdir()
    for index, source in enumerate(python_sources, 1):
        target = python_dir / (source.name if index == 1 else f"{index}_{source.name}")
        shutil.copy2(source, target)
    lines.extend([f"Python: {sys.version.split()[0]}", "License files: licenses/Python/", ""])

    distributions = sorted(
        metadata.distributions(),
        key=lambda dist: (dist.metadata.get("Name") or "").casefold(),
    )
    for dist in distributions:
        name = dist.metadata.get("Name") or "unknown"
        version = dist.version or "unknown"
        package_dir = licenses_root / safe_name(name)
        copied = []
        for source in license_files(dist):
            package_dir.mkdir(exist_ok=True)
            destination = package_dir / source.name
            counter = 2
            while destination.exists():
                destination = package_dir / f"{source.stem}_{counter}{source.suffix}"
                counter += 1
            shutil.copy2(source, destination)
            copied.append(destination.name)
        declared = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "not declared in wheel metadata"
        homepage = dist.metadata.get("Home-page") or dist.metadata.get("Project-URL") or ""
        lines.extend([
            f"{name}: {version}",
            f"Declared license: {declared}",
            f"Upstream metadata: {homepage}" if homepage else "Upstream metadata: not declared",
            f"Bundled license files: licenses/{package_dir.name}/" if copied else "Bundled license files: none discovered in installed distribution",
            "",
        ])

    notice = component_root / "THIRD_PARTY_NOTICES.txt"
    notice.write_text("\n".join(lines), encoding="utf-8")
    return notice


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_ai_notices.py COMPONENT_ROOT")
    print(generate(Path(sys.argv[1])))
