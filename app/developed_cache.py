"""Validated cached developed_full images with compact timing instrumentation."""
from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from PIL import Image
from .io import atomic_json_write
from .manifest import sha256
from .normalization_pipeline import DEVELOPMENT,paths
from .paths import REPORTS,require_relative
from .standardize import decode,image_id
from .png_atomic import atomic_save_png

def _params_hash():return hashlib.sha256(json.dumps(DEVELOPMENT,sort_keys=True).encode()).hexdigest()
def _event(source,step,seconds,rawpy=False,cache=False):
 REPORTS.mkdir(exist_ok=True)
 with (REPORTS/"gui_image_timing.jsonl").open("a",encoding="utf-8") as f:f.write(json.dumps({"source":require_relative(source),"step":step,"seconds":round(seconds,4),"rawpy":rawpy,"cache":cache})+"\n")
def cached_meta(source:Path):
 _,_,target,meta_path,*_=paths(source)
 if not target.exists() or not meta_path.exists():return None
 meta=json.loads(meta_path.read_text(encoding="utf-8"));stat=source.stat()
 if meta.get("parameters_sha256")!=_params_hash() or meta.get("source_size")!=stat.st_size or meta.get("source_mtime_ns")!=stat.st_mtime_ns:return None
 return meta
def ensure(source:Path):
 started=time.monotonic();meta=cached_meta(source)
 if meta:
  _event(source,"developed_full_cache_hit",time.monotonic()-started,cache=True);return meta
 digest_started=time.monotonic();digest=sha256(source);_event(source,"source_hash",time.monotonic()-digest_started)
 base,ident,target,meta_path,*_=paths(source);decode_started=time.monotonic();image=decode(source);_event(source,"nef_rawpy_decode",time.monotonic()-decode_started,rawpy=True)
 save_started=time.monotonic();atomic_save_png(image,target,image_id(source));_event(source,"developed_full_png_write",time.monotonic()-save_started)
 stat=source.stat();meta={"image_id":ident,"source_relpath":require_relative(source),"source_sha256":digest,"developed_full_relpath":require_relative(target),"width":image.width,"height":image.height,"development":DEVELOPMENT,"parameters_sha256":_params_hash(),"source_size":stat.st_size,"source_mtime_ns":stat.st_mtime_ns};atomic_json_write(meta_path,meta);return meta
def load_png(source:Path,display_max=1800):
 meta=ensure(source);_,_,target,*_=paths(source);started=time.monotonic();full=Image.open(target).convert("RGB");_event(source,"developed_full_png_decode",time.monotonic()-started,cache=True)
 proxy=full.copy();started=time.monotonic();proxy.thumbnail((display_max,display_max));_event(source,"display_proxy_create",time.monotonic()-started,cache=True);return meta,full,proxy
