"""Fair, GUI-independent RTMPose input-resolution experiments."""
from __future__ import annotations
import time, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from .ai_batch import active_backend, backend_for_model
from .ai_hardware import auto_performance_config, get_hardware_profile
from .landmark_ai_workflow import control_set_summary
from .landmark_dataset import create_dataset, deterministic_splits, v2_human_final_eligible_image_ids
from .landmark_qc import evaluate_control_set
from .project_storage import schema_hash
from .rtmpose_backend import RTMPoseBackend, RTMPoseModelSpec, train_project

RESOLUTIONS=((512,256),(640,320),(768,384))

@dataclass(frozen=True)
class ResolutionExperimentPlan:
 experiment_id:str; parent_model_id:str; dataset_id:str; image_ids:tuple; splits:dict; seed:int; control_image_ids:tuple

def prepare_experiment(project, *, seed):
 parent,backend=active_backend(project)
 ids=tuple(v2_human_final_eligible_image_ids(project))
 if len(ids)<2: raise ValueError('at least two human-verified training images are required')
 validation=max(1,min(len(ids)-1,round(len(ids)*.15)))
 splits=deterministic_splits(project,split_counts={'train':len(ids)-validation,'validation':validation,'test':0},seed=int(seed),eligibility_mode='v2_human_final')
 token=f'{parent["model_id"]}_resolution_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")}_{uuid.uuid4().hex[:8]}'
 return ResolutionExperimentPlan(token,parent['model_id'],f'{token}_dataset',ids,splits,int(seed),tuple(control_set_summary(project)['current_ids']))

def run_experiment(project, plan, *, progress_callback=None):
 """Train three inactive candidates sequentially; errors propagate unchanged."""
 parent,base=active_backend(project)
 if parent['model_id']!=plan.parent_model_id: raise ValueError('active model changed after resolution experiment was prepared')
 if tuple(v2_human_final_eligible_image_ids(project))!=plan.image_ids: raise ValueError('training image set changed after resolution experiment was prepared')
 if tuple(control_set_summary(project)['current_ids'])!=plan.control_image_ids: raise ValueError('Control Set changed after resolution experiment was prepared')
 create_dataset(project,dataset_id=plan.dataset_id,splits=plan.splits,seed=plan.seed,eligibility_mode='v2_human_final')
 results=[];hardware=get_hardware_profile()
 for ordinal,size in enumerate(RESOLUTIONS,1):
  def probe(batch): return base._invoke('probe',{'config_path':str(base.spec.config_path),'input_size':list(size),'batch_size':int(batch),'device':'cuda:0'})
  settings=dict(auto_performance_config(project,workload='landmark_resolution_training',model=plan.parent_model_id,input_size=size,training=True,hardware=hardware,probe=probe if hardware.cuda_available else None))
  settings.update({'persistent_workers':bool(settings['workers']>0),'pin_memory':str(settings['device']).startswith('cuda'),'hardware':hardware.as_dict(),'max_epochs':210,'checkpoint_interval':10,'max_keep_ckpts':2,'smoke':False,'force_backbone_only_init':True,'resolution_experiment_id':plan.experiment_id,'resolution_experiment_ordinal':ordinal})
  model_id=f'{plan.experiment_id}_{size[0]}x{size[1]}'
  if progress_callback:progress_callback(ordinal,size,model_id)
  candidate=RTMPoseBackend(RTMPoseModelSpec(model_id,schema_hash(project.schema_path),base.spec.config_path,base.spec.checkpoint_path,size,settings['device']))
  train_project(project,plan.dataset_id,candidate,parent_model_id=plan.parent_model_id,settings=settings)
  _,evaluation_backend=backend_for_model(project,model_id);started=time.perf_counter();metrics=evaluate_control_set(project,model_id,backend=evaluation_backend);duration=time.perf_counter()-started
  aggregate=metrics['aggregate'];results.append({'model_id':model_id,'input_size':size,'median_error_percent':aggregate['median_error_percent'],'p90_error_percent':aggregate['p90_error_percent'],'p95_error_percent':aggregate['p95_error_percent'],'inference_seconds':duration,'control_image_ids':tuple(metrics['control_image_ids']),'dataset_id':plan.dataset_id,'seed':plan.seed,'force_backbone_only_init':True})
 return {'experiment_id':plan.experiment_id,'parent_model_id':plan.parent_model_id,'dataset_id':plan.dataset_id,'seed':plan.seed,'image_ids':plan.image_ids,'control_image_ids':plan.control_image_ids,'candidates':results,'recommendation':recommend_resolution(results)}

def recommend_resolution(candidates):
 baseline=next((row for row in candidates if tuple(row['input_size'])==(512,256)),None)
 if baseline is None: raise ValueError('512x256 baseline is required')
 def meaningful(row):
  if tuple(row['input_size'])==(512,256): return True
  p90,p95=baseline['p90_error_percent'],baseline['p95_error_percent']
  return p90 and p95 and row['p90_error_percent']<=p90*.95 and row['p95_error_percent']<=p95*.95
 eligible=[row for row in candidates if meaningful(row)]
 chosen=min(eligible,key=lambda row:(row['p95_error_percent'],row['p90_error_percent'],row['median_error_percent']))
 return {'model_id':chosen['model_id'],'input_size':chosen['input_size'],'reason':'meaningful P90 and P95 improvement' if chosen is not baseline else 'larger resolutions did not improve both P90 and P95 by at least 5%'}