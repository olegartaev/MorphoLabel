"""Small, GUI-independent production crop orchestration."""
from __future__ import annotations
import logging,time
from itertools import chain
from .crop_training import current_label
from .normalization_pipeline import prepare_crop_result, commit_crop_result
from .crop_parallel import auto_config,bounded_map,tune_and_prepare

LOG=logging.getLogger("morphology.crop")

def _log(event, **values): LOG.info("%s %s",event," ".join(f"{k}={v}" for k,v in values.items()))

def candidates(project, rerun=False, image_ids=None): return project.crop_auto_candidates(rerun=rerun,image_ids=image_ids)

def process(project, *, rerun=False, image_ids=None, cancel=None, progress=None, materialize_learned=False):
 ids,protected=candidates(project,rerun,image_ids);kind="rerun_unreviewed" if rerun else "auto_crop_remaining";started=time.monotonic();model_id=current_label(project)
 def compute(image_id):return prepare_crop_result(project.image_path(image_id),project=project,force=True,image_id_value=image_id,materialize_learned=materialize_learned)
 # A new machine key benchmarks only a bounded real proposal sample.  Results
 # of the selected candidate are committed below, so no sampled image is
 # prepared again by the production pass.  SQLite mutation remains serialized.
 config=auto_config();prepared={}
 if len(ids)>=8:
  config,prepared=tune_and_prepare(project,workload="crop_learned_proposal",sample=ids[:min(8,len(ids))],worker=compute,fallback=config)
 _log(kind+"_start",active_model=model_id,eligible_count=len(ids),protected_count=protected,**config)
 result={"attempted":len(ids),"success":0,"failed":0,"skipped":0,"cancelled":0,"protected":protected,"image_ids":ids,"successful_ids":[],"model_id":model_id,"config":config,"failures":[],"timings":{}}
 pending=[image_id for image_id in ids if image_id not in prepared]
 ready=((image_id,prepared[image_id],None) for image_id in ids if image_id in prepared)
 for index,(image_id,output,failure) in enumerate(chain(ready,bounded_map(pending,compute,cancel=cancel,config=config)),1):
  if failure is not None:
   LOG.exception("crop_inference_failed image_id=%s",image_id,exc_info=failure);result["failed"]+=1;result["failures"].append({"image_id":image_id,"reason":str(failure)});_log("crop_inference_end",image_id=image_id,save_result="failed",failure_reason=repr(failure))
  else:
   try:
    for key,value in (output.get("timings") or {}).items():result["timings"][key]=result["timings"].get(key,0.0)+float(value)
    old=project.crop_record(image_id);commit_started=time.monotonic();commit_crop_result(project,output,provenance="automatic");saved=project.record_ai_crop_prediction(image_id,output,model_id);result["success"]+=1;result["successful_ids"].append(image_id)
    commit_s=time.monotonic()-commit_started;result["timings"]["sqlite_commit_s"]=result["timings"].get("sqlite_commit_s",0.0)+commit_s;_log("crop_inference_end",image_id=image_id,prediction_id=saved["prediction_id"],crop_model_id=model_id,ai_proposal=output.get("crop_bounds"),qc_result=saved["qc_result"],commit_s=round(commit_s,4),save_result="ok")
    if rerun and old:_log("active_prediction_changed",image_id=image_id,old_prediction_id=old.get("active_prediction_id"),old_model_id=old.get("model_id"),new_prediction_id=saved["prediction_id"],new_model_id=model_id)
   except Exception as exc:LOG.exception("crop_commit_failed image_id=%s",image_id);result["failed"]+=1;result["failures"].append({"image_id":image_id,"reason":str(exc)});_log("crop_inference_end",image_id=image_id,save_result="failed",failure_reason=repr(exc))
  if progress:progress(index,len(ids),image_id,result)
 if cancel and cancel.is_set():result["cancelled"]=max(0,len(ids)-result["success"]-result["failed"])
 elapsed=max(.001,time.monotonic()-started);_log(kind+"_complete",success_count=result["success"],failed_count=result["failed"],skipped_count=result["skipped"],cancelled_count=result["cancelled"],wall_time_s=round(elapsed,3),images_per_second=round((result["success"]+result["failed"])/elapsed,3),workers=config['workers'])
 return result

