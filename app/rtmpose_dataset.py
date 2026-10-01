"""Immutable Gate-2 manifest to COCO keypoint adapter for RTMPose."""
from __future__ import annotations
import json, math
from dataclasses import dataclass
from pathlib import Path
from .io import atomic_json_write

FISH_INPUT_SIZE=(512,256)  # width, height; horizontal standardized fish image.

class RTMPoseDatasetError(ValueError): pass

@dataclass(frozen=True)
class ResizeTransform:
 source_width:int; source_height:int; target_width:int; target_height:int
 @property
 def scale(self): return min(self.target_width/self.source_width,self.target_height/self.source_height)
 @property
 def pad_x(self): return (self.target_width-self.source_width*self.scale)/2
 @property
 def pad_y(self): return (self.target_height-self.source_height*self.scale)/2
 def forward(self,x,y): return (x*self.scale+self.pad_x,y*self.scale+self.pad_y)
 def inverse(self,x,y): return ((x-self.pad_x)/self.scale,(y-self.pad_y)/self.scale)

def _manifest(path):
 try: data=json.loads(Path(path).read_text(encoding='utf-8'))
 except (OSError,json.JSONDecodeError) as exc: raise RTMPoseDatasetError(f'invalid immutable dataset manifest: {path}') from exc
 if data.get('format_version')!=1 or not isinstance(data.get('schema_landmarks'),list) or not isinstance(data.get('images'),list): raise RTMPoseDatasetError('unsupported immutable dataset manifest')
 return data

def export_coco(dataset_manifest, output_path, *, splits=('train','validation','test')):
 """Export snapshot labels only; never reads current Project landmarks."""
 manifest=_manifest(dataset_manifest); selected=set(splits);schema=manifest['schema_landmarks']; ids=[int(x['landmark_id']) for x in schema]
 if len(ids)!=len(set(ids)): raise RTMPoseDatasetError('schema landmark IDs are not unique')
 categories=[{'id':1,'name':'fish','supercategory':'fish','keypoints':[str(x.get('abbr') or x['landmark_id']) for x in schema],'skeleton':[], 'simm_landmark_ids':ids}]
 images=[];annotations=[]
 for image_index,entry in enumerate(x for x in manifest['images'] if x.get('split') in selected):
  width,height=int(entry['standardized_width']),int(entry['standardized_height']); labels={int(x['landmark_id']):x for x in entry.get('landmarks',())}
  if set(labels)!=set(ids): raise RTMPoseDatasetError(f"snapshot labels do not match schema: {entry.get('image_id')}")
  keypoints=[];visible=0
  for ident in ids:
   point=labels[ident]
   if point.get('state')=='missing': keypoints.extend((0.0,0.0,0))
   else:
    x,y=point.get('x'),point.get('y')
    if not (isinstance(x,(int,float)) and isinstance(y,(int,float)) and math.isfinite(x) and math.isfinite(y)): raise RTMPoseDatasetError(f'invalid point {ident}')
    keypoints.extend((float(x),float(y),2));visible+=1
  coco_id=image_index+1
  images.append({'id':coco_id,'file_name':entry['standardized_relpath'],'width':width,'height':height,'simm_image_id':entry['image_id'],'split':entry['split']})
  annotations.append({'id':coco_id,'image_id':coco_id,'category_id':1,'bbox':[0.0,0.0,float(width),float(height)],'area':float(width*height),'iscrowd':0,'num_keypoints':visible,'keypoints':keypoints})
 result={'info':{'description':'MorphoLabel immutable dataset snapshot','dataset_id':manifest['dataset_id'],'schema_sha256':manifest['schema_sha256']},'images':images,'annotations':annotations,'categories':categories}
 atomic_json_write(Path(output_path),result);return result

def mmpose_metainfo(dataset_manifest):
 manifest=_manifest(dataset_manifest);schema=manifest['schema_landmarks'];ids=[int(x['landmark_id']) for x in schema]
 return {'dataset_name':'simm_immutable','keypoint_info':{index:{'name':str(row.get('abbr') or ident),'id':index,'color':[255,255,255],'type':'','swap':''} for index,(ident,row) in enumerate(zip(ids,schema))},'skeleton_info':{},'joint_weights':[1.0]*len(ids),'sigmas':[0.05]*len(ids),'simm_landmark_ids':ids,'schema_sha256':manifest['schema_sha256']}

def generate_smoke_config(dataset_manifest, *, data_root, train_coco, val_coco, output_path, base_config, base_checkpoint, batch_size=1, workers=0, mixed_precision=False, device="cpu", pin_memory=None, persistent_workers=None, max_epochs=1, checkpoint_interval=1, max_keep_ckpts=1, parent_checkpoint=None, input_size=FISH_INPUT_SIZE, backbone_checkpoint=None, photometric_augmentation=False):
 """Write a small reproducible RTMPose smoke configuration; no unsafe flips."""
 manifest=_manifest(dataset_manifest);meta=mmpose_metainfo(dataset_manifest);n=len(meta['simm_landmark_ids']);out=Path(output_path).resolve();size=tuple(map(int,input_size));featuremap=(size[0]//32,size[1]//32);parent_load=str(Path(parent_checkpoint).resolve()) if parent_checkpoint else None;backbone_load=str(Path(backbone_checkpoint or base_checkpoint).resolve())
 sigma=5.66*((size[0]/512)*(size[1]/256))**.25
 photometric = "    dict(type='mmdet.PhotoMetricDistortion', brightness_delta=12, contrast_range=(0.9, 1.1), saturation_range=(0.9, 1.1), hue_delta=5),\n" if photometric_augmentation else ""
 config=f'''_base_ = [{str(Path(base_config).resolve())!r}]

# Generated by MorphoLabel from immutable dataset {manifest['dataset_id']}; smoke only.
# Do not inherit obsolete project-local custom imports from an older parent
# model config. Supported MorphoLabel RTMPose configs use registered
# OpenMMLab components only.
custom_imports = None
env_cfg = dict(cudnn_benchmark={bool(str(device).startswith("cuda"))!r})
max_epochs = {int(max_epochs)}
codec = dict(type='SimCCLabel', input_size={size!r}, sigma=({sigma:.12g}, {sigma:.12g}), simcc_split_ratio=2.0, normalize=False, use_dark=False)
metainfo = {meta!r}
model = dict(
    backbone=dict(init_cfg=dict(_delete_=True, type="Pretrained", checkpoint={backbone_load!r}, prefix="backbone.")),
    head=dict(out_channels={n}, input_size=codec['input_size'], in_featuremap_size={featuremap!r}, decoder=codec),
    test_cfg=dict(flip_test=False))
load_from = {parent_load!r}
train_cfg = dict(max_epochs=max_epochs, val_interval=1)
custom_hooks = [dict(type='EMAHook', momentum=0.0002, update_buffers=True)]
default_hooks = dict(checkpoint=dict(interval={int(checkpoint_interval)}, by_epoch=True, max_keep_ckpts={int(max_keep_ckpts)}))
train_pipeline = [
    dict(type='LoadImage'),
    dict(type='GetBBoxCenterScale'),
    dict(type='RandomBBoxTransform', shift_factor=0.1, scale_factor=[0.8, 1.2], rotate_factor=5),
    dict(type='TopdownAffine', input_size=codec['input_size']),
{photometric}    dict(type='GenerateTarget', encoder=codec),
    dict(type='PackPoseInputs')]
val_pipeline = [dict(type='LoadImage'),dict(type='GetBBoxCenterScale'),dict(type='TopdownAffine', input_size=codec['input_size']),dict(type='PackPoseInputs')]
train_dataloader = dict(batch_size={int(batch_size)}, num_workers={int(workers)}, persistent_workers={bool(persistent_workers if persistent_workers is not None else int(workers)>0)!r}, pin_memory={bool(pin_memory if pin_memory is not None else str(device).startswith("cuda"))!r}, sampler=dict(type='DefaultSampler', shuffle=True), dataset=dict(type='CocoDataset', data_root={str(Path(data_root).resolve())!r}, data_mode='topdown', ann_file={str(Path(train_coco).resolve())!r}, data_prefix=dict(img=''), metainfo=metainfo, pipeline=train_pipeline))
val_dataloader = None
val_cfg = None
val_evaluator = None
test_dataloader = None
test_cfg = None
test_evaluator = None
optim_wrapper = dict(type={"AmpOptimWrapper" if mixed_precision else "OptimWrapper"!r}, optimizer=dict(type='AdamW', lr=1e-4, weight_decay=0.05))
param_scheduler = []
'''
 out.write_text(config,encoding='utf-8');return out
