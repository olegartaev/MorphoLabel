"""Validate/upgrade 20 existing developed_full PNG cache records without GUI."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.developed_cache_v2 import ensure
from app.normalization_pipeline import paths
from app.workflow import image_catalog

rows=[]
for row in image_catalog():
 source=Path(row["source_relpath"])
 developed, standard=paths(source)[2],paths(source)[4]
 if developed.exists() and standard.exists():
  rows.append(source)
 if len(rows)==20: break
if len(rows)<20: raise RuntimeError(f"Need 20 existing developed_full+standardized PNGs, found {len(rows)}")
out=[]
for source in rows:
 meta=ensure(source)
 out.append({"source":str(source),"developed_full":meta["developed_full_relpath"]})
(ROOT/"reports"/"navigation_20_cache_ready.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps({"count":len(out),"rawpy_nef_calls_expected":0}))
