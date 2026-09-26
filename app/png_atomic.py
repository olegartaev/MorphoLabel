"""Atomic PNG publication and in-process per-image preparation locks."""
from __future__ import annotations
import os, threading, uuid
from contextlib import contextmanager
from pathlib import Path
from PIL import Image
from .gui_crop_debug import log

_GUARD=threading.Lock(); _LOCKS={}

def verify_png(path:Path):
 try:
  with Image.open(path) as image: image.load()
  with Image.open(path) as image: image.verify()
  return True,None
 except Exception as exc: return False,str(exc)

def atomic_save_png(image, target:Path, image_id="UNKNOWN"):
 target.parent.mkdir(parents=True,exist_ok=True); temporary=target.with_name(target.name+f".{uuid.uuid4().hex}.tmp.png")
 try:
  image.save(temporary,"PNG",compress_level=6)
  valid,reason=verify_png(temporary)
  log(image_id,"png_integrity_check","END",path=str(temporary),detail=f"valid={valid} reason={reason or 'ok'}")
  if not valid: raise OSError("temporary PNG integrity failure: "+reason)
  os.replace(temporary,target)
  log(image_id,"atomic_png_replace","END",path=str(target),detail="published=true")
 finally:
  if temporary.exists(): temporary.unlink(missing_ok=True)

@contextmanager
def prepare_lock(image_id, path=""):
 with _GUARD: lock=_LOCKS.setdefault(image_id,threading.Lock())
 waited=not lock.acquire(blocking=False)
 if waited:
  log(image_id,"prepare_lock_wait","START",path=path,detail="already_preparing=true");lock.acquire();log(image_id,"prepare_lock_wait","END",path=path,detail="preparation_finished=true")
 try: yield
 finally: lock.release()

HEAVY_PREPARE_LOCK=threading.Lock()
@contextmanager
def heavy_prepare_lock(image_id, path=""):
 if not HEAVY_PREPARE_LOCK.acquire(blocking=False):
  log(image_id,"heavy_prepare_wait","START",path=path,detail="single_preparation_worker=true");HEAVY_PREPARE_LOCK.acquire();log(image_id,"heavy_prepare_wait","END",path=path,detail="preparation_slot_available=true")
 try: yield
 finally: HEAVY_PREPARE_LOCK.release()
