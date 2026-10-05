"""Persistent finite review sessions for successful Landmark prediction batches."""
from __future__ import annotations
from datetime import datetime, timezone

_STATE_KEY="landmark_prediction_review_sessions"
def _now(): return datetime.now(timezone.utc).isoformat()
def _load(project):
 value=project.get_ui_state(_STATE_KEY,{}) or {}
 return value if isinstance(value,dict) else {"format_version":1,"sessions":[]}
def _save(project,value): project.set_ui_state(_STATE_KEY,value)
def successful_prediction_ids(batch):
 runs=set((batch or {}).get("prediction_runs",{}))
 return tuple(str(item["image_id"]) for item in (batch or {}).get("selected_images",()) if str(item.get("image_id")) in runs)
def _session(doc,batch_id): return next((item for item in doc.get("sessions",()) if item.get("batch_id")==str(batch_id)),None)
def create_review_session(project,batch, *, kind="prediction_batch"):
 ids=successful_prediction_ids(batch)
 if not ids: raise ValueError("prediction batch has no successful images to review")
 doc=_load(project);session=_session(doc,batch["batch_id"])
 if session is None:
  session={"kind":kind,"batch_id":str(batch["batch_id"]),"image_ids":list(ids),"current_position":0,"current_image_id":ids[0],"complete":False,"active":False,"created_at":_now()};doc.setdefault("sessions",[]).append(session)
 _save(project,doc);return dict(session)
def create_review_session_for_ids(project, session_id, image_ids, *, kind="review_worst", metadata=None):
 ids=tuple(str(image_id) for image_id in image_ids)
 if kind=="review_worst_v2":
  ids=tuple(image_id for image_id in ids if not project.landmark_ai_review_ready(image_id))
 if not ids: raise ValueError("AI review has no pending images")
 review_meta={str(key):dict(value) for key,value in (metadata or {}).items() if str(key) in ids}
 doc=_load(project);session=_session(doc,session_id)
 if kind=="review_worst_v2":
  # A fresh review becomes active independently. Earlier unfinished queues
  # remain resumable until the user closes them or all their members are done.
  for item in doc.get("sessions",()):
   if item is session or item.get("complete") or item.get("kind")!="review_worst_v2":continue
   item.update({"active":False,"superseded_at":_now()})
 if session is None:
  session={"kind":kind,"batch_id":str(session_id),"image_ids":list(ids),"current_position":0,"current_image_id":ids[0],"complete":False,"active":False,"created_at":_now(),"review_meta":review_meta};doc.setdefault("sessions",[]).append(session)
 else:
  session.update({"kind":kind,"image_ids":list(ids),"current_position":0,"current_image_id":ids[0],"complete":False,"active":False,"refreshed_at":_now(),"review_meta":review_meta})
 _save(project,doc);return dict(session)
def supersede_unfinished_reviews(project,reason=None):
 doc=_load(project);changed=False
 for item in doc.get("sessions",()):
  if item.get("complete"):continue
  item.update({"active":False,"superseded_at":_now()})
  if reason:item["superseded_reason"]=str(reason)
  changed=True
 if changed:_save(project,doc)
 return changed

def pending_review_session(project):
 doc=_load(project)
 return next((dict(item) for item in doc.get("sessions",()) if not item.get("complete") and not item.get("closed")),None)

def pending_review_sessions(project):
 return tuple(dict(item) for item in _load(project).get("sessions",()) if not item.get("complete") and not item.get("closed"))
def active_review_session(project):
 doc=_load(project)
 return next((dict(item) for item in doc.get("sessions",()) if item.get("active") and not item.get("complete") and not item.get("closed")),None)
def _pending_positions(project,ids):
 return [index for index,image_id in enumerate(ids) if not project.landmark_ai_review_ready(image_id)]

def _pending_target(project,ids,current_position,step=1):
 pending=_pending_positions(project,ids)
 if not pending:return None
 current_position=max(0,min(int(current_position),len(ids)-1))
 if int(step)<0:
  before=[index for index in pending if index<current_position]
  if before:return before[-1]
  return current_position if current_position in pending else pending[0]
 after=[index for index in pending if index>current_position]
 if after:return after[0]
 return current_position if current_position in pending else pending[0]

def activate_review_session(project,batch_id=None):
 doc=_load(project);session=_session(doc,batch_id) if batch_id else next((item for item in doc.get("sessions",()) if not item.get("complete") and not item.get("closed")),None)
 if session is None or session.get("complete") or session.get("closed"):return None
 for item in doc.get("sessions",()):item["active"]=False
 ids=list(session.get("image_ids",()))
 if not ids:return None
 if session.get("kind")=="review_worst_v2":
  pending=[image_id for image_id in ids if not project.landmark_ai_review_ready(image_id)]
  if pending!=ids:
   session.setdefault("original_image_ids",list(ids))
   meta=dict(session.get("review_meta") or {})
   session["review_meta"]={image_id:meta[image_id] for image_id in pending if image_id in meta}
   ids=pending;session["image_ids"]=list(ids);session["current_position"]=0;session["current_image_id"]=ids[0] if ids else None
  if not ids:
   session.update({"complete":True,"active":False});_save(project,doc);return None
 position=max(0,min(int(session.get("current_position",0)),len(ids)-1))
 if project.landmark_ai_review_ready(ids[position]):
  target=_pending_target(project,ids,position,1)
  if target is None:
   session.update({"complete":True,"active":False});_save(project,doc);return None
  position=target
 session["active"]=True;session["current_position"]=position;session["current_image_id"]=ids[position]
 _save(project,doc);return dict(session)
def deactivate_review_session(project,batch_id=None):
 doc=_load(project)
 session=_session(doc,batch_id) if batch_id else next((item for item in doc.get("sessions",()) if item.get("active") and not item.get("complete")),None)
 if session is None:return None
 session["active"]=False;_save(project,doc);return dict(session)
def close_review_session(project,batch_id=None):
 """Remove an unfinished review queue without falsely marking its review complete."""
 doc=_load(project)
 session=_session(doc,batch_id) if batch_id else next((item for item in doc.get("sessions",()) if not item.get("complete") and not item.get("closed")),None)
 if session is None:return None
 session.update({"active":False,"closed":True,"closed_at":_now()});_save(project,doc);return dict(session)

def review_summary(project,session=None,current_id=None):
 session=session or active_review_session(project)
 if not session:return None
 ids=tuple(map(str,session.get("image_ids",())))
 current=str(current_id or session.get("current_image_id") or "")
 done=tuple(image_id for image_id in ids if project.landmark_ai_review_ready(image_id))
 remaining=sum(image_id not in done for image_id in ids)
 position=min(len(ids),len(done)+1) if current in ids and current not in done else (ids.index(current)+1 if current in ids else 0)
 return {"batch_id":session["batch_id"],"image_ids":ids,"position":position,"total":len(ids),"remaining":remaining,"confirmed_ids":done,"complete":bool(session.get("complete"))}
def move_review_position(project,batch_id,current_id,step):
 doc=_load(project);session=_session(doc,batch_id)
 if session is None or session.get("complete"):return None
 ids=list(session.get("image_ids",()))
 if str(current_id) not in ids:return None
 position=ids.index(str(current_id));target=_pending_target(project,ids,position,step)
 if target is None:
  session.update({"complete":True,"active":False});_save(project,doc);return dict(session)
 session["current_position"]=target;session["current_image_id"]=ids[target];_save(project,doc);return dict(session)
def complete_or_advance_review(project,batch_id,current_id):
 doc=_load(project);session=_session(doc,batch_id)
 if session is None:return None,False
 ids=list(session.get("image_ids",()))
 position=ids.index(str(current_id));target=_pending_target(project,ids,position,1)
 if target is None:
  session["complete"]=True;session["active"]=False;session["current_position"]=position;session["current_image_id"]=str(current_id);_save(project,doc);return dict(session),True
 session["current_position"]=target;session["current_image_id"]=ids[target];_save(project,doc);return dict(session),False

def remove_image_from_reviews(project,image_id):
 """Remove an excluded image from every unfinished Landmark AI review session."""
 image_id=str(image_id);doc=_load(project);active_target=None
 for session in doc.get("sessions",()):
  if session.get("complete"):continue
  ids=[str(value) for value in session.get("image_ids",())]
  if image_id not in ids:continue
  old_position=max(0,min(int(session.get("current_position",0)),max(0,len(ids)-1)))
  was_active=bool(session.get("active"))
  kept=[value for value in ids if value!=image_id]
  meta=dict(session.get("review_meta") or {});meta.pop(image_id,None);session["review_meta"]=meta
  if not kept:
   session.update({"image_ids":[],"current_position":0,"current_image_id":None,"complete":True,"active":False})
   continue
  removed_before=sum(1 for value in ids[:old_position] if value==image_id)
  position=min(max(0,old_position-removed_before),len(kept)-1)
  session.update({"image_ids":kept,"current_position":position,"current_image_id":kept[position]})
  if was_active:active_target=kept[position]
 _save(project,doc)
 return active_target

