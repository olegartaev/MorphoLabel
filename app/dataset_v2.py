"""Strict training export: an image is eligible only after all profile points are final."""
from __future__ import annotations
from .io import atomic_json_write, read_json
from .paths import REPORTS, WORK, PROFILES
from .profile import load_profile

FINAL_STATES={"manual","corrected","missing"}

def export_training_dataset(profile_id: str) -> dict:
    profile=load_profile(PROFILES/f"{profile_id}.json"); expected={str(p.number) for p in profile.landmarks}; images=[]; excluded=[]
    for path in WORK.glob("*/landmarks/*.json"):
        record=read_json(path,{})
        if record.get("profile_id")!=profile_id: continue
        points=record.get("points",{})
        if set(points)!=expected or any(point.get("state") not in FINAL_STATES for point in points.values()):
            excluded.append({"image_id":record.get("image_id"),"reason":"incomplete_or_nonhuman_final"}); continue
        images.append({"image_id":record["image_id"],"sample_id":record["sample_id"],"source_relpath":record["source_relpath"],"points":[points[str(i)] for i in sorted(p.number for p in profile.landmarks)]})
    result={"format":"morphology-landmarks-v2","profile_id":profile_id,"images":images,"excluded":excluded,"guard":"All schema landmarks must be human manual/corrected/missing; no auto-only or partial image enters training."}
    atomic_json_write(REPORTS/f"training_{profile_id}_strict.json",result); return result

