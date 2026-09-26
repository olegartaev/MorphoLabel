"""Immutable, GUI-independent landmark training dataset snapshots."""
from __future__ import annotations
import hashlib
import json
import random
import uuid
from pathlib import Path
from PIL import Image
from .io import atomic_json_write
from .project_storage import Project, schema_hash
from .landmark_frames import landmark_frame_ready, restore_standardized_frame

DATASET_FORMAT_VERSION = 1
SPLITS = ("train", "validation", "test")

class DatasetError(ValueError): pass
class DatasetIntegrityError(DatasetError): pass
class ModelLineageError(DatasetError): pass

def _sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _dataset_dir(project, dataset_id): return project.data_root / "ai" / "datasets" / str(dataset_id)
def dataset_manifest_path(project, dataset_id): return _dataset_dir(project, dataset_id) / "manifest.json"
def _crop_identity(project, image_id):
 with project.transaction() as c: row=c.execute("SELECT crop_json,transform_json,rotation_degrees,standardized_relpath FROM crops WHERE image_id=?",(image_id,)).fetchone()
 value=dict(row) if row else {"crop_json":None,"transform_json":None,"rotation_degrees":None,"standardized_relpath":None}
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
def _standardized_path(project, image_id): return project.cache_root / "standardized" / f"{image_id}.png"
def _manifest_from_path(project, dataset_id_or_path):
 path=Path(dataset_id_or_path) if isinstance(dataset_id_or_path,Path) else dataset_manifest_path(project,dataset_id_or_path)
 try: manifest=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as exc: raise DatasetIntegrityError(f"invalid dataset manifest: {path}") from exc
 if manifest.get("format_version")!=DATASET_FORMAT_VERSION or not manifest.get("dataset_id") or not isinstance(manifest.get("images"),list): raise DatasetIntegrityError("dataset manifest has invalid format")
 return path,manifest

def eligible_image_ids(project: Project, *, include_permanent=False, require_verified=False):
 held=project.permanent_test_image_ids();result=[]
 for row in project.catalog_rows():
  status=project.annotation_status(row["image_id"])
  if row.get("excluded") or status["color"]!="green": continue
  if require_verified and not status["verified"]: continue
  if require_verified and not landmark_frame_ready(project,row["image_id"]): continue
  if not include_permanent and row["image_id"] in held: continue
  result.append(row["image_id"])
 return tuple(sorted(result))

def v2_human_final_eligible(project: Project, image_id, *, include_permanent=False):
 """Exact single-image predicate used by both training and live UI counters."""
 row=project.catalog_row(str(image_id))
 if not row or row.get("excluded"):return False
 status=project.annotation_status(str(image_id))
 if status.get("color")!="green" or not status.get("verified"):return False
 if not landmark_frame_ready(project,str(image_id)):return False
 if not include_permanent and str(image_id) in project.permanent_test_image_ids():return False
 return bool(project.landmark_ai_review_ready(str(image_id)))

def v2_human_final_eligible_image_ids(project: Project, *, include_permanent=False):
 """Checked manual finals and explicitly human-confirmed current AI finals only."""
 checked=eligible_image_ids(project,include_permanent=include_permanent,require_verified=True)
 return tuple(image_id for image_id in checked if project.landmark_ai_review_ready(image_id))

def _eligible_for_mode(project, eligibility_mode, *, include_permanent=False):
 if eligibility_mode=="default": return eligible_image_ids(project,include_permanent=include_permanent)
 if eligibility_mode=="v2_human_final": return v2_human_final_eligible_image_ids(project,include_permanent=include_permanent)
 raise DatasetError("unknown eligibility_mode")

def _validate_explicit(project, splits, eligibility_mode="default"):
 clean={name:tuple(sorted(str(value) for value in values)) for name,values in splits.items() if values}
 if set(clean)-set(SPLITS): raise DatasetError("splits may contain only train, validation, test")
 seen=set();eligible=set(_eligible_for_mode(project,eligibility_mode,include_permanent=True));held=project.permanent_test_image_ids()
 for name,ids in clean.items():
  if len(ids)!=len(set(ids)) or seen.intersection(ids): raise DatasetError("dataset split image IDs overlap")
  if not set(ids)<=eligible: raise DatasetError("dataset contains image that is not human-ready and eligible")
  if name=="train" and set(ids)&held: raise DatasetError("permanent_test image cannot be used for training")
  seen.update(ids)
 return {name:clean.get(name,()) for name in SPLITS}

def deterministic_splits(project: Project, *, split_fractions=None, split_counts=None, seed=None, group_by=None, eligibility_mode="default"):
 if (split_fractions is None)==(split_counts is None): raise DatasetError("provide exactly one of split_fractions or split_counts")
 if seed is None: raise DatasetError("deterministic split requires an explicit seed")
 if group_by not in (None,"sample","locality"): raise DatasetError("group_by must be None, sample or locality")
 rows={row["image_id"]:row for row in project.catalog_rows()};pool=list(_eligible_for_mode(project,eligibility_mode));n=len(pool)
 if split_fractions is not None:
  values={key:float(split_fractions.get(key,0)) for key in SPLITS}
  if any(value<0 for value in values.values()) or abs(sum(values.values())-1)>1e-9: raise DatasetError("split fractions must be non-negative and sum to 1")
  raw={key:values[key]*n for key in SPLITS};counts={key:int(raw[key]) for key in SPLITS}
  for key in sorted(SPLITS,key=lambda key:(raw[key]-counts[key],key),reverse=True)[:n-sum(counts.values())]: counts[key]+=1
 else:
  counts={key:int(split_counts.get(key,0)) for key in SPLITS}
  if any(value<0 for value in counts.values()) or sum(counts.values())!=n: raise DatasetError("split counts must be non-negative and cover the eligible pool")
 rng=random.Random(seed)
 if group_by is None:
  rng.shuffle(pool);out={};offset=0
  for key in SPLITS: out[key]=tuple(sorted(pool[offset:offset+counts[key]]));offset+=counts[key]
  return out
 groups={}
 for image_id in pool: groups.setdefault(str(rows[image_id].get(group_by) or rows[image_id].get("sample_id") or ""),[]).append(image_id)
 needed=[key for key in SPLITS if counts[key]>0]
 if len(groups)<len(needed): raise DatasetError("not enough groups for requested group split")
 group_names=sorted(groups);rng.shuffle(group_names);out={key:[] for key in SPLITS};remaining=dict(counts)
 for index,name in enumerate(group_names):
  left=len(group_names)-index;empty=[key for key in needed if not out[key]]
  choices=empty if len(empty)>=left else SPLITS
  key=max(choices,key=lambda value:(remaining[value],value))
  out[key].extend(groups[name]);remaining[key]-=len(groups[name])
 return {key:tuple(sorted(value)) for key,value in out.items()}

def create_dataset(project: Project, *, dataset_id=None, splits=None, split_fractions=None, split_counts=None, seed=None, group_by=None, eligibility_mode="default", prepared_snapshot=None, hardware=None):
 assigned=_validate_explicit(project,splits,eligibility_mode) if splits is not None else deterministic_splits(project,split_fractions=split_fractions,split_counts=split_counts,seed=seed,group_by=group_by,eligibility_mode=eligibility_mode)
 dataset_id=str(dataset_id or uuid.uuid4())
 directory=_dataset_dir(project,dataset_id);path=directory/"manifest.json"
 try: directory.mkdir(parents=True,exist_ok=False)
 except FileExistsError as exc: raise FileExistsError(f"dataset_id already exists: {dataset_id}") from exc
 schema=tuple(dict(row) for row in project.schema);digest=schema_hash(project.schema_path);images=[]
 # One GUI-independent preparation snapshot is shared by preflight, the
 # current-data probe and this immutable manifest.  It is revalidated here,
 # after the user has confirmed training, so changed labels/crops never leak
 # into a scientific snapshot.
 from .landmark_preparation import prepare_training_snapshot
 prior = prepared_snapshot
 if isinstance(prior, (str, Path)):
  try: prior=json.loads(Path(prior).read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError): prior=None
 all_ids=tuple(image_id for split in SPLITS for image_id in assigned[split])
 prepared=prepare_training_snapshot(project,all_ids,reuse=prior,hardware=hardware)
 try:
  for split in SPLITS:
   for image_id in assigned[split]:
    entry=prepared["entries"][str(image_id)]
    images.append({"image_id":image_id,"split":split,"sample_id":entry.get("sample_id"),"locality":entry.get("locality"),"standardized_relpath":entry["standardized_relpath"],"standardized_width":entry["standardized_width"],"standardized_height":entry["standardized_height"],"standardized_sha256":entry["standardized_sha256"],"crop_transform_sha256":entry["crop_transform_sha256"],"human_verified":bool(entry["human_verified"]),"qc_color":entry["qc_color"],"training_label_origins":entry["training_label_origins"],"landmarks":entry["labels"]})
  manifest={"format_version":DATASET_FORMAT_VERSION,"dataset_id":dataset_id,"created_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"schema_sha256":digest,"schema_landmarks":[{"landmark_id":int(row["id"]),"abbr":row["abbr"],"role":row.get("role","BOTH")} for row in schema],"split_seed":seed,"group_by":group_by,"eligibility_mode":eligibility_mode,"images":images}
  atomic_json_write(path,manifest)
 except BaseException:
  # No partial manifest is published; the reserved directory keeps this ID unusable.
  raise
 return manifest

def verify_dataset(project: Project, dataset_id_or_path):
 try: path,manifest=_manifest_from_path(project,dataset_id_or_path)
 except DatasetIntegrityError as exc: return {"ok":False,"errors":[str(exc)]}
 errors=[]
 current_identity=tuple(str(row.get("abbr") or "").strip() for row in project.schema)
 manifest_identity=tuple(str(row.get("abbr") or "").strip() for row in (manifest.get("schema_landmarks") or ()))
 if manifest_identity!=current_identity: errors.append("schema_identity_mismatch")
 seen=set()
 for entry in manifest["images"]:
  image_id=entry.get("image_id")
  if image_id in seen: errors.append(f"duplicate_image:{image_id}")
  seen.add(image_id);standard=project.data_root/entry.get("standardized_relpath","")
  if not standard.exists(): errors.append(f"standardized_missing:{image_id}");continue
  try:
   with Image.open(standard) as image: width,height=image.size
  except Exception: errors.append(f"standardized_invalid:{image_id}");continue
  if (width,height)!=(entry.get("standardized_width"),entry.get("standardized_height")): errors.append(f"standardized_dimensions_changed:{image_id}")
  if _sha256(standard)!=entry.get("standardized_sha256"): errors.append(f"standardized_sha256_mismatch:{image_id}")
  if _crop_identity(project,image_id)!=entry.get("crop_transform_sha256"): errors.append(f"crop_transform_mismatch:{image_id}")
 return {"ok":not errors,"errors":errors,"manifest_path":str(path)}

def _training_label_fingerprint(labels, crop_transform_sha256):
 normalized=[]
 for value in labels:
  state="missing" if value.get("state")=="missing" else "present"
  normalized.append({
   "landmark_id":int(value["landmark_id"]),
   "state":state,
   "x":None if state=="missing" else float(value["x"]),
   "y":None if state=="missing" else float(value["y"]),
  })
 payload={"crop_transform_sha256":crop_transform_sha256,"landmarks":normalized}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()

def current_training_state_fingerprint(project: Project, image_id):
 """Scientific training state of one current human-final image, without hashing image bytes."""
 points=project.load_landmarks(str(image_id));labels=[]
 for row in project.schema:
  ident=int(row["id"]);value=points.get(ident)
  if value is None:return None
  state="missing" if value.get("state")=="missing" else "present"
  if state=="present" and (value.get("x_standardized") is None or value.get("y_standardized") is None):return None
  labels.append({"landmark_id":ident,"state":state,"x":value.get("x_standardized"),"y":value.get("y_standardized")})
 return _training_label_fingerprint(labels,_crop_identity(project,str(image_id)))

def current_training_state_fingerprints(project: Project, image_ids):
 """Bulk current training fingerprints without per-image SQLite round trips."""
 wanted={str(value) for value in image_ids}
 if not wanted:return {}
 schema=tuple(dict(row) for row in project.schema);display_by_abbr={str(row["abbr"]):int(row["id"]) for row in schema}
 crops={};points={image_id:{} for image_id in wanted}
 with project.transaction() as connection:
  for row in connection.execute("SELECT image_id,crop_json,transform_json,rotation_degrees,standardized_relpath FROM crops"):
   image_id=str(row["image_id"])
   if image_id not in wanted:continue
   value={key:row[key] for key in ("crop_json","transform_json","rotation_degrees","standardized_relpath")}
   crops[image_id]=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
  for row in connection.execute("SELECT image_id,landmark_abbr,x_standardized,y_standardized,state FROM landmarks"):
   image_id=str(row["image_id"])
   if image_id not in wanted:continue
   ident=display_by_abbr.get(str(row["landmark_abbr"] or ""))
   if ident is not None:points[image_id][ident]=dict(row)
 out={}
 for image_id in wanted:
  labels=[];valid=True
  for row in schema:
   ident=int(row["id"]);value=points.get(image_id,{}).get(ident)
   if value is None:
    valid=False;break
   state="missing" if value.get("state")=="missing" else "present"
   if state=="present" and (value.get("x_standardized") is None or value.get("y_standardized") is None):
    valid=False;break
   labels.append({"landmark_id":ident,"state":state,"x":value.get("x_standardized"),"y":value.get("y_standardized")})
  out[image_id]=_training_label_fingerprint(labels,crops.get(image_id)) if valid else None
 return out

def model_training_state_fingerprints(project: Project, model_id):
 """Latest train/validation state for each image represented by a model lineage."""
 fingerprints={};seen_models=set();current=str(model_id)
 while current:
  if current in seen_models:raise ModelLineageError("model lineage cycle detected")
  seen_models.add(current)
  with project.transaction() as connection:
   row=connection.execute("SELECT model_id,dataset_id,parent_model_id,dataset_manifest_path FROM models WHERE model_id=?",(current,)).fetchone()
  if row is None:raise ModelLineageError(f"model lineage parent is missing: {current}")
  row=dict(row);manifest_path=row.get("dataset_manifest_path")
  if manifest_path:
   path=Path(manifest_path);path=path if path.is_absolute() else project.data_root/path
   _,manifest=_manifest_from_path(project,path)
   if row.get("dataset_id")!=manifest.get("dataset_id"):raise ModelLineageError("model dataset_id does not match manifest")
   for entry in manifest["images"]:
    if entry.get("split") not in {"train","validation"}:continue
    image_id=str(entry["image_id"])
    if image_id in fingerprints:continue
    try:fingerprints[image_id]=_training_label_fingerprint(entry.get("landmarks") or (),entry.get("crop_transform_sha256"))
    except (KeyError,TypeError,ValueError):fingerprints[image_id]=None
  current=row.get("parent_model_id")
 return fingerprints

def training_ready_image_ids(project: Project, model_id=None):
 """Human-final images whose current labels/crop are not represented by the active lineage."""
 eligible=tuple(v2_human_final_eligible_image_ids(project))
 if model_id is None:
  try:active=project.active_model_readonly("landmark") or {}
  except ValueError:active={}
  model_id=active.get("model_id")
 if not model_id:return eligible
 try:represented=model_training_state_fingerprints(project,model_id)
 except Exception:return eligible
 current=current_training_state_fingerprints(project,eligible)
 return tuple(image_id for image_id in eligible if represented.get(str(image_id))!=current.get(str(image_id)))

def model_seen_image_ids(project: Project, model_id):
 seen_models=set();seen_images=set();current=str(model_id)
 while current:
  if current in seen_models: raise ModelLineageError("model lineage cycle detected")
  seen_models.add(current)
  with project.transaction() as c: row=c.execute("SELECT model_id,dataset_id,parent_model_id,dataset_manifest_path FROM models WHERE model_id=?",(current,)).fetchone()
  if row is None: raise ModelLineageError(f"model lineage parent is missing: {current}")
  row=dict(row);manifest_path=row.get("dataset_manifest_path")
  if manifest_path:
   path=Path(manifest_path);path=path if path.is_absolute() else project.data_root/path
   _,manifest=_manifest_from_path(project,path)
   if row.get("dataset_id")!=manifest.get("dataset_id"): raise ModelLineageError("model dataset_id does not match manifest")
   seen_images.update(entry["image_id"] for entry in manifest["images"] if entry.get("split") in {"train","validation"})
  current=row.get("parent_model_id")
 return frozenset(seen_images)

def is_image_unseen_by_model(project: Project, model_id, image_id): return str(image_id) not in model_seen_image_ids(project,model_id)
