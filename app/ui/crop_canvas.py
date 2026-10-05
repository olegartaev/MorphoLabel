"""Responsive main-workspace crop canvas backed by existing crop workflow."""
import queue,threading,math
from collections import OrderedDict
from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox
from PIL import Image,ImageTk
from app.crop_editor_async_v2 import load_project_developed
from app.crop_model import CropModel
from app.crop_quality import assess_crop
from app.crop_workflow import apply_reviewed_crop, reviewed_crop_change
from app.ai_hardware import persisted_hardware_profile
from app.ui.design import prediction_stamp


@dataclass(frozen=True)
class CropViewport:
 scale: float; offset_x: float; offset_y: float; canvas_width: int; canvas_height: int; rotation_reserve: int=48


_MIB=1024*1024

def crop_navigation_cache_budget():
 try:profile=persisted_hardware_profile();ram=int(getattr(profile,"ram_bytes",0) or 0)
 except Exception:ram=0
 return min(1024*_MIB,max(128*_MIB,int(ram*.02))) if ram else 256*_MIB

def _image_bytes(image):
 if image is None:return 0
 try:return int(image.width)*int(image.height)*max(1,len(image.getbands()))
 except Exception:return 0

def _row_source_key(row):
 return (row.get("file_size"),row.get("mtime_ns"),row.get("source_sha256"))

def _rotate_about_center(x,y,cx,cy,degrees):
 theta=math.radians(-float(degrees));dx=float(x)-float(cx);dy=float(y)-float(cy);c=math.cos(theta);sn=math.sin(theta)
 return (dx*c-dy*sn+float(cx),dx*sn+dy*c+float(cy))

def crop_model_to_source(model,x,y):
 """Map a point in the persisted rotated-image crop frame back onto the original image."""
 return _rotate_about_center(x,y,model.width/2,model.height/2,-float(model.angle))

def crop_source_to_model(model,x,y):
 """Inverse of crop_model_to_source; persistence still receives the established model frame."""
 return _rotate_about_center(x,y,model.width/2,model.height/2,float(model.angle))

def crop_frame_polygon(model):
 return tuple(crop_model_to_source(model,x,y) for x,y in (
  (model.left,model.top),(model.right,model.top),(model.right,model.bottom),(model.left,model.bottom)
 ))

class CropCanvasController:
 def __init__(self,parent,context,changed):
  self.parent,self.context,self.changed=parent,context,changed;self.canvas=tk.Canvas(parent,background='#202020',highlightthickness=0);self.canvas.pack(fill='both',expand=True);self.canvas.bind('<Configure>',self._on_configure);self.canvas.bind('<Button-1>',self.down);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.up);self.base=self.photo=self.model=None;self.requested_image_id=self.displayed_image_id=None;self.scale=1.;self.offset=(0,0);self.viewport=CropViewport(1.,0.,0.,1,1);self.mode=self.anchor=self.initial=None;self.loading=False;self._load_token=0;self.requested_generation=0;self.requested_request_epoch=0;self.on_image_ready=None;self._poll_job=self._rotation_render_job=None;self._loading_pulse_job=None;self._loading_pulse_step=0;self._closed=False;self._cancel=threading.Event();self._worker=None;self._display_base=None;self._display_source=None;self._display_key=None;self._raster_key=None;self._current_cache_entry=None
  project_key=str(getattr(getattr(context,"project",None),"root",""))
  if getattr(context,"_crop_navigation_cache_project",None)!=project_key:
   context._crop_navigation_cache_project=project_key
   context._crop_navigation_image_cache=OrderedDict()
   context._crop_navigation_cache_lock=threading.Lock()
   context._crop_navigation_cache_budget=crop_navigation_cache_budget()
  self._image_cache=context._crop_navigation_image_cache
  self._cache_lock=context._crop_navigation_cache_lock
  self._image_cache_budget=int(context._crop_navigation_cache_budget)
  self._image_cache_bytes=sum(int(item.get("bytes") or 0) for item in self._image_cache.values())
  self._prefetch_thread=None;self._idle_jobs=set();self.photo_creations=0;self.preview_rotate_source_sizes=[];self.context_message="";self.status_callback=None;self.canvas.bind('<Destroy>',self._destroy,add='+');self.load_current()
 def _destroy(self,event):
  if event.widget is self.canvas:self._closed=True;self._cancel.set();self._load_token+=1
  if event.widget is self.canvas:
   for job in (self._poll_job,self._rotation_render_job,self._loading_pulse_job,*self._idle_jobs):
    if job:
     try:self.canvas.after_cancel(job)
     except tk.TclError:pass
   self._idle_jobs.clear()
   for worker in (self._worker,self._prefetch_thread):
    if worker is not None:worker.join(timeout=.25)
 def _after_idle(self,callback):
  job=None
  def invoke():
   self._idle_jobs.discard(job)
   if not self._closed:callback()
  job=self.canvas.after_idle(invoke);self._idle_jobs.add(job)
 def ready_for(self,image_id):
  return bool(image_id and self.requested_image_id==self.displayed_image_id==((self.context.current() or {}).get('image_id'))==image_id and self.base and self.model and not self.loading)
 def _cache_get(self,row):
  image_id=str(row.get("image_id") or "");source_key=_row_source_key(row)
  if not image_id:return None
  with self._cache_lock:
   entry=self._image_cache.get(image_id)
   if entry is None:return None
   if entry.get("source_key")!=source_key:
    self._image_cache.pop(image_id,None);self._image_cache_bytes=sum(int(item.get("bytes") or 0) for item in self._image_cache.values());return None
   self._image_cache.move_to_end(image_id);return entry
 def _cache_put(self,row,base,proxy):
  image_id=str(row.get("image_id") or "")
  if not image_id:return None
  size=_image_bytes(base)+_image_bytes(proxy);entry={"base":base,"proxy":proxy,"source_key":_row_source_key(row),"bytes":size,"display":None,"display_dimensions":None}
  with self._cache_lock:
   self._image_cache.pop(image_id,None)
   self._image_cache[image_id]=entry
   total=sum(int(item.get("bytes") or 0) for item in self._image_cache.values())
   while total>self._image_cache_budget and len(self._image_cache)>1:
    old_id,old_entry=self._image_cache.popitem(last=False)
    if old_id==image_id:
     self._image_cache[old_id]=old_entry;break
    total-=int(old_entry.get("bytes") or 0)
   self._image_cache_bytes=sum(int(item.get("bytes") or 0) for item in self._image_cache.values())
  return entry
 def _crop_state(self,project,image_id,base):
  active=project.get_ui_state("crop_active_batch",{});record=project.crop_record(image_id) or {};proposal=(active.get("proposals",{}) or {}).get(image_id)
  angle=record.get("rotation_degrees") if record.get("crop_json") else (active.get("proposal_rotations",{}) or {}).get(image_id,0)
  return record.get("crop_json") or proposal or [0,0,base.width,base.height],float(angle or 0)
 def _activate_loaded(self,row,entry,bounds,angle,token):
  image_id=str(row["image_id"])
  if self._closed or token!=self._load_token or image_id!=self.requested_image_id or image_id!=((self.context.current() or {}).get("image_id")):return False
  self.loading=False;self._stop_loading_pulse();self.canvas.delete('crop_loading_status');self.base=entry["base"];self._display_source=entry.get("proxy");self._current_cache_entry=entry;self.displayed_image_id=image_id;self.model=CropModel(self.base.width,self.base.height,*bounds,angle).clamp();self._display_base=None;self._display_key=None;self._raster_key=None
  record=self.context.project.crop_record(image_id) or {};self.context_message=prediction_stamp(record.get("model_id"),record.get("prediction_at")) if record.get("model_id") else ""
  from app.crop_training import rotation_supported
  model_id=record.get("model_id") or (self.context.project.active_model("crop") or {}).get("model_id")
  self._rotation_unavailable=bool(model_id and self.context.project.model_metadata(model_id) and not rotation_supported(self.context.project,model_id))
  if self._rotation_unavailable:self.context_message+=(" · " if self.context_message else "")+"Bounds-only model: adjust rotation manually or train a new model."
  self.render()
  callback=self.on_image_ready
  if callback and self.ready_for(image_id) and token==self.requested_generation:
   self._after_idle(lambda: callback(image_id,token,getattr(self,'requested_request_epoch',0)) if token==self.requested_generation and self.ready_for(image_id) else None)
  self._after_idle(self._prefetch_neighbors)
  return True
 def _prefetch_neighbors(self):
  if self._closed or self._prefetch_thread and self._prefetch_thread.is_alive():return
  project=self.context.project;rows=self.context.rows;selected=int(self.context.selected)
  snapshots=[]
  for index in (selected+1,selected+2,selected-1):
   if 0<=index<len(rows):
    row=dict(rows[index])
    if row.get("excluded") or self._cache_get(row) is not None:continue
    target=project.cache_root/"developed"/f"{row.get('image_id')}.png"
    if target.is_file():snapshots.append(row)
  if not snapshots:return
  def prefetch():
   for row in snapshots:
    if self._closed:return
    if self._cache_get(row) is not None:continue
    try:base,proxy=load_project_developed(project,row["image_id"]);self._cache_put(row,base,proxy)
    except Exception:continue
  self._prefetch_thread=threading.Thread(target=prefetch,daemon=True,name="crop-navigation-prefetch");self._prefetch_thread.start()
 def _start_loading_pulse(self,text):
  self._loading_pulse_step=0
  def tick():
   if self._closed or not self.loading:self._loading_pulse_job=None;return
   self._loading_pulse_step+=1;dots='.'*(self._loading_pulse_step%4)
   try:self.canvas.itemconfigure('crop_loading_status',text=text+dots)
   except tk.TclError:return
   self._loading_pulse_job=self.canvas.after(350,tick)
  tick()
 def _stop_loading_pulse(self):
  if self._loading_pulse_job:
   try:self.canvas.after_cancel(self._loading_pulse_job)
   except tk.TclError:pass
   self._loading_pulse_job=None
 def load_current(self,request_epoch=None):
  if self._closed:return
  row=self.context.current()
  self._load_token+=1;token=self._load_token;self.requested_generation=token
  if self._poll_job is not None:
   try:self.canvas.after_cancel(self._poll_job)
   except tk.TclError:pass
   self._poll_job=None
  if request_epoch is not None:self.requested_request_epoch=request_epoch
  self.requested_image_id=(row or {}).get('image_id');self.displayed_image_id=None;self.base=self.model=self.photo=self._display_base=None;self._display_source=None;self._current_cache_entry=None;self._display_key=self._raster_key=None;self.mode=self.anchor=self.initial=None;self.context_message=""
  self.canvas.delete('crop_overlay')
  if not row:return
  project=self.context.project;row=dict(row);image_id=row['image_id'];cached=self._cache_get(row)
  if cached is not None:
   bounds,angle=self._crop_state(project,image_id,cached["base"]);self._activate_loaded(row,cached,bounds,angle,token);return
  self.loading=True;self.canvas.delete('crop_loading_status');self.canvas.create_text(16,16,anchor='nw',fill='white',text='Loading image',tags='crop_loading_status');self._start_loading_pulse('Loading image');events=queue.Queue()
  def worker():
   try:
    active=project.get_ui_state("crop_active_batch",{});record=project.crop_record(image_id) or {}
    base,proxy=load_project_developed(project,image_id);proposal=(active.get('proposals',{}) or {}).get(image_id);angle=record.get('rotation_degrees') if record.get('crop_json') else (active.get('proposal_rotations',{}) or {}).get(image_id,0);events.put(('ok',base,proxy,record.get('crop_json') or proposal or [0,0,base.width,base.height],float(angle or 0)))
   except Exception as exc:events.put(('error',exc))
  self._worker=threading.Thread(target=worker,daemon=True,name='production-main-crop-load');self._worker.start()
  def poll():
   try:kind,*data=events.get_nowait()
   except queue.Empty:self._poll_job=self.canvas.after(20,poll);return
   self._poll_job=None
   if self._closed or token != self._load_token or image_id!=self.requested_image_id or image_id!=((self.context.current() or {}).get('image_id')):return
   if kind=='error':
    self.loading=False;self._stop_loading_pulse();self.canvas.delete('all');self.canvas.create_text(16,16,anchor='nw',fill='white',text=f'Crop preparation failed: {data[0]}',tags='crop_loading_status');return
   entry=self._cache_put(row,data[0],data[1]);self._activate_loaded(row,entry,data[2],data[3],token)
  poll()
 def _on_configure(self,_event=None):
  # A drag anchor is expressed in screen pixels and cannot survive a new viewport.
  if self.mode:self.mode=self.anchor=self.initial=None
  if self._rotation_render_job is not None:
   try:self.canvas.after_cancel(self._rotation_render_job)
   except tk.TclError:pass
   self._rotation_render_job=None
  self.render()
 def _fit(self):
  reserve=48;width=max(1,self.canvas.winfo_width());height=max(1,self.canvas.winfo_height());w=max(1,width-28);h=max(1,height-28-reserve);scale=min(w/self.base.width,h/self.base.height,1.0);offset=((width-self.base.width*scale)/2,reserve+(height-reserve-self.base.height*scale)/2);self.viewport=CropViewport(scale,offset[0],offset[1],width,height,reserve);self.scale,self.offset=scale,offset
 def _display_dimensions(self):return max(1,round(self.base.width*self.scale)),max(1,round(self.base.height*self.scale))
 def _ensure_display_base(self):
  dimensions=self._display_dimensions();key=(id(self.base),dimensions);entry=self._current_cache_entry
  if key==self._display_key:return
  if entry is not None and entry.get("display_dimensions")==dimensions and entry.get("display") is not None:
   self._display_base=entry["display"]
  else:
   source=self._display_source if self._display_source is not None and self._display_source.width>=dimensions[0] and self._display_source.height>=dimensions[1] else self.base
   self._display_base=source if source.size==dimensions else source.resize(dimensions,Image.Resampling.BICUBIC)
   if entry is not None:entry["display"]=self._display_base;entry["display_dimensions"]=dimensions
  self._display_key=key;self._raster_key=None
 def _render_raster(self,resample=Image.Resampling.BICUBIC):
  self._ensure_display_base();key=(self._display_key,resample);items=self.canvas.find_withtag('image')
  if key!=self._raster_key or not items:
   # Keep the biological image fixed while the persisted crop frame rotates above it.
   shown=self._display_base;self.photo=ImageTk.PhotoImage(shown,master=self.canvas);self.photo_creations+=1;self._raster_key=key
   if items:self.canvas.itemconfigure(items[0],image=self.photo)
   else:self.canvas.create_image(*self.offset,anchor='nw',image=self.photo,tags='image')
  # Raster pixels may be cached, but placement is never cached.
  items=self.canvas.find_withtag('image')
  if items:self.canvas.coords(items[0],*self.offset)
 def _screen_source(self,x,y):
  ox,oy=self.offset;return ox+float(x)*self.scale,oy+float(y)*self.scale
 def _draw_overlay(self,qc=True):
  self.canvas.delete('crop_overlay')
  source_corners=crop_frame_polygon(self.model);screen=[self._screen_source(x,y) for x,y in source_corners]
  flat=[value for point in screen for value in point];self.canvas.create_polygon(*flat,outline='#35d07f',fill='',width=2,tags='crop_overlay')
  for x,y in screen:self.canvas.create_rectangle(x-5,y-5,x+5,y+5,fill='#35d07f',outline='#fff',tags='crop_overlay')
  qcx=(self.model.left+self.model.right)/2;qtop=self.model.top;qhy=self.model.top-35/self.scale
  tcx,tcy=self._screen_source(*crop_model_to_source(self.model,qcx,qtop));hx,hy=self._screen_source(*crop_model_to_source(self.model,qcx,qhy))
  self.canvas.create_line(tcx,tcy,hx,hy,fill='#ffcc00',width=2,tags='crop_overlay');self.canvas.create_oval(hx-7,hy-7,hx+7,hy+7,fill='#ffcc00',outline='#fff',tags='crop_overlay')
  label_x,label_y=screen[0];angle_label=f'rotation {self.model.angle:.1f}°'
  if getattr(self,'_rotation_unavailable',False) and self.model.angle==0:angle_label+=' (manual; model has no angle)'
  self.canvas.create_text(label_x,label_y-9,anchor='sw',fill='#ffcc00',text=angle_label,tags='crop_overlay')
  message_y=12
  if self.context_message:
   self.canvas.create_text(13,message_y+1,anchor='nw',fill='#202020',text=self.context_message,font=('Segoe UI',10,'bold'),tags='crop_overlay')
   self.canvas.create_text(12,message_y,anchor='nw',fill='#ffdf80',text=self.context_message,font=('Segoe UI',10,'bold'),tags='crop_overlay');message_y+=23
  if qc:
   quality=assess_crop((self.model.left,self.model.top,self.model.right,self.model.bottom),self.base.width,self.base.height)
   if self.status_callback:self.status_callback(f"Crop QC: {quality.level.upper()} — {quality.reasons[0]}")
 def render(self,qc=True,resample=Image.Resampling.BICUBIC):
  if not self.base or not self.model:return
  self._fit();self._render_raster(resample);self._draw_overlay(qc=qc)
 def _source_point(self,x,y):ox,oy=self.offset;return ((x-ox)/self.scale,(y-oy)/self.scale)
 def _point(self,x,y):
  sx,sy=self._source_point(x,y);return crop_source_to_model(self.model,sx,sy)
 def _hit(self,x,y):
  l,t,r,b=self.model.left,self.model.top,self.model.right,self.model.bottom;tol=12/self.scale;cx=(l+r)/2;hy=t-35/self.scale
  if (x-cx)**2+(y-hy)**2<tol**2:return 'rotate'
  for name,px,py in (('lt',l,t),('rt',r,t),('lb',l,b),('rb',r,b)):
   if abs(x-px)<tol and abs(y-py)<tol:return name
  if abs(x-l)<tol and t<=y<=b:return 'l'
  if abs(x-r)<tol and t<=y<=b:return 'r'
  if abs(y-t)<tol and l<=x<=r:return 't'
  if abs(y-b)<tol and l<=x<=r:return 'b'
  return 'move' if l<=x<=r and t<=y<=b else None
 def down(self,event):
  if self.ready_for(self.displayed_image_id):self.anchor=self._point(event.x,event.y);self.mode=self._hit(*self.anchor);self.initial=(self.model.left,self.model.top,self.model.right,self.model.bottom,self.model.angle)
 def _schedule_rotation_preview(self):
  if self._rotation_render_job is None:self._rotation_render_job=self.canvas.after_idle(self._render_rotation_preview)
 def _render_rotation_preview(self):
  self._rotation_render_job=None
  if self.mode=='rotate' and self.ready_for(self.displayed_image_id):self._draw_overlay(qc=False)
 def drag(self,event):
  if not self.mode or not self.ready_for(self.displayed_image_id):return
  x,y=self._point(event.x,event.y);ax,ay=self.anchor
  if self.mode=='move':
   self.model.left,self.model.top,self.model.right,self.model.bottom=self.initial[:4];self.model.move(x-ax,y-ay)
  elif self.mode=='rotate':
   sx,sy=self._source_point(event.x,event.y);icx,icy=self.model.width/2,self.model.height/2
   qx=(self.model.left+self.model.right)/2;qy=self.model.top-35/self.scale
   qangle=math.atan2(qy-icy,qx-icx);pangle=math.atan2(sy-icy,sx-icx)
   angle=math.degrees(pangle-qangle);self.model.angle=((angle+180)%360)-180
   self._draw_overlay(qc=False);self._schedule_rotation_preview();return
  else:self.model.set_edge(self.mode,x,y)
  self._draw_overlay(qc=False)
 def up(self,_event):
  rotating=self.mode=='rotate';self.mode=self.anchor=self.initial=None
  if self._rotation_render_job is not None:
   try:self.canvas.after_cancel(self._rotation_render_job)
   except tk.TclError:pass
   self._rotation_render_job=None
  self._draw_overlay(qc=True)
 def reset(self):
  if self.base:self.model=CropModel(self.base.width,self.base.height,0,0,self.base.width,self.base.height,0);self._raster_key=None;self.render()
 def apply(self):
  row=self.context.current()
  if not row or not self.ready_for(row['image_id']):return 'DEFERRED'
  standard_path=self.context.project.cache_root/'standardized'/f"{row['image_id']}.png"
  bounds=(self.model.left,self.model.top,self.model.right,self.model.bottom)
  try:
   change=reviewed_crop_change(self.context.project,row['image_id'],self.base,bounds,self.model.angle,standard_path)
  except Exception as exc:
   messagebox.showerror('Apply crop',str(exc),parent=self.parent);return 'FAILED'
  if change['had_landmarks'] and change['frame_changed']:
   if change['old_transform'] is None:
    detail=('Landmarks already exist on this image, but their previous Crop frame cannot be proven.\n\n'
            'Changing the crop will reset their positions for re-annotation. The old values remain in the audit history.')
   else:
    detail=('Landmarks already exist on this image.\n\n'
            'Changing the crop will reproject them into the new frame and mark the image for Landmark review. '
            'Any point outside the new crop becomes unresolved.')
   if not messagebox.askyesno('Change crop with existing landmarks',detail+'\n\nContinue?',parent=self.parent,default=messagebox.NO):
    return 'CANCELLED'
  try:result=apply_reviewed_crop(self.context.project,row['image_id'],self.base,bounds,self.model.angle,standard_path,self.context.project.image_path(row['image_id']))
  except Exception as exc:messagebox.showerror('Apply crop',str(exc),parent=self.parent);return 'FAILED'
  self.context.refresh_crop_state(row['image_id']);self.changed(row['image_id'])
  if result.get('legacy_landmarks_invalidated'):
   self.last_save_message='Crop saved — the previous landmark frame was unknown, so existing landmarks were reset for re-annotation.'
  elif result.get('landmarks_remapped'):
   outside=int(result.get('outside_count') or 0)
   self.last_save_message=(f'Crop saved — landmarks were reprojected to the new crop; {outside} fell outside and must be placed again.' if outside else 'Crop saved — existing landmarks were reprojected to the new crop and must be reviewed.')
  else:self.last_save_message=''
  return 'SAVED'
