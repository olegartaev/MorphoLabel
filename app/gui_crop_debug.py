"""Durable, low-volume diagnostics for the crop-editor loading path."""
from __future__ import annotations
import faulthandler
import os
import threading
import time
import traceback
from pathlib import Path
from .paths import ROOT

LOG = ROOT / "app.log"
TRACE = LOG

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


def _append(line):
 for path_target in _log_paths():
  path_target.parent.mkdir(parents=True, exist_ok=True)
  with path_target.open("a", encoding="utf-8") as handle:
   handle.write(line); handle.flush()


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


def dump_threads(image_id, reason):
 log(image_id, "hang_trace", "START", detail=f"reason={reason}")
 for target in _log_paths():
  with target.open("a", encoding="utf-8") as handle:
   handle.write(f"\n=== {_stamp()} image_id={image_id} reason={reason} ===\n")
   faulthandler.dump_traceback(file=handle, all_threads=True)
   handle.flush()
 log(image_id, "hang_trace", "END")







