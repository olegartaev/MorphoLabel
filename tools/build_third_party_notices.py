"""Generate redistribution notices from the exact packages installed in the build environment."""
from __future__ import annotations

import importlib.metadata as metadata
import shutil
import sys
from pathlib import Path

DISTRIBUTIONS = ("Pillow", "numpy", "opencv-python", "rawpy")
LICENSE_WORDS = ("license", "copying", "notice", "copyright")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _package_license_files(dist):
    result = []
    for item in dist.files or ():
        name = Path(str(item)).name.casefold()
        if not any(word in name for word in LICENSE_WORDS):
            continue
        source = Path(dist.locate_file(item))
        if source.is_file():
            result.append(source)
    return result


def _python_license_files():
    roots = {Path(sys.base_prefix), Path(sys.prefix)}
    result = []
    for root in roots:
        for pattern in ("LICENSE.txt", "LICENSE", "LICENSE*"):
            for path in root.glob(pattern):
                if path.is_file() and path not in result:
                    result.append(path)
    return result


def generate(output_root: Path):
    output_root = Path(output_root)
    if output_root.exists():
        shutil.rmtree(output_root)
    licenses = output_root / "licenses"
    licenses.mkdir(parents=True)
    lines = [
        "MorphoLabel third-party redistribution notices",
        "==============================================",
        "",
        "Generated at build time from the exact installed runtime distributions.",
        "The copied license files in licenses/ are the authoritative redistribution texts.",
        "",
    ]

    python_files = _python_license_files()
    if not python_files:
        raise RuntimeError("Python redistribution license file was not found in the build interpreter")
    python_dir = licenses / "Python"
    python_dir.mkdir()
    for index, source in enumerate(python_files, start=1):
        name = source.name if index == 1 else f"{index}_{source.name}"
        shutil.copy2(source, python_dir / name)
    lines.extend([f"Python: {sys.version.split()[0]}", "License files: licenses/Python/", ""])

    for distribution_name in DISTRIBUTIONS:
        dist = metadata.distribution(distribution_name)
        package_dir = licenses / _safe_name(dist.metadata.get("Name") or distribution_name)
        package_dir.mkdir()
        copied = []
        for source in _package_license_files(dist):
            destination = package_dir / source.name
            counter = 2
            while destination.exists():
                destination = package_dir / f"{source.stem}_{counter}{source.suffix}"
                counter += 1
            shutil.copy2(source, destination)
            copied.append(destination.name)
        if not copied:
            raise RuntimeError(f"No license/notice files found for installed distribution {distribution_name}")
        license_expression = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See copied license files"
        lines.extend([
            f"{dist.metadata.get('Name') or distribution_name}: {dist.version}",
            f"Declared license: {license_expression}",
            f"License files: licenses/{package_dir.name}/",
            "",
        ])

    notice = output_root / "THIRD_PARTY_NOTICES.txt"
    notice.write_text("\n".join(lines), encoding="utf-8")
    return notice


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "build/third_party")
    print(generate(target))
