"""Audit long CSV plus simple wide landmark tables with explicit missing cells."""
from __future__ import annotations
import csv
from pathlib import Path
from .io import read_json
from .paths import REPORTS,WORK
from .profile import load_schema_profile
from .transforms import Transform

def _manifest_hashes():
 path=REPORTS/"source_manifest.csv"
 if not path.exists():return {}
 with path.open(encoding="utf-8",newline="") as f:return {r["source_relpath"]:r["sha256"] for r in csv.DictReader(f)}

def _records():
 for path in sorted(WORK.glob("*/landmarks/*.json")):
  r=read_json(path,{});
  if r:yield r

def _schema_path(schema_path=None):
 if schema_path is not None:return Path(schema_path)
 try:
  from .project_runtime import active_project
  project=active_project()
  if project is not None:return project.schema_path
 except Exception:pass
 raise ValueError("schema_path is required when no MorphoLabel project is active")

def export_all(schema_path=None):
 REPORTS.mkdir(exist_ok=True); hashes=_manifest_hashes(); long=[]; wide20=[];wide25=[]
 schema=load_schema_profile(_schema_path(schema_path))
 for r in _records():
  r=dict(r);r["source_sha256"]=r.get("source_sha256") or hashes.get(r.get("source_relpath"),"")
  meta=read_json(WORK/r["sample_id"]/"metadata"/f"{r['image_id']}.json",{}); t=Transform(**meta["transform"]) if meta.get("transform") else None
  base={k:r.get(k,"") for k in ("sample_id","image_id","source_relpath","source_sha256","profile_id","profile_version")}; row20=dict(base);row25=dict(base)
  for n in [point.number for point in schema.landmarks]:
   p=r.get("points",{}).get(str(n),{});x,y=p.get("x_standardized"),p.get("y_standardized"); original=t.standardized_to_original(x,y) if t and x is not None else (None,None)
   long.append({**base,"point_number":n,"point_code":p.get("point_code",""),"state":p.get("state","unplaced"),"x_standardized":x,"y_standardized":y,"x_original":original[0],"y_original":original[1],"predicted_x":p.get("predicted_x"),"predicted_y":p.get("predicted_y"),"final_x":p.get("final_x"),"final_y":p.get("final_y"),"confidence":p.get("confidence"),"model_id":p.get("model_id"),"reviewed":p.get("reviewed",False),"timestamp":p.get("timestamp","")})
   for target in (row20,row25):
    if target is row20 and n>20:continue
    target[f"p{n:02d}_state"]=p.get("state","unplaced");target[f"p{n:02d}_x"]=x;target[f"p{n:02d}_y"]=y
  wide20.append(row20);wide25.append(row25)
 def write(name,rows):
  keys=list(rows[0]) if rows else ["sample_id","image_id"]
  with (REPORTS/name).open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
 write("landmarks_canonical.csv",long);write("landmarks_GM.csv",wide20);write("landmarks_all.csv",wide25)
 return {"canonical":REPORTS/"landmarks_canonical.csv","gm":REPORTS/"landmarks_GM.csv","all":REPORTS/"landmarks_all.csv"}
