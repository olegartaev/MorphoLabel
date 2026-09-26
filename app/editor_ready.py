"""Single-state standardized-image landmark editor.
Annotations are disabled in source review mode by design.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog
from pathlib import Path
from collections import Counter
from PIL import ImageTk
from .editor_state import EditorState
from .paths import ORIGINALS,ROOT
from .identity import apply_window_identity
from .profile import load_schema_profile
from .standardize import decode
from .standardize_working import standardized_master
from .workflow import image_catalog,load_record,save_record,set_human_point
from .manifest import sha256
from .storage import load_calibration,save_calibration
from .landmark_ids import landmark_id,number_from_id,list_index_to_number,number_to_list_index,record_key

class ReadyEditor(tk.Tk):
 def __init__(self, project=None):
  self.project=project;super().__init__();apply_window_identity(self);self.geometry("1450x920");self.profile=load_schema_profile(project.schema_path if project is not None else ROOT / "landmark_schema.csv");self.images=image_catalog();self.index=0;self.state=EditorState(point_ids=tuple(x.number for x in self.profile.landmarks));self.record={};self.standard=None;self.source=None;self.source_mode=False;self.zoom=1.;self.pan=[0.,0.];self.dragging=None;self.right_anchor=None;self.calibration=None;self._layout();self.open_image()
 def _layout(self):
  p=ttk.PanedWindow(self,orient=tk.HORIZONTAL);p.pack(fill=tk.BOTH,expand=True);left=ttk.Frame(p,padding=8);p.add(left,weight=1);right=ttk.Frame(p,padding=8);p.add(right,weight=5)
  self.left_split=tk.PanedWindow(left,orient=tk.VERTICAL,sashrelief=tk.RAISED,showhandle=True);self.left_split.pack(fill=tk.BOTH,expand=True)
  self.photo_pane=ttk.Frame(self.left_split);self.landmark_pane=ttk.Frame(self.left_split);self.left_split.add(self.photo_pane,minsize=140);self.left_split.add(self.landmark_pane,minsize=220)
  self.photo_list_frame=ttk.Frame(self.photo_pane);self.photo_list_frame.pack(fill=tk.BOTH,expand=True)
  self.images_box=tk.Listbox(self.photo_list_frame,width=48,exportselection=False);self.images_box.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
  self.photo_scrollbar=ttk.Scrollbar(self.photo_list_frame,orient=tk.VERTICAL,command=self.images_box.yview);self.photo_scrollbar.pack(side=tk.RIGHT,fill=tk.Y);self.images_box.configure(yscrollcommand=self.photo_scrollbar.set)
  self.images_box.bind("<MouseWheel>",lambda e:self.images_box.yview_scroll(-1 if e.delta>0 else 1,"units"));counts=Counter(r["sample_id"] for r in self.images)
  for r in self.images:self.images_box.insert(tk.END,f"{r.get('locality',r['sample_id'])} | {Path(r['source_relpath']).name} ({r.get('index_in_locality',1)} | {r.get('total_in_locality',counts[r['sample_id']])})")
  self.images_box.bind("<<ListboxSelect>>",self.pick_image);self.images_box.selection_set(0)
  self.landmark_list_frame=ttk.Frame(self.landmark_pane);self.landmark_list_frame.pack(fill=tk.BOTH,expand=True,pady=(0,5))
  self.landmarks=tk.Listbox(self.landmark_list_frame,height=10,exportselection=False);self.landmarks.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
  self.landmark_scrollbar=ttk.Scrollbar(self.landmark_list_frame,orient=tk.VERTICAL,command=self.landmarks.yview);self.landmark_scrollbar.pack(side=tk.RIGHT,fill=tk.Y);self.landmarks.configure(yscrollcommand=self.landmark_scrollbar.set)
  self.landmarks.bind("<MouseWheel>",lambda e:self.landmarks.yview_scroll(-1 if e.delta>0 else 1,"units"))
  for x in self.profile.landmarks:self.landmarks.insert(tk.END,f"{x.number} {x.code} — {x.name}")
  self.landmarks.bind("<<ListboxSelect>>",self.pick_landmark)
  for text,fn in (("Mark missing (M)",self.missing),("Remove (Del)",self.remove),("Calibrate sample",self.start_calibration),("Source / standardized",self.toggle_source)):
   ttk.Button(self.landmark_pane,text=text,command=fn).pack(fill=tk.X)
  self.header=ttk.Label(right,font=("Segoe UI",11));self.header.pack(anchor="w");self.canvas=tk.Canvas(right,bg="#262626",highlightthickness=0);self.canvas.pack(fill=tk.BOTH,expand=True)
  self.canvas.bind("<Button-1>",self.left_down);self.canvas.bind("<B1-Motion>",self.left_drag);self.canvas.bind("<ButtonRelease-1>",self.left_up);self.canvas.bind("<Button-3>",self.right_down);self.canvas.bind("<B3-Motion>",self.right_drag);self.canvas.bind("<MouseWheel>",self.wheel)
  self.bind("m",lambda _:self.missing());self.bind("<Delete>",lambda _:self.remove());self.bind("<BackSpace>",lambda _:self.remove());self.bind("<Control-z>",lambda _:self.undo())
 def _point(self,identifier):
  return self.profile.by_id(identifier) if hasattr(self.profile,"by_id") else next(p for p in self.profile.landmarks if getattr(p,"number",None)==identifier or self.profile.landmarks.index(p)+1==identifier)
 def current(self):return self.images[self.index]
 def image_point(self,x,y):return ((x-self.pan[0])/self.zoom,(y-self.pan[1])/self.zoom)
 def open_image(self):
  row=self.current();src=Path(row["source_relpath"]);meta=standardized_master(src);self.source=decode(src);self.standard=decode(Path(meta["standardized_relpath"]));self.source_mode=False;self.record=load_record(row,self.profile.profile_id,self.profile.version)
  if not self.record.get("source_sha256"):self.record["source_sha256"]=meta["source_sha256"];save_record(self.record)
  self.state.open_record(self.record);self.zoom=min(1.,1050/self.standard.width,720/self.standard.height);self.pan=[0.,0.];self.sync()
 def pick_image(self,_=None):
  s=self.images_box.curselection()
  if s:self.index=s[0];self.open_image()
 def pick_landmark(self,_=None):
  s=self.landmarks.curselection()
  if s:self.state.select(self.profile.landmarks[s[0]].number);self.sync()
 def sync(self):
  n=self.state.current_landmark;i=next(i for i,p in enumerate(self.profile.landmarks) if p.number==n);self.landmarks.selection_clear(0,tk.END);self.landmarks.selection_set(i);self.landmarks.see(i);self.render()
 def image(self):return self.source if self.source_mode else self.standard
 def render(self):
  image=self.image();size=(max(1,round(image.width*self.zoom)),max(1,round(image.height*self.zoom)));self.photo=ImageTk.PhotoImage(image.resize(size), master=self.canvas);self.canvas.delete("all");self.canvas.create_image(*self.pan,anchor=tk.NW,image=self.photo)
  if not self.source_mode:
   for k,p in self.record.get("points",{}).items():
    if p.get("x_standardized") is not None:
     x=self.pan[0]+p["x_standardized"]*self.zoom;y=self.pan[1]+p["y_standardized"]*self.zoom;number=number_from_id(k);color="#ffb000" if number==self.state.current_landmark else "#00e5ff";self.canvas.create_oval(x-5,y-5,x+5,y+5,outline=color,width=2);self.canvas.create_text(x+8,y-8,text=str(number),anchor=tk.SW,fill=color)
  point=ReadyEditor._point(self,self.state.current_landmark);mode="SOURCE REVIEW (read-only)" if self.source_mode else "STANDARDIZED MASTER (annotation)";self.header.config(text=f"{mode} | {self.index+1}/{len(self.images)} | {point.number} {point.code}: {point.instruction}")
 def left_down(self,e):
  if self.source_mode:return
  x,y=self.image_point(e.x,e.y)
  if self.calibration is not None:
   self.calibration.append((x,y));
   if len(self.calibration)==2:self.finish_calibration()
   return
  # Hit-test in screen pixels: existing landmark always wins over adding.
  candidates=[]
  for key,point in self.record.get("points",{}).items():
   if point.get("x_standardized") is None:continue
   sx=self.pan[0]+point["x_standardized"]*self.zoom;sy=self.pan[1]+point["y_standardized"]*self.zoom
   distance=((e.x-sx)**2+(e.y-sy)**2)**.5
   if distance<=10:candidates.append((distance,number_from_id(key)))
  if candidates:
   _,number=min(candidates);self.state.select(number);self.dragging=number;self.sync();return
  # Blank click creates only the lowest truly unplaced landmark number.
  number=next((i for i in self.state.point_ids if not any(number_from_id(key)==i for key in self.record.get("points",{}))),None)
  if number is None:return
  self.state.select(number);point=ReadyEditor._point(self,number);set_human_point(self.record,number,point.code,x,y,corrected=False);save_record(self.record);self.state.after_place_new(False);self.sync()
 def left_drag(self,e):
  if not self.dragging or self.source_mode:return
  x,y=self.image_point(e.x,e.y);n=self.dragging;point=ReadyEditor._point(self,n);set_human_point(self.record,n,point.code,x,y,corrected=True);self.render()
 def left_up(self,e):
  if self.dragging:save_record(self.record);self.dragging=None;self.sync()
 def right_down(self,e):self.right_anchor=(e.x,e.y)
 def right_drag(self,e):
  if not self.right_anchor:return
  dx=e.x-self.right_anchor[0];dy=e.y-self.right_anchor[1];self.pan[0]+=dx;self.pan[1]+=dy;self.right_anchor=(e.x,e.y);self.render()
 def wheel(self,e):
  old=self.zoom;self.zoom=max(.05,min(4.,old*(1.15 if e.delta>0 else 1/1.15)));self.pan[0]=e.x-(e.x-self.pan[0])*self.zoom/old;self.pan[1]=e.y-(e.y-self.pan[1])*self.zoom/old;self.render()
 def missing(self):
  if self.source_mode:return
  n=self.state.current_landmark;point=ReadyEditor._point(self,n);set_human_point(self.record,n,point.code,None,None);save_record(self.record);self.state.after_missing();self.sync()
 def remove(self):
  if self.source_mode:return
  points=self.record.setdefault("points",{});points.pop(record_key(points,self.state.current_landmark),None);save_record(self.record);self.sync()
 def toggle_source(self):self.source_mode=not self.source_mode;self.render()
 def start_calibration(self):
  if self.source_mode:messagebox.showinfo("Calibration","Return to standardized master first.");return
  self.calibration=[];self.header.config(text="Calibration: click two ruler endpoints on standardized master")
 def finish_calibration(self):
  length=simpledialog.askfloat("Calibration","Known length (mm)",initialvalue=10.,minvalue=.001)
  if length:
   (x1,y1),(x2,y2)=self.calibration;d=((x2-x1)**2+(y2-y1)**2)**.5;save_calibration(self.current()["sample_id"],{"physical_length_mm":length,"points_standardized":[[x1,y1],[x2,y2]],"pixels_per_mm":d/length,"state":"manual"})
  self.calibration=None;self.sync()
 def undo(self):messagebox.showinfo("Undo","Use saved history in the prior operator until history is wired into this corrected editor.")
def run():ReadyEditor().mainloop()
if __name__=="__main__":run()







