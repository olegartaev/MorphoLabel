"""Strict Listbox-to-record navigation binding for the operator editor."""
from __future__ import annotations
import queue
import threading
import time
from pathlib import Path
from PIL import Image
from .editor_ready_v11 import ReadyEditorV11
from .developed_cache_v2 import cached_png_ready
from .gui_crop_debug import error, log
from .normalization_pipeline import paths
from .standardize import image_id
from .workflow import load_record, save_record


class ReadyEditorV12(ReadyEditorV11):
 def __init__(self, project=None):
  if project is not None:self.project=project
  self._programmatic_image_selection = False
  self._display_row = None
  self._display_source = None
  self.navigation_results = []
  super().__init__(project=project)

 def _set_image_selection_programmatically(self, index):
  self._programmatic_image_selection = True
  try:
   self.images_box.selection_clear(0, "end")
   self.images_box.selection_set(index)
   self.images_box.see(index)
  finally:
   # Keep the guard through Tk's queued ListboxSelect delivery.
   self.after_idle(lambda: setattr(self, "_programmatic_image_selection", False))

 def pick_image(self, _=None):
  selection = self.images_box.curselection()
  if not selection:
   return
  index = selection[0]
  row = self.images[index]
  source = Path(row.get("source_path", row["source_relpath"]))
  ident = self._canonical_id(row, source)
  if self._programmatic_image_selection:
   log(ident, "listbox_programmatic_selection", "END", path=str(source), detail=f"listbox_index={index} ignored=true")
   return
  log(ident, "listbox_user_selection", "START", path=str(source), detail=f"listbox_index={index} filename={source.name} resolved_image_id={ident}")
  self.index = index
  self.open_image(row=row, source=source, listbox_index=index, user_selection=True)

 def open_image(self, row=None, source=None, listbox_index=None, user_selection=False):
  if row is None:
   listbox_index = self.index
   row = self.images[listbox_index]
   source = Path(row.get("source_path", row["source_relpath"]))
  self._display_image_id = self._canonical_id(row, source)
  self._load_token += 1
  token = self._load_token
  ident = self._canonical_id(row, source)
  log(ident, "select_image_navigation", "START", path=str(source), detail=f"token={token} listbox_index={listbox_index} filename={source.name} user_selection={user_selection}")
  self.header.config(text=f"Preparing image {listbox_index + 1}/{len(self.images)}…")
  threading.Thread(target=self._load_selected_v12, args=(token, row, source, listbox_index), daemon=True,
                   name=f"editor-png-{ident}").start()
  self.after(20, lambda: self._poll_selected_v12(token))

 def _load_selected_v12(self, token, row, source, listbox_index):
  ident = self._canonical_id(row, source); developed, standard = paths(source)[2], paths(source)[4]; started = time.monotonic()
  try:
   ready = developed.exists() and standard.exists() and cached_png_ready(source)
   log(ident, "navigation_cache_validation", "END", time.monotonic()-started, str(developed), detail=f"token={token} listbox_index={listbox_index} ready={ready} rawpy_nef_calls=0")
   if not ready:
    raise RuntimeError("Prepared PNG cache is missing or invalid; use local precache worker.")
   started = time.monotonic(); source_png = Image.open(developed).convert("RGB"); standardized = Image.open(standard).convert("RGB")
   log(ident, "navigation_png_load", "END", time.monotonic()-started, str(standard), detail=f"token={token} listbox_index={listbox_index} standardized={standardized.width}x{standardized.height}/{standardized.mode} rawpy_nef_calls=0")
   self._pending.put((token, "ok", row, source, listbox_index, source_png, standardized, None))
  except Exception as exc:
   error(ident, "navigation_loader", str(source), exc)
   self._pending.put((token, "error", row, source, listbox_index, None, None, str(exc)))

 def _poll_selected_v12(self, token):
  try:
   received, status, row, source, listbox_index, source_png, standardized, message = self._pending.get_nowait()
  except queue.Empty:
   if token == self._load_token:
    self.after(20, lambda: self._poll_selected_v12(token))
   return
  ident = self._canonical_id(row, source)
  if received != self._load_token:
   log(ident, "navigation_stale_load", "END", path=str(source), detail=f"token={received} current={self._load_token} listbox_index={listbox_index}")
   if token == self._load_token:
    self.after(1, lambda: self._poll_selected_v12(token))
   return
  if status != "ok":
   self.header.config(text="Image loading failed — see debug log")
   log(ident, "select_image_navigation", "ERROR", path=str(source), detail=message)
   return
  self.source, self.standard = source_png, standardized
  self._display_row, self._display_source = row, source
  self._display_image_id = self._canonical_id(row, source)
  self.source_mode = False
  self.record = load_record(row, self.profile.profile_id, self.profile.version)
  # Project navigation is cache-only: source hash was recorded at import.
  # Do not touch a remote RAW merely to fill an optional legacy field.
  if not self.record.get("source_sha256") and getattr(self,"project",None) is None:
   from .developed_cache_v2 import ensure
   self.record["source_sha256"] = ensure(source)["source_sha256"]
   save_record(self.record)
  self.state.open_record(self.record)
  self.zoom = min(1., 1050 / self.standard.width, 720 / self.standard.height)
  self.pan = [0., 0.]; self._render_signature = None; self._display_cache = None
  try:
   self.sync()
   self.header.config(text=f"STANDARDIZED MASTER (annotation) | {self.index+1}/{len(self.images)}")
  except Exception as exc:
   self.header.config(text="Image render failed — see app.log")
   error(ident, "navigation_render", str(source), exc)
   return
  self.navigation_results.append((listbox_index, ident, self._display_image_id))
  log(ident, "navigation_first_successful_render", "END", path=str(source), detail=f"token={token} listbox_index={listbox_index} displayed_filename={source.name} displayed_image_id={self._display_image_id} renders={self.navigation_render_counts.get(token, 0)} rawpy_nef_calls=0")

 def render(self):
  if self.standard is None or self._display_source is None:
   return
  points = tuple(sorted((key, tuple(sorted(value.items()))) for key, value in self.record.get("points", {}).items()))
  signature = (self._display_image_id, self.source_mode, round(self.zoom, 8), tuple(round(v, 3) for v in self.pan), self.state.current_landmark, points)
  if signature == self._render_signature:
   log(self._display_image_id, "main_render", "END", path=str(self._display_source), detail="skipped_unchanged=true")
   return
  self._render_signature = signature; token = self._load_token; started = time.monotonic(); ident = self._display_image_id
  log(ident, "main_render", "START", path=str(self._display_source), detail=f"token={token}")
  ReadyEditorV11.render(self)
  self.navigation_render_counts[token] = self.navigation_render_counts.get(token, 0) + 1
  log(ident, "main_render", "END", time.monotonic()-started, str(self._display_source), detail=f"token={token} count={self.navigation_render_counts[token]}")


def run():
 ReadyEditorV12().mainloop()


if __name__ == "__main__":
 run()








