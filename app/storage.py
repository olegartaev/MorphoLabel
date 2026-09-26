from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from .io import atomic_json_write, read_json
from .paths import sample_work

def landmark_path(sample_id: str, image_id: str) -> Path:
    return sample_work(sample_id) / "landmarks" / f"{image_id}.json"

def save_landmarks(sample_id: str, image_id: str, record: dict) -> None:
    record = dict(record)
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json_write(landmark_path(sample_id, image_id), record)

def load_landmarks(sample_id: str, image_id: str) -> dict:
    return read_json(landmark_path(sample_id, image_id), {"points": {}})

def save_calibration(sample_id: str, calibration: dict) -> None:
    calibration = dict(calibration)
    calibration["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json_write(sample_work(sample_id) / "metadata" / "calibration.json", calibration)

def load_calibration(sample_id: str) -> dict:
    return read_json(sample_work(sample_id) / "metadata" / "calibration.json", {})
