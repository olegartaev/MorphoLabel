"""Offline verification that the installed EXE ships its external CUDA worker source.

The Windows application has its own bundled Python code, but the separately
installed CUDA Python interpreter cannot import code from PyInstaller's PYZ.
Keep source modules available to that external interpreter as ordinary files.
"""
from __future__ import annotations

import argparse
from pathlib import Path

REQUIRED = (
    "tools/train_universal_multires.py",
    "ai_runtime/universal_multires.py",
    "ai_runtime/universal_multires_training_data.py",
    "ai_runtime/xray_structure_runner.py",
    "app/__init__.py",
    "app/xray_multires_training.py",
    "app/xray_project.py",
    "app/xray_structure_ai.py",
    "app/xray_schema.py",
    "app/runtime_paths.py",
)


def verify_distribution(distribution: Path):
    target=Path(distribution)
    bundle=target/"_internal" if (target/"_internal").is_dir() else target
    missing=[name for name in REQUIRED if not (bundle/name).is_file()]
    if missing:
        raise FileNotFoundError("Packaged high-resolution training worker missing: "+", ".join(missing))
    for path in sorted((bundle/"app").rglob("*.py"))+sorted((bundle/"ai_runtime").rglob("*.py")):
        compile(path.read_text(encoding="utf-8"),str(path),"exec")
    worker=bundle/REQUIRED[0]
    compile(worker.read_text(encoding="utf-8"),str(worker),"exec")
    return len(list((bundle/"app").rglob("*.py"))),len(list((bundle/"ai_runtime").rglob("*.py")))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("distribution",type=Path)
    args=parser.parse_args()
    app_count,ai_count=verify_distribution(args.distribution)
    print(f"Package worker source: PASS ({app_count} application, {ai_count} AI modules)")

if __name__=="__main__":
    main()
