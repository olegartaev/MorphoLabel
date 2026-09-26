"""Visual developed_full crop/rotation correction. No numeric user entry."""
from __future__ import annotations
import math
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageTk
from .crop_model import CropModel
from .io import atomic_json_write,read_json
from .normalization_pipeline import paths,develop_full
from .paths import require_relative
from .transforms import Transform
from .crop_training import current_label,save_correction
from .png_atomic import atomic_save_png
from .crop_quality import assess_crop
from .gui_crop_debug import log


def calculate_initial_crop_view(crop_bounds, display_scale, viewport_width, viewport_height, current_zoom, *, margin_ratio=.04, minimum_margin=24, rotation_space=48):
 """Fit the visible crop and its handles without changing scientific coordinates."""
 left, top, right, bottom = (float(value) for value in crop_bounds)
 width = max(2.0, right - left); height = max(2.0, bottom - top)
 viewport_width = max(1.0, float(viewport_width)); viewport_height = max(1.0, float(viewport_height)); display_scale = max(1e-9, float(display_scale))
 margin_x = max(float(minimum_margin), viewport_width * float(margin_ratio)); margin_y = max(float(minimum_margin), viewport_height * float(margin_ratio))
 available_width = max(1.0, viewport_width - 2 * margin_x)
 available_height = max(1.0, viewport_height - 2 * margin_y - float(rotation_space))
 fit_image_scale = min(available_width / width, available_height / height)
 fit_zoom = fit_image_scale / display_scale
 zoom = min(float(current_zoom), fit_zoom)
 image_scale = zoom * display_scale
 shown_width = width * image_scale; shown_height = height * image_scale
 crop_screen_left = (viewport_width - shown_width) / 2
 crop_screen_top = float(rotation_space) + (viewport_height - float(rotation_space) - shown_height) / 2
 return {"zoom": zoom, "pan": (crop_screen_left - left * image_scale, crop_screen_top - top * image_scale), "margin_x": margin_x, "margin_y": margin_y, "rotation_space": float(rotation_space), "auto_fit": fit_zoom < float(current_zoom), "fit_zoom": fit_zoom, "displayed_crop": (crop_screen_left, crop_screen_top, crop_screen_left + shown_width, crop_screen_top + shown_height)}

class CropEditor(tk.Toplevel):
 def __init__(self,parent,source:Path,on_done):
  super().__init__(parent);self.title("Visual crop / rotation correction — developed full image");self.geometry("1300x900");self.source=source;self.on_done=on_done;self.base=None;self.photo=None;self.zoom=.16;self.pan=[20.,20.];self.mode=None;self.anchor=None;self.reject=False
  _,ident,developed,dev_meta,standard,meta_path,_=paths(source);self.ident=ident;self.developed=developed;self.standard=standard;self.meta_path=meta_path;develop_full(source);self.base=Image.open(developed).convert("RGB");meta=read_json(meta_path,{})
  crop=meta.get("crop_bounds",[0,0,self.base.width,self.base.height]);self.predicted_crop=tuple(crop);self.model=CropModel(self.base.width,self.base.height,*crop,float(meta.get("rotation_degrees",0))).clamp();self._layout();self.render()
 def _layout(self):
  bar=ttk.Frame(self,padding=6);bar.pack(fill="x");ttk.Button(bar,text="Apply",command=self.accept).pack(side="left");ttk.Button(bar,text="Reset auto crop",command=self.reset).pack(side="left");ttk.Button(bar,text="Reject automatic proposal",command=self.reject_proposal).pack(side="left");ttk.Button(bar,text="Cancel",command=self.cancel).pack(side="right");ttk.Label(bar,text="Left-drag handles/edges/inside. Rotation handle above crop. Wheel zoom; right-drag pan.").pack(side="left",padx=12);self.crop_qc_label=ttk.Label(bar,text="");self.crop_qc_label.pack(side="left",padx=6)
  self.canvas=tk.Canvas(self,bg="#222",highlightthickness=0);self.canvas.pack(fill="both",expand=True);self.canvas.bind("<Button-1>",self.down);self.canvas.bind("<B1-Motion>",self.drag);self.canvas.bind("<ButtonRelease-1>",self.up);self.canvas.bind("<Button-3>",self.right_down);self.canvas.bind("<B3-Motion>",self.right_drag);self.canvas.bind("<MouseWheel>",self.wheel)
 def pt(self,x,y):return ((x-self.pan[0])/self.zoom,(y-self.pan[1])/self.zoom)
 def _assert_gui_thread(self,operation):
  if threading.current_thread() is not threading.main_thread():
   import logging;logging.getLogger("morphology.crop").error("crop_gui_thread_violation operation=%s thread=%s",operation,threading.current_thread().name);return False
  return True
 def _draw_overlay(self):
  self.canvas.delete("crop_overlay")
  l,t,r,b=[v*self.zoom for v in (self.model.left,self.model.top,self.model.right,self.model.bottom)];l+=self.pan[0];r+=self.pan[0];t+=self.pan[1];b+=self.pan[1]
  self.canvas.create_rectangle(l,t,r,b,outline="#00ff66",width=3,tags="crop_overlay")
  for x,y in ((l,t),(r,t),(l,b),(r,b)):self.canvas.create_rectangle(x-6,y-6,x+6,y+6,fill="#00ff66",tags="crop_overlay")
  cx=(l+r)/2;hy=t-35;self.canvas.create_line(cx,t,cx,hy,fill="#ffcc00",width=2,tags="crop_overlay");self.canvas.create_oval(cx-8,hy-8,cx+8,hy+8,fill="#ffcc00",tags="crop_overlay");self.canvas.create_text(l,t-10,anchor="sw",fill="#00ff66",text=f"rotation {self.model.angle:.1f}°",tags="crop_overlay")
 def render(self):
  if not self._assert_gui_thread("render"):return
  self.crop_quality=assess_crop((self.model.left,self.model.top,self.model.right,self.model.bottom),self.base.width,self.base.height);self.crop_qc_label.config(text=f"Crop QC: {self.crop_quality.level.upper()} — {self.crop_quality.reasons[0]}")
  image_signature=(round(self.zoom,6),tuple(round(v,2) for v in self.pan),round(self.model.angle,3))
  if image_signature!=getattr(self,"_image_signature",None):
   shown=self.base.rotate(self.model.angle,resample=Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255)).resize((max(1,round(self.base.width*self.zoom)),max(1,round(self.base.height*self.zoom))))
   old_photo=getattr(self,"photo",None);new_photo=ImageTk.PhotoImage(shown,master=self.canvas);self.photo=new_photo;self._image_signature=image_signature
   self.canvas.delete("all");self._image_item=self.canvas.create_image(*self.pan,anchor="nw",image=self.photo)
   # Drop the old Tk image only on the GUI thread, after canvas reassignment.
   old_photo=None
  self._draw_overlay()
 def hit(self,x,y):
  l,t,r,b=self.model.left,self.model.top,self.model.right,self.model.bottom;tol=14/self.zoom;cx=(l+r)/2;hy=t-35/self.zoom
  if (x-cx)**2+(y-hy)**2<tol**2:return "rotate"
  for name,px,py in (("lt",l,t),("rt",r,t),("lb",l,b),("rb",r,b)):
   if abs(x-px)<tol and abs(y-py)<tol:return name
  if abs(x-l)<tol and t<=y<=b:return "l"
  if abs(x-r)<tol and t<=y<=b:return "r"
  if abs(y-t)<tol and l<=x<=r:return "t"
  if abs(y-b)<tol and l<=x<=r:return "b"
  if l<=x<=r and t<=y<=b:return "move"
  return None
 def down(self,e):self.mode=self.hit(*self.pt(e.x,e.y));self.anchor=self.pt(e.x,e.y);self.initial=(self.model.left,self.model.top,self.model.right,self.model.bottom,self.model.angle)
 def drag(self,e):
  if not self.mode:return
  x,y=self.pt(e.x,e.y);ax,ay=self.anchor
  if self.mode=="move":self.model.left,self.model.top,self.model.right,self.model.bottom=self.initial[:4];self.model.move(x-ax,y-ay)
  elif self.mode=="rotate":
   cx,cy=self.model.center;self.model.angle=math.degrees(math.atan2(y-cy,x-cx))+90
  else:self.model.set_edge(self.mode,x,y)
  self.render()
 def up(self,e):self.mode=None
 def right_down(self,e):self.anchor=(e.x,e.y)
 def right_drag(self,e):
  if not self.anchor:return
  dx=e.x-self.anchor[0];dy=e.y-self.anchor[1];self.pan[0]+=dx;self.pan[1]+=dy;self.anchor=(e.x,e.y);self.render()
 def wheel(self,e):
  old=self.zoom;self.zoom=max(.03,min(4.,old*(1.15 if e.delta>0 else 1/1.15)));self.pan[0]=e.x-(e.x-self.pan[0])*self.zoom/old;self.pan[1]=e.y-(e.y-self.pan[1])*self.zoom/old;self.render()
 def reset(self):self.model=CropModel(self.base.width,self.base.height,0,0,self.base.width,self.base.height,0);self.reject=False;self.render()
 def reject_proposal(self):
  old=read_json(self.meta_path,{});old.setdefault("normalization_history",[]).append({"event":"automatic_proposal_rejected","proposal_crop":old.get("crop_bounds"),"proposal_rotation":old.get("rotation_degrees")});atomic_json_write(self.meta_path,old);self.reject=True;self.reset();messagebox.showinfo("Proposal rejected","Automatic proposal saved as rejected. Draw a new crop on the complete developed image.")
 def cancel(self):
  self.destroy()
 def _old_project_transform_for_remap(self):
  """Return the previous standardized transform, refusing unsafe coordinate guesses."""
  rows=self.project.load_landmarks(self.ident).values()
  needs_transform=any((row.get("x_standardized") is not None and row.get("y_standardized") is not None) or (row.get("predicted_x") is not None and row.get("predicted_y") is not None) for row in rows)
  if not needs_transform:return None
  crop=self.project.crop_record(self.ident) or {};stored=crop.get("transform_json")
  if stored:return Transform(**stored)
  bounds=crop.get("crop_json")
  if isinstance(bounds,(list,tuple)) and len(bounds)==4:
   left,top,right,bottom=(round(float(value)) for value in bounds)
   if right>left and bottom>top:return Transform(self.base.width,self.base.height,float(crop.get("rotation_degrees") or 0),self.base.width/2,self.base.height/2,left,top,right-left,bottom-top)
  if self.standard.exists():
   with Image.open(self.standard) as standard:
    if standard.size==(self.base.width,self.base.height):return Transform(self.base.width,self.base.height,0,self.base.width/2,self.base.height/2,0,0,self.base.width,self.base.height)
  raise ValueError("Cannot safely change crop: previous landmark transform is unavailable.")
 def accept(self):
  old_transform=self._old_project_transform_for_remap() if getattr(self,"project",None) is not None else None
  rotated=self.base.rotate(self.model.angle,resample=Image.Resampling.BICUBIC,expand=False,fillcolor=(255,255,255));crop=(round(self.model.left),round(self.model.top),round(self.model.right),round(self.model.bottom));master=rotated.crop(crop);new_transform=Transform(self.base.width,self.base.height,self.model.angle,self.base.width/2,self.base.height/2,crop[0],crop[1],master.width,master.height);atomic_save_png(master,self.standard,self.ident)
  transform=new_transform.__dict__
  if getattr(self,"project",None) is not None:
   self.project.save_reviewed_crop(self.ident,{"developed_full_relpath":f"cache/developed/{self.ident}.png","standardized_relpath":f"cache/standardized/{self.ident}.png","crop_bounds":list(crop),"rotation_degrees":self.model.angle,"transform":transform,"normalization_status":"PASS","source_sha256":None});result=self.project.remap_landmarks_for_transform(self.ident,old_transform,new_transform);log(self.ident,"landmark_transform_remap","END",path=str(self.source),detail="present_before={} present_after={} outside_count={} old_rotation={} new_rotation={}".format(result["present_before"],result["present_after"],result["outside_count"],getattr(old_transform,"rotation_degrees",None),new_transform.rotation_degrees))
  else:
   save_correction(self.ident,self.source,self.developed,self.base.width,self.base.height,getattr(self,"predicted_crop",crop),crop,current_label());old=read_json(self.meta_path,{})
   old.setdefault("normalization_history",[]).append({"event":"human_crop_accepted","rejected_auto":self.reject,"crop":list(crop),"rotation_degrees":self.model.angle});old.update({"standardized_relpath":require_relative(self.standard),"normalization_status":"PASS","qc_reason":"human_corrected_accepted","normalization_algorithm":"human_visual_crop_rotation_v1","crop_bounds":list(crop),"rotation_degrees":self.model.angle,"mirrored":False,"interpolation":"bicubic","transform":transform});atomic_json_write(self.meta_path,old)
  callback=self.on_done;parent=self.master;self.destroy()
  try:parent.after_idle(callback)
  except tk.TclError:callback()
