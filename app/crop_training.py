"""Append-only human crop corrections and lightweight local crop regression."""
from __future__ import annotations
import csv, json, time, os, tempfile, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image
from .gui_crop_debug import log
from .io import atomic_json_write, read_json
from .paths import ROOT, require_relative

DATA = ROOT / "data" / "crop_training"
CSV = DATA / "crop_corrections.csv"
MODELS = ROOT / "models"
ACTIVE = MODELS / "crop_model_active.json"
FIELDS = ["timestamp","image_id","source_relpath","developed_full_relpath","width","height","predicted_crop","accepted_crop","x1","y1","x2","y2","crop_model_version"]

def active_info(): return read_json(ACTIVE, {"version":"rule-based","model_id":None})
def current_label(project=None):
 if project is not None:
  row=project.active_model("crop")
  return row.get("model_id") if row else "rule-based"
 info=active_info(); return info.get("model_id") or "rule-based"
def activate(model_id,path=None):
 directory=Path(path) if path else MODELS/str(model_id);manifest=read_json(directory/"model_manifest.json",None)
 if not manifest: raise ValueError(f"unknown crop model: {model_id}")
 atomic_json_write(ACTIVE,{"model_id":model_id,"path":str(directory),"version":model_id,"validation_iou":manifest.get("metrics",{}).get("validation_iou"),"activated_at":datetime.now(timezone.utc).isoformat()})
 return model_id
def _box(box,w,h): return [round(box[0]/w,8),round(box[1]/h,8),round(box[2]/w,8),round(box[3]/h,8)]
def correction_count(): return len(latest_corrections())
def latest_corrections():
 if not CSV.exists(): return []
 latest={}
 with CSV.open(newline="",encoding="utf-8") as f:
  for row in csv.DictReader(f): latest[row["image_id"]]=row
 return list(latest.values())
def save_correction(image_id,source,developed,width,height,predicted,accepted,model_version):
 if tuple(map(round,predicted))==tuple(map(round,accepted)): return False
 DATA.mkdir(parents=True,exist_ok=True); exists=CSV.exists()
 row={"timestamp":datetime.now(timezone.utc).isoformat(),"image_id":image_id,"source_relpath":require_relative(source),"developed_full_relpath":require_relative(developed),"width":width,"height":height,"predicted_crop":json.dumps(list(predicted)),"accepted_crop":json.dumps(list(accepted)),"x1":_box(accepted,width,height)[0],"y1":_box(accepted,width,height)[1],"x2":_box(accepted,width,height)[2],"y2":_box(accepted,width,height)[3],"crop_model_version":model_version}
 with CSV.open("a",newline="",encoding="utf-8") as f:
  writer=csv.DictWriter(f,fieldnames=FIELDS)
  if not exists: writer.writeheader()
  writer.writerow(row);f.flush()
 log(image_id,"crop_correction_saved","END",path=str(CSV),detail=f"model_version={model_version} accepted_crop={accepted}")
 return True
def _feature_image(image):
 image=image.convert("L");image.thumbnail((32,24));canvas=Image.new("L",(32,24),255);canvas.paste(image,((32-image.width)//2,(24-image.height)//2));return np.asarray(canvas,dtype=np.float32).reshape(-1)/255.

def _feature(path):
 with Image.open(ROOT/path) as image:return _feature_image(image)
def _project_target(row,width,height):
 """Production Crop target: four normalized bounds plus circular rotation."""
 bounds=row['crop_bounds'];angle=normalize_rotation(row.get('rotation_degrees') or 0.0)
 return [bounds[0]/width,bounds[1]/height,bounds[2]/width,bounds[3]/height,math.sin(math.radians(angle)),math.cos(math.radians(angle))]
def _project_example(row):
 """One bounded decode supplies both the 32×24 feature and target dimensions."""
 with Image.open(Path(row['developed_path'])) as image:
  image.load();width,height=image.size;feature=_feature_image(image)
 return row['image_id'],feature,_project_target(row,width,height)
_FEATURE_VERSION="crop_feature_gray32x24_v1"
def _feature_signature(path):
 stat=Path(path).stat();return {"version":_FEATURE_VERSION,"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}
def _load_project_feature_cache(project,row):
 """Return a valid cached feature without opening the developed PNG."""
 path=Path(row['developed_path']);cache=project.cache_root/'crop_features'/f"{row['image_id']}.npz";signature=_feature_signature(path)
 try:
  with np.load(cache,allow_pickle=False) as saved:
   if json.loads(str(saved['signature'].item()))==signature:
    return saved['feature'],int(saved['width']),int(saved['height'])
 except (OSError,ValueError,KeyError,json.JSONDecodeError):pass
 return None
def _save_project_feature_cache(project,row,feature,width,height):
 path=Path(row['developed_path']);cache=project.cache_root/'crop_features'/f"{row['image_id']}.npz";signature=_feature_signature(path)
 cache.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix=cache.stem,suffix='.npz',dir=cache.parent);os.close(fd)
 try:
  np.savez_compressed(tmp,feature=feature,width=width,height=height,signature=json.dumps(signature,sort_keys=True));Path(tmp).replace(cache)
 finally:
  if Path(tmp).exists():Path(tmp).unlink()
def _project_feature_cache(project,row):
 """Load a disposable feature cache or decode the developed PNG exactly once."""
 path=Path(row['developed_path']);cache=project.cache_root/'crop_features'/f"{row['image_id']}.npz";signature=_feature_signature(path)
 cached=_load_project_feature_cache(project,row)
 if cached:return *cached,True
 with Image.open(path) as image:
  image.load();width,height=image.size;feature=_feature_image(image)
 _save_project_feature_cache(project,row,feature,width,height)
 return feature,width,height,False
def _iou(a,b):
 x1=max(a[0],b[0]);y1=max(a[1],b[1]);x2=min(a[2],b[2]);y2=min(a[3],b[3]); inter=max(0,x2-x1)*max(0,y2-y1); union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter;return inter/union if union else 0.
def normalize_rotation(angle):
 """SIMM Crop/PIL convention: positive is counter-clockwise about image centre."""
 return (float(angle)+180.0)%360.0-180.0
def circular_error_degrees(predicted,actual): return abs(normalize_rotation(float(predicted)-float(actual)))
def _angles_from_output(values):
 values=np.asarray(values)
 return np.zeros(len(values),dtype=float) if values.shape[1]<6 else np.asarray([normalize_rotation(math.degrees(math.atan2(s,c))) for s,c in values[:,4:6]],dtype=float)
def _predict_features(features,weights):
 raw=np.c_[np.ones((len(features),1)),features]@weights
 raw[:,:4]=np.clip(raw[:,:4],0,1) # Never clip sin/cos: negative values encode rotation.
 return raw
def _metrics(pred,target):
 result={"validation_iou":float(np.mean([_iou(p[:4],t[:4]) for p,t in zip(pred,target)])),"boundary_mae_percent":(np.mean(np.abs(pred[:,:4]-target[:,:4]),axis=0)*100).round(4).tolist()}
 if pred.shape[1]>=6 and target.shape[1]>=6:result["rotation_mae_degrees"]=float(np.mean([circular_error_degrees(a,b) for a,b in zip(_angles_from_output(pred),_angles_from_output(target))]))
 return result
def train(seed=42, ridge=1.0, project=None):
 if project is not None:return train_project(project,seed=seed,ridge=ridge)
 rows=latest_corrections();log("GLOBAL","training_started","START",path=str(CSV),detail=f"training_examples={len(rows)} backend=numpy_ridge")
 if len(rows)<5:
  log("GLOBAL","training_finished","END",path=str(CSV),detail=f"training_examples={len(rows)} validation_iou=NA new_model_activated=False reason=need_at_least_5_unique_corrections")
  return {"trained":False,"reason":"need_at_least_5_unique_corrections","training_examples":len(rows)}
 rng=np.random.default_rng(seed); order=rng.permutation(len(rows)); val_n=max(1,round(len(rows)*.2)); val_i=order[:val_n];train_i=order[val_n:]
 X=np.asarray([_feature(row["developed_full_relpath"]) for row in rows]);Y=np.asarray([[float(row[k]) for k in ("x1","y1","x2","y2")]+[0.,1.] for row in rows])
 A=np.c_[np.ones((len(train_i),1)),X[train_i]]; weights=np.linalg.solve(A.T@A+ridge*np.eye(A.shape[1]),A.T@Y[train_i]);pred=_predict_features(X[val_i],weights);metrics=_metrics(pred,Y[val_i])
 existing=sorted(MODELS.glob("crop_model_v[0-9][0-9][0-9]"));version=f"crop_model_v{len(existing)+1:03d}";directory=MODELS/version;directory.mkdir(parents=True,exist_ok=False);np.savez_compressed(directory/"model.npz",weights=weights);manifest={"model_id":version,"backend":"numpy_ridge_image_regression","input":"32x24 grayscale","output_schema":{"version":2,"fields":["x1","y1","x2","y2","sin_rotation","cos_rotation"],"rotation_convention":"PIL/CropModel positive counter-clockwise about image centre; normalized [-180,180)"},"training_examples":len(rows),"train_indices":train_i.tolist(),"validation_indices":val_i.tolist(),"seed":seed,"ridge":ridge,"metrics":metrics,"created_at":datetime.now(timezone.utc).isoformat()};atomic_json_write(directory/"model_manifest.json",manifest)
 current=active_info();current_iou=-1.
 if current.get("model_id"):
  old=np.load(MODELS/current["model_id"] / "model.npz")["weights"];current_iou=_metrics(_predict_features(X[val_i],old),Y[val_i])["validation_iou"]
 activated=False
 log("GLOBAL","crop_training_candidate_created","END",path=str(directory),detail=f"candidate_model_id={version} previous_active_model_id={current.get('model_id')} training_examples={len(rows)} validation_iou={metrics['validation_iou']:.4f}")
 return {"trained":True,"model_id":version,"metrics":metrics,"new_model_activated":activated,"training_examples":len(rows),"previous_model_id":current.get("model_id")}

def train_project(project,seed=42,ridge=1.0):
 """Use only canonical human-verified Project records; model artifacts stay in Project."""
 started_total=time.perf_counter();rows_started=time.perf_counter();rows=list(project.crop_training_rows());row_query_s=time.perf_counter()-rows_started;log("GLOBAL","crop_training_dataset","END",path=str(project.path),detail=f"total_crops={project.count('crops')} training_eligible={len(rows)} source=project.sqlite")
 if len(rows)<5:return {"trained":False,"reason":"need_at_least_5_project_verified_crops","training_examples":len(rows)}
 rng=np.random.default_rng(seed);order=rng.permutation(len(rows));val_n=max(1,round(len(rows)*.2));val_i=order[:val_n];train_i=order[val_n:]
 timings={"row_query_s":row_query_s};feature_started=time.perf_counter()
 # Only independent cache misses decode PNGs.  Cache hits never open a
 # developed image and are intentionally read on this coordinator thread.
 from .crop_parallel import auto_config,bounded_map,tune_and_prepare
 cached={};misses=[]
 for row in rows:
  try:
   entry=_load_project_feature_cache(project,row)
   if entry is None:misses.append(row)
   else:cached[row['image_id']]=entry
  except OSError:raise
 # The first real cache-miss pass uses the shared bounded executor.  It never
 # touches Project/SQLite and each image has one owner, so writing its feature
 # cache is safe and resumable.
 config=auto_config()
 if misses:
  def probe_extract(row):
   with Image.open(Path(row['developed_path'])) as image:
    image.load();return _feature_image(image),image.width,image.height
  sample=misses[:min(8,len(misses))]
  config,prepared=(tune_and_prepare(project,workload=f"crop_feature_extract_{_FEATURE_VERSION}",sample=sample,worker=probe_extract,fallback=config)
                   if len(sample)>=8 else (config,{}))
  by_id={row['image_id']:row for row in sample}
  for ident,(feature,width,height) in prepared.items():
   row=by_id[ident];_save_project_feature_cache(project,row,feature,width,height);cached[ident]=(feature,width,height)
  misses=[row for row in misses if row['image_id'] not in prepared]
  def extract(row):
   feature,width,height,_=_project_feature_cache(project,row)
   return row['image_id'],feature,width,height
  for row,output,failure in bounded_map(misses,extract,config=config):
   if failure is not None:raise failure
   ident,feature,width,height=output;cached[ident]=(feature,width,height)
 timings["feature_prepare_s"]=time.perf_counter()-feature_started;timings["feature_cache_hits"]=len(rows)-len(misses);timings["feature_cache_misses"]=len(misses)
 solve_started=time.perf_counter()
 X=np.asarray([cached[row['image_id']][0] for row in rows]);Y=np.asarray([_project_target(row,cached[row['image_id']][1],cached[row['image_id']][2]) for row in rows])
 A=np.c_[np.ones((len(train_i),1)),X[train_i]];weights=np.linalg.solve(A.T@A+ridge*np.eye(A.shape[1]),A.T@Y[train_i]);timings["ridge_solve_s"]=time.perf_counter()-solve_started;validation_started=time.perf_counter();metrics=_metrics(_predict_features(X[val_i],weights),Y[val_i]);metrics.update({"train_count":int(len(train_i)),"validation_count":int(len(val_i))});timings["validation_s"]=time.perf_counter()-validation_started
 write_started=time.perf_counter()
 existing=sorted(project.models_root.glob('crop_model_v[0-9][0-9][0-9]'));version=f"crop_model_v{len(existing)+1:03d}";directory=project.models_root/version;directory.mkdir(parents=True,exist_ok=False);np.savez_compressed(directory/'model.npz',weights=weights)
 manifest={"model_id":version,"backend":"numpy_ridge_image_regression","input":"32x24 grayscale","output_schema":{"version":2,"fields":["x1","y1","x2","y2","sin_rotation","cos_rotation"],"rotation_convention":"PIL/CropModel positive counter-clockwise about image centre; normalized [-180,180)"},"training_examples":len(rows),"training_image_ids":[r['image_id'] for r in rows],"train_indices":train_i.tolist(),"validation_indices":val_i.tolist(),"seed":seed,"ridge":ridge,"feature_workers":config['workers'],"metrics":metrics,"created_at":datetime.now(timezone.utc).isoformat()};atomic_json_write(directory/'model_manifest.json',manifest)
 previous=(project.active_model('crop') or {}).get('model_id');image_ids=[r['image_id'] for r in rows];summary=project.crop_training_breakdown(previous,image_ids);all_metrics={**metrics,"training_examples":len(rows),"dataset_summary":summary};project.register_model(version,'crop',path=str(directory.relative_to(project.data_root)).replace('\\','/'),metrics=all_metrics,active=True,parent_model_id=previous);project.record_crop_training_membership(version,image_ids);log("GLOBAL","crop_training_dataset_summary","END",path=str(project.path),detail=" ".join(f"{k}={v}" for k,v in summary.items()));log("GLOBAL","crop_training_candidate_created","END",path=str(directory),detail=f"candidate_model_id={version} previous_active_model_id={previous} training_examples={len(rows)} source=project.sqlite")
 timings["model_write_register_s"]=time.perf_counter()-write_started;timings["total_s"]=time.perf_counter()-started_total
 return {"trained":True,"model_id":version,"metrics":all_metrics,"training_examples":len(rows),"previous_model_id":previous,"project_model":True,"dataset_summary":summary,"timings":timings,"feature_config":config}

def predict(image, *, image_id="UNKNOWN", model_id=None, project=None):
 """Existing crop inference with concise diagnostics; prediction semantics unchanged."""
 info=active_info();project_row=project.active_model("crop") if project is not None else None
 if project is not None and project_row is None: model_id=None
 else: model_id=model_id or (project_row or {}).get("model_id") or info.get("model_id")
 if project_row: info={**info,"path":str(project.data_root/project_row["path"])}
 log(image_id,"crop_inference_start","START",detail=f"active_crop_model_id={model_id or 'None'} image_width={image.width} image_height={image.height}")
 if not model_id:
  log(image_id,"crop_inference_skipped","END",detail="active_crop_model_id=None inference_executed=false reason=no_active_crop_model raw_output=NA confidence=NA")
  return None,"rule-based"
 weights=np.load(Path(info.get("path") or (MODELS/model_id))/"model.npz")["weights"];feature=_feature_image(image);raw=_predict_features(np.asarray([feature]),weights)[0];rotation=normalize_rotation(math.degrees(math.atan2(raw[4],raw[5]))) if len(raw)>=6 else 0.0
 result={"bounds":raw[:4],"rotation_degrees":rotation,"output_count":int(len(raw))}
 log(image_id,"crop_inference_result","END",detail=f"active_crop_model_id={model_id} inference_executed=true raw_output={raw.tolist()} predicted_rotation={rotation:.3f}")
 return result,model_id
