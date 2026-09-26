"""Stable human-readable CSV export with reversible original coordinates."""
from __future__ import annotations
import csv
from dataclasses import fields
from pathlib import Path
from .io import read_json
from .paths import REPORTS, WORK
from .transforms import Transform

COLUMNS=["sample_id","image_id","source_relpath","source_sha256","profile_id","profile_version","point_number","point_code","state","x_standardized","y_standardized","x_original","y_original","predicted_x","predicted_y","final_x","final_y","confidence","model_id","reviewed","timestamp"]

def export_canonical_csv(destination: Path|None=None) -> Path:
    destination=destination or REPORTS/"landmarks_canonical.csv"; destination.parent.mkdir(exist_ok=True)
    rows=[]
    for path in sorted(WORK.glob("*/landmarks/*.json")):
        record=read_json(path,{})
        meta_path=WORK/record.get("sample_id","")/"metadata"/f"{record.get('image_id','')}.json"; meta=read_json(meta_path,{})
        transform=Transform(**meta["transform"]) if meta.get("transform") else None
        for point in record.get("points",{}).values():
            row={key:record.get(key) for key in COLUMNS}; row.update(point)
            x,y=point.get("x_standardized"),point.get("y_standardized")
            if transform and x is not None: row["x_original"],row["y_original"]=transform.standardized_to_original(x,y)
            rows.append(row)
    with destination.open("w",newline="",encoding="utf-8") as out:
        writer=csv.DictWriter(out,fieldnames=COLUMNS,extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
    return destination
