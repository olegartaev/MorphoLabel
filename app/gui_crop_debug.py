"""Durable, low-volume diagnostics for the crop-editor loading path."""
from __future__ import annotations
import faulthandler
import os
import tempfile
import threading
import time
import traceback
from pathlib import Path
from .runtime_paths import app_state_dir

LOG = app_state_dir() / "logs" / "app.log"
TRACE = LOG
LOG_MAX_BYTES = 8 * 1024**2
LOG_BACKUP_BYTES = 8 * 1024**2
_IO_LOCK = threading.RLock()

def _log_paths():
 """Always retain the launcher log; mirror Project events when a project is open."""
 paths = [LOG]
 try:
  from .project_runtime import active_project
  project = active_project()
  if project:
   project.data_root.mkdir(parents=True, exist_ok=True)
   project_log = project.data_root / "app.log"
   if project_log != LOG: paths.append(project_log)
 except Exception:
  pass
 return tuple(paths)

def _log_path():
 return _log_paths()[-1]

def _fallback_log_path():
 """Writable last-resort diagnostics path; never part of project state."""
 return Path(tempfile.gettempdir()) / "MorphoLabel" / "logs" / "app.log"

def _rotate_log(path_target, *, max_bytes=LOG_MAX_BYTES, backup_bytes=LOG_BACKUP_BYTES):
 path_target=Path(path_target)
 try:size=path_target.stat().st_size
 except OSError:return False
 if size<int(max_bytes):return False
 backup=path_target.with_name(path_target.name+".1")
 try:
  with path_target.open("rb") as source:
   keep=min(size,max(0,int(backup_bytes)))
   source.seek(max(0,size-keep))
   payload=source.read()
  if payload:
   newline=payload.find(b"\n")
   if newline>=0 and size>keep:payload=payload[newline+1:]
   backup.write_bytes(payload)
  else:
   backup.unlink(missing_ok=True)
  path_target.unlink(missing_ok=True)
  return True
 except OSError:
  return False

def _append_to_path(path_target,line):
 """Best-effort single-target write. Diagnostics must never block application startup."""
 path_target=Path(path_target)
 try:
  path_target.parent.mkdir(parents=True,exist_ok=True)
  _rotate_log(path_target)
  with path_target.open("a",encoding="utf-8") as handle:
   handle.write(line);handle.flush()
  return True
 except OSError:
  return False

def _append(line):
 with _IO_LOCK:
  paths=tuple(_log_paths());written=False
  for path_target in paths:
   written=_append_to_path(path_target,line) or written
  fallback=_fallback_log_path()
  if not written and fallback not in paths:
   written=_append_to_path(fallback,line)
  return written

def _stamp():
 return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()) + f".{int(time.time_ns() % 1_000_000_000 / 1_000_000):03d}"

def log(image_id, operation, state, elapsed=0.0, path="", detail=""):
 thread = threading.current_thread()
 line = (f"{_stamp()} thread={thread.name}/{threading.get_ident()} image_id={image_id} "
         f"op={operation} state={state} elapsed_s={elapsed:.3f} path={path} {detail}\n")
 _append(line)

def debug_enabled():
 return os.environ.get("SIMM_CROP_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

def trace(image_id, operation, *, path="", detail=""):
 """Detailed interaction trace; enabled only with SIMM_CROP_DEBUG=1."""
 if debug_enabled():
  log(image_id, operation, "TRACE", path=path, detail=detail)

def error(image_id, operation, path, exc):
 log(image_id, operation, "ERROR", path=path, detail=f"error={exc!r}")
 _append(traceback.format_exc())

def _dump_threads_to_path(target,image_id,reason):
 target=Path(target)
 try:
  target.parent.mkdir(parents=True,exist_ok=True)
  _rotate_log(target)
  with target.open("a",encoding="utf-8") as handle:
   handle.write(f"\n=== {_stamp()} image_id={image_id} reason={reason} ===\n")
   faulthandler.dump_traceback(file=handle,all_threads=True)
   handle.flush()
  return True
 except (OSError,ValueError,RuntimeError):
  return False

def dump_threads(image_id, reason):
 log(image_id, "hang_trace", "START", detail=f"reason={reason}")
 with _IO_LOCK:
  paths=tuple(_log_paths());written=False
  for target in paths:
   written=_dump_threads_to_path(target,image_id,reason) or written
  fallback=_fallback_log_path()
  if not written and fallback not in paths:
   _dump_threads_to_path(fallback,image_id,reason)
 log(image_id, "hang_trace", "END")
