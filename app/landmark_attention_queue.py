"""Persistent, DB-authoritative attention queue after Landmark prediction.

The queue stores only stable order/provenance. The action required for each
image is re-derived from SQLite every time so UI state never becomes a second
scientific source of truth.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .landmark_frames import crop_frame_record, landmark_frame_ready
from .landmark_state import load_current_landmark_state

_STATE_KEY="landmark_attention_queue"
_FORMAT_VERSION=1

def _now():
 return datetime.now(timezone.utc).isoformat()

def _load(project):
 value=project.get_ui_state(_STATE_KEY,{}) or {}
 return value if isinstance(value,dict) else {}

def _save(project,value):
 project.set_ui_state(_STATE_KEY,value)

def _unique(values):
 seen=set();result=[]
 for value in values:
  ident=str(value)
  if ident and ident not in seen:
   seen.add(ident);result.append(ident)
 return result

def start(project,image_ids,*,batch_id=None,failure_reasons=None,source="landmark_prediction"):
 ids=_unique(image_ids)
 value={
  "format_version":_FORMAT_VERSION,
  "generation_id":_now(),
  "created_at":_now(),
  "source":str(source),
  "batch_id":None if batch_id is None else str(batch_id),
  "image_ids":ids,
  "position":0,
  "current_image_id":ids[0] if ids else None,
  "completed_ids":[],
  "active":bool(ids),
  "failure_reasons":{str(k):str(v) for k,v in (failure_reasons or {}).items() if str(k) in ids},
 }
 _save(project,value);return dict(value)

def state(project):
 value=_load(project)
 if int(value.get("format_version") or 0)!=_FORMAT_VERSION:return {}
 return value

def active(project):
 value=state(project)
 return value if value.get("active") and value.get("image_ids") else None

def _machine_origin(row):
 return row.get("provenance")=="machine" or row.get("model_id") is not None or row.get("prediction_run_id") is not None

def classify(project,image_id):
 image_id=str(image_id)
 row=project.catalog_row(image_id)
 if not row or row.get("excluded"):
  return {"image_id":image_id,"stage":"resolved","reason":"Excluded or unavailable"}
 crop=crop_frame_record(project,image_id)
 if not crop:
  return {"image_id":image_id,"stage":"crop","reason":"Crop is missing or invalid"}
 if crop.get("provenance") not in {"manual","ai_accepted","ai_corrected"} or not crop.get("human_verified"):
  return {"image_id":image_id,"stage":"crop","reason":"Crop needs human confirmation"}
 if project.landmark_crop_review_required(image_id):
  return {"image_id":image_id,"stage":"crop","reason":"Crop changed and landmarks need review"}
 current=load_current_landmark_state(project,image_id)
 if project.landmark_ai_review_ready(image_id):
  return {"image_id":image_id,"stage":"resolved","reason":"Landmarks verified"}
 points=project.load_landmarks(image_id)
 locked=project.landmark_prediction_locked(image_id)
 if not current.complete:
  if locked:
   return {"image_id":image_id,"stage":"landmarks","reason":"Complete the protected human-confirmed landmark set manually"}
  if landmark_frame_ready(project,image_id):
   return {"image_id":image_id,"stage":"prediction","reason":"AI prediction is missing or incomplete"}
  return {"image_id":image_id,"stage":"crop","reason":"Landmark frame is not ready"}
 if any(_machine_origin(point) for point in points.values()):
  return {"image_id":image_id,"stage":"landmarks","reason":"Review the AI landmark prediction"}
 return {"image_id":image_id,"stage":"landmarks","reason":"Review the completed landmark set"}

def _pending_ids(project,value):
 completed=set(map(str,value.get("completed_ids") or ()))
 result=[]
 for image_id in value.get("image_ids") or ():
  image_id=str(image_id)
  if image_id in completed:continue
  issue=classify(project,image_id)
  if issue["stage"]=="resolved":
   completed.add(image_id);continue
  result.append(image_id)
 if completed!=set(map(str,value.get("completed_ids") or ())):
  value["completed_ids"]=sorted(completed)
 return result

def _position_for(ids,current,default=0):
 if not ids:return 0
 if current in ids:return ids.index(current)
 return max(0,min(int(default or 0),len(ids)-1))

def current(project):
 value=active(project)
 if not value:return None
 pending=_pending_ids(project,value)
 if not pending:
  value.update({"active":False,"current_image_id":None,"position":0});_save(project,value);return None
 current_id=str(value.get("current_image_id") or "")
 position=_position_for(pending,current_id,value.get("position",0))
 value["position"]=position;value["current_image_id"]=pending[position];_save(project,value)
 issue=classify(project,pending[position])
 if issue["stage"]=="prediction":
  issue["reason"]=value.get("failure_reasons",{}).get(pending[position]) or issue["reason"]
 issue["position"]=position+1;issue["total"]=len(pending);issue["remaining"]=len(pending);issue["batch_id"]=value.get("batch_id")
 return issue

def summary(project):
 issue=current(project)
 if not issue:return None
 return {key:issue[key] for key in ("image_id","stage","reason","position","total","remaining","batch_id")}

def move(project,step):
 value=active(project)
 if not value:return None
 pending=_pending_ids(project,value)
 if not pending:
  value.update({"active":False,"current_image_id":None,"position":0});_save(project,value);return None
 current_id=str(value.get("current_image_id") or "")
 position=_position_for(pending,current_id,value.get("position",0))
 target=max(0,min(len(pending)-1,position+int(step)))
 value["position"]=target;value["current_image_id"]=pending[target];_save(project,value)
 return current(project)

def complete_current(project,image_id=None):
 value=active(project)
 if not value:return None
 image_id=str(image_id or value.get("current_image_id") or "")
 completed=set(map(str,value.get("completed_ids") or ()));completed.add(image_id)
 value["completed_ids"]=sorted(completed)
 reasons=dict(value.get("failure_reasons") or {});reasons.pop(image_id,None);value["failure_reasons"]=reasons
 _save(project,value);return current(project)

def record_failure(project,image_id,reason):
 value=active(project)
 if not value:return None
 reasons=dict(value.get("failure_reasons") or {});reasons[str(image_id)]=str(reason);value["failure_reasons"]=reasons
 _save(project,value);return current(project)

def clear_failure(project,image_id):
 value=active(project)
 if not value:return None
 reasons=dict(value.get("failure_reasons") or {});reasons.pop(str(image_id),None);value["failure_reasons"]=reasons
 _save(project,value);return current(project)

def remove_image(project,image_id):
 value=active(project)
 if not value:return None
 image_id=str(image_id);ids=[str(v) for v in value.get("image_ids") or ()]
 if image_id not in ids:return current(project)
 old_index=ids.index(image_id);ids=[v for v in ids if v!=image_id]
 completed=[str(v) for v in value.get("completed_ids") or () if str(v)!=image_id]
 reasons=dict(value.get("failure_reasons") or {});reasons.pop(image_id,None)
 value.update({"image_ids":ids,"completed_ids":completed,"failure_reasons":reasons})
 if not ids:
  value.update({"active":False,"current_image_id":None,"position":0});_save(project,value);return None
 position=min(old_index,len(ids)-1);value["position"]=position;value["current_image_id"]=ids[position]
 _save(project,value);return current(project)

def clear(project):
 _save(project,{"format_version":_FORMAT_VERSION,"active":False,"image_ids":[],"completed_ids":[],"position":0,"current_image_id":None})
