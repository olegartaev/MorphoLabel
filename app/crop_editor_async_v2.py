"""Diagnostic crop editor: never leaves a silent loading window."""
from __future__ import annotations
import queue,threading,time
import tkinter as tk
from pathlib import Path
from PIL import ImageTk
from .crop_editor_async import AsyncCropEditor
from .crop_editor import calculate_initial_crop_view
from .crop_model import CropModel
from .developed_cache_v2 import load_png
from .gui_crop_debug import dump_threads,error,log,trace
from .io import read_json
from .normalization_pipeline import paths
from .standardize import image_id
from .project_runtime import active_project
from .crop_training import current_label

def load_project_developed(project, canonical_image_id):
 """Use the fast developed cache when present; rebuild it from the linked source on a miss."""
 from PIL import Image
 target=project.cache_root/"developed"/f"{canonical_image_id}.png"
 if not target.exists():
  source=project.image_path(canonical_image_id)
  if not source or not Path(source).is_file():
   raise FileNotFoundError("Original image is unavailable and no developed cache exists.")
  from .normalization_pipeline import develop_full
  develop_full(Path(source),project=project,image_id_value=canonical_image_id)
 if not target.is_file():
  raise FileNotFoundError("Developed cache could not be rebuilt from the original image.")
 with Image.open(target) as opened:
  opened.load(); full=opened.convert("RGB")
 proxy=full.copy(); proxy.thumbnail((1800,1800)); return full,proxy

class AsyncCropEditorV2(AsyncCropEditor):
 def __init__(self,parent,source:Path,on_done,project=None,image_id_value=None,batch_diagnostics=None,batch_index=None,batch_total=None):
  self.project=project or active_project(); self.ident=str(image_id_value or image_id(source)); self.batch_diagnostics=batch_diagnostics;self.batch_index=batch_index;self.batch_total=batch_total;self._batch_close_started=False;self.created=time.monotonic(); log(self.ident,"crop_editor_window_creation","START",path=str(source))
  tk.Toplevel.__init__(self,parent);self.title("Visual crop / rotation correction");self.geometry("1100x760");self.minsize(760,520);self.source=source;self.on_done=on_done;self.base=None;self.proxy=None;self.photo=None;self.zoom=.6;self.pan=[20.,20.];self.mode=None;self.anchor=None;self.reject=False;self.queue=queue.Queue();self.rendered=False;self.first_callback=False;self._render_signature=None;self._initial_view_fitted=False;self._initial_fit_tries=0;self.loading=tk.Label(self,text="Loading developed cache…",font=("Segoe UI",14));self.loading.pack(expand=True);self.retry_button=tk.Button(self,text="Cancel",command=self.cancel)
  log(self.ident,"crop_editor_window_creation","END",time.monotonic()-self.created,path=str(source));self._batch_event("crop_batch_editor_opened","END",detail="editor_window_created");self.bind("<Destroy>",self._on_destroy,add="+");self._start_loader();self.after(30,self._poll);self.after(10_000,self._watchdog);self.after(20_000,self._timeout)
 def _batch_event(self,name,state="END",detail=""):
  if self.batch_diagnostics:self.batch_diagnostics.event(name,state,image_id=self.ident,path=str(self.source),batch_index=self.batch_index,batch_total=self.batch_total,detail=detail)
 def _batch_begin(self,name,detail=""):
  if self.batch_diagnostics:self.batch_diagnostics.begin(name,image_id=self.ident,path=str(self.source),batch_index=self.batch_index,batch_total=self.batch_total,detail=detail)
 def _batch_end(self,name,detail=""):
  if self.batch_diagnostics:self.batch_diagnostics.end(name,image_id=self.ident,path=str(self.source),batch_index=self.batch_index,batch_total=self.batch_total,detail=detail)
 def _on_destroy(self,event):
  if event.widget is self:
   self._batch_event("crop_batch_editor_close","END",detail="editor_destroyed");self._batch_event("crop_batch_editor_closed","END",detail="editor_destroyed")

 def _start_loader(self):
  log(self.ident,"background_loader","START",path=str(self.source));threading.Thread(target=self._load,daemon=True,name=f"crop-png-{self.ident}").start()
 def retry(self):
  log(self.ident,"retry","START",path=str(self.source));self.retry_button.pack_forget();self.loading.config(text="Loading cached developed_full image…");self._start_loader();self.after(30,self._poll);log(self.ident,"retry","END",path=str(self.source))
 def _load(self):
  ident=getattr(self,"ident",image_id(self.source)); created=getattr(self,"created",time.monotonic())
  try:
   
   if getattr(self,"project",None):
    full,proxy=load_project_developed(self.project,self.ident);result=({},full,proxy)
   else: result=load_png(self.source)
   self.queue.put(("ok",result));log(ident,"background_loader","END",time.monotonic()-created,path=str(self.source),detail="rawpy_nef_calls=0")
  except Exception as exc:
   error(ident,"background_loader",str(self.source),exc);self.queue.put(("error",str(exc)))
 def _poll(self):
  if not self.first_callback: self.first_callback=True;log(self.ident,"first_scheduled_ui_callback","END",time.monotonic()-self.created,path=str(self.source))
  try:kind,data=self.queue.get_nowait()
  except queue.Empty:
   if not self.rendered:self.after(100,self._poll)
   return
  if kind=="error":
   self._batch_end("crop_batch_editor_open",detail=f"editor_ready=false error={data}");self._batch_event("crop_batch_editor_error","ERROR",detail=data)
   self.loading.config(text="Original image is unavailable and no developed cache exists.");self.retry_button.pack();log(self.ident,"ui_loader_result","ERROR",path=str(self.source),detail=data);return
  try:
   meta,full,proxy=data;self.base=full;self.proxy=proxy;self.display_scale=proxy.width/full.width;self._batch_event("crop_batch_editor_opened","END",detail=f"image_width={full.width} image_height={full.height} developed_path={getattr(self,'developed','pending')}")
   if self.project:
    self.developed=self.project.cache_root/"developed"/f"{self.ident}.png";self.standard=self.project.cache_root/"standardized"/f"{self.ident}.png";self.meta_path=None;old={}
    with self.project.transaction() as c:
     row=c.execute("SELECT crop_json,rotation_degrees,provenance,model_id,status FROM crops WHERE image_id=?",(self.ident,)).fetchone()
    if row and row[0]: import json; old={"crop_bounds":json.loads(row[0]),"rotation_degrees":row[1] or 0}
    elif self.meta_path is not None: old=read_json(self.meta_path,{})
    else: old=read_json(self.project.cache_root/"metadata"/f"{self.ident}.json",{})
    active_model=current_label(self.project);stored_model=(row["model_id"] if row else old.get("crop_model_version"));stored_provenance=(row["provenance"] if row else "prepared_proposal");stored_status=(row["status"] if row else old.get("normalization_status"))
    log(self.ident,"crop_editor_proposal_diagnostic","END",path=str(self.source),detail=f"active_crop_model_id={active_model} inference_executed=false reason=editor_uses_persisted_crop_record stored_crop_record={bool(row and row[0])} stored_model_id={stored_model} stored_provenance={stored_provenance} stored_status={stored_status} raw_model_output=unavailable_at_editor_open confidence=unavailable")
   else:
    _,_,self.developed,_,self.standard,self.meta_path,_=paths(self.source);old=read_json(self.meta_path,{})
   crop=old.get("crop_bounds",[0,0,full.width,full.height]);self.predicted_crop=tuple(crop);self.model=CropModel(full.width,full.height,*crop,float(old.get("rotation_degrees",0))).clamp();log(self.ident,"crop_editor_gui_rectangle","END",path=str(self.source),detail=f"final_crop_rectangle_sent_to_gui={tuple(round(v,3) for v in (self.model.left,self.model.top,self.model.right,self.model.bottom))} full_image_fallback={not bool(old.get('crop_bounds'))} image_width={full.width} image_height={full.height}");log(self.ident,"crop_editor_opened","END",time.monotonic()-self.created,path=str(self.source),detail=f"image_width={full.width} image_height={full.height} crop={tuple(round(v,3) for v in crop)} rotation={self.model.angle:.3f} zoom={self.zoom:.5f} source_id={self.ident}");log(self.ident,"canvas_widget_creation","START",path=str(self.source));self.loading.destroy();self._layout();self.canvas.bind("<Configure>",self._crop_canvas_configure,add="+");log(self.ident,"canvas_widget_creation","END",path=str(self.source));self.render();self.after_idle(self._fit_initial_crop_view);self.rendered=True;self._batch_end("crop_batch_editor_open",detail="editor_ready=true");self._batch_event("crop_batch_editor_ready","END",detail=f"crop={self._crop_values()} rotation={self.model.angle:.3f}");log(self.ident,"first_successful_render","END",time.monotonic()-self.created,path=str(self.source),detail="rawpy_nef_calls=0");self.after(20,self._event_loop_responsive)
  except Exception as exc:
   self._batch_end("crop_batch_editor_open",detail=f"editor_ready=false exception={exc!r}");self._batch_event("crop_batch_editor_error","ERROR",detail=repr(exc))
   error(self.ident,"ui_loader_result",str(self.source),exc);self.loading.config(text="Original image is unavailable and no developed cache exists.");self.retry_button.pack()
 def render(self):
  signature=(round(self.zoom,8),tuple(round(v,3) for v in self.pan),round(self.model.angle,4),self.proxy.size)
  image_changed=signature!=self._render_signature;self._render_signature=signature;started=time.monotonic()
  if image_changed:log(self.ident,"gui_image_object_creation","START",path=str(self.source))
  super().render()
  if image_changed:log(self.ident,"gui_image_object_creation","END",time.monotonic()-started,str(self.source));log(self.ident,"canvas_image_assignment_and_handles","END",path=str(self.source))
  else:trace(self.ident,"crop_overlay_geometry_update",path=str(self.source),detail="photoimage_recreated=false")
 def _crop_canvas_configure(self,event):
  trace(self.ident,"crop_canvas_resize",path=str(self.source),detail=f"viewport_width={event.width} viewport_height={event.height}")
  if not self._initial_view_fitted:self.after_idle(self._fit_initial_crop_view)
 def _fit_initial_crop_view(self):
  if self._initial_view_fitted or not getattr(self,"canvas",None):return
  width,height=self.canvas.winfo_width(),self.canvas.winfo_height()
  if (width<100 or height<100) and self._initial_fit_tries<10:
   self._initial_fit_tries+=1;self.after(30,self._fit_initial_crop_view);return
  self._initial_view_fitted=True
  view=calculate_initial_crop_view((self.model.left,self.model.top,self.model.right,self.model.bottom),self.display_scale,width,height,self.zoom)
  self.zoom=view["zoom"];self.pan=list(view["pan"])
  log(self.ident,"crop_initial_view","END",path=str(self.source),detail=f"viewport_width={width} viewport_height={height} canvas_width={width} canvas_height={height} display_scale={self.display_scale:.7f} zoom={self.zoom:.7f} pan=({self.pan[0]:.3f},{self.pan[1]:.3f}) margin_x={view['margin_x']:.2f} margin_y={view['margin_y']:.2f} rotation_space={view['rotation_space']:.2f} displayed_crop={tuple(round(v,2) for v in view['displayed_crop'])} auto_fit={view['auto_fit']} fallback={width<100 or height<100}")
  try:self.render()
  except Exception as exc:error(self.ident,"crop_initial_view_render",str(self.source),exc)
 def _crop_values(self):
  return tuple(round(value,3) for value in (self.model.left,self.model.top,self.model.right,self.model.bottom,self.model.angle))
 def down(self,event):
  before=self._crop_values();super().down(event);log(self.ident,"crop_handle_press","END",path=str(self.source),detail=f"screen=({event.x},{event.y}) handle={self.mode} before={before}")
 def drag(self,event):
  before=self._crop_values();super().drag(event);trace(self.ident,"crop_handle_drag",path=str(self.source),detail=f"handle={self.mode} screen=({event.x},{event.y}) before={before} after={self._crop_values()}")
 def up(self,event):
  handle=self.mode;before=self._crop_values();super().up(event);log(self.ident,"crop_handle_release","END",path=str(self.source),detail=f"handle={handle} screen=({event.x},{event.y}) before={before} after={self._crop_values()}")
 def right_down(self,event):
  super().right_down(event);log(self.ident,"crop_pan_press","END",path=str(self.source),detail=f"screen=({event.x},{event.y}) pan=({self.pan[0]:.3f},{self.pan[1]:.3f})")
 def right_drag(self,event):
  before=tuple(self.pan);super().right_drag(event);trace(self.ident,"crop_pan_drag",path=str(self.source),detail=f"screen=({event.x},{event.y}) before={before} after={tuple(round(v,3) for v in self.pan)}")
 def wheel(self,event):
  before=self.zoom;super().wheel(event);log(self.ident,"crop_zoom","END",path=str(self.source),detail=f"delta={event.delta} screen=({event.x},{event.y}) before={before:.7f} after={self.zoom:.7f} pan=({self.pan[0]:.3f},{self.pan[1]:.3f})")
 def reset(self):
  log(self.ident,"crop_reset_auto","START",path=str(self.source),detail=f"before={self._crop_values()}");super().reset();log(self.ident,"crop_reset_auto","END",path=str(self.source),detail=f"after={self._crop_values()}")
 def reject_proposal(self):
  self._batch_event("crop_batch_reject_automatic_proposal","START",detail=f"crop={self._crop_values()}");log(self.ident,"crop_reject_automatic_proposal","START",path=str(self.source),detail=f"crop={self._crop_values()}");super().reject_proposal();log(self.ident,"crop_reject_automatic_proposal","END",path=str(self.source),detail=f"crop={self._crop_values()}");self._batch_event("crop_batch_reject_automatic_proposal","END",detail=f"crop={self._crop_values()}")
 def cancel(self):
  self._batch_event("crop_batch_cancel_pressed","END",detail=f"crop={self._crop_values()}");self._batch_event("crop_batch_editor_close","START",detail="reason=cancel")
  if not self.batch_diagnostics:return super().cancel()
  callback=self.on_done;parent=self.master;self.destroy()
  try:parent.after_idle(callback)
  except tk.TclError:callback()
 def accept(self):
  self._batch_event("crop_batch_apply_pressed","END",detail=f"crop={self._crop_values()}");self._batch_begin("crop_batch_crop_save",detail=f"crop_before_save={self._crop_values()}");self._batch_begin("crop_batch_crop_correction_write",detail=f"crop_before_write={self._crop_values()}")
  self._batch_event("crop_batch_editor_close","START",detail="reason=apply")
  log(self.ident,"crop_apply","START",path=str(self.source),detail=f"saved_crop={self._crop_values()} reject_auto={self.reject}")
  self._applied=True
  try:super().accept()
  except Exception as exc:
   if self.batch_diagnostics:
    self.batch_diagnostics.failure("crop_batch_crop_correction_write",exc,image_id=self.ident,path=str(self.source),batch_index=self.batch_index,batch_total=self.batch_total)
    self.batch_diagnostics.failure("crop_batch_crop_save",exc,image_id=self.ident,path=str(self.source),batch_index=self.batch_index,batch_total=self.batch_total)
   error(self.ident,"crop_apply",str(self.source),exc);raise
  self._batch_end("crop_batch_crop_correction_write",detail=f"saved_crop={self._crop_values()} training_example_write=completed")
  self._batch_end("crop_batch_crop_save",detail=f"saved_crop={self._crop_values()} final_status=PASS")
  log(self.ident,"crop_apply","END",path=str(self.source),detail=f"saved_crop={self._crop_values()} final_status=PASS")

 def _event_loop_responsive(self):
  log(self.ident,"event_loop_responsive","END",time.monotonic()-self.created,path=str(self.source))
 def _watchdog(self):
  if not self.rendered:
   dump_threads(self.ident,"no_first_render_after_10_seconds");self.after(10_000,self._watchdog)
 def _timeout(self):
  if not self.rendered:
   log(self.ident,"first_render_timeout","ERROR",20.,str(self.source),"showing_retry=true");self.loading.config(text="Image loading failed or stalled — see debug log");self.retry_button.pack()
