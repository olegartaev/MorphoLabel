"""Runs inside ai_runtime only. Reads one JSON request from stdin and emits one JSON response."""
from __future__ import annotations
import gc,json,sys,subprocess,time
from pathlib import Path

class _TrainingProbeDataset:
 """Read-only standardized-image source for a bounded training throughput probe."""
 def __init__(self, paths, width, height, samples):
  self.paths=tuple(paths);self.width=int(width);self.height=int(height);self.samples=max(1,int(samples))
 def __len__(self): return self.samples
 def __getitem__(self,index):
  import numpy as np
  import torch
  from PIL import Image
  path=self.paths[index % len(self.paths)]
  with Image.open(path) as image:
   rgb=image.convert('RGB').resize((self.width,self.height))
   array=np.asarray(rgb,dtype=np.float32).copy()/255.0
  return torch.from_numpy(array).permute(2,0,1)

def _managed_component_root():
 """Locate a managed component by its own manifest instead of directory shape."""
 executable=Path(sys.executable).resolve()
 for candidate in executable.parents:
  manifest=candidate/"component.json"
  if not manifest.is_file():continue
  try:
   meta=json.loads(manifest.read_text(encoding="utf-8"))
   relative=str(meta.get("python_relative_path") or "python.exe")
   if (candidate/relative).resolve()==executable:return candidate
  except (OSError,ValueError,TypeError,json.JSONDecodeError):
   continue
 return None

def resolve_mmpose_training_source():
 """Resolve MMPose source beside the active runtime, then local fallback."""
 executable=Path(sys.executable).resolve()
 runtime_root=_managed_component_root() or executable.parent.parent
 repo_root=Path(__file__).resolve().parents[1]
 candidates=(runtime_root / "vendor" / "mmpose", repo_root / "ai_runtime" / "vendor" / "mmpose")
 checked=[]
 for source in candidates:
  checked.append(str(source))
  if (source / "tools" / "train.py").is_file() and source.is_dir(): return source
 raise RuntimeError("RTMPose MMPose training source unavailable; checked: " + "; ".join(checked))

def stream_training_process(command, log_path, *, cwd):
 """Run MMEngine unbuffered and make its output visible before it exits."""
 tail=[]
 with open(log_path,'w',encoding='utf-8',buffering=1) as log_file:
  process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,cwd=str(cwd))
  for line in iter(process.stdout.readline,''):
   log_file.write(line);log_file.flush();tail.append(line)
   if len(tail)>200:tail.pop(0)
  process.stdout.close();returncode=process.wait()
 return returncode,''.join(tail)

_LEGACY_INFERENCE_IMPORTS=("rtmpose_augmentations",)

def _load_inference_config(config_loader, config_path):
 """Load old MorphoLabel/SIMM configs without requiring training-only augmentations."""
 try:
  return config_loader.fromfile(config_path)
 except ImportError as exc:
  missing=next((name for name in _LEGACY_INFERENCE_IMPORTS if name in str(exc)),None)
  if missing is None:raise
  import types
  previous=sys.modules.get(missing)
  inserted=previous is None
  if inserted:sys.modules[missing]=types.ModuleType(missing)
  try:cfg=config_loader.fromfile(config_path)
  finally:
   if inserted:sys.modules.pop(missing,None)
  # The legacy module only registered training-time augmentation transforms.
  # Inference must not retain the obsolete import requirement after loading.
  try:cfg["custom_imports"]=None
  except (TypeError,KeyError):pass
  return cfg

def prepare_inference_config(config_path, *, config_loader=None):
 """Provide MMPose an inference dataloader even for legacy training configs."""
 if config_loader is None:
  from mmengine.config import Config as config_loader
 cfg=_load_inference_config(config_loader,config_path)
 if cfg.get("test_dataloader") is None:
  dataset=cfg.train_dataloader.dataset.copy()
  dataset["pipeline"]=cfg.val_pipeline
  cfg.test_dataloader=dict(dataset=dataset)
 return cfg

def _configure_inference_runtime(device):
 import torch
 if str(device).startswith("cuda") and torch.cuda.is_available():
  # Fixed SIMM input shapes benefit from cuDNN autotuning.  Keep precision
  # policy unchanged; batch benchmarking below still verifies output equality.
  torch.backends.cudnn.benchmark=True


def inference_model(request):
 _configure_inference_runtime(request.get("device","cuda:0"))
 from mmpose.apis import init_model
 return init_model(prepare_inference_config(request["config_path"]),request["checkpoint_path"],device=request.get("device","cuda:0"))
def _is_cuda_oom(error):
 text=str(error).lower()
 return 'out of memory' in text or 'cuda oom' in text or 'cublas_status_alloc_failed' in text

def rank_inference_batches(model, requests, landmark_ids, batch_size, emit_progress, *, prefetch_workers=None, prefetch_depth=None):
 """Run ordered MMPose batches with bounded CPU preprocessing overlap.

 At most two not-yet-inferred batches are prepared.  Each worker owns its
 Compose instance, so transforms never share mutable state across threads.
 """
 import os
 import threading
 from collections import deque
 from concurrent.futures import ThreadPoolExecutor
 import numpy as np
 import torch
 from PIL import Image
 from mmengine.dataset import Compose,pseudo_collate
 from mmengine.registry import init_default_scope
 scope=model.cfg.get('default_scope','mmpose')
 if scope is not None:init_default_scope(scope)
 pipeline_spec=model.cfg.test_dataloader.dataset.pipeline
 default_workers=max(1,min(4,max(1,(os.cpu_count() or 2)//2)))
 serial_prefetch=prefetch_workers == 0
 worker_count=1 if serial_prefetch else max(1,int(prefetch_workers or default_workers))
 prefetch_depth=1 if serial_prefetch else max(1,min(4,int(prefetch_depth or 2)))
 worker_local=threading.local()
 timings={'image_open_seconds':0.0,'pipeline_seconds':0.0,'preprocess_wait_seconds':0.0,'inference_seconds':0.0,'postprocess_seconds':0.0,'batches':0,'prefetch_workers':0 if serial_prefetch else worker_count}
 def prepare_batch(items):
  if not hasattr(worker_local,'pipeline'):worker_local.pipeline=Compose(pipeline_spec)
  pipeline=worker_local.pipeline;data_list=[];local={'image_open_seconds':0.0,'pipeline_seconds':0.0}
  for item in items:
   started=time.perf_counter()
   with Image.open(item['image_path']) as image:w,h=image.size
   local['image_open_seconds']+=time.perf_counter()-started
   data_info={'img_path':item['image_path'],'bbox':np.array([[0,0,w,h]],dtype=np.float32),'bbox_score':np.ones(1,dtype=np.float32)}
   data_info.update(model.dataset_meta)
   started=time.perf_counter();data_list.append(pipeline(data_info));local['pipeline_seconds']+=time.perf_counter()-started
  return data_list,local
 total=len(requests);cursor=0;effective=max(1,int(batch_size));results=[]
 executor=ThreadPoolExecutor(max_workers=worker_count,thread_name_prefix='rtmpose-prep')
 pending=deque();next_cursor=0
 def schedule():
  nonlocal next_cursor
  while len(pending)<prefetch_depth and next_cursor<total:
   size=min(effective,total-next_cursor);items=requests[next_cursor:next_cursor+size]
   pending.append((next_cursor,items,executor.submit(prepare_batch,items)));next_cursor+=size
 try:
  schedule()
  while cursor<total:
   position,items,future=pending.popleft()
   if position!=cursor:raise RuntimeError('RTMPose rank prefetch order changed')
   started=time.perf_counter();data_list,prepared=future.result();timings['preprocess_wait_seconds']+=time.perf_counter()-started
   timings['image_open_seconds']+=prepared['image_open_seconds'];timings['pipeline_seconds']+=prepared['pipeline_seconds']
   if prefetch_depth>1:schedule()
   size=len(items)
   try:
    if torch.cuda.is_available():torch.cuda.synchronize()
    started=time.perf_counter()
    with torch.inference_mode():outputs=model.test_step(pseudo_collate(data_list))
    if torch.cuda.is_available():torch.cuda.synchronize()
    timings['inference_seconds']+=time.perf_counter()-started;timings['batches']+=1
   except RuntimeError as exc:
    if _is_cuda_oom(exc) and size>1:
     gc.collect()
     if torch.cuda.is_available():torch.cuda.empty_cache()
     effective=max(1,size//2);next_cursor=cursor;pending.clear();schedule();continue
    raise
   if len(outputs)!=size:raise RuntimeError(f'RTMPose rank batch returned {len(outputs)} results for {size} images')
   started=time.perf_counter()
   for item,data in zip(items,outputs):
    prediction=data.pred_instances;points=prediction.keypoints[0];scores=prediction.keypoint_scores[0]
    results.append({'image_id':item['image_id'],'landmarks':[{'landmark_id':int(i),'x':float(x),'y':float(y),'confidence':float(score)} for i,(x,y),score in zip(landmark_ids,points,scores)]})
   timings['postprocess_seconds']+=time.perf_counter()-started
   cursor+=size;emit_progress(cursor,total)
   if prefetch_depth==1:schedule()
 finally:
  executor.shutdown(wait=True,cancel_futures=True)
 return results,effective,timings
def export_portable_inference_config(config_path, output_path):
 """Flatten a training config into a model-only inference config with no project paths."""
 from copy import deepcopy
 from mmengine.config import Config
 cfg=Config.fromfile(config_path)
 model=deepcopy(cfg.model)
 try:
  if model.get('init_cfg') is not None:model['init_cfg']=None
  backbone=model.get('backbone')
  if isinstance(backbone,dict) and backbone.get('init_cfg') is not None:backbone['init_cfg']=None
 except AttributeError:pass
 train_dataset=cfg.train_dataloader.dataset
 metainfo=deepcopy(train_dataset.get('metainfo',cfg.get('metainfo',{})))
 pipeline=deepcopy(cfg.get('val_pipeline') or train_dataset.get('pipeline') or [])
 dataset=dict(type='CocoDataset',data_mode='topdown',metainfo=metainfo,pipeline=pipeline)
 portable=Config(dict(
  default_scope=cfg.get('default_scope','mmpose'),
  model=model,
  train_dataloader=dict(dataset=deepcopy(dataset)),
  test_dataloader=dict(dataset=deepcopy(dataset)),
  val_pipeline=deepcopy(pipeline),
 ))
 target=Path(output_path).resolve();target.parent.mkdir(parents=True,exist_ok=True);portable.dump(str(target))
 # Re-open what was written so a broken serialization never enters a model artifact.
 check=Config.fromfile(str(target))
 if check.get('model') is None or check.get('test_dataloader') is None:
  raise RuntimeError('portable inference config is incomplete')
 return target

def main():
 operation=sys.argv[1] if len(sys.argv)>1 else ''; request=json.load(sys.stdin)
 if operation=='export_inference_config':
  target=export_portable_inference_config(request['config_path'],request['output_path']);print(json.dumps({'status':'ok','config_path':str(target)}));return
 if operation=='predict':
  from mmpose.apis import inference_topdown
  model=inference_model(request)
  image=request['image_path'];from PIL import Image
  with Image.open(image) as im:w,h=im.size
  data=inference_topdown(model,image,bboxes=[[0,0,w,h]],bbox_format='xyxy')[0].pred_instances
  points=data.keypoints[0];scores=data.keypoint_scores[0];ids=request.get('simm_landmark_ids') or list(range(1,len(points)+1))
  out={'image_id':request['image_id'],'model_id':request['model_id'],'schema_sha256':request['schema_sha256'],'landmarks':[{'landmark_id':int(i),'x':float(x),'y':float(y),'confidence':float(s)} for i,(x,y),s in zip(ids,points,scores)]};print(json.dumps(out));return
 if operation=='rank':
  import torch
  if str(request.get('device','')).startswith('cuda') and torch.cuda.is_available():
   torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats()
  init_started=time.perf_counter();model=inference_model(request);model_init_seconds=time.perf_counter()-init_started
  ids=request.get('simm_landmark_ids') or []
  requests=request.get('requests',[]);total=len(requests);requested_batch=max(1,int(request.get('batch_size',1)))
  print(f'RANK_PROGRESS 0 {total}',file=sys.stderr,flush=True)
  def emit_progress(done,all_items):print(f'RANK_PROGRESS {done} {all_items}',file=sys.stderr,flush=True)
  rank_started=time.perf_counter();results,effective_batch,timings=rank_inference_batches(model,requests,ids,requested_batch,emit_progress,prefetch_workers=request.get('prefetch_workers'),prefetch_depth=request.get('prefetch_depth'));timings['rank_seconds']=time.perf_counter()-rank_started;timings['model_init_seconds']=model_init_seconds
  peak_vram_mib=int(torch.cuda.max_memory_allocated()/1024/1024) if torch.cuda.is_available() else None
  print(json.dumps({'model_id':request['model_id'],'schema_sha256':request['schema_sha256'],'results':results,'effective_batch_size':effective_batch,'peak_vram_mib':peak_vram_mib,'timing':timings}));return
 if operation=='rank_checkpoints':
  # Engineering validation keeps one Python/MMPose model alive while loading
  # each saved EMA state. The point pipeline is identical to ``rank``.
  import torch
  from pathlib import Path
  paths=[Path(value) for value in request.get('checkpoint_paths',())]
  if not paths:raise SystemExit('rank_checkpoints requires at least one checkpoint')
  if str(request.get('device','')).startswith('cuda') and torch.cuda.is_available():
   torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats()
  def ema_state(source):
   raw=torch.load(source,map_location='cpu',weights_only=False);state=raw.get('state_dict');ema=raw.get('ema_state_dict')
   if not isinstance(state,dict) or not isinstance(ema,dict) or 'steps' not in ema:raise SystemExit(f'checkpoint lacks required EMA state: {source}')
   normalized={}
   for key,value in ema.items():
    if key=='steps':continue
    if not str(key).startswith('module.'):raise SystemExit(f'invalid EMA key in {source}: {key}')
    normalized[str(key)[7:]]=value
   if set(normalized)!=set(state):raise SystemExit('EMA/model key mismatch in '+str(source))
   for key in state:
    if not torch.is_tensor(state[key]) or not torch.is_tensor(normalized[key]) or state[key].shape!=normalized[key].shape or state[key].dtype!=normalized[key].dtype:raise SystemExit(f'EMA tensor mismatch in {source}: {key}')
   return normalized
  init_started=time.perf_counter();model=inference_model({**request,'checkpoint_path':str(paths[0])});model_init_seconds=time.perf_counter()-init_started
  ids=request.get('simm_landmark_ids') or [];requests=request.get('requests',[]);total=len(requests);batch=max(1,int(request.get('batch_size',1)));all_results=[]
  print(f'RANK_PROGRESS 0 {max(1,total*len(paths))}',file=sys.stderr,flush=True)
  for index,path in enumerate(paths,1):
   model.load_state_dict(ema_state(path),strict=True);model.eval()
   def emit_progress(done,all_items,base=(index-1)*total):print(f'RANK_PROGRESS {base+done} {max(1,total*len(paths))}',file=sys.stderr,flush=True)
   started=time.perf_counter();results,effective,timing=rank_inference_batches(model,requests,ids,batch,emit_progress,prefetch_workers=request.get('prefetch_workers'),prefetch_depth=request.get('prefetch_depth'));timing['rank_seconds']=time.perf_counter()-started
   all_results.append({'checkpoint_path':str(path),'results':results,'effective_batch_size':effective,'timing':timing})
  peak_vram_mib=int(torch.cuda.max_memory_allocated()/1024/1024) if torch.cuda.is_available() else None
  print(json.dumps({'model_id':request['model_id'],'schema_sha256':request['schema_sha256'],'model_init_seconds':model_init_seconds,'checkpoints':all_results,'peak_vram_mib':peak_vram_mib}));return
 if operation=='rank_benchmark':
  import torch
  if str(request.get('device','')).startswith('cuda') and torch.cuda.is_available():torch.cuda.empty_cache()
  init_started=time.perf_counter();model=inference_model(request);model_init_seconds=time.perf_counter()-init_started
  ids=request.get('simm_landmark_ids') or [];requests=request.get('requests',[]);total=len(requests)
  requested=[max(1,int(value)) for value in request.get('batch_sizes',(1,2,4,8,16,32,64))]
  supplied=request.get('candidates') or ()
  candidates=[{'batch_size':max(1,int(item.get('batch_size',1))),'prefetch_workers':item.get('prefetch_workers'),'prefetch_depth':item.get('prefetch_depth')} for item in supplied] if supplied else [{'batch_size':value,'prefetch_workers':None,'prefetch_depth':None} for value in dict.fromkeys([1]+[value for value in requested if value<=max(1,total)])]
  tolerance=float(request.get('coordinate_tolerance',0.001))
  print(f'RANK_PROGRESS 0 {total}',file=sys.stderr,flush=True)
  def heartbeat(done,all_items):print(f'RANK_PROGRESS {done} {all_items}',file=sys.stderr,flush=True)
  def output_delta(reference,candidate):
   if [row['image_id'] for row in reference] != [row['image_id'] for row in candidate]:raise RuntimeError('RTMPose batch benchmark changed image order')
   maximum=0.0
   for first,second in zip(reference,candidate):
    if [point['landmark_id'] for point in first['landmarks']] != [point['landmark_id'] for point in second['landmarks']]:raise RuntimeError('RTMPose batch benchmark changed landmark order')
    for left,right in zip(first['landmarks'],second['landmarks']):
     maximum=max(maximum,abs(left['x']-right['x']),abs(left['y']-right['y']),abs(left['confidence']-right['confidence']))
   return maximum
  # Prime the model once, then warm each candidate's own batch/preprocess
  # shape before timing so the first candidate gets no cuDNN advantage.
  if total:rank_inference_batches(model,requests[:min(2,total)],ids,1,lambda *_:None,prefetch_workers=0,prefetch_depth=1)
  rows=[];best=None;reference=None
  def measure(config):
   batch=max(1,int(config['batch_size']))
   if torch.cuda.is_available():torch.cuda.empty_cache()
   warm=requests[:min(total,max(2,batch))]
   _,warm_effective,_=rank_inference_batches(model,warm,ids,batch,lambda *_:None,prefetch_workers=config.get('prefetch_workers'),prefetch_depth=config.get('prefetch_depth'))
   if warm_effective!=batch:raise RuntimeError(f'CUDA OOM fallback to batch {warm_effective}')
   if torch.cuda.is_available():torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
   rank_started=time.perf_counter()
   candidate,effective,timing=rank_inference_batches(model,requests,ids,batch,heartbeat,prefetch_workers=config.get('prefetch_workers'),prefetch_depth=config.get('prefetch_depth'))
   if torch.cuda.is_available():torch.cuda.synchronize()
   timing['rank_seconds']=time.perf_counter()-rank_started
   return candidate,effective,timing
  def record(config,candidate,effective,timing):
   delta=0.0 if reference is None else output_delta(reference,candidate)
   elapsed=max(float(timing['rank_seconds']),1e-9);equivalent=delta<=tolerance and effective==int(config['batch_size'])
   return {'batch_size':int(config['batch_size']),'prefetch_workers':config.get('prefetch_workers'),'prefetch_depth':config.get('prefetch_depth'),'effective_batch_size':effective,'preprocess_seconds':float(timing['pipeline_seconds']),'preprocess_wait_seconds':float(timing.get('preprocess_wait_seconds',0.0)),'inference_seconds':float(timing['inference_seconds']),'rank_seconds':elapsed,'images_per_second':total/elapsed,'peak_vram_mib':int(torch.cuda.max_memory_allocated()/1024/1024) if torch.cuda.is_available() else None,'max_output_delta':delta,'scientifically_equivalent':equivalent}
  def try_candidate(config):
   nonlocal best,reference
   try:
    candidate,effective,timing=measure(config)
    row=record(config,candidate,effective,timing)
    if reference is None and effective==int(config['batch_size']):reference=candidate
    rows.append(row)
    if row['scientifically_equivalent'] and (best is None or row['images_per_second']>best['images_per_second']):best=row
   except Exception as exc:
    rows.append({'batch_size':int(config['batch_size']),'prefetch_workers':config.get('prefetch_workers'),'prefetch_depth':config.get('prefetch_depth'),'scientifically_equivalent':False,'error':f'{type(exc).__name__}: {exc}'})
    if torch.cuda.is_available():torch.cuda.empty_cache()
  for config in candidates:
   try_candidate(config)
  # Stage 2 compares a compact preprocessing set at the best batch. Startup
  # is warmed per candidate, so this measures steady-state overlap.
  if not supplied and best is not None:
   worker_values=list(dict.fromkeys(max(0,int(value)) for value in request.get('prefetch_worker_candidates',(0,2,4))))[:4]
   depth_values=list(dict.fromkeys(max(1,int(value)) for value in request.get('prefetch_depth_candidates',(1,2))))[:2]
   best_batch=max(1,int(best['effective_batch_size']))
   seen={(row['batch_size'],row.get('prefetch_workers'),row.get('prefetch_depth')) for row in rows if 'batch_size' in row}
   for workers in worker_values:
    for depth in depth_values:
     if workers==0 and depth!=depth_values[0]:continue
     config={'batch_size':best_batch,'prefetch_workers':workers,'prefetch_depth':depth}
     key=(best_batch,workers,depth)
     if key in seen:continue
     try_candidate(config);seen.add(key)
  if best is None:
   best={'effective_batch_size':1,'prefetch_workers':0,'prefetch_depth':1,'images_per_second':0.0}
  print(json.dumps({'model_id':request['model_id'],'schema_sha256':request['schema_sha256'],'model_init_seconds':model_init_seconds,'coordinate_tolerance':tolerance,'selected_batch_size':best['effective_batch_size'],'selected_config':{'batch_size':best['effective_batch_size'],'prefetch_workers':best.get('prefetch_workers'),'prefetch_depth':best.get('prefetch_depth')},'benchmarks':rows}));return
 if operation=='backbone_init':
  import torch
  from pathlib import Path
  source=Path(request['parent_checkpoint']);target=Path(request['output_checkpoint']);raw=torch.load(source,map_location='cpu',weights_only=False);state=raw.get('state_dict')
  if not isinstance(state,dict):raise SystemExit('parent checkpoint has no state_dict')
  kept={key:value for key,value in state.items() if str(key).startswith('backbone.')}
  if not kept:raise SystemExit('parent checkpoint contains no backbone parameters')
  if any(str(key).startswith(('head.','codec.')) for key in kept):raise SystemExit('head parameter entered backbone-only checkpoint')
  result=dict(raw);result['state_dict']=kept;meta=dict(result.get('meta') or {});meta['simm_backbone_only_init']={'parent_checkpoint':str(source),'source_model_id':str(request['source_model_id']),'parameter_count':len(kept)};result['meta']=meta;
  if target.exists():raise SystemExit('backbone-only init artifact already exists')
  target.parent.mkdir(parents=True,exist_ok=True);torch.save(result,target)
  print(json.dumps({'status':'ok','output_checkpoint':str(target),'backbone_parameter_count':len(kept)}));return
 if operation=='ema_inference_checkpoint':
  import torch
  from pathlib import Path
  source=Path(request['source_checkpoint']);target=Path(request['output_checkpoint']);raw=torch.load(source,map_location='cpu',weights_only=False);state=raw.get('state_dict');ema=raw.get('ema_state_dict')
  if not isinstance(state,dict) or not isinstance(ema,dict) or 'steps' not in ema:raise SystemExit('checkpoint lacks required state_dict/ema_state_dict/steps')
  normalized={}
  for key,value in ema.items():
   if key=='steps':continue
   if not str(key).startswith('module.'):raise SystemExit(f'invalid EMA key: {key}')
   normalized[str(key)[7:]]=value
  if set(normalized)!=set(state):raise SystemExit('EMA/model key mismatch: '+str(sorted(set(normalized)^set(state))[:20]))
  for key in state:
   if not torch.is_tensor(state[key]) or not torch.is_tensor(normalized[key]) or state[key].shape!=normalized[key].shape or state[key].dtype!=normalized[key].dtype:raise SystemExit(f'EMA tensor mismatch: {key}')
  if target.exists():raise SystemExit('EMA inference checkpoint already exists')
  target.parent.mkdir(parents=True,exist_ok=True);torch.save({'state_dict':normalized,'meta':raw.get('meta',{})},target);check=torch.load(target,map_location='cpu',weights_only=False)
  if set(check['state_dict'])!=set(state) or any(not torch.equal(check['state_dict'][k],normalized[k]) for k in state):raise SystemExit('EMA inference checkpoint verification failed')
  print(json.dumps({'status':'ok','output_checkpoint':str(target),'parameter_count':len(normalized)}));return
 if operation=='info':
  import torch,torchvision,mmengine,mmcv,mmpose,mmdet,cv2,numpy
  print(json.dumps({'python':sys.version,'torch':torch.__version__,'torchvision':torchvision.__version__,'mmengine':mmengine.__version__,'mmcv':mmcv.__version__,'mmpose':mmpose.__version__,'mmdet':mmdet.__version__,'opencv':cv2.__version__,'numpy':numpy.__version__,'cuda_available':torch.cuda.is_available(),'cuda_runtime':torch.version.cuda,'device':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}));return
 if operation=='probe_many':
  import threading
  startup_total=max(1,len(request.get("candidates",())))
  startup_done=threading.Event()
  def startup_heartbeat():
   while not startup_done.wait(20):
    print(f'RANK_PROGRESS 0 {startup_total}',file=sys.stderr,flush=True)
  print(f'RANK_PROGRESS 0 {startup_total}',file=sys.stderr,flush=True)
  threading.Thread(target=startup_heartbeat,daemon=True).start()
  from pathlib import Path
  import torch
  from torch.utils.data import DataLoader, Subset
  from mmengine.config import Config
  from mmengine.dataset import pseudo_collate
  from mmpose.registry import MODELS, DATASETS
  from mmpose.utils import register_all_modules
  register_all_modules()
  device=request.get("device","cuda:0")
  if not str(device).startswith("cuda") or not torch.cuda.is_available():
   print(json.dumps({"status":"cpu_no_cuda","results":[]}));return
  candidates=[dict(item) for item in request.get("candidates",())]
  if not candidates:print(json.dumps({"status":"ok","results":[]}));return
  config_path=Path(request["config_path"])
  if not config_path.is_file():raise SystemExit("training probe config is unavailable")
  torch.backends.cudnn.benchmark=True
  amp=bool(request.get("mixed_precision",False))
  cfg=Config.fromfile(config_path)
  custom=cfg.get("custom_imports")
  if custom:
   from mmengine.utils import import_modules_from_strings
   import_modules_from_strings(**custom)
  model=MODELS.build(cfg.model).to(device);model.train()
  dataset=DATASETS.build(cfg.train_dataloader.dataset)
  if not len(dataset):raise SystemExit("training probe dataset is empty")
  optimizer=torch.optim.AdamW(model.parameters(),lr=1e-4,weight_decay=0.05)
  scaler=torch.cuda.amp.GradScaler(enabled=amp)
  def train_step(data_batch):
   optimizer.zero_grad(set_to_none=True)
   with torch.autocast(device_type="cuda",dtype=torch.float16,enabled=amp):
    data=model.data_preprocessor(data_batch,training=True)
    losses=model(**data,mode="loss")
    loss=sum(value for value in losses.values() if torch.is_tensor(value))
   if amp:
    scaler.scale(loss).backward();scaler.step(optimizer);scaler.update()
   else:
    loss.backward();optimizer.step()
   return int(data["inputs"].shape[0])
  def measure_candidate(batch,workers,pin,persistent,target_samples):
   # Warm the exact candidate shape before timing. With cudnn_benchmark=True,
   # each new batch shape can otherwise pay one-time kernel search inside its
   # measurement, which strongly biases the first warmed batch.
   timed_samples=max(target_samples,batch*3)
   timed_samples=((timed_samples+batch-1)//batch)*batch
   warmup_batches=2
   total_samples=batch*warmup_batches+timed_samples
   subset=Subset(dataset,[index % len(dataset) for index in range(total_samples)])
   loader=DataLoader(subset,batch_size=batch,num_workers=workers,pin_memory=pin,persistent_workers=bool(workers and persistent),collate_fn=pseudo_collate)
   iterator=iter(loader)
   try:
    for _ in range(warmup_batches):
     train_step(next(iterator))
    torch.cuda.synchronize()
    # Worker process startup, initial prefetch and cuDNN selection are one-time
    # costs in a long training run. Exclude them from steady-state throughput.
    torch.cuda.reset_peak_memory_stats()
    started=time.perf_counter();seen=0
    for data_batch in iterator:
     seen+=train_step(data_batch)
    torch.cuda.synchronize()
    return seen,max(time.perf_counter()-started,1e-9)
   finally:
    del iterator,loader
  startup_done.set()
  target=max(1,int(request.get("samples",24)))
  results=[]
  total=len(candidates)
  for index,config in enumerate(candidates,1):
   batch=max(1,int(config.get("batch_size",1)));workers=max(0,int(config.get("workers",0)))
   pin=bool(config.get("pin_memory",True));persistent=bool(config.get("persistent_workers",workers>0))
   gc.collect();torch.cuda.empty_cache()
   candidate_done=threading.Event()
   def candidate_heartbeat():
    while not candidate_done.wait(10):
     print(f'RANK_PROGRESS {index-1} {max(1,total)}',file=sys.stderr,flush=True)
   threading.Thread(target=candidate_heartbeat,daemon=True).start()
   try:
    seen,elapsed=measure_candidate(batch,workers,pin,persistent,target)
    results.append({"batch_size":batch,"workers":workers,"samples":seen,"items_per_sec":seen/elapsed,"elapsed_seconds":elapsed,"peak_vram_mib":int(torch.cuda.max_memory_allocated()/1024/1024),"mixed_precision":amp,"dataset_probe":True,"warmup_batches":2,"timing_scope":"steady_state_after_candidate_warmup","pipeline":"CocoDataset/RandomBBoxTransform/TopdownAffine/GenerateTarget"})
   except Exception as exc:
    optimizer.zero_grad(set_to_none=True);gc.collect();torch.cuda.empty_cache()
    # Candidate-specific loader/CUDA/resource failures must not discard the
    # safe measurements already collected for this machine.
    results.append({"batch_size":batch,"workers":workers,"elapsed_seconds":0.0,"error":f"{type(exc).__name__}: {exc}","peak_vram_mib":int(torch.cuda.max_memory_allocated()/1024/1024)})
   finally:
    candidate_done.set()
   print(f'RANK_PROGRESS {index} {max(1,total)}',file=sys.stderr,flush=True)
  print(json.dumps({"status":"ok","results":results}));return
 if operation=='probe':
  from pathlib import Path
  import torch
  from torch.utils.data import DataLoader, Subset
  from mmengine.config import Config
  from mmengine.dataset import pseudo_collate
  from mmpose.registry import MODELS, DATASETS
  from mmpose.utils import register_all_modules
  register_all_modules()
  device=request.get("device","cuda:0");batch=max(1,int(request.get("batch_size",1)));iterations=max(2,min(12,int(request.get("iterations",4))));workers=max(0,int(request.get("workers",0)))
  if not str(device).startswith("cuda") or not torch.cuda.is_available():print(json.dumps({"status":"cpu_no_cuda"}));return
  config_path=Path(request["config_path"])
  if not config_path.is_file():raise SystemExit("training probe config is unavailable")
  torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats()
  if str(device).startswith("cuda"):torch.backends.cudnn.benchmark=True
  amp=bool(request.get("mixed_precision",False)) and str(device).startswith("cuda")
  cfg=Config.fromfile(config_path)
  custom=cfg.get("custom_imports")
  if custom:
   from mmengine.utils import import_modules_from_strings
   import_modules_from_strings(**custom)
  model=MODELS.build(cfg.model).to(device);model.train()
  dataset=DATASETS.build(cfg.train_dataloader.dataset)
  if not len(dataset):raise SystemExit("training probe dataset is empty")
  # Cycle real current examples so small datasets still produce a sustained
  # end-to-end measurement instead of one noisy optimizer step.
  # Every candidate receives the same sustained real-image workload.
  # Round only to full batches so large batches do not receive extra warm-up.
  # A caller may select a bounded, statistically useful probe budget.  Keep
  # at least two full batches, but do not silently inflate a 32-image budget
  # to the old fixed 64-image benchmark.
  requested_samples=max(batch*2,int(request.get("samples",64)))
  samples=max(batch,((requested_samples+batch-1)//batch)*batch)
  subset=Subset(dataset,[index % len(dataset) for index in range(samples)])
  loader=DataLoader(subset,batch_size=batch,num_workers=workers,pin_memory=bool(request.get("pin_memory",True)),persistent_workers=bool(workers and request.get("persistent_workers",True)),collate_fn=pseudo_collate)
  optimizer=torch.optim.AdamW(model.parameters(),lr=1e-4,weight_decay=0.05)
  scaler=torch.cuda.amp.GradScaler(enabled=amp)
  started=time.perf_counter();seen=0
  for data_batch in loader:
   optimizer.zero_grad(set_to_none=True)
   with torch.autocast(device_type="cuda",dtype=torch.float16,enabled=amp):
    data=model.data_preprocessor(data_batch,training=True)
    losses=model(**data,mode="loss")
    loss=sum(value for value in losses.values() if torch.is_tensor(value))
   if amp:
    scaler.scale(loss).backward();scaler.step(optimizer);scaler.update()
   else:
    loss.backward();optimizer.step()
   seen+=int(data["inputs"].shape[0])
  torch.cuda.synchronize();elapsed=max(time.perf_counter()-started,1e-9)
  print(json.dumps({"status":"ok","batch_size":batch,"workers":workers,"samples":seen,"items_per_sec":seen/elapsed,"elapsed_seconds":elapsed,"peak_vram_mib":int(torch.cuda.max_memory_allocated()/1024/1024),"mixed_precision":amp,"dataset_probe":True,"pipeline":"CocoDataset/RandomBBoxTransform/TopdownAffine/GenerateTarget"}));return
 if operation=='train':
  import hashlib,torch
  from pathlib import Path
  source=resolve_mmpose_training_source(); out=Path(request["output_dir"]).resolve(); log=out/"training.log"
  train_py=source/"tools"/"train.py"
  command=[sys.executable,"-u",str(train_py),request["settings"]["config_path"],"--work-dir",str(out)]
  start=time.time(); returncode,tail=stream_training_process(command,log,cwd=source)
  if returncode: raise SystemExit(tail[-2000:])
  checkpoints=sorted(out.glob('epoch_*.pth'),key=lambda path:int(path.stem.split('_')[1])); checkpoint=checkpoints[-1] if checkpoints else out/'latest.pth'
  if not checkpoint.exists() or checkpoint.stat().st_size==0: raise SystemExit('training completed without checkpoint')
  print(json.dumps({'status':'trained','checkpoint_path':str(checkpoint),'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),'duration_seconds':time.time()-start,'command':command}));return
 raise SystemExit('unknown RTMPose operation')
if __name__=='__main__':main()
