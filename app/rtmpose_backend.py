"""RTMPose subprocess backend. This module never imports torch or mmpose."""
from __future__ import annotations
import json, queue, subprocess, sys, threading, time
from dataclasses import dataclass
from pathlib import Path
from .ai import ImagePrediction,InferenceRequest,LandmarkBackend,LandmarkPrediction
from .landmark_dataset import dataset_manifest_path,verify_dataset
from .rtmpose_dataset import FISH_INPUT_SIZE,export_coco,mmpose_metainfo,generate_smoke_config
from .io import atomic_json_write
from .project_storage import schema_hash, landmark_model_schema_compatible
from .ai_runtime_resolver import validate_ai_runtime
from .ai_delivery import ensure_ai_runtime

class RTMPoseRuntimeError(RuntimeError): pass
@dataclass(frozen=True)
class RTMPoseModelSpec:
 model_id:str; schema_sha256:str; config_path:Path; checkpoint_path:Path; input_size:tuple[int,int]=FISH_INPUT_SIZE; device:str='cuda:0'; inference_batch_size:int=1; prefetch_workers:int|None=None; prefetch_depth:int|None=None

class RTMPoseBackend(LandmarkBackend):
 """JSON/subprocess bridge; the manual SIMM runtime has no OpenMMLab imports."""
 def __init__(self,spec:RTMPoseModelSpec,*,runtime_python=None,runner_path=None):
  self.spec=spec;self.model_id=spec.model_id;self.schema_sha256=spec.schema_sha256;self.last_rank_batch_size=max(1,int(spec.inference_batch_size))
  self.runtime_python,self.runner_path=ensure_ai_runtime(explicit=runtime_python,runner_path=runner_path)
  self._runtime_explicit=runtime_python is not None or runner_path is not None
  self._runtime_validated=False
 def _invoke(self,operation,payload,*,progress_callback=None,no_progress_timeout=180):
  if not self._runtime_explicit and not self._runtime_validated:
   validate_ai_runtime(self.runtime_python,self.runner_path)
   self._runtime_validated=True
  if not self.runtime_python.exists(): raise RTMPoseRuntimeError(f'AI runtime is unavailable: {self.runtime_python}')
  if not self.runner_path.exists(): raise RTMPoseRuntimeError(f'RTMPose runner is unavailable: {self.runner_path}')
  if operation in {'rank','rank_benchmark','rank_checkpoints','probe_many'}: return self._invoke_rank(payload,operation=operation,progress_callback=progress_callback,no_progress_timeout=no_progress_timeout)
  try: run=subprocess.run([str(self.runtime_python),str(self.runner_path),operation],input=json.dumps(payload),text=True,capture_output=True,check=False,cwd=str(Path(__file__).resolve().parents[1]))
  except OSError as exc: raise RTMPoseRuntimeError(f'cannot start isolated AI runtime: {exc}') from exc
  if run.returncode: raise RTMPoseRuntimeError(f"RTMPose {operation} failed (return code {run.returncode})\nFULL STDOUT:\n{run.stdout}\nFULL STDERR:\n{run.stderr}")
  try: return json.loads(next(line for line in reversed(run.stdout.splitlines()) if line.strip()))
  except (json.JSONDecodeError,StopIteration) as exc: raise RTMPoseRuntimeError(f'RTMPose {operation} emitted invalid JSON: {run.stdout[:500]}') from exc
 def _invoke_rank(self,payload,*,operation='rank',progress_callback=None,no_progress_timeout=180):
  """Run one rank process, terminating only when its heartbeat stops."""
  command=[str(self.runtime_python),str(self.runner_path),operation];events=queue.Queue();stdout=[];stderr=[]
  try: process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,cwd=str(Path(__file__).resolve().parents[1]))
  except OSError as exc: raise RTMPoseRuntimeError(f'cannot start isolated AI runtime: {exc}') from exc
  def drain(stream,kind):
   try:
    for line in iter(stream.readline,''):events.put((kind,line))
   finally:
    stream.close();events.put((kind,None))
  readers=[threading.Thread(target=drain,args=(process.stdout,'stdout'),daemon=True),threading.Thread(target=drain,args=(process.stderr,'stderr'),daemon=True)]
  for reader in readers:reader.start()
  try: process.stdin.write(json.dumps(payload));process.stdin.close()
  except (BrokenPipeError,OSError): pass
  last_progress=time.monotonic();closed=set();stalled=False
  while len(closed)<2:
   try: kind,line=events.get(timeout=.25)
   except queue.Empty:
    if process.poll() is None and time.monotonic()-last_progress>=no_progress_timeout:
     stalled=True;process.terminate()
     try:process.wait(timeout=10)
     except subprocess.TimeoutExpired:process.kill()
     continue
    if process.poll() is not None and not any(reader.is_alive() for reader in readers):break
    continue
   if line is None:closed.add(kind);continue
   (stdout if kind=='stdout' else stderr).append(line)
   if kind=='stderr':
    parts=line.strip().split()
    if len(parts)==3 and parts[0]=='RANK_PROGRESS':
     try: done,total=int(parts[1]),int(parts[2])
     except ValueError: continue
     last_progress=time.monotonic()
     if progress_callback:progress_callback(done,total)
  for reader in readers:reader.join(timeout=1)
  returncode=process.wait();output=''.join(stdout);errors=''.join(stderr)
  if stalled:raise RTMPoseRuntimeError(f'RTMPose rank stalled: no progress for 180 seconds.\nFULL STDOUT:\n{output}\nFULL STDERR:\n{errors}')
  if returncode:raise RTMPoseRuntimeError(f'RTMPose rank failed (return code {returncode})\nFULL STDOUT:\n{output}\nFULL STDERR:\n{errors}')
  try:return json.loads(next(line for line in reversed(output.splitlines()) if line.strip()))
  except (json.JSONDecodeError,StopIteration) as exc:raise RTMPoseRuntimeError(f'RTMPose rank emitted invalid JSON: {output[:500]}') from exc
 def predict(self,request:InferenceRequest):
  raw=self._invoke('predict',{'image_id':request.image_id,'image_path':str(request.standardized_image_path),'schema_sha256':request.schema_sha256,'model_id':self.model_id,'config_path':str(self.spec.config_path),'checkpoint_path':str(self.spec.checkpoint_path),'input_size':list(self.spec.input_size),'device':self.spec.device,'simm_landmark_ids':[int(row['id']) for row in request.schema]})
  return ImagePrediction(raw['image_id'],raw['model_id'],raw['schema_sha256'],tuple(LandmarkPrediction(int(x['landmark_id']),float(x['x']),float(x['y']),None if x.get('confidence') is None else float(x['confidence'])) for x in raw['landmarks']))
 def predict_readonly_many(self,requests,*,progress_callback=None,batch_size=None,prefetch_workers=None,prefetch_depth=None):
  requests=tuple(requests)
  if any(request.schema_sha256!=self.schema_sha256 for request in requests): raise RTMPoseRuntimeError('ranking request schema does not match backend')
  raw=self._invoke('rank',{'schema_sha256':self.schema_sha256,'model_id':self.model_id,'config_path':str(self.spec.config_path),'checkpoint_path':str(self.spec.checkpoint_path),'input_size':list(self.spec.input_size),'device':self.spec.device,'batch_size':max(1,int(batch_size if batch_size is not None else self.spec.inference_batch_size)),'prefetch_workers':prefetch_workers if prefetch_workers is not None else self.spec.prefetch_workers,'prefetch_depth':prefetch_depth if prefetch_depth is not None else self.spec.prefetch_depth,'simm_landmark_ids':[int(row['id']) for row in requests[0].schema] if requests else [],'requests':[{'image_id':request.image_id,'image_path':str(request.standardized_image_path)} for request in requests]},progress_callback=progress_callback)
  if raw.get('model_id')!=self.model_id or raw.get('schema_sha256')!=self.schema_sha256: raise RTMPoseRuntimeError('ranking response model/schema mismatch')
  self.last_rank_batch_size=max(1,int(raw.get('effective_batch_size',self.spec.inference_batch_size)))
  by_id={item['image_id']:item for item in raw.get('results',())}
  return tuple(ImagePrediction(request.image_id,self.model_id,self.schema_sha256,tuple(LandmarkPrediction(int(item['landmark_id']),float(item['x']),float(item['y']),None if item.get('confidence') is None else float(item['confidence'])) for item in by_id[request.image_id].get('landmarks',()))) for request in requests)
 def benchmark_training_configurations(self,config_path,candidates,*,samples=48,mixed_precision=True,device=None,progress_callback=None):
  """Measure several training configs while loading torch/MMPose/model once."""
  raw=self._invoke('probe_many',{'config_path':str(config_path),'candidates':[dict(item) for item in candidates],'samples':int(samples),'mixed_precision':bool(mixed_precision),'device':str(device or self.spec.device)},progress_callback=progress_callback)
  if raw.get('status')!='ok':raise RTMPoseRuntimeError('training autotune probe did not complete')
  return tuple(raw.get('results',()))

 def benchmark_readonly_many(self,requests,*,batch_sizes=(1,2,4,8,16,32,64),candidates=None,prefetch_worker_candidates=None,prefetch_depth_candidates=(1,2,4),progress_callback=None):
  requests=tuple(requests)
  if not requests: return {'selected_batch_size':1,'benchmarks':[]}
  raw=self._invoke('rank_benchmark',{'schema_sha256':self.schema_sha256,'model_id':self.model_id,'config_path':str(self.spec.config_path),'checkpoint_path':str(self.spec.checkpoint_path),'input_size':list(self.spec.input_size),'device':self.spec.device,'batch_sizes':[int(value) for value in batch_sizes],'candidates':list(candidates or ()), 'prefetch_worker_candidates':list(prefetch_worker_candidates or ()), 'prefetch_depth_candidates':[int(value) for value in prefetch_depth_candidates], 'simm_landmark_ids':[int(row['id']) for row in requests[0].schema],'requests':[{'image_id':request.image_id,'image_path':str(request.standardized_image_path)} for request in requests]},progress_callback=progress_callback)
  if raw.get('model_id')!=self.model_id or raw.get('schema_sha256')!=self.schema_sha256:raise RTMPoseRuntimeError('rank benchmark response model/schema mismatch')
  return raw
 def predict_readonly_checkpoints(self,requests,checkpoint_paths,*,progress_callback=None,batch_size=None):
  """Evaluate several saved EMA epochs through one persistent runtime."""
  requests=tuple(requests);paths=tuple(map(Path,checkpoint_paths))
  if not requests:return {}
  raw=self._invoke('rank_checkpoints',{'schema_sha256':self.schema_sha256,'model_id':self.model_id,'config_path':str(self.spec.config_path),'checkpoint_paths':[str(path) for path in paths],'input_size':list(self.spec.input_size),'device':self.spec.device,'batch_size':max(1,int(batch_size if batch_size is not None else self.spec.inference_batch_size)),'prefetch_workers':self.spec.prefetch_workers,'prefetch_depth':self.spec.prefetch_depth,'simm_landmark_ids':[int(row['id']) for row in requests[0].schema],'requests':[{'image_id':request.image_id,'image_path':str(request.standardized_image_path)} for request in requests]},progress_callback=progress_callback)
  if raw.get('model_id')!=self.model_id or raw.get('schema_sha256')!=self.schema_sha256:raise RTMPoseRuntimeError('checkpoint rank response model/schema mismatch')
  results={}
  for item in raw.get('checkpoints',()):
   by_id={row['image_id']:row for row in item.get('results',())}
   results[str(item['checkpoint_path'])]=tuple(ImagePrediction(request.image_id,self.model_id,self.schema_sha256,tuple(LandmarkPrediction(int(point['landmark_id']),float(point['x']),float(point['y']),None if point.get('confidence') is None else float(point['confidence'])) for point in by_id[request.image_id].get('landmarks',()))) for request in requests)
  return results
 def train(self,dataset_manifest,output_dir,*,parent_model_id=None,settings=None):
  manifest=Path(dataset_manifest).resolve();out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True);coco=out/'annotations.coco.json';export_coco(manifest,coco,splits=('train','validation'));payload={'dataset_manifest':str(manifest),'coco_path':str(coco),'output_dir':str(out),'schema_sha256':self.schema_sha256,'model_id':self.model_id,'parent_model_id':parent_model_id,'input_size':list(self.spec.input_size),'settings':settings or {}}
  return self._invoke('train',payload)
 def evaluate(self,dataset_manifest): return self._invoke('evaluate',{'dataset_manifest':str(dataset_manifest),'model_id':self.model_id})
 def export(self,output_dir): return self._invoke('export',{'output_dir':str(output_dir),'model_id':self.model_id})
 def model_info(self): return {'backend':'rtmpose','model_id':self.model_id,'schema_sha256':self.schema_sha256,'config_path':str(self.spec.config_path),'checkpoint_path':str(self.spec.checkpoint_path),'input_size':list(self.spec.input_size),'runtime_python':str(self.runtime_python)}

def _resolve_parent_checkpoint(parent_dir):
 """Resolve the same immutable parent artifact checkpoint accepted by inference."""
 primary=Path(parent_dir)/"best_engineering_validation.pth"
 checkpoint=primary
 if not checkpoint.is_file():
  try:info=json.loads((Path(parent_dir)/"model.json").read_text(encoding="utf-8"))
  except (OSError,json.JSONDecodeError):info={}
  checkpoint=Path(info.get("result",{}).get("checkpoint_path", ""))
 if not checkpoint.is_file() or checkpoint.stat().st_size<=0:
  raise RTMPoseRuntimeError(f"parent model checkpoint is unavailable: {primary}")
 return checkpoint
def create_backbone_only_checkpoint(backend, parent_checkpoint, output_checkpoint, source_model_id):
 """Create an immutable init checkpoint with RTMPose backbone parameters only."""
 result=backend._invoke("backbone_init",{"parent_checkpoint":str(parent_checkpoint),"output_checkpoint":str(output_checkpoint),"source_model_id":str(source_model_id)})
 if result.get("status")!="ok" or int(result.get("backbone_parameter_count",0))<1:raise RTMPoseRuntimeError("backbone-only initialization checkpoint was not created")
 return Path(result["output_checkpoint"])

def _model_input_size(project, model, fallback=FISH_INPUT_SIZE):
 artifact=Path(model.get("path") or "");artifact=artifact if artifact.is_absolute() else project.data_root/artifact
 try:info=json.loads((artifact/"model.json").read_text(encoding="utf8"))
 except (OSError,json.JSONDecodeError):info={}
 return tuple(map(int,info.get("input_size") or model.get("input_size") or fallback))
def create_ema_inference_checkpoint(backend,source_checkpoint,output_checkpoint):
 result=backend._invoke("ema_inference_checkpoint",{"source_checkpoint":str(source_checkpoint),"output_checkpoint":str(output_checkpoint)})
 path=Path(result.get("output_checkpoint",output_checkpoint))
 if result.get("status")!="ok" or not path.is_file() or path.stat().st_size<=0:raise RTMPoseRuntimeError("EMA inference checkpoint conversion failed")
 return path
def evaluate_epoch_checkpoint(project,dataset_manifest,config_path,epoch_checkpoint,input_size,device):
 """Evaluate one source epoch through a temporary verified EMA inference checkpoint."""
 import tempfile
 from .landmark_qc import evaluate_dataset_split
 source=Path(epoch_checkpoint);temporary=Path(tempfile.mkdtemp(prefix="simm_ema_epoch_"))/f"{source.stem}_ema_inference.pth"
 try:
  spec=RTMPoseModelSpec("epoch_validation",schema_hash(project.schema_path),Path(config_path),source,tuple(input_size),device);runner=RTMPoseBackend(spec)
  converted=create_ema_inference_checkpoint(runner,source,temporary)
  evaluator=RTMPoseBackend(RTMPoseModelSpec("epoch_validation",schema_hash(project.schema_path),Path(config_path),converted,tuple(input_size),device))
  try: metrics=evaluate_dataset_split(project,dataset_manifest,evaluator,split="validation")
  except Exception as first_error:
   try: metrics=evaluate_dataset_split(project,dataset_manifest,evaluator,split="validation")
   except Exception as second_error: raise RTMPoseRuntimeError(f"epoch checkpoint rank failed twice for {source.name}; first attempt: {first_error}; second attempt: {second_error}") from second_error
  import re
  epoch=int(re.search(r"epoch_(\d+)",source.stem).group(1));return {"epoch":epoch,"median_error_percent":metrics["median_error_percent"],"p90_error_percent":metrics["p90_error_percent"],"p95_error_percent":metrics["p95_error_percent"]}
 finally:
  import shutil;shutil.rmtree(temporary.parent,ignore_errors=True)
def select_best_epoch(project,dataset_manifest,config_path,checkpoint_dir,input_size,device,*,backend=None,progress_path=None,progress_callback=None):
 import re
 paths=sorted(Path(checkpoint_dir).glob("epoch_*.pth"),key=lambda p:int(re.search(r"epoch_(\d+)",p.stem).group(1)))
 if not paths:raise RTMPoseRuntimeError("no saved epoch checkpoints")
 state={}
 if progress_path and Path(progress_path).is_file():
  try:state=json.loads(Path(progress_path).read_text(encoding="utf8"))
  except (OSError,json.JSONDecodeError):state={}
 stored={int(item["epoch"]):item for item in state.get("validation_by_epoch",()) if all(key in item for key in ("epoch","median_error_percent","p90_error_percent","p95_error_percent"))}
 values=[]
 missing=[]
 for path in paths:
  epoch=int(re.search(r"epoch_(\d+)",path.stem).group(1))
  if epoch not in stored:missing.append(path)
 # The new runtime operation preserves the exact metric calculations but
 # removes repeated Python/MMPose startup and immutable-manifest parsing.
 if missing and isinstance(backend,RTMPoseBackend):
  try:
   from .landmark_qc import dataset_split_records,dataset_split_metrics
   expected,digest,records=dataset_split_records(project,dataset_manifest,split="validation")
   if digest!=backend.schema_sha256:raise RTMPoseRuntimeError("dataset schema does not match finalization backend")
   predictions=backend.predict_readonly_checkpoints([record[3] for record in records],missing,progress_callback=(lambda done,total: progress_callback("VALIDATING CHECKPOINTS",done,total)) if progress_callback else None)
   for path in missing:
    epoch=int(re.search(r"epoch_(\d+)",path.stem).group(1))
    metrics=dataset_split_metrics(records,expected,predictions[str(path)],model_id=backend.model_id,split="validation")
    stored[epoch]={"epoch":epoch,"median_error_percent":metrics["median_error_percent"],"p90_error_percent":metrics["p90_error_percent"],"p95_error_percent":metrics["p95_error_percent"]}
   if progress_path:
    state["stage"]="VALIDATING CHECKPOINTS";state["validation_by_epoch"]=[stored[key] for key in sorted(stored)];atomic_json_write(Path(progress_path),state)
  except Exception:
   # A compatible older/external runtime retains the verified serial path.
   # Nothing is marked complete until it has actually been evaluated.
   pass
 for index,path in enumerate(paths,1):
  epoch=int(re.search(r"epoch_(\d+)",path.stem).group(1));value=stored.get(epoch)
  if value is None:
   value=evaluate_epoch_checkpoint(project,dataset_manifest,config_path,path,input_size,device);stored[epoch]=value
   if progress_path:
    state["stage"]="VALIDATING CHECKPOINTS";state["validation_by_epoch"]=[stored[key] for key in sorted(stored)];atomic_json_write(Path(progress_path),state)
  values.append(value)
  if progress_callback:progress_callback("VALIDATING CHECKPOINTS",index,len(paths))
 best=min(values,key=lambda item:(item["p95_error_percent"],item["p90_error_percent"],item["median_error_percent"]))
 if progress_path:
  state["stage"]="SELECTING BEST EPOCH";state["best_epoch"]=best["epoch"];state["best_metrics"]=best;state["validation_by_epoch"]=[stored[key] for key in sorted(stored)];atomic_json_write(Path(progress_path),state)
 return {"best_epoch":best["epoch"],"best_metrics":best,"validation_by_epoch":values}
def _finalization_path(artifact): return Path(artifact)/"finalization.json"
def _read_finalization(artifact):
 try:return json.loads(_finalization_path(artifact).read_text(encoding="utf8"))
 except (OSError,json.JSONDecodeError):return {}
def _write_finalization(artifact,state): atomic_json_write(_finalization_path(artifact),state)
def _prune_completed_training_checkpoints(artifact,state):
 """Remove only intermediate training checkpoints after a verified final model exists.

 Validation metrics and lineage stay in finalization/model metadata; the portable
 EMA checkpoint used by inference and by child-model training is always retained.
 Cleanup is best-effort so a filesystem lock can never turn a valid trained model
 into a failed training run.
 """
 artifact=Path(artifact);result=state.get("result") or {}
 if state.get("stage")!="COMPLETE" or not state.get("registered"):
  return {"pruned":False,"reason":"finalization_incomplete","removed_files":[],"removed_bytes":0}
 final=artifact/"best_engineering_validation.pth";portable=artifact/"inference_config.py";legacy_config=artifact/"config.py";model_json=artifact/"model.json"
 usable_config=portable if portable.is_file() and portable.stat().st_size>0 else legacy_config if legacy_config.is_file() and legacy_config.stat().st_size>0 else None
 if not final.is_file() or final.stat().st_size<=0 or usable_config is None or not model_json.is_file():
  return {"pruned":False,"reason":"portable_model_incomplete","removed_files":[],"removed_bytes":0}
 expected=str(result.get("checkpoint_sha256") or "").lower()
 if not expected or __import__("hashlib").sha256(final.read_bytes()).hexdigest()!=expected:
  return {"pruned":False,"reason":"final_checkpoint_checksum_unverified","removed_files":[],"removed_bytes":0}
 candidates=list(sorted(artifact.glob("epoch_*.pth"),key=lambda path:path.name))
 for name in ("latest.pth","last_checkpoint"):
  path=artifact/name
  if path.exists() or path.is_symlink():candidates.append(path)
 removed=[];removed_bytes=0;errors=[]
 for path in candidates:
  try:
   size=path.stat().st_size if path.is_file() else 0
   path.unlink(missing_ok=True);removed.append(path.name);removed_bytes+=size
  except OSError as exc:errors.append({"file":path.name,"error":str(exc)})
 retention={"pruned":not errors,"reason":"completed_model_retention","removed_files":removed,"removed_bytes":removed_bytes,"errors":errors,"retained_checkpoint":final.name,"retained_config":usable_config.name,"validation_metrics_retained":bool(result.get("validation_by_epoch"))}
 state["retention"]=retention;_write_finalization(artifact,state)
 return retention
def _finalize_trained_artifact(project,artifact,backend,state,progress_callback=None):
 manifest=Path(state["dataset_manifest"]);config_path=state["config_path"]
 if progress_callback:progress_callback("VALIDATING CHECKPOINTS",len(state.get("validation_by_epoch",())),len(list(Path(artifact).glob("epoch_*.pth"))))
 selection=select_best_epoch(project,manifest,config_path,artifact,backend.spec.input_size,state.get("device",backend.spec.device),backend=backend,progress_path=_finalization_path(artifact),progress_callback=progress_callback)
 state=_read_finalization(artifact);state.update({"stage":"CREATING FINAL EMA CHECKPOINT","best_epoch":selection["best_epoch"],"best_metrics":selection["best_metrics"]});_write_finalization(artifact,state)
 if progress_callback:progress_callback("CREATING FINAL EMA CHECKPOINT",0,0)
 final=Path(artifact)/"best_engineering_validation.pth"
 if not final.is_file() or final.stat().st_size<=0: final=create_ema_inference_checkpoint(backend,Path(artifact)/f"epoch_{selection['best_epoch']}.pth",final)
 portable_config=Path(artifact)/"inference_config.py"
 backend._invoke("export_inference_config",{"config_path":str(config_path),"output_path":str(portable_config)})
 if not portable_config.is_file() or portable_config.stat().st_size<=0:raise RTMPoseRuntimeError("portable inference config was not created")
 portable_sha=__import__("hashlib").sha256(portable_config.read_bytes()).hexdigest()
 result=dict(state.get("training_result",{}));result.update({"checkpoint_path":str(final),"best_epoch":selection["best_epoch"],"engineering_validation":selection["best_metrics"],"validation_by_epoch":selection["validation_by_epoch"],"ema_used":True,"checkpoint_sha256":__import__("hashlib").sha256(final.read_bytes()).hexdigest(),"inference_config":"inference_config.py","inference_config_sha256":portable_sha})
 state.update({"stage":"REGISTERING MODEL","result":result});_write_finalization(artifact,state)
 if progress_callback:progress_callback("REGISTERING MODEL",0,0)
 environment_path=Path(artifact)/"environment.json"
 if environment_path.is_file(): environment=json.loads(environment_path.read_text(encoding="utf8"))
 else: environment=backend._invoke("info",{});atomic_json_write(environment_path,environment)
 base_sha=__import__("hashlib").sha256(backend.spec.checkpoint_path.read_bytes()).hexdigest();model={"model_id":backend.model_id,"backend":"rtmpose","schema_sha256":backend.schema_sha256,"dataset_id":state["dataset_id"],"dataset_manifest":str(manifest.relative_to(project.data_root).as_posix()),"parent_model_id":state.get("parent_model_id"),"input_size":list(backend.spec.input_size),"smoke":bool(state.get("settings",{}).get("smoke",True)),"base_checkpoint_path":str(backend.spec.checkpoint_path),"base_checkpoint_sha256":base_sha,"parent_checkpoint_path":state.get("settings",{}).get("parent_checkpoint"),"result":result,"model_info":backend.model_info(),"training_settings":state.get("settings",{}),"hardware":state.get("settings",{}).get("hardware")}
 atomic_json_write(Path(artifact)/"model.json",model)
 if not project.model_metadata(backend.model_id): project.register_model(backend.model_id,"landmark",path=str(Path(artifact).relative_to(project.data_root).as_posix()),metrics=model,schema_digest=backend.schema_sha256,dataset_id=state["dataset_id"],parent_model_id=state.get("parent_model_id"),dataset_manifest_path=str(manifest.relative_to(project.data_root).as_posix()))
 state.update({"stage":"COMPLETE","registered":True});_write_finalization(artifact,state);_prune_completed_training_checkpoints(artifact,state)
 return model
def pending_finalization_artifact(project):
 artifacts=Path(project.data_root)/"ai"/"models"
 pending=[]
 for artifact in artifacts.glob("rtmpose_v*") if artifacts.is_dir() else ():
  state=_read_finalization(artifact)
  if state.get("training_completed") and not state.get("registered"):pending.append((artifact,state))
 return max(pending,key=lambda item:item[0].stat().st_mtime) if pending else None
def train_project(project,dataset_id,backend:RTMPoseBackend,*,parent_model_id=None,settings=None,progress_callback=None):
 """Train from a verified immutable snapshot and register one immutable model artifact."""
 manifest=dataset_manifest_path(project,dataset_id);verified=verify_dataset(project,manifest)
 if not verified['ok']: raise RTMPoseRuntimeError('immutable dataset is not valid: '+', '.join(verified['errors']))
 if backend.schema_sha256!=__import__('app.project_storage',fromlist=['schema_hash']).schema_hash(project.schema_path): raise RTMPoseRuntimeError('RTMPose model schema does not match current landmark_schema.csv')
 artifact=project.data_root/'ai'/'models'/backend.model_id
 if artifact.exists():
  state=_read_finalization(artifact)
  if state.get('training_completed') and not state.get('registered'): return _finalize_trained_artifact(project,artifact,backend,state,progress_callback)
  raise FileExistsError(f'immutable model artifact already exists: {backend.model_id}')
 artifact.mkdir(parents=True);settings=dict(settings or {})
 if parent_model_id:
  parent=project.model_metadata(parent_model_id)
  if not parent: raise RTMPoseRuntimeError(f'parent model is unavailable: {parent_model_id}')
  if not landmark_model_schema_compatible(project,parent): raise RTMPoseRuntimeError('parent model landmark identities/order do not match current landmark_schema.csv')
  parent_dir=Path(parent['path']);parent_dir=parent_dir if parent_dir.is_absolute() else project.data_root/parent_dir
  parent_checkpoint=_resolve_parent_checkpoint(parent_dir)
  parent_size=_model_input_size(project,parent)
  if tuple(parent_size)==tuple(backend.spec.input_size) and not settings.get('force_backbone_only_init'):settings.setdefault('parent_checkpoint',str(parent_checkpoint))
  else:
   init=artifact/'backbone_only_init.pth';settings['backbone_checkpoint']=str(create_backbone_only_checkpoint(backend,parent_checkpoint,init,parent_model_id));settings['cross_resolution_init']='backbone_only';settings['parent_checkpoint']=None
 def write_training_config(batch, filename):
  return generate_smoke_config(manifest,data_root=project.data_root,train_coco=artifact/'train.coco.json',val_coco=artifact/'val.coco.json',output_path=artifact/filename,base_config=backend.spec.config_path,base_checkpoint=backend.spec.checkpoint_path,batch_size=batch,workers=settings.get('workers',0),mixed_precision=settings.get('mixed_precision',False),device=settings.get('device',backend.spec.device),pin_memory=settings.get('pin_memory'),persistent_workers=settings.get('persistent_workers'),max_epochs=settings.get('max_epochs',1),checkpoint_interval=settings.get('checkpoint_interval',1),max_keep_ckpts=settings.get('max_keep_ckpts',1),parent_checkpoint=settings.get('parent_checkpoint'),input_size=backend.spec.input_size,backbone_checkpoint=settings.get('backbone_checkpoint'),photometric_augmentation=bool(settings.get('photometric_augmentation',False)))
 batch=max(1,int(settings.get('batch_size',1)))
 if not settings.get('config_path'):settings['config_path']=str(write_training_config(batch,'config.py'))
 export_coco(manifest,artifact/'train.coco.json',splits=('train',)); export_coco(manifest,artifact/'val.coco.json',splits=('validation',))
 attempted_batches=[]
 while True:
  attempted_batches.append(batch)
  if progress_callback:progress_callback("TRAINING",f"Training {backend.model_id}: batch {batch}, workers {int(settings.get('workers',0))}")
  try:
   result=backend.train(manifest,artifact,parent_model_id=parent_model_id,settings=settings)
   break
  except RTMPoseRuntimeError as exc:
   from .ai_hardware import is_cuda_oom
   if not is_cuda_oom(exc) or batch<=1:raise
   next_batch=max(1,batch//2)
   for checkpoint in artifact.glob('epoch_*.pth'):checkpoint.unlink(missing_ok=True)
   for name in ('latest.pth','last_checkpoint'):
    (artifact/name).unlink(missing_ok=True)
   batch=next_batch;settings['batch_size']=batch
   settings['config_path']=str(write_training_config(batch,f'config_runtime_batch_{batch}.py'))
   if progress_callback:progress_callback("TRAINING",f"CUDA memory limit reached; retrying safely with batch {batch}")
 if len(attempted_batches)>1:
  from .performance_engine import PerformanceCache
  cache_saved=PerformanceCache(project).record_runtime_fallback(settings.get('tuning_key'),attempted_batches[0],batch)
  settings['runtime_batch_fallback']={'attempted_batches':attempted_batches,'effective_batch_size':batch,'cache_saved':cache_saved}
  from .ai_hardware import _write_autotune_diagnostic
  _write_autotune_diagnostic({'stage':'runtime_fallback','workload':'landmark_training','tuning_key':settings.get('tuning_key'),'hardware':settings.get('hardware'),'attempted_batches':attempted_batches,'effective_batch_size':batch,'cache_saved':cache_saved,'reason':'CUDA out of memory during actual training'})
  if progress_callback:progress_callback('TRAINING',f'Batch {batch} completed after CUDA memory retry. '+('Cache saved.' if cache_saved else 'Cache could not be saved.'))
 state={'training_completed':True,'stage':'VALIDATING CHECKPOINTS','model_id':backend.model_id,'dataset_id':dataset_id,'dataset_manifest':str(manifest),'parent_model_id':parent_model_id,'settings':settings,'config_path':settings['config_path'],'device':settings.get('device',backend.spec.device),'training_result':result,'validation_by_epoch':[]};_write_finalization(artifact,state)
 if progress_callback:progress_callback("VALIDATING CHECKPOINTS",0,len(list(artifact.glob("epoch_*.pth"))))
 return _finalize_trained_artifact(project,artifact,backend,state,progress_callback)
