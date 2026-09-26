"""Bounded, read-only Landmark preflight timing for a disposable QA project."""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.landmark_training_workflow import prepare_landmark_training
from app.project_storage import Project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--parent", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    started = time.perf_counter()
    report = {"project": str(Path(args.project)), "started": time.time()}
    try:
        project = Project.open(Path(args.project))
        plan = prepare_landmark_training(project, parent_model_id=args.parent, epochs=210)
        report.update({
            "ok": True,
            "elapsed_seconds": time.perf_counter() - started,
            "model_id": plan.model_id,
            "parent_model_id": plan.parent_model_id,
            "image_count": len(plan.image_ids),
            "training_settings": plan.training_settings,
        })
    except BaseException as exc:  # persist diagnostics even for runtime exits
        report.update({"ok": False, "elapsed_seconds": time.perf_counter() - started,
                       "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
