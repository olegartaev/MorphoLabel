"""Migration-safe cache validation plus exhaustive crop-loader diagnostics."""
from pathlib import Path
import json,time
from PIL import Image
from . import developed_cache as base
from .gui_crop_debug import log,error
from .io import atomic_json_write
from .normalization_pipeline import paths
from .standardize import image_id
from .png_atomic import verify_png

def ensure(source:Path):
 ident=image_id(source); _,_,target,meta_path,*_=paths(source)
 log(ident,"developed_full_cache_path","START",path=str(target))
 log(ident,"developed_full_cache_path","END",path=str(target))
 exists=target.exists() and meta_path.exists();log(ident,"cache_existence_check","END",path=str(target),detail=f"exists={exists}")
 started=time.monotonic();log(ident,"source_hash_settings_validation","START",path=str(source))
 meta=base.cached_meta(source)
 log(ident,"source_hash_settings_validation","END",time.monotonic()-started,str(source),detail=f"validated={bool(meta)} rawpy_nef_calls=0")
 if meta:return meta
 if target.exists() and meta_path.exists():
  old=json.loads(meta_path.read_text(encoding="utf-8"))
  if old.get("source_sha256") and old.get("parameters_sha256")==base._params_hash():
   started=time.monotonic();log(ident,"legacy_source_hash_validation","START",path=str(source));digest=base.sha256(source);log(ident,"legacy_source_hash_validation","END",time.monotonic()-started,str(source),detail="rawpy_nef_calls=0")
   if digest==old["source_sha256"]:
    stat=source.stat();old.update({"source_size":stat.st_size,"source_mtime_ns":stat.st_mtime_ns});atomic_json_write(meta_path,old);base._event(source,"developed_full_legacy_cache_hit",0,cache=True);return old
 log(ident,"rawpy_nef_decode","START",path=str(source),detail="reason=cache_missing_or_validation_failed")
 try:
  result=base.ensure(source)
  log(ident,"rawpy_nef_decode","END",path=str(source),detail="delegated_cache_build_completed")
  return result
 except Exception as exc:
  error(ident,"rawpy_nef_decode",str(source),exc);raise

def cached_png_ready(source:Path):
 """True only when PNG cache is validated; never develops RAW."""
 return base.cached_meta(source) is not None

def load_png(source:Path,display_max=1800):
 ident=image_id(source); meta=ensure(source);_,_,target,*_=paths(source)
 try:
  stat=target.stat();log(ident,"developed_full_file_stat","END",path=str(target),detail=f"bytes={stat.st_size}")
  started=time.monotonic();log(ident,"png_open","START",path=str(target));opened=Image.open(target);log(ident,"png_open","END",time.monotonic()-started,str(target))
  started=time.monotonic();log(ident,"png_decode_load","START",path=str(target));opened.load();log(ident,"png_decode_load","END",time.monotonic()-started,str(target),detail=f"width={opened.width} height={opened.height} mode={opened.mode}")
  started=time.monotonic();log(ident,"convert_rgb","START",path=str(target));full=opened.convert("RGB");log(ident,"convert_rgb","END",time.monotonic()-started,str(target),detail=f"width={full.width} height={full.height} mode={full.mode}")
  proxy=full.copy();started=time.monotonic();log(ident,"display_proxy_generation","START",path=str(target));proxy.thumbnail((display_max,display_max));log(ident,"display_proxy_generation","END",time.monotonic()-started,str(target),detail=f"width={proxy.width} height={proxy.height} mode={proxy.mode}")
  return meta,full,proxy
 except Exception as exc:
  error(ident,"load_png",str(target),exc);raise

def navigation_cache_status(source:Path, *, validate_source=False, verify_integrity=False):
 """Detailed selected-image cache diagnosis; safe in a background worker.

 Normal editor navigation validates the published cache manifest, rather than
 hashing a possibly remote or offline RAW file. Strong validation is reserved
 for explicit import/repair flows via validate_source=True.
 """
 _,_,png,meta_path,standard,_,_=paths(source)
 png_exists=png.exists(); standardized_exists=standard.exists()
 png_valid,png_error=verify_png(png) if png_exists and verify_integrity else (png_exists,"deferred")
 standard_valid,standard_error=verify_png(standard) if standardized_exists and verify_integrity else (standardized_exists,"deferred")
 metadata={}
 if meta_path.exists():
  try: metadata=json.loads(meta_path.read_text(encoding="utf-8"))
  except Exception: metadata={}
 settings_hash_match=metadata.get("parameters_sha256")==base._params_hash()
 source_hash_match=bool(metadata.get("source_sha256"))
 if validate_source and source_hash_match:
  source_hash_match=base.sha256(source)==metadata["source_sha256"]
 reasons=[]
 if not png_exists: reasons.append("developed_full_png_missing")
 if not standardized_exists: reasons.append("standardized_png_missing")
 if verify_integrity and png_exists and not png_valid: reasons.append("developed_full_png_integrity_failed")
 if verify_integrity and standardized_exists and not standard_valid: reasons.append("standardized_png_integrity_failed")
 if not metadata: reasons.append("developed_metadata_missing_or_invalid")
 if metadata and not source_hash_match: reasons.append("source_sha256_missing" if not metadata.get("source_sha256") else "source_sha256_mismatch")
 if metadata and not settings_hash_match: reasons.append("development_settings_hash_mismatch")
 return {"ready":not reasons,"png_exists":png_exists,"source_hash_match":source_hash_match,
         "settings_hash_match":settings_hash_match,"standardized_exists":standardized_exists,
         "reason":";".join(reasons) if reasons else "ready","png_path":str(png),"standardized_path":str(standard),"png_integrity":png_valid,"standardized_integrity":standard_valid,"png_integrity_error":png_error,"standardized_integrity_error":standard_error}
