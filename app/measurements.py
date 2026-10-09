"""Read-only landmark-derived measurements and portable CSV export."""
from __future__ import annotations
import csv, io, os, tempfile
from pathlib import Path
from .transforms import Transform
from .export_identity import IDENTITY_FIELDS, export_identity

FIELDS=("Use","Abbr","Name","Point1","Point2","Point1Abbr","Point2Abbr")
MEASUREMENT_DECIMALS=2
SCALE_DECIMALS=6

def schema_path(project): return Path(project.root)/"measurement_schema.csv"
def _atomic(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",newline="",dir=path.parent,delete=False) as f:
  f.write(text); tmp=Path(f.name)
 os.replace(tmp,path)
def ensure_schema(project):
 path=schema_path(project)
 if not path.exists(): _atomic(path,",".join(FIELDS)+"\n")
 return path
def _used(value): return str(value).strip().lower() in {"1","true","yes","y","on"}
def load_measurements(project,*,include_unresolved=False):
 path=ensure_schema(project)
 with path.open(encoding="utf-8-sig",newline="") as f:
  result=[]
  for row in csv.DictReader(f):
   if not any(row.values()): continue
   # New files persist scientific endpoints by abbreviation. Legacy numeric
   # endpoints resolve only through the persisted old project schema.
   a=(row.get("Point1Abbr") or "").strip() or project.historical_abbr_for_numeric(row.get("Point1",0) or 0)
   b=(row.get("Point2Abbr") or "").strip() or project.historical_abbr_for_numeric(row.get("Point2",0) or 0)
   p1,p2=project.active_landmark_id_for_abbr(a),project.active_landmark_id_for_abbr(b)
   unresolved=p1 is None or p2 is None
   if unresolved and not include_unresolved:continue
   value={"use":_used(row.get("Use","")),"abbr":row.get("Abbr","").strip(),"name":row.get("Name","").strip(),"point1":p1,"point2":p2,"point1_abbr":a,"point2_abbr":b}
   if unresolved:value.update({"unresolved":True,"_legacy_point1":row.get("Point1",''),"_legacy_point2":row.get("Point2",'')})
   result.append(value)
 return result
def validate_measurement(value, schema, existing=(), editing_index=None):
 abbr=str(value.get("abbr","")).strip(); name=str(value.get("name","")).strip()
 if not abbr: raise ValueError("Abbr is required.")
 if not name: raise ValueError("Name is required.")
 try:p1,p2=int(value["point1"]),int(value["point2"])
 except (KeyError,TypeError,ValueError):raise ValueError("Choose two landmark IDs.")
 if p1==p2:raise ValueError("Point 1 and Point 2 must be different.")
 ids={int(x.get("id",x.get("landmark_id"))) for x in schema}
 if p1 not in ids or p2 not in ids:raise ValueError("Both points must exist in the landmark schema.")
 for index,row in enumerate(existing):
  if index!=editing_index and row["abbr"].casefold()==abbr.casefold():raise ValueError("Abbr must be unique.")
 return {"use":bool(value.get("use",True)),"abbr":abbr,"name":name,"point1":p1,"point2":p2,"point1_abbr":next(x["abbr"] for x in schema if int(x.get("id",x.get("landmark_id")))==p1),"point2_abbr":next(x["abbr"] for x in schema if int(x.get("id",x.get("landmark_id")))==p2)}
def save_measurements(project, values,*,preserve_unresolved=True):
 unresolved=[row for row in load_measurements(project,include_unresolved=True) if row.get("unresolved")]
 rows=[]
 for index,value in enumerate(values):
  if value.get("unresolved"):
   if value not in unresolved:raise ValueError("Resolve the missing landmarks before changing this historical measurement.")
   rows.append(value)
  else:rows.append(validate_measurement(value,project.schema,values,index))
 if preserve_unresolved:
  codes={row['abbr'].casefold() for row in rows}
  rows.extend(row for row in unresolved if row['abbr'].casefold() not in codes)
 _atomic(schema_path(project),_definitions_csv(rows)); return rows

def _definitions_csv(rows):
 out=io.StringIO(newline=""); w=csv.DictWriter(out,fieldnames=FIELDS,lineterminator="\n");w.writeheader()
 for row in rows:w.writerow({"Use":"1" if row["use"] else "0","Abbr":row["abbr"],"Name":row["name"],"Point1":row["point1"] if row['point1'] is not None else row.get('_legacy_point1',''),"Point2":row["point2"] if row['point2'] is not None else row.get('_legacy_point2',''),"Point1Abbr":row["point1_abbr"],"Point2Abbr":row["point2_abbr"]})
 return out.getvalue()
def active_measurements(project):return [x for x in load_measurements(project) if x["use"]]

def export_measurement_definitions(project,target):
 """Portable definitions bind endpoints to abbreviations, never display numbers."""
 if not project.schema:raise ValueError("Apply a landmark scheme before exporting measurement definitions.")
 target=Path(target);_atomic(target,measurement_definitions_csv(project));return target

def measurement_definitions_csv(project):
 """Read every definition without creating or rewriting the source project."""
 source=schema_path(project);values=[]
 if not source.exists():return _definitions_csv([])
 with source.open(encoding="utf-8-sig",newline="") as stream:
  reader=csv.DictReader(stream)
  if not {"Use","Abbr","Name","Point1","Point2"}<=set(reader.fieldnames or ()):raise ValueError("Invalid measurement definitions file.")
  for row in reader:
   if not any(row.values()):continue
   a=(row.get("Point1Abbr") or "").strip() or project.historical_abbr_for_numeric(row.get("Point1") or 0)
   b=(row.get("Point2Abbr") or "").strip() or project.historical_abbr_for_numeric(row.get("Point2") or 0)
   p1,p2=project.active_landmark_id_for_abbr(a),project.active_landmark_id_for_abbr(b)
   if p1 is None or p2 is None:raise ValueError("A measurement refers to an unresolved landmark; restore its scheme before exporting definitions.")
   values.append(validate_measurement({"use":_used(row.get("Use")),"abbr":row.get("Abbr") or "","name":row.get("Name") or "","point1":p1,"point2":p2},project.schema,values))
 return _definitions_csv(values)

def parse_measurement_definitions(text,schema):
 reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff'),newline=""))
 fields=reader.fieldnames or ()
 if len(fields)!=len(set(fields)) or not {"Use","Abbr","Name","Point1Abbr","Point2Abbr"}<=set(fields):raise ValueError("Portable definitions must include unique landmark abbreviation columns; export them from Measurement definitions first.")
 byabbr={row["abbr"]:int(row["id"]) for row in schema};values=[]
 for row in reader:
  if not any(row.values()):continue
  if None in row:raise ValueError("Measurement definitions contain a malformed CSV row.")
  a,b=(row.get("Point1Abbr") or "").strip(),(row.get("Point2Abbr") or "").strip()
  if a not in byabbr or b not in byabbr:raise ValueError(f"Measurement refers to landmarks absent from this scheme: {a}, {b}.")
  flag=(row.get("Use") or "").strip().lower()
  if flag not in {"","0","1","true","false","yes","no","y","n","on","off"}:raise ValueError("Invalid Use value in measurement definitions.")
  values.append(validate_measurement({"use":_used(flag),"abbr":row.get("Abbr") or "","name":row.get("Name") or "","point1":byabbr[a],"point2":byabbr[b]},schema,values))
 return values

def import_measurement_definitions(project,source):
 if not project.schema:raise ValueError("Apply a landmark scheme before importing measurement definitions.")
 values=parse_measurement_definitions(Path(source).read_text(encoding="utf-8-sig"),project.schema)
 path=schema_path(project)
 if path.exists():
  import shutil,uuid
  backup=project.root/"backups"/"measurement_definitions"/(uuid.uuid4().hex+".csv");backup.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,backup)
 return save_measurements(project,values,preserve_unresolved=False)
def _mm_per_pixel(project, locality):
 cal=project.locality_calibration(locality)
 if not cal:return None
 data=cal.get("calibration_data") or {}
 if isinstance(data,str):
  import json
  try:data=json.loads(data)
  except json.JSONDecodeError:data={}
 value=data.get("mm_per_pixel")
 if value is None: value=1/float(cal["scale"]) if cal.get("scale") else None
 try:return float(value) if value and float(value)>0 else None
 except (TypeError,ValueError):return None
def _points(project,image_id):
 """Return original-frame coordinates; skipped crop uses a non-persisted identity transform."""
 crop=project.crop_record(image_id) or {}; raw=crop.get("transform_json")
 if raw:
  try:transform=Transform(**raw)
  except (TypeError,ValueError):return {},None
 else:
  from PIL import Image
  target=project.cache_root/"developed"/f"{image_id}.png"
  if not target.is_file():return {},None
  try:
   with Image.open(target) as image: width,height=image.size
   transform=Transform(width,height,0.0,width/2,height/2,0,0,width,height)
  except Exception:return {},None
 output={}
 for ident,p in project.load_landmarks(image_id).items():
  if p.get("state")!="missing" and p.get("x_standardized") is not None and p.get("y_standardized") is not None:
   output[int(ident)]=transform.standardized_to_original(float(p["x_standardized"]),float(p["y_standardized"]))
 return output,transform
def values_for_image(project,row,definitions=None):
 definitions=active_measurements(project) if definitions is None else definitions; points,_=_points(project,row["image_id"]); mpp=_mm_per_pixel(project,row.get("locality") or row.get("sample_id")); output={}
 for item in definitions:
  a,b=points.get(item["point1"]),points.get(item["point2"])
  output[item["abbr"]]="NA" if not a or not b or mpp is None else ((a[0]-b[0])**2+(a[1]-b[1])**2)**.5*mpp
 return output,mpp
def measurement_summary(project):
 definitions=active_measurements(project); rows=[r for r in project.catalog_rows() if not r.get("excluded")]; complete=na=0; calibrated=set()
 for row in rows:
  values,mpp=values_for_image(project,row,definitions); locality=row.get("locality") or row.get("sample_id") or ""; calibrated.add(locality) if mpp is not None else None
  complete_here=bool(definitions) and all(v!="NA" for v in values.values()); complete+=int(complete_here);na+=int(not complete_here)
 return {"rows":len(rows),"measurements":len(definitions),"calibrated_samples":len(calibrated),"samples":len({r.get("locality") or r.get("sample_id") or "" for r in rows}),"complete":complete,"na":na}
def export_measurements(project,target=None,delimiter=","):
 definitions=active_measurements(project); rows=[r for r in project.catalog_rows() if not r.get("excluded")]
 fields=[*IDENTITY_FIELDS,"mm_per_pixel",*[f'{d["abbr"]}_mm' for d in definitions]]; out=io.StringIO(newline=""); w=csv.DictWriter(out,fieldnames=fields,delimiter=delimiter,lineterminator="\n");w.writeheader(); complete=na=0; calibrated=set()
 for row in rows:
  values,mpp=values_for_image(project,row,definitions); locality=row.get("locality") or row.get("sample_id") or ""; calibrated.add(locality) if mpp is not None else None
  complete_here=bool(definitions) and all(v!="NA" for v in values.values()); complete+=int(complete_here);na+=int(not complete_here)
  w.writerow({**export_identity(row),"mm_per_pixel":"" if mpp is None else f"{mpp:.{SCALE_DECIMALS}f}",**{f'{k}_mm':"" if v=="NA" else f"{v:.{MEASUREMENT_DECIMALS}f}" for k,v in values.items()}})
 target=Path(target) if target else Path(project.root)/"measurements.csv";_atomic(target,out.getvalue())
 summary=measurement_summary(project);summary["path"]=target;return summary
