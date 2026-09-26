"""Selected-image background rebuild with atomic PNG publication coordination."""
from pathlib import Path
import time
from PIL import Image
from .editor_ready_v12 import ReadyEditorV12
from .developed_cache_v2 import ensure, navigation_cache_status
from .gui_crop_debug import error, log
from .normalization_pipeline_v2 import normalize
from .normalization_pipeline import paths
from .png_atomic import prepare_lock,heavy_prepare_lock
from .standardize import image_id
from .timing_profile import record

class ReadyEditorV13(ReadyEditorV12):
 def _status_detail(self, status, token, listbox_index):
  return (f"token={token} listbox_index={listbox_index} ready={status['ready']} png_exists={status['png_exists']} "
          f"source_hash_match={status['source_hash_match']} settings_hash_match={status['settings_hash_match']} "
          f"standardized_exists={status['standardized_exists']} png_integrity={status['png_integrity']} "
          f"standardized_integrity={status['standardized_integrity']} reason={status['reason']}")
 def _load_selected_v12(self, token, row, source, listbox_index):
  """All rebuild/decode work is worker-only and serialized per image_id."""
  ident=row.get("image_id") or image_id(source)
  try:
   with prepare_lock(ident,str(source)):
    cache_started=time.perf_counter();status=navigation_cache_status(source)
    cache_elapsed=time.perf_counter()-cache_started
    log(ident,"cache_lookup_ms","END",cache_elapsed,path=status["png_path"],detail=f"cache_lookup_ms={cache_elapsed*1000:.1f} source_validation_ms=0.0 manifest_only=true")
    log(ident,"source_validation_ms","END",0.0,path=str(source),detail="source_validation_ms=0.0 manifest_only=true")
    log(ident,"navigation_cache_validation","END",cache_elapsed,path=status["png_path"],detail=self._status_detail(status,token,listbox_index))
    if not status["ready"]:
     log(ident,"navigation_background_prepare","START",path=str(source),detail=f"reason={status['reason']} gui_thread_rawpy=false")
     with heavy_prepare_lock(ident,str(source)):
      normalize(source,force=True);ensure(source)
     status=navigation_cache_status(source)
     log(ident,"navigation_background_prepare","END",path=status["png_path"],detail=self._status_detail(status,token,listbox_index))
     if not status["ready"]: raise RuntimeError("Background preparation completed without valid PNG cache: "+status["reason"])
    developed,standard=paths(source)[2],paths(source)[4]
    for attempt in range(2):
     try:
      display_started=time.perf_counter();standardized=Image.open(standard).convert("RGB");source_png=None;display_elapsed=time.perf_counter()-display_started
      record(source,"display_load_ms",display_elapsed);log(ident,"standardized_png_decode_ms","END",display_elapsed,path=str(standard),detail=f"standardized_png_decode_ms={display_elapsed*1000:.1f}");break
     except OSError as exc:
      if "truncated" not in str(exc).lower() or attempt: raise
      log(ident,"navigation_png_truncated","ERROR",path=str(developed),detail="rebuild_once_in_background=true")
      with heavy_prepare_lock(ident,str(source)):
       normalize(source,force=True);ensure(source)
    log(ident,"navigation_png_load","END",path=str(standard),detail=f"token={token} listbox_index={listbox_index} standardized={standardized.width}x{standardized.height}/{standardized.mode} rawpy_nef_calls=0")
    self._pending.put((token,"ok",row,source,listbox_index,source_png,standardized,None))
  except Exception as exc:
   error(ident,"navigation_loader",str(source),exc);self._pending.put((token,"error",row,source,listbox_index,None,None,str(exc)))

def run():ReadyEditorV13().mainloop()
if __name__=="__main__":run()



