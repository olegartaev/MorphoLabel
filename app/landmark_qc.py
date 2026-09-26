"""GUI-independent QC over immutable prediction-run manifests."""
from __future__ import annotations
import json, math, uuid, hashlib
from PIL import Image
from datetime import datetime, timezone
from pathlib import Path
from .io import atomic_json_write
from .landmark_dataset import is_image_unseen_by_model
from .project_storage import schema_hash, load_schema
from .ai import InferenceRequest
from .landmark_ai_service import LandmarkAIService
from .ai_hardware import auto_performance_config, is_cuda_oom

def _pct(values,p):
 if not values:return None
 values=sorted(values);return values[min(len(values)-1,max(0,math.ceil(len(values)*p)-1))]
def _median(values): return _pct(values,.5)
def _manifest_paths(project,model_id): return sorted((project.data_root/'ai'/'predictions').glob('*/manifest.json')) if (project.data_root/'ai'/'predictions').exists() else []
def prediction_input_identity(project, run):
 """Compare immutable prediction input bytes/dimensions to the current standardized cache."""
 path=project.cache_root/'standardized'/f"{run['image_id']}.png"
 if not path.is_file(): return False, 'standardized_png_missing'
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 try:
  with Image.open(path) as image: dimensions=(image.width,image.height)
 except Exception: return False, 'standardized_png_unreadable'
 if digest!=run.get('standardized_sha256'): return False, 'standardized_png_sha256_changed'
 if dimensions!=(run.get('standardized_width'),run.get('standardized_height')): return False, 'standardized_png_dimensions_changed'
 return True, None
def evaluate_model(project,model_id,*,unseen_only=True,image_ids=None,prediction_run_ids=None):
 selected_images=None if image_ids is None else {str(value) for value in image_ids};selected_runs=None if prediction_run_ids is None else {str(value) for value in prediction_run_ids}
 digest=schema_hash(project.schema_path);per_image=[];per_landmark={};all_errors=[];norm=[];mm=[];accepted=corrected=predicted=omitted_present=omitted_missing=pred_human_missing=0;runs=[];input_changed=[]
 for path in _manifest_paths(project,model_id):
  try: run=json.loads(path.read_text(encoding='utf-8'))
  except Exception as exc: raise ValueError(f'invalid prediction manifest: {path}') from exc
  if run.get('model_id')!=model_id or run.get('status')!='success':continue
  if selected_images is not None and str(run.get('image_id')) not in selected_images:continue
  if selected_runs is not None and str(run.get('prediction_run_id')) not in selected_runs:continue
  if run.get('schema_sha256')!=digest:continue
  image_id=run['image_id'];matches,reason=prediction_input_identity(project,run)
  if not matches:
   input_changed.append({'image_id':image_id,'prediction_run_id':run.get('prediction_run_id'),'reason':reason});continue
  ex=project.image_exclusion(image_id)
  if ex.get('excluded') or not project.annotation_status(image_id)['verified']:continue
  unseen=is_image_unseen_by_model(project,model_id,image_id)
  if unseen_only and not unseen:continue
  points=project.load_landmarks(image_id);returned={p['landmark_id']:p for p in run['returned_predictions']};diag=math.hypot(run['standardized_width'],run['standardized_height']);loc=None
  with project.transaction() as c: row=c.execute('SELECT locality,sample_id FROM images WHERE image_id=?',(image_id,)).fetchone()
  if row: loc=row['locality'] or row['sample_id'];cal=project.locality_calibration(loc) if loc else None
  else: cal=None
  image_errors=[];image_corrected=0;image_missing=0;image_omitted=0
  for ident in run['required_landmark_ids']:
   current=points.get(ident);pred=returned.get(ident);bucket=per_landmark.setdefault(str(ident),{'landmark_id':ident,'n':0,'errors_px':[],'confidence':[],'accepted':0,'corrected':0,'omitted_but_human_present':0,'predicted_on_human_missing':0})
   if pred is None:
    image_omitted+=1
    if current and current.get('state')=='missing': omitted_missing+=1
    else: omitted_present+=1;bucket['omitted_but_human_present']+=1
    continue
   predicted+=1
   if current is None or current.get('state')=='missing': pred_human_missing+=1;image_missing+=1;bucket['predicted_on_human_missing']+=1;continue
   if current.get('prediction_run_id')!=run['prediction_run_id']: continue
   error=math.hypot(pred['x']-current['x_standardized'],pred['y']-current['y_standardized']);all_errors.append(error);norm.append(error/diag);image_errors.append(error);bucket['errors_px'].append(error);bucket['n']+=1
   if pred.get('confidence') is not None: bucket['confidence'].append(pred['confidence'])
   if current.get('state')=='auto': accepted+=1;bucket['accepted']+=1
   else: corrected+=1;image_corrected+=1;bucket['corrected']+=1
   if cal: mm.append(error/cal['scale'])
  final_snapshot=[{'landmark_id':ident,'state':'missing' if value.get('state')=='missing' else 'present','x':None if value.get('state')=='missing' else value.get('x_standardized'),'y':None if value.get('state')=='missing' else value.get('y_standardized'),'provenance':value.get('provenance')} for ident,value in sorted(points.items()) if ident in run['required_landmark_ids']]
  runs.append(run['prediction_run_id']);per_image.append({'image_id':image_id,'model_id':model_id,'prediction_run_id':run['prediction_run_id'],'unseen':unseen,'comparable_landmarks':len(image_errors),'median_error_px':_median(image_errors),'max_error_px':max(image_errors) if image_errors else None,'corrected_count':image_corrected,'omitted_count':image_omitted,'missing_mismatch_count':image_missing,'human_final_snapshot':final_snapshot})
 landmarks={key:{'landmark_id':v['landmark_id'],'n':v['n'],'median_error_px':_median(v['errors_px']),'p95_error_px':_pct(v['errors_px'],.95),'accepted_without_correction_fraction':v['accepted']/(v['accepted']+v['corrected']) if v['accepted']+v['corrected'] else None,'omitted_but_human_present':v['omitted_but_human_present'],'predicted_on_human_missing':v['predicted_on_human_missing'],'median_confidence':_median(v['confidence'])} for key,v in per_landmark.items()}
 return {'metric_version':2,'model_id':model_id,'schema_sha256':digest,'report_type':'prospective_unseen' if unseen_only else 'all_reviewed','unseen_only':unseen_only,'prediction_run_ids':runs,'image_ids':[x['image_id'] for x in per_image],'aggregate':{'n_images':len(per_image),'n_comparable_landmarks':len(all_errors),'median_error_px':_median(all_errors),'p90_error_px':_pct(all_errors,.9),'p95_error_px':_pct(all_errors,.95),'max_error_px':max(all_errors) if all_errors else None,'median_error_normalized':_median(norm),'median_error_mm':_median(mm),'accepted_without_correction_fraction':accepted/(accepted+corrected) if accepted+corrected else None,'prediction_completion_rate':predicted/(predicted+omitted_present+omitted_missing) if predicted+omitted_present+omitted_missing else None,'predicted_on_human_missing':pred_human_missing,'omitted_but_human_present':omitted_present,'omitted_human_missing':omitted_missing,'insufficient_data':len(all_errors)<3},'per_landmark':landmarks,'per_image':per_image,'input_changed_after_prediction':input_changed}
def save_qc_report(project,result,report_id=None):
 report_id=str(report_id or uuid.uuid4());path=project.data_root/'ai'/'qc'/'model'/result['model_id']/f'{report_id}.json'
 if path.exists():raise FileExistsError(f'report_id already exists: {report_id}')
 result=dict(result,report_id=report_id,created_at=datetime.now(timezone.utc).isoformat());atomic_json_write(path,result);return path
def evaluate_control_set(project, model_id, *, backend=None, image_ids=None):
 """Read-only Control Set errors; RTMPose batches when its backend supports it."""
 if backend is None:
  from .ai_batch import backend_for_model
  _,backend=backend_for_model(project,model_id)
 if backend.model_id!=str(model_id):raise ValueError("control evaluator prediction model_id does not match requested model")
 digest=schema_hash(project.schema_path)
 if backend.schema_sha256!=digest:raise ValueError("control evaluator backend schema hash does not match current landmark_schema.csv")
 from .landmark_ai_workflow import control_set_summary
 schema=tuple(dict(row) for row in load_schema(project.schema_path));records=[]
 control_ids=tuple(map(str,control_set_summary(project)["current_ids"]))
 requested=None if image_ids is None else tuple(map(str,image_ids))
 evaluation_ids=control_ids if requested is None else requested
 for image_id in evaluation_ids:
  if project.image_exclusion(image_id).get("excluded") or not project.annotation_status(image_id).get("verified"):continue
  human=project.load_landmarks(image_id);valid=[(int(ident),float(point["x_standardized"]),float(point["y_standardized"])) for ident,point in human.items() if point.get("state")!="missing" and point.get("x_standardized") is not None and point.get("y_standardized") is not None and math.isfinite(point["x_standardized"]) and math.isfinite(point["y_standardized"])]
  if len(valid)<2:continue
  span=max(math.hypot(left[1]-right[1],left[2]-right[2]) for index,left in enumerate(valid) for right in valid[index+1:])
  if span<=0:continue
  path=project.cache_root/"standardized"/f"{image_id}.png"
  if not path.is_file():raise FileNotFoundError(f"standardized cache is missing for Control image: {image_id}")
  with Image.open(path) as image:request=InferenceRequest(str(image_id),path,schema,digest,image.width,image.height)
  records.append((image_id,valid,span,request))
 predictions={}
 requests=[record[3] for record in records]
 if hasattr(backend,"predict_readonly_many") and requests:
  performance=auto_performance_config(project,workload="control_evaluation",model=str(model_id),input_size=(requests[0].width,requests[0].height),training=False);size=max(1,int(performance["batch_size"]));offset=0
  while offset<len(requests):
   chunk=requests[offset:offset+size]
   try:returned=backend.predict_readonly_many(chunk)
   except Exception as exc:
    if size>1 and is_cuda_oom(exc):size=max(1,size//2);continue
    if size>1 and "RTMPose rank failed (return code" in str(exc):size=max(1,size//2);continue
    if size==1 and "RTMPose rank failed (return code" in str(exc):raise type(exc)(f"{exc} (image_id={chunk[0].image_id})") from exc
    raise
   predictions.update({prediction.image_id:prediction for prediction in returned});offset+=len(chunk)
 else:
  predictions={request.image_id:backend.predict(request) for request in requests}
 raw_errors=[];percent_errors=[];per_landmark={};evaluated=[]
 for image_id,valid,span,request in records:
  prediction=predictions[request.image_id]
  if prediction.model_id!=backend.model_id:raise ValueError("control evaluator prediction model_id does not match backend")
  LandmarkAIService._validate(prediction,request);returned={point.landmark_id:point for point in prediction.landmarks};image_raw=[];image_percent=[]
  for landmark_id,x,y in valid:
   predicted=returned.get(landmark_id)
   if predicted is None:continue
   error=math.hypot(predicted.x-x,predicted.y-y);percent=error/span*100;raw_errors.append(error);percent_errors.append(percent);per_landmark.setdefault(landmark_id,[]).append(percent);image_raw.append(error);image_percent.append(percent)
  evaluated.append({"image_id":image_id,"reference_span_px":span,"n_landmarks":len(image_percent),"median_error_px":_median(image_raw),"median_error_percent":_median(image_percent)})
 return {"model_id":str(model_id),"schema_sha256":digest,"control_image_ids":tuple(item["image_id"] for item in evaluated),"per_image":evaluated,"per_landmark":{str(ident):{"landmark_id":ident,"median_error_percent":_median(values),"p90_error_percent":_pct(values,.9)} for ident,values in sorted(per_landmark.items())},"aggregate":{"n_images":len(evaluated),"n_comparable_landmarks":len(percent_errors),"median_error_percent":_median(percent_errors),"p90_error_percent":_pct(percent_errors,.9),"p95_error_percent":_pct(percent_errors,.95),"median_error_px":_median(raw_errors),"p90_error_px":_pct(raw_errors,.9),"p95_error_px":_pct(raw_errors,.95)}}
def stored_control_landmark_quality_profile(project, model_id, *, image_ids=None, schema_digest=None):
 """Read a persisted model evaluation, optionally requiring the exact comparison set."""
 path=project.data_root/"ai"/"qc"/"control"/f"{model_id}.json"
 try: profile=json.loads(path.read_text(encoding="utf8"))
 except (OSError,json.JSONDecodeError): return None
 if profile.get("model_id")!=str(model_id):return None
 if image_ids is not None and list(map(str,profile.get("control_image_ids",())))!=list(map(str,image_ids)):return None
 if schema_digest is not None and profile.get("schema_sha256")!=str(schema_digest):return None
 if image_ids is not None and not isinstance(profile.get("aggregate"),dict):return None
 return profile
def persist_control_landmark_quality_profile(project, result, *, activated=False):
 """Persist an already computed Control Set evaluation without inference."""
 model_id=str(result["model_id"]);path=project.data_root/"ai"/"qc"/"control"/f"{model_id}.json"
 ranked=sorted((value for value in result["per_landmark"].values() if value["p90_error_percent"] is not None and value["median_error_percent"] is not None),key=lambda value:(-value["p90_error_percent"],-value["median_error_percent"],value["landmark_id"]))
 weak=ranked[:max(1,math.ceil(len(ranked)*.2))] if ranked else []
 profile={"format_version":2,"model_id":model_id,"schema_sha256":result.get("schema_sha256") or schema_hash(project.schema_path),"created_at":datetime.now(timezone.utc).isoformat(),"control_image_ids":list(result["control_image_ids"]),"aggregate":dict(result.get("aggregate") or {}),"per_landmark":result["per_landmark"],"weak_landmark_ids":[value["landmark_id"] for value in weak],"weak_landmarks":[{"landmark_id":value["landmark_id"],"p90_error_percent":value["p90_error_percent"],"median_error_percent":value["median_error_percent"]} for value in weak]}
 atomic_json_write(path,profile)
 if activated:
  history_path=path.parent/"activated_models.json"
  try: history=json.loads(history_path.read_text(encoding="utf8"))
  except (OSError,json.JSONDecodeError): history={"model_ids":[]}
  model_ids=list(history.get("model_ids",()))
  if model_id not in model_ids:model_ids.append(model_id)
  atomic_json_write(history_path,{"model_ids":model_ids})
 return profile
def control_landmark_quality_profile(project, model_id, *, backend=None, recalculate=False, image_ids=None):
 """Persist a model-specific Control evaluation, evaluating only when needed."""
 digest=schema_hash(project.schema_path)
 if not recalculate:
  profile=stored_control_landmark_quality_profile(project,model_id,image_ids=image_ids,schema_digest=digest if image_ids is not None else None)
  if profile is not None:return profile
 result=evaluate_control_set(project,model_id,backend=backend,image_ids=image_ids)
 return persist_control_landmark_quality_profile(project,result,activated=recalculate)

def stable_weak_landmark_profile(project, model_id):
 """Return only weak landmarks repeated by the two latest activated models."""
 directory=project.data_root/"ai"/"qc"/"control";history_path=directory/"activated_models.json"
 try: model_ids=list(json.loads(history_path.read_text(encoding="utf8")).get("model_ids",()))
 except (OSError,json.JSONDecodeError): return None
 if len(model_ids)<2 or model_ids[-1]!=str(model_id): return None
 try:
  previous=json.loads((directory/f"{model_ids[-2]}.json").read_text(encoding="utf8"));current=json.loads((directory/f"{model_ids[-1]}.json").read_text(encoding="utf8"))
 except (OSError,json.JSONDecodeError): return None
 weak_ids=set(previous.get("weak_landmark_ids",()))&set(current.get("weak_landmark_ids",()))
 if not weak_ids:return None
 details={int(item["landmark_id"]):item for item in current.get("weak_landmarks",())}
 return {"model_id":str(model_id),"weak_landmark_ids":tuple(sorted(map(int,weak_ids))),"weak_landmarks":[details[ident] for ident in sorted(map(int,weak_ids)) if ident in details]}
def compare_control_models(project, previous_model_id, new_model_id, *, backends=None):
 backends=backends or {}
 previous=evaluate_control_set(project,previous_model_id,backend=backends.get(previous_model_id))
 new=evaluate_control_set(project,new_model_id,backend=backends.get(new_model_id))
 keys=("median_error_percent","p90_error_percent","p95_error_percent");old=previous["aggregate"];current=new["aggregate"]
 if any(old[key] is None or current[key] is None for key in keys):result="Mixed"
 elif all(current[key]<old[key] for key in keys):result="Improved"
 elif all(current[key]>old[key] for key in keys):result="Worse"
 else:result="Mixed"
 metrics={key:{"previous":old[key],"new":current[key],"delta_percent":None if old[key] in (None,0) or current[key] is None else (current[key]-old[key])*100/old[key]} for key in keys}
 return {"previous":previous,"new":new,"metrics":metrics,"result":result}
def dataset_split_records(project, dataset_manifest, *, split="validation"):
 """Load immutable validation requests once for one or many checkpoints.

 The returned records contain no model state.  Keeping this preparation
 separate lets the RTMPose finalizer reuse exactly the same images, labels and
 scale spans while a persistent runtime evaluates several saved epochs.
 """
 manifest=json.loads(Path(dataset_manifest).read_text(encoding="utf8"));raw_schema=tuple(manifest["schema_landmarks"]);
 if any("landmark_id" not in row for row in raw_schema):raise ValueError("immutable manifest schema lacks landmark_id")
 expected_ids=tuple(int(row["landmark_id"]) for row in raw_schema)
 if len(set(expected_ids))!=len(expected_ids):raise ValueError("immutable manifest schema landmark IDs are not unique")
 schema=tuple({**row,"id":int(row["landmark_id"])} for row in raw_schema);digest=manifest["schema_sha256"]
 from .ai import InferenceRequest
 records=[]
 for item in manifest["images"]:
  if item.get("split")!=split:continue
  path=project.data_root/item["standardized_relpath"]
  if not path.is_file():raise FileNotFoundError(f"snapshot standardized image is missing: {path}")
  with Image.open(path) as image:request=InferenceRequest(item["image_id"],path,schema,digest,image.width,image.height)
  valid=[(int(x["landmark_id"]),float(x["x"]),float(x["y"])) for x in item["landmarks"] if x.get("state")!="missing" and x.get("x") is not None and x.get("y") is not None]
  if len(valid)<2:continue
  span=max(math.hypot(a[1]-b[1],a[2]-b[2]) for i,a in enumerate(valid) for b in valid[i+1:])
  if span>0:records.append((item["image_id"],valid,span,request))
 return expected_ids,digest,records

def dataset_split_metrics(records, expected_ids, predictions, *, model_id, split="validation"):
 """Calculate the unchanged engineering metrics from prepared requests."""
 predictions={x.image_id:x for x in predictions};errors=[];per_image=[]
 for image_id,valid,span,request in records:
  prediction=predictions.get(image_id)
  if prediction is None or prediction.model_id!=model_id:raise ValueError("missing or mismatched dataset-split prediction")
  returned={x.landmark_id:x for x in prediction.landmarks};
  if tuple(sorted(returned))!=tuple(sorted(expected_ids)):raise ValueError("prediction landmark IDs do not match immutable manifest schema")
  image_errors=[]
  for ident,x,y in valid:
   point=returned.get(ident)
   if point is None:raise ValueError(f"prediction omitted landmark {ident}")
   value=math.hypot(point.x-x,point.y-y)/span*100;errors.append(value);image_errors.append(value)
  per_image.append({"image_id":image_id,"reference_span_px":span,"median_error_percent":_median(image_errors)})
 return {"split":split,"n_images":len(records),"n_landmarks":len(errors),"median_error_percent":_median(errors),"p90_error_percent":_pct(errors,.9),"p95_error_percent":_pct(errors,.95),"per_image":per_image}

def evaluate_dataset_split(project, dataset_manifest, backend, split="validation"):
 """Read-only scale-independent evaluation against immutable snapshot labels."""
 expected_ids,digest,records=dataset_split_records(project,dataset_manifest,split=split)
 if backend.schema_sha256!=digest:raise ValueError("dataset schema does not match backend")
 return dataset_split_metrics(records,expected_ids,backend.predict_readonly_many([r[3] for r in records]),model_id=backend.model_id,split=split)
