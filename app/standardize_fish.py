"""Working fish-centered high-resolution normalization proposal (REVIEW-only)."""
from dataclasses import asdict
from pathlib import Path
import json,numpy as np
from PIL import Image
from .fish_crop import interior_component
from .io import atomic_json_write
from .manifest import sha256
from .paths import require_relative,sample_work
from .standardize import decode,image_id
from .transforms import Transform

def _component(image):
 scale=min(1.,1400/max(image.size));small=image.resize((round(image.width*scale),round(image.height*scale)));a=np.asarray(small.convert("RGB"),float);h,w=a.shape[:2];b=max(2,min(h,w)//30);edge=np.concatenate((a[:b].reshape(-1,3),a[-b:].reshape(-1,3),a[:,:b].reshape(-1,3),a[:,-b:].reshape(-1,3)));bg=np.median(edge,0);d=np.sqrt(((a-bg)**2).sum(2));mask=d>np.percentile(d,70);return interior_component(mask),scale
def propose(image):
 p,scale=_component(image)
 if len(p)<100:return 0.,(0,0,image.width,image.height),"no_confident_fish_component"
 cen=p.mean(0);_,v=np.linalg.eigh(np.cov((p-cen).T));axis=v[:,-1];degree=np.degrees(np.arctan2(axis[0],axis[1]));degree=degree-180 if degree>90 else degree+180 if degree<-90 else degree
 ys,xs=p[:,0]/scale,p[:,1]/scale;mx=image.width*.07;my=image.height*.08;crop=(max(0,int(xs.min()-mx)),max(0,int(ys.min()-my)),min(image.width,int(xs.max()+mx)),min(image.height,int(ys.max()+my+image.height*.16)))
 return float(-degree),crop,"adaptive_interior_component_v1"
def standardized_master(source:Path,force=False):
 ident=image_id(source);base=sample_work(source.parent.name);meta_path=base/"metadata"/f"{ident}.json"
 if meta_path.exists() and not force:
  old=json.loads(meta_path.read_text(encoding="utf-8"));
  if old.get("normalization_algorithm")=="adaptive_interior_component_v1" and Path(old["standardized_relpath"]).exists():return old
 im=decode(source);angle,crop,reason=propose(im);rotated=im.rotate(angle,resample=Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255));master=rotated.crop(crop);output=base/"standardized"/f"{ident}.png";output.parent.mkdir(parents=True,exist_ok=True);master.save(output,"PNG",compress_level=6)
 t=Transform(im.width,im.height,angle,im.width/2,im.height/2,crop[0],crop[1],master.width,master.height);result={"image_id":ident,"source_relpath":require_relative(source),"source_sha256":sha256(source),"standardized_relpath":require_relative(output),"normalization_status":"REVIEW","qc_reason":reason,"normalization_algorithm":"adaptive_interior_component_v1","rotation_degrees":angle,"crop_bounds":list(crop),"mirrored":False,"interpolation":"bicubic","transform":asdict(t)};atomic_json_write(meta_path,result);return result
