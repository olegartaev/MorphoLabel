"""Persistent, GUI-independent state for the contextual Landmark AI workflow."""
from __future__ import annotations
import random
from datetime import datetime, timezone
from .gui_crop_debug import log
from .landmark_dataset import model_seen_image_ids

CONTROL_TARGET=25
INITIAL_TARGET=30
IMPROVEMENT_TARGET=20
STATE_KEY="landmark_ai_workflow"
_VERSION=2


def _eligible_catalog(project,excluded=()):
 blocked=set(excluded);return [row for row in project.catalog_rows() if not row.get("excluded") and row["image_id"] not in blocked]

def diverse_selection(project,candidates,count,seed):
 groups={}
 for row in candidates:groups.setdefault(str(row.get("locality") or row.get("sample_id") or ""),[]).append(row["image_id"])
 rng=random.Random(int(seed));names=sorted(groups);rng.shuffle(names)
 for name in names:rng.shuffle(groups[name])
 selected=[]
 while names and len(selected)<count:
  remaining=[]
  for name in names:
   if groups[name] and len(selected)<count:selected.append(groups[name].pop())
   if groups[name]:remaining.append(name)
  names=remaining
 return tuple(selected)

def _verified(project,image_ids):return sum(bool(project.annotation_status(image_id).get("verified")) for image_id in image_ids)
def _now():return datetime.now(timezone.utc).isoformat()
def default_state(project):
 return {"version":_VERSION,"stage":"CONTROL_SET","seed":20260823,"control_target":CONTROL_TARGET,"initial_target":INITIAL_TARGET,"improvement_target":IMPROVEMENT_TARGET,"control_image_ids":[],"initial_image_ids":[],"improvement_image_ids":[],"improvement_history_ids":[],"full_prediction_done":False,"created_at":None,"stage_created_at":{},"current_image_id":None,"current_position":None,"unfinished_image_id":None}

def load_state(project):
 raw=project.get_ui_state(STATE_KEY)
 # v1 already has a scientific selection: retain its exact stored order.
 if not isinstance(raw,dict):return default_state(project)
 state={**default_state(project),**raw};state["version"]=_VERSION
 if not state["control_image_ids"]:
  # Safe recovery only: use existing permanent membership once, never rerun selection.
  held=list(project.permanent_test_image_ids())
  if held:state["control_image_ids"]=held
 return state

def save_state(project,state):project.set_ui_state(STATE_KEY,state);return state

def _ids_for(state,stage):return state[{"CONTROL_SET":"control_image_ids","INITIAL_TRAINING":"initial_image_ids","MODEL_IMPROVEMENT":"improvement_image_ids"}[stage]]
def _target_key(stage):return {"CONTROL_SET":"control_target","INITIAL_TRAINING":"initial_target","MODEL_IMPROVEMENT":"improvement_target"}[stage]
def _blocked_for(stage,state):
 if stage=="CONTROL_SET":return ()
 if stage=="INITIAL_TRAINING":return state["control_image_ids"]
 return list(state["control_image_ids"])+list(state["initial_image_ids"])+list(state.get("improvement_history_ids",()))+list(state.get("improvement_image_ids",()))

def create_stage(project,stage,target,allow_small=False):
 state=load_state(project)
 if stage not in {"CONTROL_SET","INITIAL_TRAINING","MODEL_IMPROVEMENT"}:raise ValueError("unsupported workflow stage")
 if _ids_for(state,stage):return save_state(project,state)
 candidates=_eligible_catalog(project,_blocked_for(stage,state));target=int(target)
 if target<5 and not allow_small:raise ValueError("workflow target must be at least 5")
 if target>len(candidates):
  if allow_small:target=len(candidates)
  else:raise ValueError(f"only {len(candidates)} eligible images are available")
 ids=list(diverse_selection(project,candidates,target,int(state["seed"])+{"CONTROL_SET":0,"INITIAL_TRAINING":1,"MODEL_IMPROVEMENT":2}[stage]))
 state[_target_key(stage)]=target;state[{"CONTROL_SET":"control_image_ids","INITIAL_TRAINING":"initial_image_ids","MODEL_IMPROVEMENT":"improvement_image_ids"}[stage]]=ids;created=_now();state["created_at"]=state.get("created_at") or created;state.setdefault("stage_created_at",{}).setdefault(stage,created);state["stage"]=stage
 if stage=="CONTROL_SET":project.reserve_permanent_test(ids)
 return save_state(project,state)

def repair_excluded_stage_members(project,state=None,stage=None):
 """Replace only excluded persisted members, preserving every other stage position."""
 state=load_state(project) if state is None else state
 stages=(stage,) if stage else ("CONTROL_SET","INITIAL_TRAINING","MODEL_IMPROVEMENT")
 for current_stage in stages:
  ids=list(_ids_for(state,current_stage))
  if not ids:continue
  excluded={row["image_id"] for row in project.catalog_rows() if row.get("excluded")}
  for position,old_id in tuple(enumerate(ids)):
   if old_id not in excluded:continue
   blocked=set(_blocked_for(current_stage,state))|set(ids)
   candidates=_eligible_catalog(project,blocked)
   replacement=next(iter(diverse_selection(project,candidates,1,int(state["seed"])+{"CONTROL_SET":0,"INITIAL_TRAINING":1,"MODEL_IMPROVEMENT":2}[current_stage]+position)),None)
   if replacement is None:raise ValueError(f"no eligible replacement for excluded {current_stage} member")
   ids[position]=replacement;state[{"CONTROL_SET":"control_image_ids","INITIAL_TRAINING":"initial_image_ids","MODEL_IMPROVEMENT":"improvement_image_ids"}[current_stage]]=ids
   if current_stage=="CONTROL_SET":project.reserve_permanent_test((replacement,))
   if state.get("current_image_id")==old_id:state["current_image_id"]=replacement;state["current_position"]=position
   if state.get("unfinished_image_id")==old_id:state["unfinished_image_id"]=None
   log(replacement,"landmark_workflow_excluded_replaced","END",detail=f"stage={current_stage} position={position+1} excluded_image_id={old_id} replacement_image_id={replacement} reason=excluded")
 return save_state(project,state)
def ensure_control_set(project,state=None,create_missing=True):
 state=load_state(project) if state is None else state
 if not state["control_image_ids"] and create_missing:return create_stage(project,"CONTROL_SET",state["control_target"],allow_small=True)
 return save_state(project,state)

def refresh_stage(project,state=None,create_missing=True):
 state=repair_excluded_stage_members(project,ensure_control_set(project,load_state(project) if state is None else state,create_missing))
 controls=tuple(state["control_image_ids"])
 if not controls:state["stage"]="CONTROL_SET";return save_state(project,state)
 if _verified(project,controls)<len(controls):state["stage"]="CONTROL_SET";return save_state(project,state)
 initial=tuple(state["initial_image_ids"])
 if not initial:
  if create_missing:state=create_stage(project,"INITIAL_TRAINING",state["initial_target"],allow_small=True);initial=tuple(state["initial_image_ids"])
  else:state["stage"]="INITIAL_TRAINING";return save_state(project,state)
 try:active_model=project.active_model("landmark")
 except ValueError:active_model=None
 if _verified(project,initial)<len(initial) or active_model is None or not set(initial).issubset(model_seen_image_ids(project,active_model["model_id"])):state["stage"]="INITIAL_TRAINING";return save_state(project,state)
 improvement=tuple(state["improvement_image_ids"])
 if improvement and (_verified(project,improvement)<len(improvement) or not set(improvement).issubset(model_seen_image_ids(project,active_model["model_id"]))):state["stage"]="MODEL_IMPROVEMENT"
 else:state["stage"]="READY_FOR_FULL_PREDICTION" if not state.get("full_prediction_done") else "REVIEW_AI_RESULTS"
 return save_state(project,state)

def start_or_continue(project,create_missing=True):return refresh_stage(project,create_missing=create_missing)
def begin_improvement(project,state=None,target=None,*,selected_ids=None,selection_artifact=None):
 """Persist a new Improvement cycle; selection must already be successful."""
 state=refresh_stage(project,state,create_missing=False)
 if state["stage"] not in {"READY_FOR_FULL_PREDICTION","MODEL_IMPROVEMENT"} or _verified(project,state.get("improvement_image_ids",()))<len(state.get("improvement_image_ids",())):raise ValueError("a new improvement batch requires a completed current batch")
 previous=list(state.get("improvement_history_ids",()))+list(state.get("improvement_image_ids",()))
 history=list(dict.fromkeys(previous));blocked=set(state["control_image_ids"])|set(state["initial_image_ids"])|set(history)
 candidates=_eligible_catalog(project,blocked);chosen=int(target or state["improvement_target"])
 if chosen<5:raise ValueError("workflow target must be at least 5")
 if chosen>len(candidates):raise ValueError(f"only {len(candidates)} eligible images are available")
 ids=list(selected_ids) if selected_ids is not None else list(diverse_selection(project,candidates,chosen,int(state["seed"])+2+len(history)))
 if len(ids)!=chosen or len(set(ids))!=chosen or not set(ids).issubset({row["image_id"] for row in candidates}):raise ValueError("smart Improvement selection contains ineligible images")
 state["improvement_history_ids"]=history;state["improvement_image_ids"]=ids;state["improvement_target"]=chosen;state["improvement_selection"]=selection_artifact;state["current_image_id"]=None;state["current_position"]=None;state["unfinished_image_id"]=None;state["stage"]="MODEL_IMPROVEMENT";state.setdefault("stage_created_at",{})["MODEL_IMPROVEMENT"]=_now()
 return save_state(project,state)
def workflow_current(project,state=None):
 state=refresh_stage(project,state,create_missing=False);stage=state["stage"]
 if stage not in {"CONTROL_SET","INITIAL_TRAINING","MODEL_IMPROVEMENT"}:return state,None,None,False
 ids=list(_ids_for(state,stage));drafts=[image_id for image_id in ids if (draft:=project.annotation_draft(image_id)) and draft.get("workflow_stage")==stage]
 image_id=drafts[0] if drafts else next((image_id for image_id in ids if not project.annotation_status(image_id)["verified"]),None)
 if image_id is None:return state,None,None,False
 position=ids.index(image_id);state["current_image_id"]=image_id;state["current_position"]=position;state["unfinished_image_id"]=image_id if drafts else None;save_state(project,state)
 return state,image_id,position,bool(drafts)
def workflow_advance(project,previous_image_id):
 state,image_id,position,restored=workflow_current(project)
 return state,image_id,position,restored

def stage_summary(project,state=None,create_missing=True):
 state=refresh_stage(project,state,create_missing);stage=state["stage"];ids={"CONTROL_SET":state["control_image_ids"],"INITIAL_TRAINING":state["initial_image_ids"],"MODEL_IMPROVEMENT":state["improvement_image_ids"]}.get(stage,[])
 friendly={"CONTROL_SET":"Control set","INITIAL_TRAINING":"Initial training","MODEL_IMPROVEMENT":"Improve model","READY_FOR_FULL_PREDICTION":"Ready for full dataset","REVIEW_AI_RESULTS":"Review AI results"}[stage]
 try:active=(project.active_model("landmark") or {}).get("model_id")
 except ValueError:active=None
 return {"state":state,"stage":stage,"friendly_stage":friendly,"current_ids":tuple(ids),"verified":_verified(project,ids),"total":len(ids),"active_model_id":active}
def control_set_summary(project,state=None):
 """Return the persisted Control Set even after the active stage has advanced."""
 state=load_state(project) if state is None else state
 ids=tuple(state["control_image_ids"])
 try:active=(project.active_model("landmark") or {}).get("model_id")
 except ValueError:active=None
 return {"state":state,"stage":"CONTROL_SET","friendly_stage":"Control set","current_ids":ids,"verified":_verified(project,ids),"total":len(ids),"active_model_id":active}

def add_control_image(project,image_id):
 """Append one non-excluded image to the permanent, project-local Control Set."""
 state=repair_excluded_stage_members(project,load_state(project),stage="CONTROL_SET")
 row=next((row for row in project.catalog_rows() if row["image_id"]==image_id),None)
 if row is None:raise KeyError(f"unknown image_id: {image_id}")
 if row.get("excluded"):raise ValueError("excluded images cannot be added to the Control Set")
 ids=list(state["control_image_ids"])
 if image_id in ids:return control_set_summary(project,state),False
 ids.append(image_id);state["control_image_ids"]=ids;state["control_target"]=len(ids)
 project.reserve_permanent_test((image_id,));save_state(project,state)
 log(image_id,"landmark_workflow_control_added","END",detail=f"control_target={len(ids)} image_id={image_id}")
 return control_set_summary(project,state),True
def training_eligible_ids(project):
 from .landmark_dataset import v2_human_final_eligible_image_ids
 return tuple(v2_human_final_eligible_image_ids(project))





