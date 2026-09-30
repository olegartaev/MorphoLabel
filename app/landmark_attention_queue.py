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
  "current_stage":None,
  "current_reason":None,
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
 current=load_current_landmark_state(project,image_id)
 if project.landmark_crop_review_required(image_id):
  reason="Crop confirmed; review landmarks in the new crop" if current.complete else "Crop confirmed; complete landmarks in the new crop"
  return {"image_id":image_id,"stage":"landmarks","reason":reason}
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

def stage_counts(project,image_ids):
 counts={"crop":0,"prediction":0,"landmarks":0,"resolved":0}
 for image_id in _unique(image_ids):
  stage=classify(project,image_id).get("stage","resolved")
  counts[stage]=counts.get(stage,0)+1
 counts["total"]=sum(counts.get(key,0) for key in ("crop","prediction","landmarks"))
 return counts

def _short_reason(reason):
 text=str(reason or "").strip()
 if not text:return ""
 lines=[line.strip() for line in text.splitlines() if line.strip()]
 preferred=next((line for line in reversed(lines) if line.startswith(("ModuleNotFoundError:","ImportError:","RuntimeError:","ValueError:","FileNotFoundError:","OSError:"))),lines[-1] if lines else text)
 return preferred[:180]

def user_copy(issue):
 stage=str((issue or {}).get("stage") or "")
 reason=_short_reason((issue or {}).get("reason"))
 if stage=="crop":
  detail={
   "Crop is missing or invalid":"The crop is missing or cannot be used for landmark prediction.",
   "Crop needs human confirmation":"The crop exists but has not yet been confirmed.",
   "Crop changed and landmarks need review":"The crop changed after landmarks were created, so it must be confirmed before continuing.",
   "Landmark frame is not ready":"The image is not ready for landmark prediction until its crop is confirmed.",
  }.get(reason,reason or "This image needs its crop checked before landmark prediction can continue.")
  return {"title":"Crop needs attention","message":detail+" Adjust the frame if needed, then confirm it. The review queue will continue automatically.","action":"Confirm crop & continue","help":"Save and confirm this crop, then continue the same prediction-review queue."}
 if stage=="prediction":
  detail="AI could not finish landmark prediction for this image."
  if reason and reason!="AI prediction is missing or incomplete":detail+=" "+reason
  return {"title":"AI prediction needs attention","message":detail+" Retry AI. If it fails again, check the crop or exclude the image.","action":"Retry AI","help":"Retry landmark prediction for this queued image without changing human-confirmed images."}
 if reason.startswith("Crop confirmed;"):
  message="The Crop is already confirmed. Check the landmarks in this updated Crop, correct or complete them if needed, then verify the image. You will not be sent back to Crop."
 else:
  message="Check the landmark positions and correct any that are wrong. When they are ready, verify the image and continue the same queue."
 return {"title":"Review landmarks","message":message,"action":"Verify & continue","help":"Verify this landmark set after review and continue to the next queued image."}

def _mark_completed(value,image_id):
 completed=set(map(str,value.get("completed_ids") or ()));completed.add(str(image_id));value["completed_ids"]=sorted(completed)

def _seek(project,value,start,direction=1):
 ids=[str(v) for v in value.get("image_ids") or ()]
 if not ids:return None
 completed=set(map(str,value.get("completed_ids") or ()))
 index=max(0,min(int(start),len(ids)-1))
 positions=range(index,len(ids)) if int(direction)>=0 else range(index,-1,-1)
 for position in positions:
  image_id=ids[position]
  if image_id in completed:continue
  issue=classify(project,image_id)
  if issue["stage"]=="resolved":
   completed.add(image_id);continue
  value["completed_ids"]=sorted(completed)
  value["position"]=position;value["current_image_id"]=image_id
  value["current_stage"]=issue["stage"];value["current_reason"]=issue["reason"]
  value["active"]=True;_save(project,value)
  issue["position"]=position+1;issue["total"]=len(ids);issue["remaining"]=max(0,len(ids)-len(completed));issue["batch_id"]=value.get("batch_id")
  if issue["stage"]=="prediction":
   issue["reason"]=value.get("failure_reasons",{}).get(image_id) or issue["reason"]
   value["current_reason"]=issue["reason"];_save(project,value)
  return issue
 value["completed_ids"]=sorted(completed);value.update({"active":False,"current_image_id":None,"current_stage":None,"current_reason":None});_save(project,value)
 return None

def current(project):
 value=active(project)
 if not value:return None
 return _seek(project,value,int(value.get("position") or 0),1)

def display_summary(project):
 value=active(project)
 if not value:return None
 ids=[str(v) for v in value.get("image_ids") or ()];current_id=str(value.get("current_image_id") or "")
 if current_id not in ids:return None
 completed=set(map(str,value.get("completed_ids") or ()))
 return {
  "image_id":current_id,
  "stage":value.get("current_stage"),
  "reason":value.get("current_reason"),
  "position":ids.index(current_id)+1,
  "total":len(ids),
  "remaining":max(0,len(ids)-len(completed)),
  "batch_id":value.get("batch_id"),
 }

def summary(project):
 return display_summary(project)

def move(project,step):
 value=active(project)
 if not value:return None
 ids=[str(v) for v in value.get("image_ids") or ()]
 current_id=str(value.get("current_image_id") or "")
 position=ids.index(current_id) if current_id in ids else max(0,min(int(value.get("position") or 0),max(0,len(ids)-1)))
 if int(step)<0:
  issue=_seek(project,value,max(0,position-1),-1)
  return issue or current(project)
 return _seek(project,value,min(len(ids)-1,position+1),1)

def complete_current(project,image_id=None):
 value=active(project)
 if not value:return None
 image_id=str(image_id or value.get("current_image_id") or "")
 completed=set(map(str,value.get("completed_ids") or ()));completed.add(image_id)
 value["completed_ids"]=sorted(completed)
 reasons=dict(value.get("failure_reasons") or {});reasons.pop(image_id,None);value["failure_reasons"]=reasons
 position=int(value.get("position") or 0);_save(project,value)
 return _seek(project,value,position,1)

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
 position=min(old_index,len(ids)-1);value["position"]=position;value["current_image_id"]=ids[position];value["current_stage"]=None;value["current_reason"]=None
 _save(project,value);return current(project)

def clear(project):
 _save(project,{"format_version":_FORMAT_VERSION,"active":False,"image_ids":[],"completed_ids":[],"position":0,"current_image_id":None})
