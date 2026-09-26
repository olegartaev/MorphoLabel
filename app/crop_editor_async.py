"""Responsive visual crop editor: loading work is outside Tk thread."""
from __future__ import annotations
import queue,threading,time
import tkinter as tk
from pathlib import Path
from PIL import ImageTk
from .crop_editor import CropEditor
from .crop_model import CropModel
from .developed_cache import load_png,_event
from .io import read_json
from .normalization_pipeline import paths

class AsyncCropEditor(CropEditor):
 def __init__(self,parent,source:Path,on_done):
  tk.Toplevel.__init__(self,parent);self.title("Visual crop / rotation correction");self.geometry("1300x900");self.source=source;self.on_done=on_done;self.base=None;self.proxy=None;self.photo=None;self.zoom=.6;self.pan=[20.,20.];self.mode=None;self.anchor=None;self.reject=False;self.queue=queue.Queue();self.created=time.monotonic();self.loading=tk.Label(self,text="Loading cached developed_full image…",font=("Segoe UI",14));self.loading.pack(expand=True);_event(source,"crop_window_created",time.monotonic()-self.created)
  threading.Thread(target=self._load,daemon=True).start();self.after(30,self._poll)
 def _load(self):
  try:self.queue.put(("ok",load_png(self.source)))
  except Exception as exc:self.queue.put(("error",str(exc)))
 def _poll(self):
  try:kind,data=self.queue.get_nowait()
  except queue.Empty:self.after(30,self._poll);return
  if kind=="error":self.loading.config(text="Could not load cached image:\n"+data);return
  meta,full,proxy=data;self.base=full;self.proxy=proxy;self.display_scale=proxy.width/full.width;_,_,self.developed,_,self.standard,self.meta_path,_=paths(self.source);old=read_json(self.meta_path,{});crop=old.get("crop_bounds",[0,0,full.width,full.height]);self.model=CropModel(full.width,full.height,*crop,float(old.get("rotation_degrees",0))).clamp();self.loading.destroy();self._layout();self.render();_event(self.source,"crop_first_successful_render",time.monotonic()-self.created,cache=True)
 def pt(self,x,y):
  z=self.zoom*self.display_scale;return ((x-self.pan[0])/z,(y-self.pan[1])/z)
 def hit(self,x,y):
  l,t,r,b=self.model.left,self.model.top,self.model.right,self.model.bottom;tol=14/(self.zoom*self.display_scale);cx=(l+r)/2;hy=t-35/(self.zoom*self.display_scale)
  if (x-cx)**2+(y-hy)**2<tol**2:return "rotate"
  for name,px,py in (("lt",l,t),("rt",r,t),("lb",l,b),("rb",r,b)):
   if abs(x-px)<tol and abs(y-py)<tol:return name
  if abs(x-l)<tol and t<=y<=b:return "l"
  if abs(x-r)<tol and t<=y<=b:return "r"
  if abs(y-t)<tol and l<=x<=r:return "t"
  if abs(y-b)<tol and l<=x<=r:return "b"
  return "move" if l<=x<=r and t<=y<=b else None
 def render(self):
  shown=self.proxy.rotate(self.model.angle,resample=__import__('PIL.Image',fromlist=['Image']).Resampling.BICUBIC,expand=False,fillcolor=(255,255,255));shown=shown.resize((max(1,round(shown.width*self.zoom)),max(1,round(shown.height*self.zoom))));self.photo=ImageTk.PhotoImage(shown, master=self.canvas);self.canvas.delete("all");self.canvas.create_image(*self.pan,anchor="nw",image=self.photo);z=self.zoom*self.display_scale;l,t,r,b=[v*z for v in (self.model.left,self.model.top,self.model.right,self.model.bottom)];l+=self.pan[0];r+=self.pan[0];t+=self.pan[1];b+=self.pan[1];self.canvas.create_rectangle(l,t,r,b,outline="#00ff66",width=3)
  for x,y in ((l,t),(r,t),(l,b),(r,b)):self.canvas.create_rectangle(x-6,y-6,x+6,y+6,fill="#00ff66")
  cx=(l+r)/2;hy=t-35;self.canvas.create_line(cx,t,cx,hy,fill="#ffcc00",width=2);self.canvas.create_oval(cx-8,hy-8,cx+8,hy+8,fill="#ffcc00");self.canvas.create_text(l,t-10,anchor="sw",fill="#00ff66",text=f"rotation {self.model.angle:.1f}°")

