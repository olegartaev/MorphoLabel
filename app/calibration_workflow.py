"""Full-frame locality calibration workflow."""
from __future__ import annotations
import math, threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from .normalization_pipeline import develop_full
from .project_runtime import scoped_project
from .ui.dialogs import center,info

class CalibrationWorkflow(tk.Toplevel):
 def __init__(self,parent,project):
  super().__init__(parent);self.parent=parent;self.project=project;self.title("Sample calibration");self.geometry("1180x820");self.minsize(900,620);self.resizable(True,True)
  self.rows=[r for r in project.catalog_rows() if not r.get("excluded")];self.localities=[]
  for row in self.rows:
   key=row.get("locality") or row.get("sample_id")
   if key not in self.localities:self.localities.append(key)
  self.by_locality={key:[r for r in self.rows if (r.get("locality") or r.get("sample_id"))==key] for key in self.localities};self.index=next((i for i,key in enumerate(self.localities) if not project.locality_calibration(key)),0);self.image_index=0;self.points=[];self.saved_points=[];self.drag=None;self.pan_drag=None;self.image=None;self.photo=None;self.zoom=1.;self.offset=(0,0);self.mm=tk.StringVar(master=self,value="10.0");self._load_token=0;self.requested_image_id=self.displayed_image_id=None;self._pending_confirm=None;self._closed=False;self._workers=set();self._loading_job=None;self._loading_step=0

  header=ttk.Frame(self,padding=(12,10,12,6));header.pack(fill="x");header.columnconfigure(0,weight=1)
  left=ttk.Frame(header);left.grid(row=0,column=0,sticky="w")
  ttk.Label(left,text="Sample calibration",style="PageTitle.TLabel").pack(anchor="w")
  ttk.Label(left,text="Set a known distance once per sample to convert pixel distances to physical units.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,0))
  ttk.Button(header,text="Help",command=self._help).grid(row=0,column=1,sticky="ne")

  status=ttk.Frame(self,padding=(12,0,12,6));status.pack(fill="x");status.columnconfigure(0,weight=1)
  self.title_text=ttk.Label(status,text="Calibration",style="SectionTitle.TLabel");self.title_text.grid(row=0,column=0,sticky="w")
  self.progress=ttk.Label(status,style="Muted.TLabel");self.progress.grid(row=1,column=0,sticky="w",pady=(2,0))
  nav=ttk.Frame(status);nav.grid(row=0,column=1,rowspan=2,sticky="e")
  ttk.Button(nav,text="‹ Previous sample",command=lambda:self.navigate_locality(-1),style="Nav.TButton").pack(side="left")
  ttk.Button(nav,text="Next sample ›",command=lambda:self.navigate_locality(1),style="Nav.TButton").pack(side="left",padx=(6,0))

  reference=ttk.Frame(self,padding=(12,4,12,6));reference.pack(fill="x")
  ttk.Label(reference,text="Known reference length",style="SectionTitle.TLabel").pack(side="left")
  ttk.Entry(reference,textvariable=self.mm,width=9).pack(side="left",padx=(8,4))
  ttk.Label(reference,text="mm").pack(side="left")
  ttk.Label(reference,text="Place two points at the ends of this known distance.",style="Muted.TLabel").pack(side="left",padx=(12,0))

  self.canvas=tk.Canvas(self,bg="#262626",highlightthickness=0);self.canvas.pack(fill="both",expand=True,padx=12,pady=(0,6));self.canvas.bind("<Button-1>",self.click);self.canvas.bind("<B1-Motion>",self.motion);self.canvas.bind("<ButtonRelease-1>",lambda _e:setattr(self,"drag",None));self.canvas.bind("<Button-3>",self.pan_start);self.canvas.bind("<B3-Motion>",self.pan_motion);self.canvas.bind("<ButtonRelease-3>",lambda _e:setattr(self,"pan_drag",None));self.canvas.bind("<MouseWheel>",self.wheel);self.canvas.bind("<Configure>",lambda _e:self.render())

  actions=ttk.Frame(self,padding=(12,4,12,10));actions.pack(fill="x");actions.columnconfigure(2,weight=1)
  ttk.Button(actions,text="Use another image",command=self.other_image).grid(row=0,column=0,sticky="w")
  ttk.Button(actions,text="Reset points",command=self.reset).grid(row=0,column=1,sticky="w",padx=(6,0))
  ttk.Button(actions,text="Save",command=self.confirm).grid(row=0,column=3,sticky="e")
  ttk.Button(actions,text="Save & Next ›",command=self.confirm_next,style="Primary.TButton").grid(row=0,column=4,sticky="e",padx=(6,0))

  if self.localities:self.load()
  else:messagebox.showinfo("Calibration","No active samples are available.",parent=self)
  self.protocol("WM_DELETE_WINDOW",self.close)
  center(parent,self)

 def _start_loading_animation(self,text):
  if self._loading_job:
   try:self.after_cancel(self._loading_job)
   except tk.TclError:pass
  self._loading_step=0
  def tick():
   if self._closed or self.displayed_image_id==self.requested_image_id:
    self._loading_job=None;return
   self._loading_step+=1
   try:self.canvas.itemconfigure("calibration_loading",text=text+"."*(self._loading_step%4))
   except tk.TclError:return
   self._loading_job=self.after(350,tick)
  tick()
 def _stop_loading_animation(self):
  if self._loading_job:
   try:self.after_cancel(self._loading_job)
   except tk.TclError:pass
   self._loading_job=None

 def _help(self):
  info(self,"Calibration — quick guide",
       "Why: calibration converts distances measured in pixels into real units such as millimetres.\n\n"
       "For each sample, choose an image containing a known scale or reference length.\n\n"
       "Enter that length, click its two endpoints, then Save & Next. The same calibration is used for the sample.")
 def locality(self):return self.localities[self.index]
 def row(self):return self.by_locality[self.locality()][self.image_index]
 def dirty(self):return self.points!=self.saved_points or self.mm.get()!=getattr(self,"saved_mm","10.0")
 def ready_for(self,image_id):return bool(image_id and self.requested_image_id==self.displayed_image_id==image_id)
 def load(self):
  self._load_token+=1;token=self._load_token;self._pending_confirm=None
  self.points=[];self.image=self.photo=None;self.requested_image_id=None;self.displayed_image_id=None;self.saved_points=[];self.zoom=1.;self.offset=(0,0);self._positioned=False;row=self.row();saved=self.project.locality_calibration(self.locality());self.saved_mm="10.0"
  if saved:
   try:
    data=__import__("json").loads(saved.get("calibration_data") or "{}") if isinstance(saved.get("calibration_data"),str) else saved.get("calibration_data") or {};self.points=[tuple(p) for p in data.get("points_original",[])];self.saved_points=list(self.points);self.saved_mm=str(data.get("physical_length_mm",10.0));self.mm.set(self.saved_mm);ref=saved.get("calibration_reference_image_id")
    for i,item in enumerate(self.by_locality[self.locality()]):
     if item.get("image_id")==ref:self.image_index=i;row=item;break
   except Exception:pass
  else:self.mm.set(getattr(self,"last_mm","10.0"))
  image_id=row['image_id'];self.requested_image_id=image_id;source=self.project.image_path(image_id);target=self.project.cache_root/"developed"/f"{row['image_id']}.png";self.title_text.config(text=f"Sample: {self.locality()}")
  self.progress.config(text=f"{self.index+1} / {len(self.localities)} samples   ·   Calibrated {sum(bool(self.project.locality_calibration(x)) for x in self.localities)} / {len(self.localities)}")
  if target.exists():self.set_image(target,token,image_id)
  elif not source:
   self.canvas.delete("all");self.canvas.create_text(20,20,text="The original image is unavailable and no developed image is cached.",fill="white",anchor="nw")
  else:
   self.canvas.delete("all");self.canvas.create_text(20,20,text="Preparing full developed image",fill="white",anchor="nw",tags="calibration_loading");self._start_loading_animation("Preparing full developed image")
   self.progress.config(text=self.progress.cget("text")+"\nPreparing image…")
   def worker():
    try:
     with scoped_project(self.project):develop_full(source)
     if not target.exists():raise RuntimeError("Developed image cache was not created.")
     if not self._closed:self.after(0,lambda:self.set_image(target,token,image_id))
    except Exception as exc:
     if not self._closed:self.after(0,lambda:self._image_error(str(exc),token,image_id))
    finally:self._workers.discard(threading.current_thread())
   thread=threading.Thread(target=worker,daemon=True,name="calibration-full-frame");self._workers.add(thread);thread.start()
 def _image_error(self,text,token=None,image_id=None):
  if token is not None and (token!=self._load_token or image_id!=self.requested_image_id):return
  self._stop_loading_animation()
  self.canvas.delete("all");self.canvas.create_text(20,20,text=f"Could not prepare calibration image:\n{text}",fill="white",anchor="nw");messagebox.showerror("Calibration",text,parent=self)
 def set_image(self,path,token=None,image_id=None):
  if token is not None and (token!=self._load_token or image_id!=self.requested_image_id):return
  self._stop_loading_animation()
  try:
   self.image=Image.open(path).convert("RGB");self.displayed_image_id=image_id or self.requested_image_id;self.render()
   pending=self._pending_confirm
   if pending and pending[0]==self.displayed_image_id and pending[1]==self._load_token:
    self._pending_confirm=None;self.after_idle(self.confirm_next if pending[2] else self.confirm)
  except Exception as exc:self._image_error(str(exc),token,image_id)
 def render(self):
  if not self.image or not self.ready_for(self.displayed_image_id):return
  w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height());fit=min((w-20)/self.image.width,(h-20)/self.image.height);z=fit*self.zoom;dw=max(1,round(self.image.width*z));dh=max(1,round(self.image.height*z));self.offset=self.offset if getattr(self,"_positioned",False) else ((w-dw)/2,(h-dh)/2);self._positioned=True;view=self.image.resize((dw,dh));self.photo=ImageTk.PhotoImage(view,master=self);self.canvas.delete("all");self.canvas.create_image(*self.offset,anchor="nw",image=self.photo)
  xy=[]
  for i,(x,y) in enumerate(self.points,1):sx=self.offset[0]+x*z;sy=self.offset[1]+y*z;xy.append((sx,sy));self.canvas.create_oval(sx-6,sy-6,sx+6,sy+6,outline="#ff4d4d",width=2);self.canvas.create_text(sx+10,sy-10,text=str(i),fill="#ff4d4d")
  if len(xy)==2:self.canvas.create_line(*xy[0],*xy[1],fill="#ff4d4d",width=2)
  self._z=z
 def point(self,e):return ((e.x-self.offset[0])/self._z,(e.y-self.offset[1])/self._z)
 def click(self,e):
  if not self.image or self.requested_image_id != self.displayed_image_id:return
  for i,(x,y) in enumerate(self.points):
   sx=self.offset[0]+x*self._z;sy=self.offset[1]+y*self._z
   if (sx-e.x)**2+(sy-e.y)**2<=144:self.drag=i;return
  if len(self.points)<2:self.points.append(self.point(e));self.render()
 def motion(self,e):
  if self.drag is not None:self.points[self.drag]=self.point(e);self.render()
 def pan_start(self,e):self.pan_drag=(e.x,e.y,self.offset)
 def pan_motion(self,e):
  if self.pan_drag:
   x,y,origin=self.pan_drag;self.offset=(origin[0]+e.x-x,origin[1]+e.y-y);self.render()
 def wheel(self,e):
  old=self._z;factor=1.15 if e.delta>0 else 1/1.15;self.zoom=max(.25,min(8.,self.zoom*factor));before=((e.x-self.offset[0])/old,(e.y-self.offset[1])/old);self.render();self.offset=(e.x-before[0]*self._z,e.y-before[1]*self._z);self.render()
 def reset(self):self.points=[];self.render()
 def other_image(self):
  if self.dirty() and not messagebox.askyesno("Calibration","Discard unconfirmed calibration changes?",parent=self):return
  self.last_mm=self.mm.get();self.image_index=(self.image_index+1)%len(self.by_locality[self.locality()]);self.load()
 def navigate_locality(self,step):
  if self.dirty() and not messagebox.askyesno("Calibration","Discard unconfirmed calibration changes?",parent=self):return
  self.last_mm=self.mm.get();self.index=(self.index+step)%len(self.localities);self.image_index=0;self.load()
 def _save_current(self):
  try:mm=float(self.mm.get())
  except ValueError:mm=0
  if mm<=0 or len(self.points)!=2:messagebox.showwarning("Calibration","Enter a positive reference length and place exactly two points.",parent=self);return False
  distance=math.dist(*self.points)
  if distance<=0:messagebox.showwarning("Calibration","The calibration points must be different.",parent=self);return False
  row=self.row()
  if not self.ready_for(row['image_id']):self._pending_confirm=(self.requested_image_id,self._load_token,False);self.progress.config(text='Preparing image…');return False
  row={'image_id':self.displayed_image_id};data={"physical_length_mm":mm,"points_original":[list(p) for p in self.points],"pixels_per_mm":distance/mm,"mm_per_pixel":mm/distance,"reference_image_id":row["image_id"],"state":"manual"};self.project.set_locality_calibration(self.locality(),row["image_id"],distance/mm,"mm",data);self.last_mm=self.mm.get();self.saved_points=list(self.points);self.saved_mm=self.mm.get();self.progress.config(text=f"{self.index+1} / {len(self.localities)} samples   ·   Calibrated {sum(bool(self.project.locality_calibration(x)) for x in self.localities)} / {len(self.localities)}");self.render();return True
 def confirm(self):
  if not self.ready_for(self.requested_image_id):self._pending_confirm=(self.requested_image_id,self._load_token,False);self.progress.config(text="Preparing image…");return
  self._save_current()
 def confirm_next(self):
  if not self.ready_for(self.requested_image_id):self._pending_confirm=(self.requested_image_id,self._load_token,True);self.progress.config(text="Preparing image…");return
  if not self._save_current():return
  remaining=[i for i,key in enumerate(self.localities) if not self.project.locality_calibration(key)]
  if remaining:self.index=remaining[0];self.image_index=0;self.load()
  else:messagebox.showinfo("Calibration","All active samples are calibrated. Reopen Calibrate samples to review or recalibrate a sample.",parent=self)
 def close(self):
  self._closed=True;self._load_token+=1;self._pending_confirm=None;self._stop_loading_animation()
  for worker in tuple(self._workers):worker.join(timeout=.25)
  self.destroy()
