"""Compare serial and persistent-runtime epoch validation on a QA copy only."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai_batch import backend_for_model
from app.landmark_qc import dataset_split_metrics, dataset_split_records
from app.project_storage import Project
from app.rtmpose_backend import evaluate_epoch_checkpoint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--model", default="rtmpose_v002")
    parser.add_argument("--epochs", default="10,20")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    project = Project.open(Path(args.project))
    model, backend = backend_for_model(project, args.model)
    artifact = project.data_root / "ai" / "models" / args.model
    manifest = project.data_root / model["dataset_manifest_path"]
    paths = [artifact / f"epoch_{int(value)}.pth" for value in args.epochs.split(",")]
    if not all(path.is_file() for path in paths):
        raise SystemExit("requested checkpoint is absent")
    serial = {}
    started = time.perf_counter()
    for path in paths:
        serial[str(path)] = evaluate_epoch_checkpoint(project, manifest, backend.spec.config_path, path,
                                                       backend.spec.input_size, backend.spec.device)
    serial_seconds = time.perf_counter() - started
    expected, digest, records = dataset_split_records(project, manifest, split="validation")
    started = time.perf_counter()
    predicted = backend.predict_readonly_checkpoints([record[3] for record in records], paths)
    persistent_seconds = time.perf_counter() - started
    persistent = {}
    for path in paths:
        metrics = dataset_split_metrics(records, expected, predicted[str(path)], model_id=backend.model_id)
        persistent[str(path)] = {"epoch": int(path.stem.split("_")[1]),
                                  "median_error_percent": metrics["median_error_percent"],
                                  "p90_error_percent": metrics["p90_error_percent"],
                                  "p95_error_percent": metrics["p95_error_percent"]}
    report = {"model": args.model, "epochs": [int(path.stem.split("_")[1]) for path in paths],
              "serial_seconds": serial_seconds, "persistent_seconds": persistent_seconds,
              "speedup": serial_seconds / max(persistent_seconds, 1e-9),
              "serial": serial, "persistent": persistent,
              "equivalent": serial == persistent}
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
