"""Navigation-safe cache-only editor.

Image selection is tokenised: a loader that finishes after another selection
cannot paint stale pixels.  The landmark Listbox is also guarded against its
own programmatic selection events, which previously could recursively call
sync/render.
"""
from __future__ import annotations
import queue
import threading
import time
from pathlib import Path
from PIL import Image
from .editor_ready_v10 import ReadyEditorV10
from .developed_cache_v2 import cached_png_ready
from .gui_crop_debug import error, log
from .normalization_pipeline import paths
from .standardize import image_id
from .workflow import load_record, save_record


class ReadyEditorV11(ReadyEditorV10):
 def _canonical_id(self, row=None, source=None):
  if row is None:
   row = self.images[self.index] if getattr(self, "images", None) else None
  if getattr(self, "project", None) is not None and row and row.get("image_id"):
   return str(row["image_id"])
  return image_id(Path(source or row.get("source_relpath")))
 def __init__(self, project=None):
  if project is not None:self.project=project
  self._load_token = 0
  self._pending = queue.Queue()
  self._render_signature = None
  self._display_cache = None
  self._syncing = False
  self.navigation_render_counts = {}
  super().__init__(project=project)

 def pick_landmark(self, _=None):
  selection = self.landmarks.curselection()
  if not selection:
   return
  number = self.state.point_ids[selection[0]]
  # ListboxSelect emitted by sync is not a user selection and must not redraw.
  if self._syncing or number == self.state.current_landmark:
   return
  self.state.select(number)
  self.sync()

 def sync(self):
  if self._syncing:
   return
  self._syncing = True
  try:
   number = self.state.current_landmark
   self.landmarks.selection_clear(0, "end")
   self.landmarks.selection_set(number - 1)
   self.landmarks.see(number - 1)
   self.render()
  finally:
   self._syncing = False

 def pick_image(self, _=None):
  selection = self.images_box.curselection()
  if not selection or selection[0] == self.index:
   return
  self.index = selection[0]
  self.open_image()

 def open_image(self):
  row, source = self._choose_available()
  self._load_token += 1
  token = self._load_token
  ident = self._canonical_id(row, source)
  log(ident, "select_image_navigation", "START", path=str(source), detail=f"token={token}")
  self.header.config(text=f"Loading standardized image {self.index + 1}/{len(self.images)}…")
  threading.Thread(target=self._load_selected, args=(token, row, source), daemon=True,
                   name=f"editor-png-{ident}").start()
  self.after(20, lambda: self._poll_selected(token))

 def _load_selected(self, token, row, source):
  ident = self._canonical_id(row, source)
  developed, standard = paths(source)[2], paths(source)[4]
  started = time.monotonic()
  try:
   log(ident, "navigation_cache_validation", "START", path=str(developed), detail=f"token={token}")
   ready = developed.exists() and standard.exists() and cached_png_ready(source)
   log(ident, "navigation_cache_validation", "END", time.monotonic()-started, str(developed), detail=f"token={token} ready={ready} rawpy_nef_calls=0")
   if not ready:
    raise RuntimeError("Prepared PNG cache is missing or invalid; use local precache worker.")
   started = time.monotonic(); log(ident, "navigation_png_load", "START", path=str(standard), detail=f"token={token}")
   source_png = Image.open(developed).convert("RGB")
   standardized = Image.open(standard).convert("RGB")
   log(ident, "navigation_png_load", "END", time.monotonic()-started, str(standard), detail=f"token={token} standardized={standardized.width}x{standardized.height}/{standardized.mode} rawpy_nef_calls=0")
   self._pending.put((token, "ok", row, source, source_png, standardized, None))
  except Exception as exc:
   error(ident, "navigation_loader", str(source), exc)
   self._pending.put((token, "error", row, source, None, None, str(exc)))

 def _poll_selected(self, token):
  try:
   received, status, row, source, source_png, standardized, message = self._pending.get_nowait()
  except queue.Empty:
   if token == self._load_token:
    self.after(20, lambda: self._poll_selected(token))
   return
  if received != self._load_token:
   log(self._canonical_id(row, source), "navigation_stale_load", "END", path=str(source), detail=f"token={received} current={self._load_token}")
   # A stale item must not consume the selected image's poll loop.
   if token == self._load_token:
    self.after(1, lambda: self._poll_selected(token))
   return
  ident = self._canonical_id(row, source)
  if status != "ok":
   self.header.config(text="Image loading failed — see debug log")
   log(ident, "select_image_navigation", "ERROR", path=str(source), detail=message)
   return
  self.source, self.standard = source_png, standardized
  self.source_mode = False
  self.record = load_record(row, self.profile.profile_id, self.profile.version)
  # The cache metadata already validated this source; do not touch RAW.
  if not self.record.get("source_sha256"):
   from .developed_cache_v2 import ensure
   self.record["source_sha256"] = ensure(source)["source_sha256"]
   save_record(self.record)
  self.state.open_record(self.record)
  self.zoom = min(1., 1050 / self.standard.width, 720 / self.standard.height)
  self.pan = [0., 0.]
  self._render_signature = None
  self._display_cache = None
  self.sync()
  self.after_idle(self._fit_to_actual_canvas)
  log(ident, "navigation_first_successful_render", "END", path=str(source), detail=f"token={token} renders={self.navigation_render_counts.get(token, 0)} rawpy_nef_calls=0")

 def _canvas_post_render_diag(self,ident):
  try:
   items=self.canvas.find_all();iid=getattr(self,"_image_item_id",None);log(ident,"canvas_widget_diagnostic","END",detail=f"op=after_idle_render canvas_widget_path={self.canvas} canvas_parent={self.canvas.master} canvas_mapped={self.canvas.winfo_ismapped()} canvas_width={self.canvas.winfo_width()} canvas_height={self.canvas.winfo_height()} canvas_manager={self.canvas.winfo_manager()} canvas_item_count={len(items)} rendered_image_item_id={iid} rendered_image_bbox={self.canvas.bbox(iid) if iid else None}")
  except Exception as exc: log(ident,"canvas_widget_diagnostic","ERROR",detail=f"op=after_idle_render error={exc!r}")

 def _fit_to_actual_canvas(self):
  if self.standard is None or not getattr(self,"canvas",None): return
  cw,ch=self.canvas.winfo_width(),self.canvas.winfo_height()
  if cw<=2 or ch<=2:
   self.after(50,self._fit_to_actual_canvas);return
  fit=min(1.0,cw/self.standard.width,ch/self.standard.height)
  if abs(self.zoom-fit)>1e-6:
   self.zoom=fit;self.pan=[0.,0.];self._render_signature=None;self.sync()
  try:
   items=self.canvas.find_all();log(self._display_image_id,"canvas_widget_diagnostic","END",detail=f"op=after_idle_fit canvas_widget_path={self.canvas} canvas_parent={self.canvas.master} canvas_mapped={self.canvas.winfo_ismapped()} canvas_width={cw} canvas_height={ch} canvas_manager={self.canvas.winfo_manager()} canvas_item_count={len(items)} rendered_image_item_id={items[0] if items else None} rendered_image_bbox={self.canvas.bbox('all')}")
  except Exception: pass

 def render(self):
  if self.standard is None:
   return
  canonical=self.__dict__.get("landmark_state") if getattr(self,"project",None) is not None else None
  if canonical is not None and canonical.image_id==self.current().get("image_id"):
   points=canonical.fingerprint
  else:
   points=tuple(sorted((key, tuple(sorted(value.items()))) for key, value in self.record.get("points", {}).items()))
  signature = (id(self.image()), self.source_mode, round(self.zoom, 8), tuple(round(v, 3) for v in self.pan), self.state.current_landmark, points)
  ident = getattr(self, "_display_image_id", self._canonical_id(self.current(), self.current()["source_relpath"]))
  if getattr(self, "project", None) is not None:
   actual = self._canonical_id(self.current(), self.current()["source_relpath"])
   if actual != ident:
    log(ident, "project_image_id_mismatch", "ERROR", path=str(self.current()["source_relpath"]), detail=f"render_image_id={actual} expected_image_id={ident}")
    self.header.config(text="Image identity mismatch — see app.log")
    raise RuntimeError(f"project image_id mismatch: expected {ident}, got {actual}")
  if signature == self._render_signature:
   log(ident, "main_render", "END", path=str(self.current()["source_relpath"]), detail="skipped_unchanged=true")
   return
  self._render_signature = signature
  token = self._load_token
  started = time.monotonic()
  log(ident, "main_render", "START", path=str(self.current()["source_relpath"]), detail=f"token={token}")
  image = self.image()
  target = (max(1, round(image.width * self.zoom)), max(1, round(image.height * self.zoom)))
  cache_key = (id(image), target)
  t = time.monotonic()
  if self._display_cache is None or self._display_cache[0] != cache_key:
   display = image.resize(target, Image.Resampling.BILINEAR)
   self._display_cache = (cache_key, display)
  else:
   display = self._display_cache[1]
  log(ident, "gui_display_proxy", "END", time.monotonic()-t, str(self.current()["source_relpath"]), detail=f"size={display.width}x{display.height}")
  t = time.monotonic()
  from PIL import ImageTk
  self.photo = ImageTk.PhotoImage(display, master=self.canvas)
  log(ident, "gui_image_object_creation", "END", time.monotonic()-t, str(self.current()["source_relpath"]), detail=f"size={display.width}x{display.height}")
  t = time.monotonic()
  self.canvas.delete("image");self.canvas.delete("landmark_overlay")
  self._image_item_id=self.canvas.create_image(*self.pan, anchor="nw", image=self.photo, tags=("image",))
  log(ident, "canvas_image_assignment_and_handles", "END", time.monotonic()-t, str(self.current()["source_relpath"]), detail=f"size={display.width}x{display.height} canvas_item_count={len(self.canvas.find_all())} rendered_image_item_id={self._image_item_id} rendered_image_bbox={self.canvas.bbox(self._image_item_id)}")
  self.after_idle(lambda:self._canvas_post_render_diag(ident))
  if not self.source_mode:
   from .landmark_ids import number_from_id
   allowed_ids={point.number for point in self.profile.landmarks}
   extras=[]
   canvas_points=(canonical.points_by_id.items() if canonical is not None and canonical.image_id==self.current().get("image_id") else self.record.get("points", {}).items())
   for key, point_data in canvas_points:
    if point_data.get("state")=="missing" or point_data.get("x_standardized") is None or point_data.get("y_standardized") is None:
     continue
    x = self.pan[0] + point_data["x_standardized"] * self.zoom
    y = self.pan[1] + point_data["y_standardized"] * self.zoom
    number = int(key) if canonical is not None and canonical.image_id==self.current().get("image_id") else number_from_id(key)
    if number not in allowed_ids:
     extras.append(number)
     continue
    color = "#ffb000" if number == self.state.current_landmark else "#00e5ff"
    item_tags=("landmark_overlay", "landmark_handle", f"landmark:{number}")
    self.canvas.create_oval(x-5, y-5, x+5, y+5, outline=color, width=2, tags=item_tags)
    self.canvas.create_text(x+8, y-8, text=str(number), anchor="sw", fill=color, tags=("landmark_overlay", "landmark_label", f"landmark:{number}"))
   if extras:
    extras=sorted(set(extras))
    if not hasattr(self,"_orphan_landmark_logged"): self._orphan_landmark_logged=set()
    orphan_key=(getattr(self,"_display_image_id",ident),tuple(extras))
    if orphan_key not in self._orphan_landmark_logged:
     self._orphan_landmark_logged.add(orphan_key)
     log(ident,"orphan_landmarks_found","WARNING",path=str(self.current()["source_relpath"]),detail=f"extra_ids={extras}")
  point = self._point(self.state.current_landmark)
  mode = "SOURCE REVIEW (read-only)" if self.source_mode else "STANDARDIZED MASTER (annotation)"
  self.header.config(text=f"{mode} | {self.index+1}/{len(self.images)} | {point.number} {point.code}: {point.instruction}")
  self.navigation_render_counts[token] = self.navigation_render_counts.get(token, 0) + 1
  log(ident, "main_render", "END", time.monotonic()-started, str(self.current()["source_relpath"]), detail=f"token={token} count={self.navigation_render_counts[token]}")


def run():
 ReadyEditorV11().mainloop()


if __name__ == "__main__":
 run()















