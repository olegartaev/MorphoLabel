"""Runs inside ai_runtime only. Reads one JSON request from stdin and emits one JSON response."""
from __future__ import annotations
import json,sys

def main():
 operation=sys.argv[1] if len(sys.argv)>1 else ''; request=json.load(sys.stdin)
 if operation=='predict':
  from mmpose.apis import inference_topdown,init_model
  model=init_model(request['config_path'],request['checkpoint_path'],device=request.get('device','cuda:0'))
  model.cfg.test_dataloader=dict(dataset=dict(pipeline=model.cfg.val_pipeline))
  image=request['image_path'];from PIL import Image
  with Image.open(image) as im:w,h=im.size
  data=inference_topdown(model,image,bboxes=[[0,0,w,h]],bbox_format='xyxy')[0].pred_instances
  points=data.keypoints[0];scores=data.keypoint_scores[0];ids=request.get('simm_landmark_ids') or list(range(1,len(points)+1))
  out={'image_id':request['image_id'],'model_id':request['model_id'],'schema_sha256':request['schema_sha256'],'landmarks':[{'landmark_id':int(i),'x':float(x),'y':float(y),'confidence':float(s)} for i,(x,y),s in zip(ids,points,scores)]};print(json.dumps(out));return
 if operation=='info':
  import torch,torchvision,mmengine,mmcv,mmpose,cv2,numpy
  print(json.dumps({'python':sys.version,'torch':torch.__version__,'torchvision':torchvision.__version__,'mmengine':mmengine.__version__,'mmcv':mmcv.__version__,'mmpose':mmpose.__version__,'opencv':cv2.__version__,'numpy':numpy.__version__,'cuda_available':torch.cuda.is_available(),'cuda_runtime':torch.version.cuda,'device':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}));return
 if operation=='train':
  import subprocess,time,hashlib
  from pathlib import Path
  root=Path(__file__).resolve().parents[1]; source=root/'ai_runtime'/'vendor'/'mmpose'; out=Path(request['output_dir']); log=out/'training.log'
  command=[sys.executable,str(source/'tools'/'train.py'),request['settings']['config_path'],'--work-dir',str(out)]
  start=time.time(); run=subprocess.run(command,text=True,capture_output=True,cwd=str(source)); log.write_text(run.stdout+'\nSTDERR\n'+run.stderr,encoding='utf-8')
  if run.returncode: raise SystemExit(run.stderr[-2000:] or run.stdout[-2000:])
  checkpoints=sorted(out.glob('epoch_*.pth')); checkpoint=checkpoints[-1] if checkpoints else out/'latest.pth'
  if not checkpoint.exists() or checkpoint.stat().st_size==0: raise SystemExit('training completed without checkpoint')
  print(json.dumps({'status':'trained','checkpoint_path':str(checkpoint),'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),'duration_seconds':time.time()-start,'command':command}));return
 raise SystemExit('unknown RTMPose operation')
if __name__=='__main__':main()
