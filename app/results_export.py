"""Standard TPS and specimen CSV projections of authoritative Project SQLite state."""
from __future__ import annotations
import csv, os, tempfile
from pathlib import Path
from .landmark_state import load_current_landmark_state

MISSING_TPS=(-1.0,-1.0) # standard negative missing coordinates (e.g. geomorph negNA=TRUE)
COORDINATE_DECIMALS=5
SCALE_DECIMALS=6

def _atomic_text(path:Path,text:str):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",newline="",dir=path.parent,delete=False) as stream:
  stream.write(text);temporary=Path(stream.name)
 os.replace(temporary,path)

def _scale_mm_per_px(project,row):
 calibration=project.locality_calibration(row.get("locality",row["sample_id"]))
 if not calibration or not calibration.get("scale"):return "",None
 # Stored calibration scale is pixels/mm; exported SCALE and CSV are mm/pixel.
 value=1.0/float(calibration["scale"])
 return f"{value:.{SCALE_DECIMALS}f}",value

def _attributes(project,image_id): return project.attributes_for_image(image_id)

def export_project_results(project):
 rows=project.catalog_rows();schema_ids=[int(item["id"]) for item in project.schema]
 attributes=sorted({key for row in rows for key in _attributes(project,row["image_id"])})
 tps=[];csv_rows=[]
 for row in rows:
  state=load_current_landmark_state(project,row["image_id"]);scale_text,scale_value=_scale_mm_per_px(project,row)
  excluded=bool(row.get("excluded"));reason=row.get("exclusion_reason") or ""
  values={"specimen_id":row.get("specimen_id") or row["image_id"],"image_id":row["image_id"],"locality":row.get("locality",row["sample_id"]),"filename":row["original_name"],"qc":"excluded" if excluded else state.color,"checked":str(state.human_verified).lower(),"skipped":str(len(state.explicitly_missing_ids)),"excluded":str(excluded).lower(),"exclusion_reason":reason,"calibration_mm_per_px":scale_text,"coordinate_system":"original_image_pixels"}
  values.update({key:_attributes(project,row["image_id"]).get(key,"") for key in attributes});csv_rows.append(values)
  if excluded or not state.complete:continue
  canonical=project.canonical_coordinates(row["image_id"])
  tps.append(f"LM={len(schema_ids)}")
  for ident in schema_ids:
   if ident in state.explicitly_missing_ids:
    x,y=MISSING_TPS
   else:
    point=canonical.get(ident)
    if point is None:raise ValueError(f"complete landmark state has no canonical coordinate for {row['image_id']} landmark {ident}")
    x,y=float(point[0]),float(point[1])
   tps.append(f"{x:.{COORDINATE_DECIMALS}f} {y:.{COORDINATE_DECIMALS}f}")
  tps.append(f"IMAGE={row['original_name']}");tps.append(f"ID={row['image_id']}")
  if scale_text:tps.append(f"SCALE={scale_text}")
  tps.append("")
 output=project.results_root;_atomic_text(output/"landmarks.tps","\n".join(tps).rstrip()+"\n" if tps else "")
 fields=["specimen_id","image_id","locality","filename","qc","checked","skipped","excluded","exclusion_reason","calibration_mm_per_px",*attributes,"coordinate_system"]
 import io
 buf=io.StringIO(newline="");writer=csv.DictWriter(buf,fieldnames=fields,lineterminator="\n");writer.writeheader();writer.writerows(csv_rows);_atomic_text(output/"specimens.csv",buf.getvalue())
 return {"tps":output/"landmarks.tps","specimens":output/"specimens.csv","ready":len(tps and [line for line in tps if line.startswith("LM=")] or [])}

def parse_tps(path):
 """Small standards-oriented test reader; preserves LM coordinate ordering."""
 blocks=[];lines=Path(path).read_text(encoding="utf-8").splitlines();i=0
 while i<len(lines):
  if not lines[i].startswith("LM="):i+=1;continue
  count=int(lines[i].split("=",1)[1]);i+=1;coords=[]
  for _ in range(count):
   x,y=lines[i].split();coords.append((float(x),float(y)));i+=1
  metadata={}
  while i<len(lines) and lines[i]:
   key,value=lines[i].split("=",1);metadata[key]=value;i+=1
  blocks.append({"coordinates":coords,**metadata})
 return blocks
