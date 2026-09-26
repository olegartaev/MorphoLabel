"""Training-ready export that includes only human-final, non-synthetic records."""
from __future__ import annotations
import json
from pathlib import Path
from .io import atomic_json_write, read_json
from .paths import REPORTS, WORK

def export_training_dataset(profile_id: str, destination: Path|None=None) -> dict:
    images=[]
    for record_path in WORK.glob("*/landmarks/*.json"):
        record=read_json(record_path,{})
        if record.get("profile_id") != profile_id: continue
        points=record.get("points",{})
        # All visible placed points must be human final; missing is intentionally retained.
        human=[p for p in points.values() if p.get("state") in {"manual","corrected","missing"}]
        if not human or len(human)!=len(points): continue
        images.append({"image_id":record["image_id"],"sample_id":record["sample_id"],"source_relpath":record["source_relpath"],"points":list(points.values())})
    result={"format":"morphology-landmarks-v1","profile_id":profile_id,"images":images,
            "guard":"Contains human-final/manual/corrected/missing records only; no synthetic scientific coordinates."}
    destination=destination or REPORTS/f"training_{profile_id}.json"; atomic_json_write(destination,result); return result
