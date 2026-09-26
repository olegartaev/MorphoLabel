"""V2 localizer: OpenCV first, cached adaptive fallback for failures."""
from pathlib import Path
from PIL import Image
from .io import atomic_json_write
from .paths import require_relative
from .standardize_fish import propose as fallback_propose
from .transforms import Transform
from . import normalization_pipeline as base
from .png_atomic import atomic_save_png

def normalize(source:Path,force=False):
 result=base.normalize(source,force=force)
 if result.get("qc",{}).get("reason")!="FAIL_no_fish_localization":return result
 full=Image.open(Path(result["developed_full_relpath"])).convert("RGB");angle,crop,reason=fallback_propose(full)
 left,top,right,bottom=crop
 if (right-left)==full.width and (bottom-top)==full.height:return result
 master=full.rotate(angle,resample=Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255)).crop(crop);target=Path(result["standardized_relpath"]);atomic_save_png(master,target,result["image_id"])
 result.update({"normalization_algorithm":"opencv_adaptive_contour_v1+adaptive_component_fallback_v1","normalization_status":"REVIEW","rotation_degrees":angle,"crop_bounds":list(crop),"interpolation":"bicubic","qc":{"reason":"fallback_"+reason,"source":"cached_developed_full"},"transform":Transform(full.width,full.height,angle,full.width/2,full.height/2,left,top,master.width,master.height).__dict__})
 _,_,_,_,_,meta_path,_=base.paths(source);atomic_json_write(meta_path,result);return result
