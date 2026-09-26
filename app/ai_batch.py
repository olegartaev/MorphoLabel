"""Prospective AI batch selection and persistence; GUI-independent."""
from __future__ import annotations
import json, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from .io import atomic_json_write
from .ai import LandmarkBackend
from .landmark_ai_service import LandmarkAIService
from .project_storage import schema_hash, landmark_model_schema_compatible, landmark_schema_identity, load_schema
from .extensions.api import BackendContext
from .extensions.builtins import backend_registry
from .ai_hardware import auto_performance_config
from .landmark_frames import landmark_frame_ready

BATCH_FORMAT_VERSION=1
class BatchError(ValueError): pass

def _now(): return datetime.now(timezone.utc).isoformat()
def _batch_path(project,batch_id): return project.data_root/'ai'/'batches'/str(batch_id)/'manifest.json'
def _manifest(project,model):
 path=Path(model.get('dataset_manifest_path') or '')
 path=path if path.is_absolute() else project.data_root/path
 try:return json.loads(path.read_text(encoding='utf8'))
 except Exception as exc:raise BatchError('active model development dataset manifest is unavailable') from exc

def backend_for_model(project,model_id,*,model=None,registry=None):
 model=project.model_metadata(model_id) if model is None else model
 if not model or model.get('kind')!='landmark':raise BatchError('requested landmark model is unavailable')
 if not landmark_model_schema_compatible(project,model):raise BatchError('landmark model landmark identities/order do not match current landmark_schema.csv')
 artifact=project.data_root/(model.get('path') or '')
 info=json.loads((artifact/'model.json').read_text(encoding='utf8'))
 input_size=tuple(info.get('input_size') or model.get('input_size') or (512,256))
 performance=auto_performance_config(project,workload='landmark_inference',model=str(model['model_id']),input_size=input_size,training=False)
 metrics=json.loads(model.get('metrics_json') or '{}')
 provider_id=info.get('backend_id') or info.get('backend') or model.get('backend_id') or metrics.get('backend') or 'rtmpose'
 provider=(registry or backend_registry()).get(provider_id)
 if provider is None or provider.task!='landmark':raise BatchError(f'landmark backend is unavailable: {provider_id}')
 context=BackendContext(project,model,artifact,info,input_size,performance)
 try:backend=provider.factory(context)
 except ValueError as exc:raise BatchError(str(exc)) from exc
 if not isinstance(backend,LandmarkBackend):raise BatchError(f'backend provider {provider_id} did not return a LandmarkBackend')
 return model,backend

def active_backend(project,*,model=None):
 model=project.active_model('landmark') if model is None else model
 if not model:raise BatchError('no active landmark model')
 return backend_for_model(project,model['model_id'],model=model)

def prospective_candidates(project,model_id,start_image_id,count,*,allow_small=False):
 """Next catalog rows with no annotation and no development-snapshot exposure.

 When allow_small is true, return the remaining prospective images instead of
 failing just because fewer than the requested batch size remain.
 """
 model=project.model_metadata(model_id)
 if not model:raise BatchError('model metadata is unavailable')
 development={str(row['image_id']) for row in _manifest(project,model).get('images',())}
 held=project.permanent_test_image_ids();catalog=project.catalog_rows();order=[row['image_id'] for row in catalog]
 if start_image_id not in order:raise BatchError('current image is not in active catalog')
 start=order.index(start_image_id);ordered=order[start+1:]+order[:start+1];chosen=[]
 for image_id in ordered:
  row=next(row for row in catalog if row['image_id']==image_id)
  if row.get('excluded') or image_id in held or image_id in development or not landmark_frame_ready(project,image_id):continue
  if project.load_landmarks(image_id):continue
  chosen.append(image_id)
  if len(chosen)==int(count):break
 if not chosen and not allow_small:raise BatchError('no prospective unannotated candidates are available')
 if len(chosen)!=int(count) and not allow_small:raise BatchError(f'only {len(chosen)} prospective unannotated candidates are available')
 return tuple(chosen),development

def create_batch(project,model_id,start_image_id,count):
 model=project.model_metadata(model_id)
 if not model or not model.get('active'):raise BatchError('requested model is not the active landmark model')
 if not landmark_model_schema_compatible(project,model):raise BatchError('active model landmark identities/order do not match current landmark_schema.csv')
 ids,development=prospective_candidates(project,model_id,start_image_id,count,allow_small=True);catalog={row['image_id']:row for row in project.catalog_rows()}
 if not ids:raise BatchError('no prospective unannotated candidates are available')
 batch_id=f'{model_id}_batch_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}_{uuid.uuid4().hex[:8]}'
 path=_batch_path(project,batch_id);path.parent.mkdir(parents=True,exist_ok=False)
 items=[{'image_id':image_id,'display_name':f"{catalog[image_id].get('locality') or catalog[image_id].get('sample_id')} | {catalog[image_id].get('original_name')}",'outside_development_dataset':image_id not in development} for image_id in ids]
 data={'format_version':BATCH_FORMAT_VERSION,'batch_id':batch_id,'created_at':_now(),'model_id':model_id,'model_dataset_id':model.get('dataset_id'),'schema_sha256':schema_hash(project.schema_path),'schema_identity':list(landmark_schema_identity(load_schema(project.schema_path))),'selection_mode':'new_unannotated','selection_rule':'next eligible unannotated catalog images after current image; wrap only if needed','requested_count':int(count),'selected_count':len(items),'start_image_id':str(start_image_id),'selected_images':items,'prediction_runs':{},'failures':{}}
 atomic_json_write(path,data);return data,path

def create_batch_for_ids(project,model_id,image_ids,*,selection_mode='explicit'):
 model=project.model_metadata(model_id)
 if not model or not model.get("active"):raise BatchError("requested model is not the active landmark model")
 catalog={row["image_id"]:row for row in project.catalog_rows()};ids=tuple(map(str,image_ids))
 if not ids or any(i not in catalog for i in ids):raise BatchError("requested prediction image IDs are unavailable")
 invalid=[i for i in ids if catalog[i].get("excluded") or not landmark_frame_ready(project,i)]
 if invalid:raise BatchError("requested prediction image IDs are not crop-ready: "+", ".join(invalid[:5]))
 verified=[i for i in ids if project.annotation_status(i).get("verified")]
 if verified:raise BatchError("requested prediction image IDs include human-verified images: "+", ".join(verified[:5]))
 batch_id=f"{model_id}_batch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}";path=_batch_path(project,batch_id);path.parent.mkdir(parents=True,exist_ok=False)
 data={"format_version":BATCH_FORMAT_VERSION,"batch_id":batch_id,"created_at":_now(),"model_id":model_id,"schema_sha256":schema_hash(project.schema_path),"schema_identity":list(landmark_schema_identity(load_schema(project.schema_path))),"selection_mode":str(selection_mode),"selection_rule":"explicit eligible image IDs","requested_count":len(ids),"selected_count":len(ids),"start_image_id":ids[0],"selected_images":[{"image_id":i,"display_name":str(catalog[i].get("original_name") or i)} for i in ids],"prediction_runs":{},"failures":{}};atomic_json_write(path,data);return data,path
def load_batch(project,batch_id_or_path):
 path=Path(batch_id_or_path);path=path if path.suffix else _batch_path(project,path)
 return json.loads(path.read_text(encoding='utf8')),path

def run_batch(project,batch_id_or_path,service,progress=None,status=None):
 data,path=load_batch(project,batch_id_or_path);started=time.perf_counter()
 if not data.get("prediction_started_at"):
  data["prediction_started_at"]=_now();atomic_json_write(path,data)
 current_identity=landmark_schema_identity(load_schema(project.schema_path))
 if data.get("schema_identity"):
  if tuple(map(str,data["schema_identity"]))!=current_identity:raise BatchError("batch landmark identities/order do not match current landmark_schema.csv")
 elif data.get("schema_sha256")!=schema_hash(project.schema_path):
  model=project.model_metadata(data.get("model_id"))
  if not landmark_model_schema_compatible(project,model):raise BatchError("batch landmark identities/order do not match current landmark_schema.csv")
 pending=[item for item in data["selected_images"] if item["image_id"] not in data["prediction_runs"] and item["image_id"] not in data["failures"]]
 total=len(data["selected_images"]);completed=total-len(pending)
 def persisted(image_id,result,error):
  nonlocal completed
  if result:data["prediction_runs"][image_id]=result.prediction_run_id
  else:data["failures"][image_id]=str(error)
  completed+=1;atomic_json_write(path,data)
  if progress:progress(completed,total,next((item.get("display_name",image_id) for item in data["selected_images"] if item["image_id"]==image_id),image_id))
 if pending:
  if hasattr(service,"predict_many"):
   try:service.predict_many([item["image_id"] for item in pending],progress=persisted,status=status)
   except TypeError as exc:
    if "unexpected keyword argument 'status'" not in str(exc):raise
    service.predict_many([item["image_id"] for item in pending],progress=persisted)
  else:
   for item in pending:
    image_id=item["image_id"]
    try:result=service.predict_one(image_id);persisted(image_id,result,None)
    except Exception as exc:persisted(image_id,None,exc)
 data["completed_at"]=_now();atomic_json_write(path,data)
 return data,path
def preflight_backend(project,backend,image_id):
 info=backend._invoke('info',{})
 if getattr(backend.spec,'device','').startswith('cuda') and not info.get('cuda_available'):raise BatchError('configured CUDA device is unavailable')
 request=LandmarkAIService(project,backend)._request(image_id)
 LandmarkAIService._validate(backend.predict(request),request)
 return info

def reviewed_count(project,batch):
 return sum(bool(project.annotation_status(item['image_id'])['verified']) for item in batch['selected_images'])
