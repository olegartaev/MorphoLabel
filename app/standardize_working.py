"""Corrected deterministic non-deforming standardized-master generator."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json
import numpy as np
from .io import atomic_json_write
from .manifest import sha256
from .paths import require_relative, sample_work
from .standardize import decode, image_id
from .transforms import Transform

def _foreground(image,max_side=1400):
    scale=min(1.0,max_side/max(image.size)); small=image.resize((round(image.width*scale),round(image.height*scale)))
    arr=np.asarray(small.convert("RGB"),dtype=np.float32); h,w=arr.shape[:2]; band=max(2,min(h,w)//30)
    edge=np.concatenate((arr[:band].reshape(-1,3),arr[-band:].reshape(-1,3),arr[:,:band].reshape(-1,3),arr[:,-band:].reshape(-1,3)))
    bg=np.median(edge,axis=0); dist=np.sqrt(((arr-bg)**2).sum(axis=2)); edge_dist=np.sqrt(((edge-bg)**2).sum(axis=1)); return dist>max(18.,float(np.percentile(edge_dist,99))+10.),scale

def _largest(mask):
    h,w=mask.shape; seen=np.zeros_like(mask,bool); best=[]
    for y,x in zip(*np.nonzero(mask)):
        if seen[y,x]: continue
        stack=[(int(y),int(x))]; seen[y,x]=True; group=[]
        while stack:
            cy,cx=stack.pop(); group.append((cy,cx))
            for ny,nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                if 0<=ny<h and 0<=nx<w and mask[ny,nx] and not seen[ny,nx]: seen[ny,nx]=True; stack.append((ny,nx))
        if len(group)>len(best): best=group
    return np.asarray(best,dtype=float)

def propose_normalization(image):
    mask,scale=_foreground(image); points=_largest(mask)
    if len(points)<50:return 0.,(0,0,image.width,image.height),"foreground_not_confident"
    centered=points-points.mean(0); _,vectors=np.linalg.eigh(np.cov(centered.T)); axis=vectors[:,-1]; degree=np.degrees(np.arctan2(axis[0],axis[1])); degree=degree-180 if degree>90 else degree+180 if degree<-90 else degree
    ys,xs=points[:,0]/scale,points[:,1]/scale; margin=max(image.size)*.055; crop=(max(0,int(xs.min()-margin)),max(0,int(ys.min()-margin)),min(image.width,int(xs.max()+margin)),min(image.height,int(ys.max()+margin)))
    if crop[2]-crop[0]<image.width*.15 or crop[3]-crop[1]<image.height*.08:crop=(0,0,image.width,image.height)
    return float(-degree),crop,"foreground_pca_proposal"

def standardized_master(source:Path,force=False):
    ident=image_id(source); base=sample_work(source.parent.name); meta_path=base/"metadata"/f"{ident}.json"
    if meta_path.exists() and not force:
        old=json.loads(meta_path.read_text(encoding="utf-8"))
        if old.get("normalization_algorithm")=="foreground_pca_working_v1" and Path(old["standardized_relpath"]).exists():return old
    image=decode(source); angle,crop,reason=propose_normalization(image); rotated=image.rotate(angle,resample=__import__('PIL').Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255)); master=rotated.crop(crop)
    output=base/"standardized"/f"{ident}.png"; output.parent.mkdir(parents=True,exist_ok=True); master.save(output,"PNG",compress_level=6)
    transform=Transform(image.width,image.height,angle,image.width/2,image.height/2,crop[0],crop[1],master.width,master.height)
    result={"image_id":ident,"source_relpath":require_relative(source),"source_sha256":sha256(source),"standardized_relpath":require_relative(output),"normalization_status":"REVIEW","qc_reason":reason,"normalization_algorithm":"foreground_pca_working_v1","rotation_degrees":angle,"crop_bounds":list(crop),"mirrored":False,"interpolation":"bicubic","transform":asdict(transform)}
    atomic_json_write(meta_path,result);return result
