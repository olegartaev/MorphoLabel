"""Cached local image preparation: immutable NEF -> developed_full -> REVIEW crop.

No source image is ever rewritten.  All automatic masks are proposals, never
biological ground truth, and every automatic crop stays REVIEW.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib,json,time
from pathlib import Path
import cv2,numpy as np
from PIL import Image
from .io import atomic_json_write
from .manifest import sha256
from .paths import require_relative,sample_work
from .standardize import decode,image_id
from .transforms import Transform
from .crop_training import predict as crop_predict
from .gui_crop_debug import log
from .timing_profile import record
from .png_atomic import atomic_save_png
from .project_runtime import active_project

DEVELOPMENT={"version":"rawpy_camera_wb_8bit_png_v1","camera_wb":True,"no_auto_bright":True,"lossless":"PNG"}
LOCALIZATION={"version":"opencv_adaptive_contour_v1","max_side":1600,"margin_x":0.12,"margin_y":0.38}

def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def paths(source:Path, *, project=None, image_id_value=None):
 project=project or active_project();ident=image_id_value or image_id(source)
 if project:
  base=project.cache_root
  return base,ident,base/"developed"/f"{ident}.png",base/"metadata"/f"{ident}.developed.json",base/"standardized"/f"{ident}.png",base/"metadata"/f"{ident}.json",base/"masks"/f"{ident}.png"
 base=sample_work(source.parent.name)
 return base,ident,base/"developed_full"/f"{ident}.png",base/"metadata"/f"{ident}.developed.json",base/"standardized"/f"{ident}.png",base/"metadata"/f"{ident}.json",base/"analysis"/"masks"/f"{ident}.png"

def _development_meta(source,image,target,ident,digest,parameter_hash,project):
 return {"image_id":ident,"source_relpath":source.relative_to(project.source_root).as_posix() if project else require_relative(source),"source_sha256":digest,"developed_full_relpath":str(target.relative_to(project.data_root)).replace("\\","/") if project else require_relative(target),"width":image.width,"height":image.height,"development":DEVELOPMENT,"parameters_sha256":parameter_hash}

def develop_full(source:Path, *, project=None, image_id_value=None):
 base,ident,target,meta_path,*_=paths(source,project=project,image_id_value=image_id_value); digest=sha256(source);parameter_hash=_hash(DEVELOPMENT)
 if target.exists() and meta_path.exists():
  old=json.loads(meta_path.read_text(encoding="utf-8"))
  if old.get("source_sha256")==digest and old.get("parameters_sha256")==parameter_hash:return old
 decode_started=time.perf_counter();image=decode(source);record(source,"raw_decode_ms",time.perf_counter()-decode_started,image_id_value=ident);processing_started=time.perf_counter();record(source,"developed_processing_ms",time.perf_counter()-processing_started,image_id_value=ident);write_started=time.perf_counter();atomic_save_png(image,target,ident);record(source,"developed_png_write_ms",time.perf_counter()-write_started,image_id_value=ident)
 meta=_development_meta(source,image,target,ident,digest,parameter_hash,project)
 atomic_json_write(meta_path,meta);return meta

def _crop_prediction_image(source:Path, *, project=None, image_id_value=None, allow_unmaterialized=False):
 """Load one full RGB image for Crop inference without forcing a disposable PNG write.

 A valid developed cache is reused.  On a cache miss the source is decoded once
 and can stay in memory for proposal-only inference; interactive review or
 downstream landmark preparation will rebuild the disposable developed cache
 lazily when it is actually needed.
 """
 base,ident,target,meta_path,*_=paths(source,project=project,image_id_value=image_id_value)
 if not allow_unmaterialized:
  meta=develop_full(source,project=project,image_id_value=ident);opened=time.perf_counter()
  with Image.open(target) as cached:full=cached.convert("RGB")
  return meta,full,time.perf_counter()-opened,True
 digest=sha256(source);parameter_hash=_hash(DEVELOPMENT)
 if target.exists() and meta_path.exists():
  try:
   old=json.loads(meta_path.read_text(encoding="utf-8"))
  except (OSError,json.JSONDecodeError):
   old={}
  if old.get("source_sha256")==digest and old.get("parameters_sha256")==parameter_hash:
   opened=time.perf_counter()
   with Image.open(target) as cached:full=cached.convert("RGB")
   return old,full,time.perf_counter()-opened,True
 # Never leave a stale disposable full-frame PNG where the editor could later
 # trust it simply because the file exists.
 for stale in (target,meta_path):
  try:
   if stale.exists():stale.unlink()
  except OSError:
   pass
 decode_started=time.perf_counter();full=decode(source).convert("RGB");record(source,"raw_decode_ms",time.perf_counter()-decode_started,image_id_value=ident)
 meta=_development_meta(source,full,target,ident,digest,parameter_hash,project)
 return meta,full,0.0,False

def _materialize_developed(image,meta,target,meta_path,ident,source):
 write_started=time.perf_counter();atomic_save_png(image,target,ident);record(source,"developed_png_write_ms",time.perf_counter()-write_started,image_id_value=ident);atomic_json_write(meta_path,meta)

def _candidate_mask(rgb):
 h,w=rgb.shape[:2];scale=min(1.,LOCALIZATION["max_side"]/max(h,w));small=cv2.resize(rgb,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA)
 lab=cv2.cvtColor(small,cv2.COLOR_RGB2LAB);gray=cv2.cvtColor(small,cv2.COLOR_RGB2GRAY);background=cv2.GaussianBlur(lab,(0,0),max(15,round(min(small.shape[:2])/12)))
 distance=np.linalg.norm(lab.astype(np.float32)-background.astype(np.float32),axis=2);dark=cv2.GaussianBlur(gray,(0,0),7)
 # Texture/color deviation plus dark anatomy; reject very low-contrast paper background.
 threshold=max(float(np.percentile(distance,78)),8.0);mask=((distance>threshold)|((dark<np.percentile(dark,20))&(distance>np.percentile(distance,55)))).astype(np.uint8)*255
 k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(11,11));mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,k,iterations=2);mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5)),iterations=1)
 return mask,scale

def localize_fish(full:Image.Image):
 rgb=np.asarray(full.convert("RGB"));mask,scale=_candidate_mask(rgb);contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);h,w=mask.shape
 candidates=[]
 for contour in contours:
  x,y,cw,ch=cv2.boundingRect(contour);area=cv2.contourArea(contour);ratio=max(cw/ch,ch/cw) if min(cw,ch) else 0;fraction=area/(w*h)
  touches=x<=2 or y<=2 or x+cw>=w-2 or y+ch>=h-2
  if .004<fraction<.55 and 1.3<ratio<18 and not touches:
   score=area*(1+min(ratio,8)/8)*(1.15 if .15<y/h<.8 else .8);candidates.append((score,contour,(x,y,cw,ch)))
 if not candidates:return None,mask,scale,{"reason":"no_confident_component"}
 _,contour,(x,y,cw,ch)=max(candidates,key=lambda item:item[0]);margin_x=max(24,int(cw*LOCALIZATION["margin_x"]));margin_y=max(24,int(ch*LOCALIZATION["margin_y"]));
 left=max(0,x-margin_x);top=max(0,y-margin_y);right=min(w,x+cw+margin_x);bottom=min(h,y+ch+margin_y)
 # safety: detected mask must not approach standardized crop border; expand if it does.
 safe=round(min(cw,ch)*.08);boundary=min(x-left,right-(x+cw),y-top,bottom-(y+ch));review="foreground_boundary_near" if boundary<safe else "foreground_contour_proposal"
 return (left,top,right,bottom),mask,scale,{"reason":review,"contour_bbox":[x,y,cw,ch],"boundary_px":int(boundary)}

def prepare_crop_result(source:Path, *, project=None, force=False, image_id_value=None, materialize_learned=False):
 """Worker-safe crop/cache computation: no Tk, SQLite, provenance, or Project mutation."""
 project = project or active_project()
 base,ident,developed,developed_meta_path,standard,meta_path,mask_path=paths(source,project=project,image_id_value=image_id_value)
 # Bulk learned proposals are disposable calculations.  Do not spend several
 # seconds per image materializing a full-resolution PNG that review may never
 # open.  Existing valid developed caches are still reused.
 allow_unmaterialized=bool(project is not None and not materialize_learned)
 dev,full,open_s,developed_materialized=_crop_prediction_image(source,project=project,image_id_value=ident,allow_unmaterialized=allow_unmaterialized)
 digest=dev["source_sha256"];params={"development":dev["parameters_sha256"],"localization":LOCALIZATION};param_hash=_hash(params)
 if standard.exists() and meta_path.exists() and not force:
  old=json.loads(meta_path.read_text(encoding="utf-8"));
  from .crop_training import current_label
  if old.get("source_sha256")==digest and old.get("parameters_sha256")==param_hash and old.get("crop_model_version")==current_label(project):return old
 started=time.perf_counter();prediction_started=time.perf_counter();predicted,model_version=crop_predict(full,image_id=ident,project=project);prediction_s=time.perf_counter()-prediction_started
 if predicted is None and not developed_materialized:
  # Rule-based localization remains on the established materialized path.
  _materialize_developed(full,dev,developed,developed_meta_path,ident,source);developed_materialized=True
 if predicted is not None:
  # A learned result is a review proposal, not a materialized scientific
  # frame.  The review canvas uses developed_full + these bounds; only the
  # established reviewed-Crop path writes the final standardized PNG.
  values=predicted.get("bounds",predicted) if isinstance(predicted,dict) else predicted;angle=float(predicted.get("rotation_degrees",0.0)) if isinstance(predicted,dict) else 0.0
  box=(values[0]*full.width,values[1]*full.height,values[2]*full.width,values[3]*full.height);proposal_only=not materialize_learned;mask=None if proposal_only else np.zeros((full.height,full.width),dtype=np.uint8);scale=1.;qc={"reason":"crop_model_prediction","crop_model_version":model_version,"rotation_degrees":angle}
 else:
  box,mask,scale,qc=localize_fish(full);qc["crop_model_version"]="rule-based";proposal_only=False
 mask_s=0.0
 if mask is not None:
  mask_started=time.perf_counter();mask_path.parent.mkdir(parents=True,exist_ok=True);Image.fromarray(mask).save(mask_path);mask_s=time.perf_counter()-mask_started
 failed=box is None
 if failed:box=(0,0,round(full.width*scale),round(full.height*scale));qc["reason"]="FAIL_no_fish_localization"
 left,top,right,bottom=(int(np.floor(v/scale)) for v in box);left=max(0,left);top=max(0,top);right=min(full.width,right);bottom=min(full.height,bottom)
 write_s=0.0
 if proposal_only:
  output_width,output_height=right-left,bottom-top
 else:
  write_started=time.perf_counter();frame=full.rotate(angle,resample=Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255)) if predicted is not None else full;master=frame.crop((left,top,right,bottom));atomic_save_png(master,standard,ident);write_s=time.perf_counter()-write_started;output_width,output_height=master.width,master.height
 transform=Transform(full.width,full.height,angle if predicted is not None else 0.,full.width/2,full.height/2,left,top,output_width,output_height)
 result={"image_id":ident,"source_relpath":source.relative_to(project.source_root).as_posix() if project else require_relative(source),"source_sha256":digest,"developed_full_relpath":str(developed.relative_to(project.data_root)).replace('\\','/') if project else dev["developed_full_relpath"],"standardized_relpath":str(standard.relative_to(project.data_root)).replace('\\','/') if project else require_relative(standard),"mask_relpath":None if proposal_only else (str(mask_path.relative_to(project.data_root)).replace('\\','/') if project else require_relative(mask_path)),"proposal_only":proposal_only,"developed_cache_materialized":bool(developed_materialized),"original_width":int(full.width),"original_height":int(full.height),"normalization_status":"FAIL" if failed else "REVIEW","normalization_algorithm":LOCALIZATION["version"],"crop_model_version":qc.get("crop_model_version","rule-based"),"parameters_sha256":param_hash,"crop_bounds":[left,top,right,bottom],"mirrored":False,"rotation_degrees":angle if predicted is not None else 0.,"interpolation":"none","transform":asdict(transform),"qc":qc,"timings":{"prepare_s":time.perf_counter()-started,"developed_open_s":open_s,"prediction_s":prediction_s,"mask_s":mask_s,"standardized_write_s":write_s}}
 atomic_json_write(meta_path,result);return result

def commit_crop_result(project,result,*,provenance="automatic"):
 """Serialized canonical Project mutation; callers must invoke outside workers."""
 if project is None:raise ValueError("explicit Project is required for crop commit")
 project.save_crop(result["image_id"],result,provenance=provenance,model_id=result.get("crop_model_version"));return result

def normalize(source:Path,force=False):
 project=active_project();result=prepare_crop_result(source,project=project,force=force)
 if project:commit_crop_result(project,result)
 return result

