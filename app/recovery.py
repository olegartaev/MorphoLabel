"""Append-only local history for reversible landmark edits."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from .io import atomic_json_write, read_json
from .paths import WORK

def history_dir(sample_id: str, image_id: str) -> Path:
    return WORK / sample_id / "history" / image_id

def snapshot(record: dict, reason: str) -> Path:
    moment=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path=history_dir(record["sample_id"],record["image_id"])/f"{moment}.json"
    atomic_json_write(path,{"reason":reason,"record":record})
    return path

def restore_latest(record: dict) -> dict|None:
    folder=history_dir(record["sample_id"],record["image_id"])
    candidates=sorted(folder.glob("*.json"))
    if not candidates: return None
    restored=read_json(candidates[-1],{}).get("record")
    if restored: restored["restored_from_history"]=candidates[-1].name
    return restored
