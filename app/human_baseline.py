"""Immutable two-pass Human Baseline QC runs; never writes canonical landmarks."""
from __future__ import annotations
import json, math, uuid, time, statistics, hashlib
from datetime import datetime, timezone
from PIL import Image
from .io import atomic_json_write
from .operator_qc import _load, complete_repeat_session, create_repeat_session
from .gui_crop_debug import log
from .project_storage import schema_hash, landmark_schema_identity, load_schema
from .landmark_qc_geometry import pair_vector_reversal_metrics

BASELINE_FILE="human_baseline.json"
FORMAT_VERSION=2

def _now(): return datetime.now(timezone.utc).isoformat()
def _root(project): return project.data_root / "ai" / "qc" / "operator"
def _baseline_path(project): return _root(project) / BASELINE_FILE
def _runs_path(project): return _root(project) / "human_baseline_runs.json"
def _pct(values,p):
 values=sorted(values); return values[min(len(values)-1,max(0,math.ceil(len(values)*p)-1))] if values else None
def _load_json(path,default):
 try:return json.loads(path.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError):return default
def _runs(project): return _load_json(_runs_path(project),{"format_version":FORMAT_VERSION,"runs":[]})
def _save_runs(project,data): _root(project).mkdir(parents=True,exist_ok=True);atomic_json_write(_runs_path(project),data)
def baseline_image_ids(project): return tuple(_load_json(_baseline_path(project),{}).get("image_ids",()))
def available_control_image_ids(project):
 """Eligible images for a new Human repeatability run.

 Existing Control Set images are preferred, then the pool is filled from other
 fully human-reviewed images. This keeps the user's requested sample size from
 being artificially capped by a small Control Set.
 """
 from .landmark_ai_workflow import control_set_summary
 from .operator_qc import operator_eligible_image_ids
 eligible=tuple(sorted(operator_eligible_image_ids(project)))
 control=set(control_set_summary(project).get("current_ids") or ())
 ordered=[image_id for image_id in eligible if image_id in control]
 ordered.extend(image_id for image_id in eligible if image_id not in control)
 return tuple(image_id for image_id in ordered if (project.cache_root/"standardized"/f"{image_id}.png").is_file())
def ensure_baseline_set(project,*,count=10):
 existing=baseline_image_ids(project)
 if existing:return {"image_ids":existing,"available":len(existing),"fixed":True}
 from .landmark_ai_workflow import control_set_summary
 from .operator_qc import operator_eligible_image_ids
 eligible=available_control_image_ids(project)
 selected=eligible[:count];_root(project).mkdir(parents=True,exist_ok=True)
 atomic_json_write(_baseline_path(project),{"format_version":FORMAT_VERSION,"created_at":_now(),"requested_count":count,"available_eligible_control_images":len(eligible),"image_ids":list(selected)})
 return {"image_ids":selected,"available":len(eligible),"fixed":False}
def previous_runs(project):return tuple(_runs(project)["runs"])
def current_run(project):return next((r for r in reversed(previous_runs(project)) if r.get("status")=="in_progress"),None)
def abandon_run(project, run_id, *, reason="superseded_by_new_run"):
 """Retire an unfinished run without ever deleting either blind pass.

 The run remains part of the scientific audit trail; only its eligibility as
 the *current* run changes.  A later run therefore gets a new immutable image
 membership instead of silently mutating either pass of the old run.
 """
 data,run=_run_by_id(project,run_id)
 if run.get("status")!="in_progress":
  raise ValueError("only an unfinished Human repeatability run can be superseded")
 event={"timestamp":_now(),"event":"abandoned","reason":str(reason)}
 run.setdefault("history",[]).append(event)
 run.update({"status":"abandoned","abandoned_at":event["timestamp"],"abandoned_reason":event["reason"]})
 _save_runs(project,data)
 return run
def invalidate_runs_for_excluded_image(project,image_id):
 """Invalidate repeatability runs that depend on an image later excluded as unusable.

 Historical pass sessions and reports remain on disk for provenance. They are
 simply no longer eligible as the current manual-repeatability reference.
 """
 image_id=str(image_id);data=_runs(project);changed=0
 for run in data.get("runs",()):
  if run.get("status") not in {"in_progress","completed"}:continue
  if image_id not in {str(value) for value in run.get("image_ids",())}:continue
  stamp=_now();previous=run.get("status")
  run.setdefault("history",[]).append({"timestamp":stamp,"event":"invalidated","reason":"image_excluded","image_id":image_id,"previous_status":previous})
  run.update({"status":"invalidated","invalidated_at":stamp,"invalidated_reason":"image_excluded","invalidated_image_id":image_id})
  changed+=1
 if changed:_save_runs(project,data)
 return changed

def latest_completed_report(project):
 current_identity=landmark_schema_identity(load_schema(project.schema_path));current_sha=schema_hash(project.schema_path)
 for run in reversed(previous_runs(project)):
  if run.get("status")!="completed" or run.get("invalidated_reason") or run.get("report_stale") or not run.get("report_path"):continue
  identities=_run_schema_identities(project,run)
  if len(identities)>1:continue
  identity=next(iter(identities)) if identities else ()
  if identity:
   if identity!=current_identity:continue
  elif run.get("schema_sha256") and str(run["schema_sha256"])!=current_sha:
   continue
  report=_load_json(_root(project)/run["report_path"],None)
  if report:return report
 return None
def repeatability_report_state(project):
 """Return the newest repeatability report, never silently falling back past unfinished newer work."""
 runs=[run for run in previous_runs(project) if run.get("status") in {"in_progress","completed","invalidated"}]
 if not runs:
  return {"ready":False,"report":None,"run":None,"message":"Complete Human repeatability first to compare AI with manual placement."}
 run=runs[-1]
 if run.get("status")=="invalidated":
  image_id=str(run.get("invalidated_image_id") or "")
  suffix=f"\nExcluded image ID: {image_id}" if image_id else ""
  return {"ready":False,"report":None,"run":run,"message":"The newest Human repeatability run contains an image that was excluded from the project. Its historical files are preserved, but it is no longer a valid manual-repeatability reference."+suffix+"\n\nStart a new Human repeatability sample."}
 if run.get("status")=="in_progress":
  p1=pass_progress(project,run,1);p2=pass_progress(project,run,2)
  q1=pass_qc_complete(run,1);q2=pass_qc_complete(run,2)
  # Recover cleanly if the UI was interrupted after both passes and checks had
  # already finished. This calculation is human-only and does not run a model.
  if p1.get("complete") and p2.get("complete") and q1 and q2:
   report=complete_run(project,run["run_id"],include_model=False)
   _,run=_run_by_id(project,run["run_id"])
   return {"ready":True,"report":report,"run":run,"message":""}
  remaining=[]
  if not p1.get("complete"):remaining.append(f"Annotation 1: {p1.get('completed',0)}/{p1.get('total',0)} images")
  elif not q1:remaining.append("Annotation 1: point check")
  if not p2.get("complete"):remaining.append(f"Annotation 2: {p2.get('completed',0)}/{p2.get('total',0)} images")
  elif not q2:remaining.append("Annotation 2: point check")
  detail="\n".join(remaining) if remaining else "final repeatability update"
  return {"ready":False,"report":None,"run":run,"message":"The newest Human repeatability update is not finished.\n\n"+detail+"\n\nOpen Landmarks → Repeat... and finish only the remaining step(s). The older report will not be used."}
 if run.get("report_stale"):
  p1=pass_progress(project,run,1);p2=pass_progress(project,run,2)
  if p1.get("complete") and p2.get("complete") and final_qc_complete(run):
   report=recompute_completed_run(project,run["run_id"],include_model=False)
   _,run=_run_by_id(project,run["run_id"])
   return {"ready":True,"report":report,"run":run,"message":""}
  return {"ready":False,"report":None,"run":run,"message":"The newest Human repeatability report is stale after an edit. Open Landmarks → Repeat... and finish the pending annotation/check. The older report will not be used."}
 report=latest_completed_report(project)
 if report is not None and str(report.get("run_id"))==str(run.get("run_id")):
  return {"ready":True,"report":report,"run":run,"message":""}
 return {"ready":False,"report":None,"run":run,"message":"The newest Human repeatability run is not compatible with the current landmark identities/order. Start a new Human repeatability sample before comparing models."}

def _run_by_id(project,run_id):
 data=_runs(project);run=next((r for r in data["runs"] if r["run_id"]==run_id),None)
 if not run:raise KeyError(run_id)
 return data,run
def _pass_key(number):return str(int(number))
def pass_session_ids(run,number):
 if int(run.get("format_version",1))<2:return tuple(run.get("session_ids",())) if int(number)==1 else ()
 return tuple((run.get("passes",{}).get(_pass_key(number),{}) or {}).get("session_ids",()))
def pass_progress(project,run,number):
 ids=pass_session_ids(run,number)
 done=sum(_load(project,s).get("status")=="completed" for s in ids)
 total=len(ids) if ids else (len(run.get("image_ids",())) if int(run.get("format_version",1))>=2 else 0)
 return {"completed":done,"total":total,"complete":bool(ids) and done==len(ids)}
def _run_schema_sha(project,run):
 value=run.get("schema_sha256")
 if value:return str(value)
 first=pass_session_ids(run,1) or tuple(run.get("session_ids",()))
 for sid in first:
  try:
   value=_load(project,sid).get("schema_sha256")
  except (OSError,ValueError,KeyError):value=None
  if value:return str(value)
 return None

def _current_schema_identity(project):
 return landmark_schema_identity(load_schema(project.schema_path))

def _session_schema_identity(project,sid):
 try:stored=_load(project,sid).get("schema") or ()
 except (OSError,ValueError,KeyError):return ()
 return landmark_schema_identity(stored) if stored else ()

def _run_schema_identities(project,run):
 """Semantic landmark identities present in the active run and either annotation pass."""
 identities=set()
 value=tuple(map(str,run.get("schema_identity") or ()))
 if value:identities.add(value)
 session_ids=[]
 if int(run.get("format_version",1))>=2:
  session_ids.extend(pass_session_ids(run,1));session_ids.extend(pass_session_ids(run,2))
 else:
  session_ids.extend(tuple(run.get("session_ids",())))
 seen=set()
 for sid in session_ids:
  if sid in seen:continue
  seen.add(sid);value=_session_schema_identity(project,sid)
  if value:identities.add(value)
 return identities

def _run_schema_identity(project,run):
 identities=_run_schema_identities(project,run)
 return next(iter(identities)) if len(identities)==1 else ()

def _new_pass_sessions(project,run,number):
 key=_pass_key(number);passes=run.setdefault("passes",{})
 if passes.get(key,{}).get("session_ids"):return tuple(passes[key]["session_ids"])
 current_sha=schema_hash(project.schema_path);current_identity=_current_schema_identity(project);identities=_run_schema_identities(project,run);expected_sha=_run_schema_sha(project,run)
 if len(identities)>1:
  raise ValueError("Annotation passes contain different landmark identities/order. Start a new Human repeatability sample.")
 expected_identity=next(iter(identities)) if identities else ()
 if expected_identity:
  if expected_identity!=current_identity:
   raise ValueError("Landmark identities/order changed since this Human repeatability run. Start a new sample before creating another annotation pass.")
 elif expected_sha and expected_sha!=current_sha:
  raise ValueError("Landmark scheme changed since this legacy Human repeatability run. Start a new sample before creating another annotation pass.")
 run["schema_sha256"]=current_sha
 run["schema_identity"]=list(expected_identity or current_identity)
 counterpart_number=2 if int(number)==1 else 1
 counterpart=pass_session_ids(run,counterpart_number)
 sessions=[]
 for index,image_id in enumerate(run["image_ids"]):
  frozen_source=None
  if len(counterpart)==len(run["image_ids"]):
   other=_load(project,counterpart[index])
   if str(other.get("image_id"))==str(image_id) and other.get("standardized_snapshot"):
    candidate=project.data_root/str(other.get("standardized_relpath") or "")
    if candidate.is_file():frozen_source=candidate
  session=create_repeat_session(project,image_id,eligibility_prevalidated=True,standardized_source=frozen_source)
  sessions.append(session["repeat_session_id"])
 passes[key]={"session_ids":sessions,"created_at":_now(),"completed_at":None}
 if int(number)==1:run["session_ids"]=list(sessions) # v1-compatible inspection only
 return tuple(sessions)
def _upgrade_legacy_run(project,run):
 """Upgrade a v1 one-pass run without pretending it already satisfies the v2 two-pass protocol."""
 if int(run.get("format_version",1))>=2:return run,False
 first=tuple(run.get("session_ids",()));legacy_status=run.get("status");legacy_completed_at=run.get("completed_at");legacy_report=run.get("report_path")
 run["format_version"]=FORMAT_VERSION
 run["passes"]={"1":{"session_ids":list(first),"migrated_at":_now(),"completed_at":legacy_completed_at if first and all(_load(project,s).get("status")=="completed" for s in first) else None}}
 run.setdefault("history",[]).append({"timestamp":_now(),"event":"migrate_v1_to_v2","legacy_status":legacy_status,"legacy_completed_at":legacy_completed_at,"legacy_report_path":legacy_report})
 run["status"]="in_progress";run["completed_at"]=None;run["report_stale"]=bool(legacy_report)
 schema_sha=_run_schema_sha(project,run)
 if schema_sha:run["schema_sha256"]=schema_sha
 identity=_run_schema_identity(project,run)
 if identity:run["schema_identity"]=list(identity)
 return run,True

def ensure_pass(project,run_id,number):
 data,run=_run_by_id(project,run_id)
 run,migrated=_upgrade_legacy_run(project,run)
 if int(number)==2 and not pass_progress(project,run,1)["complete"]:
  if migrated:_save_runs(project,data)
  raise ValueError("Finish Annotation 1 before starting Annotation 2.")
 existing=pass_session_ids(run,2) if int(number)==2 else ()
 if int(number)==2 and not existing and not pass_qc_complete(run,1):
  if migrated:_save_runs(project,data)
  raise ValueError("Complete the Annotation 1 point check before starting Annotation 2.")
 ids=_new_pass_sessions(project,run,number)
 _save_runs(project,data);return run,ids
def pending_pass_session_ids(project,run,number):
 """Return only unfinished sessions from one pass, preserving run order."""
 ids=pass_session_ids(run,int(number))
 return tuple(sid for sid in ids if _load(project,sid).get("status")!="completed")

def redo_repeatability_image(project,run_id,position):
 """Replace only one image in existing repeatability passes; keep every other session immutable."""
 data,run=_run_by_id(project,run_id);run,_=_upgrade_legacy_run(project,run)
 image_ids=list(map(str,run.get("image_ids",())))
 try:position=int(position)
 except (TypeError,ValueError):raise ValueError("image position must be a number")
 if position<1 or position>len(image_ids):raise ValueError(f"image position must be between 1 and {len(image_ids)}")
 index=position-1;image_id=image_ids[index]
 canonical=project.cache_root/"standardized"/f"{image_id}.png"
 if not canonical.is_file():raise FileNotFoundError(f"Current standardized image is missing for image {position}/{len(image_ids)} · ID {image_id}")
 passes=run.setdefault("passes",{});replaced={};shared_source=canonical
 for number in (1,2):
  key=_pass_key(number);meta=passes.get(key) or {};session_ids=list(meta.get("session_ids") or ())
  if not session_ids:continue
  if len(session_ids)!=len(image_ids):raise ValueError(f"Annotation {number} does not contain the full saved image set")
  old_sid=session_ids[index]
  session=create_repeat_session(project,image_id,eligibility_prevalidated=True,standardized_source=shared_source)
  new_sid=session["repeat_session_id"];session_ids[index]=new_sid;meta["session_ids"]=session_ids;meta["completed_at"]=None;passes[key]=meta
  if number==1:
   run["session_ids"]=list(session_ids)
   shared_source=project.data_root/session["standardized_relpath"]
  replaced[str(number)]={"old_session_id":old_sid,"new_session_id":new_sid}
  invalidate_repeatability_pass_qc(run,number,reason=f"image_{position}_redo")
 if not replaced:raise ValueError("This Human repeatability run has no started annotation passes to repair.")
 previous_status=run.get("status")
 if previous_status=="completed":run["status"]="in_progress";run["completed_at"]=None
 run["report_stale"]=True
 run.setdefault("history",[]).append({"timestamp":_now(),"event":"redo_repeatability_image","position":position,"image_id":image_id,"passes":replaced,"previous_status":previous_status})
 _save_runs(project,data)
 return run,{"position":position,"total":len(image_ids),"image_id":image_id,"passes":replaced}

def reset_pass(project,run_id,number):
 """Replace one blind annotation pass with a fresh pass on the same fixed images.

 Old session files remain untouched for audit/history, but are no longer part of
 the active Human repeatability calculation.
 """
 number=int(number)
 if number not in (1,2):raise ValueError("annotation number must be 1 or 2")
 data,run=_run_by_id(project,run_id);run,_=_upgrade_legacy_run(project,run)
 passes=run.setdefault("passes",{})
 key=_pass_key(number);old=list((passes.get(key,{}) or {}).get("session_ids",()))
 if not old:raise ValueError(f"Annotation {number} has not been started.")
 run.setdefault("history",[]).append({"timestamp":_now(),"event":"reset_pass","pass":number,"session_ids":old})
 passes.pop(key,None)
 if number==1:run["session_ids"]=[]
 if run.get("status")=="completed":
  run["status"]="in_progress";run["completed_at"]=None
 run["report_stale"]=True;invalidate_repeatability_pass_qc(run,number,reason=f'annotation_{number}_reset')
 ids=_new_pass_sessions(project,run,number)
 _save_runs(project,data)
 return run,ids

def start_or_continue_run(project,*,count=None):
 started=time.monotonic();log("GLOBAL","HUMAN_BASELINE_START","START")
 run=current_run(project)
 if run:
  log("GLOBAL","BASELINE_SET_READY","END",time.monotonic()-started,detail="in_progress=true");return run,False
 eligible=available_control_image_ids(project)
 requested=10 if count is None else int(count)
 if requested<1:raise ValueError("Choose at least one eligible Control image.")
 ids=eligible[:min(requested,len(eligible))]
 if not ids:raise ValueError("No eligible Control Set images are available for Human Baseline.")
 for image_id in ids:
  if not (project.cache_root/"standardized"/f"{image_id}.png").is_file():raise FileNotFoundError(f"Human Baseline standardized image is missing: {image_id}")
 model=project.active_model_readonly("landmark") or {}
 run={"format_version":FORMAT_VERSION,"run_id":str(uuid.uuid4()),"created_at":_now(),"completed_at":None,"status":"in_progress","model_id":model.get("model_id"),"schema_sha256":schema_hash(project.schema_path),"schema_identity":list(_current_schema_identity(project)),"requested_count":requested,"actual_count":len(ids),"image_ids":list(ids),"passes":{},"session_ids":[],"report_path":None}
 data=_runs(project);data["format_version"]=FORMAT_VERSION;data["runs"].append(run);_save_runs(project,data)
 _new_pass_sessions(project,run,1);_save_runs(project,data)
 log("GLOBAL","SESSIONS_READY","END",time.monotonic()-started,detail=f"pass=1 count={len(ids)}");return run,True
def complete_pass(project,run_id,number):
 data,run=_run_by_id(project,run_id);run,_=_upgrade_legacy_run(project,run);progress=pass_progress(project,run,number)
 if not progress["complete"]:raise ValueError(f"Annotation {number} is not complete.")
 key=_pass_key(number);passes=run.setdefault("passes",{})
 if key not in passes:raise ValueError(f"Annotation {number} has not been started.")
 passes[key]["completed_at"]=_now();_save_runs(project,data);return run

def repeatability_next_state(project,run):
 if pass_progress(project,run,1).get('complete') and not pass_qc_complete(run,1):return 'pass_qc_1'
 if pass_progress(project,run,2).get('complete') and not pass_qc_complete(run,2):return 'pass_qc_2'
 if run.get('status')=='completed' and run.get('report_stale'):return 'report_update'
 return 'continue'

def finish_repeatability_pass(project,run_id,number):
 number=int(number);run=complete_pass(project,run_id,number)
 # User contract: finishing the last image of a pass always asks whether to
 # review likely placement errors, even if this pass was checked before.
 return run,f'pass_qc_{number}'

def _span(points):
 valid=[(float(p["x"]),float(p["y"])) for p in points.values() if p.get("state")=="present" and p.get("x") is not None and p.get("y") is not None]
 return max((math.hypot(a[0]-b[0],a[1]-b[1]) for i,a in enumerate(valid) for b in valid[i+1:]),default=0.0)
def _repeat_points(project,sid):return {p["landmark_id"]:p for p in _load(project,sid).get("repeat",())}
def _evaluate_pair(project,run,first,second):
 errors=[];per={};per_image=[]
 for a,b,image_id in zip(first,second,run["image_ids"]):
  original,repeat=_repeat_points(project,a),_repeat_points(project,b);span=_span(original);image_errors=[]
  for ident,point in original.items():
   other=repeat.get(ident)
   if not other or point.get("state")!="present" or other.get("state")!="present" or span<=0:continue
   value=math.hypot(point["x"]-other["x"],point["y"]-other["y"])/span*100;errors.append(value);image_errors.append(value);per.setdefault(str(ident),[]).append(value)
  per_image.append({"image_id":image_id,"reference_span_px":span,"median_error_percent":_pct(image_errors,.5)})
 return {"aggregate":{"n_images":len(per_image),"n_comparable_landmarks":len(errors),"median_error_percent":_pct(errors,.5),"p90_error_percent":_pct(errors,.9),"p95_error_percent":_pct(errors,.95)},"per_landmark":{i:{"landmark_id":int(i),"n":len(v),"median_error_percent":_pct(v,.5),"p90_error_percent":_pct(v,.9)} for i,v in per.items()},"per_image":per_image}
def _translation_aligned_points(present,reference):
 """Robustly remove a whole-annotation translation before local QC comparisons."""
 common=sorted(set(present)&set(reference))
 if not common:return dict(present),(0.0,0.0)
 dx=[present[i][0]-reference[i][0] for i in common]
 dy=[present[i][1]-reference[i][1] for i in common]
 shift=(statistics.median(dx),statistics.median(dy))
 return {i:(xy[0]-shift[0],xy[1]-shift[1]) for i,xy in present.items()},shift

def _swap_pair_metrics(present,reference,first,second,diag):
 first=int(first);second=int(second)
 own_first=math.dist(present[first],reference[first]);own_second=math.dist(present[second],reference[second]);own=own_first+own_second
 pair_sep=math.dist(reference[first],reference[second]);min_sep=max(2.0,.002*diag)
 current_sep=math.dist(present[first],present[second])
 reversal=pair_vector_reversal_metrics(reference[first],reference[second],present[first],present[second],min_reference_length=min_sep)
 pair_cos=reversal['pair_cos'];length_ratio=reversal['length_ratio'];vector_reversal=reversal['vector_reversal']
 cross_first=math.dist(present[first],reference[second]);cross_second=math.dist(present[second],reference[first]);swapped=cross_first+cross_second
 cross_swap=(
  pair_sep>min_sep
  and own_first>=.45*pair_sep and own_second>=.45*pair_sep
  and cross_first<.60*max(own_first,1e-9)
  and cross_second<.60*max(own_second,1e-9)
  and swapped<.45*own
 )
 accepted=vector_reversal or cross_swap
 return {
  'first':first,'second':second,
  'own_first':own_first,'own_second':own_second,'own':own,
  'pair_sep':pair_sep,'current_sep':current_sep,'min_sep':min_sep,
  'pair_cos':pair_cos,'length_ratio':length_ratio,'vector_reversal':bool(vector_reversal),
  'cross_first':cross_first,'cross_second':cross_second,'swapped':swapped,
  'cross_over_own':swapped/max(own,1e-9),
  'first_cross_over_own':cross_first/max(own_first,1e-9),
  'second_cross_over_own':cross_second/max(own_second,1e-9),
  'cross_swap':bool(cross_swap),'accepted':bool(accepted),
 }

def repeatability_qc_issues(project,run,pass_numbers=(1,2)):
 """Conservative post-blind check against each session's frozen baseline."""
 severity_order={'possible_swap':0,'duplicate':1,'large_displacement':2,'bounds':3}
 issues=[]
 for number in tuple(int(value) for value in pass_numbers):
  for image_position,sid in enumerate(pass_session_ids(run,number),start=1):
   session=_load(project,sid)
   if session.get('status')!='completed':continue
   baseline={int(p['landmark_id']):p for p in session.get('baseline',())}
   repeat={int(p['landmark_id']):p for p in session.get('repeat',())}
   width=float(session.get('standardized_width') or 0);height=float(session.get('standardized_height') or 0);diag=max(1.0,math.hypot(width,height))
   common=sorted(set(baseline)&set(repeat))
   present={}
   reference={}
   for ident in common:
    left,right=baseline[ident],repeat[ident]
    left_present=left.get('state')=='present' and left.get('x') is not None and left.get('y') is not None
    right_present=right.get('state')=='present' and right.get('x') is not None and right.get('y') is not None
    if right_present:
     x,y=float(right['x']),float(right['y']);present[ident]=(x,y)
     if width and height and not (0<=x<width and 0<=y<height):
      issues.append({'pass':number,'session_id':sid,'image_id':session.get('image_id'),'image_position':image_position,'kind':'bounds','landmark_ids':[ident],'message':f'LM{ident}: point is outside the image','score':1.0})
    if left_present:reference[ident]=(float(left['x']),float(left['y']))
   ids=sorted(present)
   duplicate_ids=set()
   for pos,first in enumerate(ids):
    for second in ids[pos+1:]:
     distance=math.dist(present[first],present[second])
     if distance<=1.0:
      duplicate_ids.update((first,second));issues.append({'pass':number,'session_id':sid,'image_id':session.get('image_id'),'image_position':image_position,'kind':'duplicate','landmark_ids':[first,second],'message':f'LM{first} and LM{second}: points nearly coincide','score':1.0})
   aligned_present,global_shift=_translation_aligned_points(present,reference)
   residuals={ident:math.dist(aligned_present[ident],reference[ident]) for ident in sorted(set(aligned_present)&set(reference))}
   median=statistics.median(residuals.values()) if residuals else 0.0
   swap_ids=set()
   residual_ids=sorted(residuals)
   for pos,first in enumerate(residual_ids):
    for second in residual_ids[pos+1:]:
     metrics=_swap_pair_metrics(aligned_present,reference,first,second,diag)
     if metrics['accepted']:
      swap_ids.update((first,second));issues.append({'pass':number,'session_id':sid,'image_id':session.get('image_id'),'image_position':image_position,'kind':'possible_swap','landmark_ids':[first,second],'message':f'Possible LM{first} ↔ LM{second} mix-up','score':(metrics['own']-metrics['swapped'])/max(diag,1.0)})
   displacement_limit=max(.02*diag,6.0*median)
   for ident,distance in residuals.items():
    if ident in swap_ids or ident in duplicate_ids:continue
    if distance>displacement_limit:
     issues.append({'pass':number,'session_id':sid,'image_id':session.get('image_id'),'image_position':image_position,'kind':'large_displacement','landmark_ids':[ident],'message':f'LM{ident}: unusually far from the original checked marking','score':distance/max(diag,1.0)})
 issues.sort(key=lambda item:(severity_order.get(item['kind'],9),-float(item.get('score') or 0),int(item.get('pass') or 0),int(item.get('image_position') or 0),tuple(item.get('landmark_ids') or ())))
 return tuple(issues)

def pass_qc_complete(run,number):
 return bool(((run.get('pass_qc') or {}).get(_pass_key(number),{}) or {}).get('checked_at'))

def final_qc_complete(run):
 # New v2 runs require an independent gross-error check after each blind pass.
 pass_qc=run.get('pass_qc') or {}
 if pass_qc:return pass_qc_complete(run,1) and pass_qc_complete(run,2)
 # Legacy reports that already recorded the old combined final check remain readable.
 return bool((run.get('final_qc') or {}).get('checked_at'))

def _compact_qc_issues(issues):
 return [{'pass':int(item.get('pass') or 0),'session_id':str(item.get('session_id') or ''),'image_id':str(item.get('image_id') or ''),'kind':str(item.get('kind') or ''),'landmark_ids':[int(value) for value in item.get('landmark_ids',())],'message':str(item.get('message') or '')} for item in issues]

def _refresh_combined_qc_marker(run):
 if not (pass_qc_complete(run,1) and pass_qc_complete(run,2)):
  run.pop('final_qc',None);run['final_check_completed_at']=None;return run
 checks=run.get('pass_qc') or {};combined=[]
 for number in (1,2):combined.extend(list((checks.get(_pass_key(number),{}) or {}).get('issues',())))
 checked_at=_now()
 run['final_qc']={'checked_at':checked_at,'issue_count':len(combined),'finished_with_warnings':bool(combined),'issues':combined,'source':'per_pass_qc'}
 run['final_check_completed_at']=checked_at
 return run

def invalidate_repeatability_pass_qc(run,number,*,reason):
 key=_pass_key(number);checks=run.setdefault('pass_qc',{});previous=checks.pop(key,None)
 if previous:
  run.setdefault('history',[]).append({'timestamp':_now(),'event':'invalidate_pass_qc','pass':int(number),'reason':str(reason),'pass_qc':previous})
 run.pop('final_qc',None);run['final_check_completed_at']=None
 return run

def invalidate_repeatability_qc(run,*,reason):
 checks=run.get('pass_qc') or {}
 for number in (1,2):
  previous=checks.get(_pass_key(number))
  if previous:run.setdefault('history',[]).append({'timestamp':_now(),'event':'invalidate_pass_qc','pass':number,'reason':str(reason),'pass_qc':previous})
 previous=run.get('final_qc')
 if previous:run.setdefault('history',[]).append({'timestamp':_now(),'event':'invalidate_final_qc','reason':str(reason),'final_qc':previous})
 run.pop('pass_qc',None);run.pop('final_qc',None);run['final_check_completed_at']=None
 return run

def repeatability_pass_qc_issues(project,run,number):
 number=int(number)
 return tuple(repeatability_qc_issues(project,run,(number,)))

def record_repeatability_pass_qc(project,run_id,number,issues,*,finished_with_warnings=False):
 number=int(number)
 if number not in (1,2):raise ValueError("annotation number must be 1 or 2")
 data,run=_run_by_id(project,run_id)
 if not pass_progress(project,run,number)['complete']:raise ValueError(f"Finish Annotation {number} before its point check.")
 compact=[item for item in _compact_qc_issues(issues) if int(item.get('pass') or 0)==number]
 run.setdefault('pass_qc',{})[_pass_key(number)]={'checked_at':_now(),'issue_count':len(compact),'finished_with_warnings':bool(finished_with_warnings),'issues':compact}
 _refresh_combined_qc_marker(run);_save_runs(project,data);return run

def record_repeatability_qc(project,run_id,issues,*,finished_with_warnings=False):
 """Legacy combined-check API retained for older runs/tests."""
 data,run=_run_by_id(project,run_id)
 compact=_compact_qc_issues(issues)
 run['final_qc']={'checked_at':_now(),'issue_count':len(compact),'finished_with_warnings':bool(finished_with_warnings),'issues':compact}
 run['final_check_completed_at']=run['final_qc']['checked_at']
 _save_runs(project,data);return run

def finalize_repeatability_pass_qc(project,run_id,number,issues,*,finished_with_warnings=False,backend=None,include_model=True):
 run=record_repeatability_pass_qc(project,run_id,number,issues,finished_with_warnings=finished_with_warnings)
 if int(number)==1:return run,None
 if not final_qc_complete(run):raise ValueError("Complete both Annotation point checks before finishing Human repeatability.")
 report=recompute_completed_run(project,run_id,backend=backend,include_model=include_model) if run.get('status')=='completed' else complete_run(project,run_id,backend=backend,include_model=include_model)
 return run,report

def finalize_repeatability_after_qc(project,run_id,issues,*,finished_with_warnings=False,backend=None,include_model=True):
 """Legacy combined-check finalizer retained for already-created runs."""
 record_repeatability_qc(project,run_id,issues,finished_with_warnings=finished_with_warnings)
 _,run=_run_by_id(project,run_id)
 return recompute_completed_run(project,run_id,backend=backend,include_model=include_model) if run.get('status')=='completed' else complete_run(project,run_id,backend=backend,include_model=include_model)

def _evaluate_model_on_repeatability_run(project,run,model_id,*,backend=None,reference_pass=1):
 """Evaluate a model against the frozen human annotation from one repeatability pass.

 The comparison is intentionally independent of mutable canonical landmark status.
 The exact standardized image bytes used by the repeatability session must still
 match their stored SHA256/dimensions; otherwise the comparison is rejected.
 """
 from .ai import InferenceRequest
 from .ai_batch import backend_for_model
 from .ai_hardware import auto_performance_config,is_cuda_oom
 from .landmark_ai_service import LandmarkAIService
 from .project_storage import landmark_model_schema_compatible
 if backend is None:_,backend=backend_for_model(project,model_id)
 if backend.model_id!=str(model_id):raise ValueError("repeatability evaluator prediction model_id does not match requested model")
 model=project.model_metadata(str(model_id))
 if not landmark_model_schema_compatible(project,model):raise ValueError("selected Landmark model is not compatible with the current landmark identities/order")
 sessions=pass_session_ids(run,int(reference_pass))
 image_ids=tuple(map(str,run.get("image_ids",())))
 if len(sessions)!=len(image_ids):raise ValueError(f"Human repeatability Annotation {reference_pass} does not contain the full saved image set")
 issue=repeatability_reference_frame_issue(project,run["run_id"],reference_pass)
 if issue:raise ValueError(repeatability_reference_frame_issue_message(issue))
 current_identity=landmark_schema_identity(load_schema(project.schema_path));stored_identity=_run_schema_identity(project,run)
 if stored_identity and stored_identity!=current_identity:raise ValueError("Human repeatability landmark identities/order no longer match the project")
 schema=tuple(dict(row) for row in load_schema(project.schema_path));request_digest=str(backend.schema_sha256);records=[]
 for image_id,sid in zip(image_ids,sessions):
  session=_load(project,sid)
  if session.get("status")!="completed":raise ValueError(f"Human repeatability Annotation {reference_pass} is not completed for image {image_id}")
  if str(session.get("image_id"))!=image_id:raise ValueError(f"Human repeatability session/image mismatch for {image_id}")
  rel=session.get("standardized_relpath");path=project.data_root/rel
  with Image.open(path) as image:width,height=image.width,image.height
  points={int(point["landmark_id"]):point for point in session.get("repeat",())}
  valid=[(ident,float(point["x"]),float(point["y"])) for ident,point in points.items() if point.get("state")=="present" and point.get("x") is not None and point.get("y") is not None and math.isfinite(float(point["x"])) and math.isfinite(float(point["y"]))]
  if len(valid)<2:raise ValueError(f"Human repeatability Annotation {reference_pass} has too few comparable landmarks: {image_id}")
  span=max(math.hypot(left[1]-right[1],left[2]-right[2]) for index,left in enumerate(valid) for right in valid[index+1:])
  if span<=0:raise ValueError(f"Human repeatability Annotation {reference_pass} has zero reference span: {image_id}")
  records.append((image_id,valid,span,InferenceRequest(image_id,path,schema,request_digest,width,height)))
 requests=[record[3] for record in records];predictions={}
 if hasattr(backend,"predict_readonly_many") and requests:
  performance=auto_performance_config(project,workload="control_evaluation",model=str(model_id),input_size=(requests[0].width,requests[0].height),training=False);size=max(1,int(performance["batch_size"]));offset=0
  while offset<len(requests):
   chunk=requests[offset:offset+size]
   try:returned=backend.predict_readonly_many(chunk)
   except Exception as exc:
    if size>1 and (is_cuda_oom(exc) or "RTMPose rank failed (return code" in str(exc)):size=max(1,size//2);continue
    raise
   predictions.update({prediction.image_id:prediction for prediction in returned});offset+=len(chunk)
 else:predictions={request.image_id:backend.predict(request) for request in requests}
 raw_errors=[];percent_errors=[];per_landmark={};evaluated=[]
 for image_id,valid,span,request in records:
  prediction=predictions.get(image_id)
  if prediction is None:raise ValueError(f"model returned no prediction for Human repeatability image: {image_id}")
  LandmarkAIService._validate(prediction,request);returned={point.landmark_id:point for point in prediction.landmarks};image_raw=[];image_percent=[]
  for landmark_id,x,y in valid:
   predicted=returned.get(landmark_id)
   if predicted is None:continue
   error=math.hypot(predicted.x-x,predicted.y-y);percent=error/span*100;raw_errors.append(error);percent_errors.append(percent);per_landmark.setdefault(landmark_id,[]).append(percent);image_raw.append(error);image_percent.append(percent)
  evaluated.append({"image_id":image_id,"reference_span_px":span,"n_landmarks":len(image_percent),"median_error_px":_pct(image_raw,.5),"median_error_percent":_pct(image_percent,.5)})
 return {"model_id":str(model_id),"schema_sha256":request_digest,"control_image_ids":tuple(item["image_id"] for item in evaluated),"reference_source":f"human_repeatability_annotation_{int(reference_pass)}","repeatability_run_id":run.get("run_id"),"per_image":evaluated,"per_landmark":{str(ident):{"landmark_id":ident,"median_error_percent":_pct(values,.5),"p90_error_percent":_pct(values,.9)} for ident,values in sorted(per_landmark.items())},"aggregate":{"n_images":len(evaluated),"n_comparable_landmarks":len(percent_errors),"median_error_percent":_pct(percent_errors,.5),"p90_error_percent":_pct(percent_errors,.9),"p95_error_percent":_pct(percent_errors,.95),"median_error_px":_pct(raw_errors,.5),"p90_error_px":_pct(raw_errors,.9),"p95_error_px":_pct(raw_errors,.95)}}

def repeatability_reference_frame_issue(project,run_id,reference_pass=1):
 """Return the first saved reference-frame problem without running inference or changing project data."""
 _,run=_run_by_id(project,run_id);reference_pass=int(reference_pass)
 sessions=pass_session_ids(run,reference_pass);image_ids=tuple(map(str,run.get("image_ids",())))
 if len(sessions)!=len(image_ids):
  return {"kind":"membership","annotation":reference_pass,"message":f"Human repeatability Annotation {reference_pass} does not contain the full saved image set"}
 for position,(image_id,sid) in enumerate(zip(image_ids,sessions),start=1):
  session=_load(project,sid);rel=session.get("standardized_relpath")
  base={"position":position,"total":len(image_ids),"image_id":image_id,"annotation":reference_pass,"session_id":sid}
  if not rel:return dict(base,kind="missing_path",message=f"Human repeatability has no saved standardized image path for image {position}/{len(image_ids)}")
  path=project.data_root/rel
  if not path.is_file():return dict(base,kind="missing_file",message=f"Human repeatability standardized image is missing for image {position}/{len(image_ids)}")
  digest=hashlib.sha256(path.read_bytes()).hexdigest();expected=session.get("standardized_sha256")
  if expected and digest!=expected:
   return dict(base,kind="frozen_changed" if session.get("standardized_snapshot") else "legacy_changed",path=str(path))
  with Image.open(path) as image:width,height=image.width,image.height
  stored_width=session.get("standardized_width");stored_height=session.get("standardized_height")
  if stored_width is not None and stored_height is not None and (int(stored_width),int(stored_height))!=(width,height):
   return dict(base,kind="size_changed",path=str(path))
 return None

def repeatability_reference_frame_issue_message(issue):
 if not issue:return ""
 position,total,image_id,annotation=issue["position"],issue["total"],issue["image_id"],issue["annotation"]
 details=f"Image: {position}/{total}\nID: {image_id}\nBatch: Annotation {annotation}"
 kind=issue.get("kind")
 if kind=="legacy_changed":
  return f"This older Human repeatability uses a changed standardized image.\n\n{details}\n\nOnly this image must be repeated in Annotation 1 and Annotation 2."
 if kind=="frozen_changed":
  return f"Human repeatability frozen image is damaged or was modified.\n\n{details}\n\nOnly this image must be repeated in Annotation 1 and Annotation 2."
 if kind=="size_changed":
  return f"Human repeatability image size changed.\n\n{details}\n\nOnly this image must be repeated in Annotation 1 and Annotation 2."
 return str(issue.get("message") or f"Human repeatability reference image problem.\n\n{details}")

def evaluate_model_on_repeatability_run(project,run_id,model_id,*,backend=None,reference_pass=1):
 _,run=_run_by_id(project,run_id)
 return _evaluate_model_on_repeatability_run(project,run,model_id,backend=backend,reference_pass=reference_pass)

def evaluate_human_baseline(project,run,*,backend=None,include_model=True):
 if int(run.get("format_version",1))>=2:
  first,second=pass_session_ids(run,1),pass_session_ids(run,2)
  human=_evaluate_pair(project,run,first,second)
 else:
  # Legacy v1 remains readable: canonical snapshot versus the one saved repeat pass.
  errors=[];per={};per_image=[]
  for sid in run["session_ids"]:
   s=_load(project,sid)
   if s.get("status")!="completed":continue
   original={p["landmark_id"]:p for p in s.get("baseline",())};repeat={p["landmark_id"]:p for p in s.get("repeat",())};span=_span(original);image_errors=[]
   for ident,point in original.items():
    other=repeat.get(ident)
    if not other or point.get("state")!="present" or other.get("state")!="present" or span<=0:continue
    value=math.hypot(point["x"]-other["x"],point["y"]-other["y"])/span*100;errors.append(value);image_errors.append(value);per.setdefault(str(ident),[]).append(value)
   per_image.append({"image_id":s["image_id"],"reference_span_px":span,"median_error_percent":_pct(image_errors,.5)})
  human={"aggregate":{"n_images":len(per_image),"n_comparable_landmarks":len(errors),"median_error_percent":_pct(errors,.5),"p90_error_percent":_pct(errors,.9),"p95_error_percent":_pct(errors,.95)},"per_landmark":{i:{"landmark_id":int(i),"n":len(v),"median_error_percent":_pct(v,.5),"p90_error_percent":_pct(v,.9)} for i,v in per.items()},"per_image":per_image}
 model_id=run.get("model_id")
 if model_id and include_model:
  model=_evaluate_model_on_repeatability_run(project,run,model_id,backend=backend,reference_pass=1)
 else:model={"aggregate":{},"per_landmark":{},"control_image_ids":[]}
 report=build_comparison(run,human,model);report["model_deferred"]=bool(model_id and not include_model)
 return report
def grade_ratio(ratio):
 if ratio is None:return "Unavailable"
 if ratio<=1.10:return "Within manual repeatability"
 if ratio<=1.25:return "Very close to manual"
 if ratio<=1.50:return "Close to manual"
 if ratio<=2:return "Needs improvement"
 return "Clearly worse than manual"
def build_comparison(run,human,model):
 h=human["aggregate"];m=model["aggregate"]
 def ratio(key):return m.get(key)/h[key] if h.get(key) not in (None,0) and m.get(key) is not None else None
 rows=[]
 for ident in sorted(set(human["per_landmark"])|set(model.get("per_landmark",{})),key=int):
  a=human["per_landmark"].get(ident,{});b=model.get("per_landmark",{}).get(ident,{});value=b.get("p90_error_percent")/a["p90_error_percent"] if a.get("p90_error_percent") not in (None,0) and b.get("p90_error_percent") is not None else None
  rows.append({"landmark_id":int(ident),"human_p90_error_percent":a.get("p90_error_percent"),"model_p90_error_percent":b.get("p90_error_percent"),"ratio":value,"status":grade_ratio(value)})
 return {"report_type":"human_baseline","format_version":run.get("format_version",1),"run_id":run["run_id"],"model_id":run.get("model_id"),"image_ids":list(run["image_ids"]),"human":human,"model":model,"ratios":{"median":ratio("median_error_percent"),"p90":ratio("p90_error_percent"),"p95":ratio("p95_error_percent")},"grade":grade_ratio(ratio("p90_error_percent")),"per_landmark":rows}
def comparison_for_model(report,model_evaluation):return build_comparison({"run_id":report["run_id"],"image_ids":report["image_ids"],"model_id":model_evaluation.get("model_id")},report["human"],model_evaluation)
def landmark_model_rows(human_report,previous_evaluation,new_evaluation):
 previous=comparison_for_model(human_report,previous_evaluation);new=comparison_for_model(human_report,new_evaluation);prior={int(r["landmark_id"]):r for r in previous["per_landmark"]};current={int(r["landmark_id"]):r for r in new["per_landmark"]};rows=[]
 for ident in sorted(set(prior)|set(current)):
  before,after=prior.get(ident,{}),current.get(ident,{});old,newv=before.get("model_p90_error_percent"),after.get("model_p90_error_percent");change=(newv-old)/old*100 if old not in (None,0) and newv is not None else None
  rows.append({"landmark_id":ident,"human_p90_error_percent":after.get("human_p90_error_percent",before.get("human_p90_error_percent")),"previous_p90_error_percent":old,"new_p90_error_percent":newv,"new_human_ratio":after.get("ratio"),"change_percent":change,"status":after.get("status","Unavailable")})
 return rows
def _assert_pass_scheme_consistency(project,run):
 if int(run.get("format_version",1))<2:return
 ids=tuple(pass_session_ids(run,1))+tuple(pass_session_ids(run,2));identities=set();hashes=set()
 for sid in ids:
  identity=_session_schema_identity(project,sid)
  if identity:identities.add(identity)
  else:
   value=_load(project,sid).get("schema_sha256")
   if value:hashes.add(str(value))
 run_identities=_run_schema_identities(project,run)
 identities.update(run_identities)
 if not identities and run.get("schema_sha256"):hashes.add(str(run["schema_sha256"]))
 if len(identities)>1 or (not identities and len(hashes)>1):raise ValueError("Annotation 1 and Annotation 2 use different landmark identities/order. Start a new Human repeatability sample.")

def complete_run(project,run_id,*,backend=None,include_model=True):
 data,run=_run_by_id(project,run_id)
 if int(run.get("format_version",1))>=2:
  if not pass_progress(project,run,1)["complete"] or not pass_progress(project,run,2)["complete"]:raise ValueError("Finish both Annotation 1 and Annotation 2 first.")
  if not final_qc_complete(run):raise ValueError("Complete the point check after Annotation 1 and Annotation 2 before finishing Human repeatability.")
  _assert_pass_scheme_consistency(project,run)
 if run.get("status")=="completed":
  if not run.get("report_stale"):return _load_json(_root(project)/run["report_path"],{})
  return recompute_completed_run(project,run_id,backend=backend,include_model=include_model)
 if int(run.get("format_version",1))<2 and any(_load(project,s).get("status")!="completed" for s in run.get("session_ids",())):
  raise ValueError("All Human Baseline images must be completed first.")
 report=evaluate_human_baseline(project,run,backend=backend,include_model=include_model);path=_root(project)/f"human_baseline_{run_id}.json";atomic_json_write(path,dict(report,created_at=_now(),final_qc=run.get('final_qc')))
 run.update({"status":"completed","completed_at":_now(),"report_path":path.relative_to(_root(project)).as_posix(),"report_stale":False,"final_check_completed_at":(run.get('final_qc') or {}).get('checked_at')});_save_runs(project,data);return report
# Existing completed-run correction API retained.
def _canonical_baseline(project,image_id):
 rows=project.load_landmarks(image_id);return [{"landmark_id":x["id"],"state":"missing" if rows[x["id"]]["state"]=="missing" else "present","x":None if rows[x["id"]]["state"]=="missing" else rows[x["id"]]["x_standardized"],"y":None if rows[x["id"]]["state"]=="missing" else rows[x["id"]]["y_standardized"],"provenance":rows[x["id"]]["provenance"]} for x in project.schema]
def refresh_first_marking_reference(project,run_id,image_id):
 data,run=_run_by_id(project,run_id)
 if image_id not in run["image_ids"]:raise ValueError("image is not part of this Human Baseline run")
 session_id=pass_session_ids(run,1)[run["image_ids"].index(image_id)];session=_load(project,session_id);session.setdefault("revisions",[]).append({"timestamp":_now(),"kind":"first_marking_before_correction","baseline":list(session.get("baseline",()))});session["baseline"]=_canonical_baseline(project,image_id)
 from .operator_qc import _save
 _save(project,session_id,session);run["report_stale"]=True;_save_runs(project,data);return session
def mark_completed_run_stale(project,run_id,pass_number=None):
 """A real annotation edit invalidates the report and the QC of the edited pass."""
 data,run=_run_by_id(project,run_id)
 if run.get("status")=="completed":run["report_stale"]=True
 if pass_number in (1,2):invalidate_repeatability_pass_qc(run,pass_number,reason='annotation_edited')
 else:invalidate_repeatability_qc(run,reason='annotation_edited')
 _save_runs(project,data);return run

def recompute_completed_run(project,run_id,*,backend=None,include_model=True):
 data,run=_run_by_id(project,run_id)
 if run.get("status")!="completed":raise ValueError("Human Baseline run is not completed")
 if not final_qc_complete(run):raise ValueError("Complete the point check after Annotation 1 and Annotation 2 before recalculating Human repeatability.")
 _assert_pass_scheme_consistency(project,run)
 report=evaluate_human_baseline(project,run,backend=backend,include_model=include_model);path=_root(project)/run["report_path"];atomic_json_write(path,dict(report,created_at=_now(),recomputed_at=_now(),final_qc=run.get('final_qc')));run["report_stale"]=False;run["final_check_completed_at"]=(run.get('final_qc') or {}).get('checked_at');_save_runs(project,data);return report
