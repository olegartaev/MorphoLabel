"""Bounded, one-worker look-ahead preparation for the next three images."""
from __future__ import annotations
import heapq, threading
from pathlib import Path
from .developed_cache_v2 import ensure, navigation_cache_status
from .gui_crop_debug import error, log
from .normalization_pipeline_v2 import normalize
from .png_atomic import heavy_prepare_lock, prepare_lock
from .standardize import image_id

class PrefetchManager:
 def __init__(self):
  self._cv=threading.Condition();self._heap=[];self._pending={};self._seq=0;self._stop=False
  threading.Thread(target=self._run,daemon=True,name="crop-prefetch-worker").start()
 def claim_user(self,source):
  ident=image_id(source)
  with self._cv:self._pending[ident]="user";self._cv.notify_all()
 def schedule(self,sources):
  with self._cv:
   for source in sources:
    ident=image_id(source)
    if ident in self._pending:continue
    self._seq+=1;self._pending[ident]="prefetch";heapq.heappush(self._heap,(0,self._seq,Path(source)));log(ident,"prefetch_queued","END",path=str(source),detail="priority=background")
   self._cv.notify_all()
 def _next(self):
  while not self._stop:
   with self._cv:
    while not self._heap and not self._stop:self._cv.wait()
    if self._stop:return None
    _,_,source=heapq.heappop(self._heap)
   ident=image_id(source)
   if self._pending.get(ident)!="prefetch":continue
   return source
  return None
 def _run(self):
  while True:
   source=self._next()
   if source is None:return
   ident=image_id(source)
   try:
    with prepare_lock(ident,str(source)):
     status=navigation_cache_status(source)
     if status["ready"]:log(ident,"prefetch_skip_ready","END",path=status["png_path"]);continue
     with heavy_prepare_lock(ident,str(source)):
      log(ident,"prefetch_prepare","START",path=str(source),detail=f"reason={status['reason']}")
      normalize(source,force=True);ensure(source);status=navigation_cache_status(source)
      log(ident,"prefetch_prepare","END",path=status["png_path"],detail=f"ready={status['ready']} reason={status['reason']}")
   except Exception as exc:error(ident,"prefetch_prepare",str(source),exc)
   finally:
    with self._cv:self._pending.pop(ident,None);self._cv.notify_all()
