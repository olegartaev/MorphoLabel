"""Prototype-style Measurements section with a real, read-only project preview."""
from __future__ import annotations
import queue
import threading
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from app.measurements import active_measurements, measurement_summary
from app.normalization_pipeline import develop_full
from app.project_runtime import scoped_project
from .section_base import SectionView

class MeasurementPreview:
 def __init__(self,parent,context):
  self.context=context;self.canvas=tk.Canvas(parent,bg='#202020',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
  self.image=self.photo=None;self.path=None;self.selected=None;self._token=0;self.requested_image_id=self.displayed_image_id=None;self._queue=queue.Queue();self._preparing=set();self._destroyed=False;self._closing=threading.Event();self._workers=set();self._loading_job=None;self._loading_step=0;self._poll=self.canvas.after(60,self.poll)
  self.canvas.bind('<Configure>',lambda _e:self.render());self.canvas.bind('<Destroy>',self.destroy,add='+')
 def destroy(self,event):
  if event.widget is self.canvas:
   self._destroyed=True;self._closing.set();self._token+=1;self._preparing.clear();self._stop_loading()
   for worker in tuple(self._workers):worker.join(timeout=.25)
  if event.widget is self.canvas and self._poll:
   try:self.canvas.after_cancel(self._poll)
   except tk.TclError:pass
   self._poll=None
 def _show_loading(self,text='Preparing measurement preview'):
  self.canvas.delete('all');self.canvas.create_text(16,16,anchor='nw',fill='white',text=text,tags='measurement_loading')
  if self._loading_job:return
  self._loading_step=0
  def tick():
   if self._destroyed or self.displayed_image_id==self.requested_image_id:
    self._loading_job=None;return
   self._loading_step+=1
   try:self.canvas.itemconfigure('measurement_loading',text=text+'.'*(self._loading_step%4))
   except tk.TclError:return
   self._loading_job=self.canvas.after(350,tick)
  tick()
 def _stop_loading(self):
  if self._loading_job:
   try:self.canvas.after_cancel(self._loading_job)
   except tk.TclError:pass
   self._loading_job=None
 def load_current(self):
  if self._destroyed:return
  self._token+=1;self.requested_image_id=(self.context.current() or {}).get('image_id');self.displayed_image_id=None;self.image=self.photo=None;self.path=None;self.render()
 def path_for_row(self,row):
  project=self.context.project;crop=project.crop_record(row['image_id']) or {};rel=crop.get('standardized_relpath')
  if rel:
   target=project.resolve_data_path(rel)
   if target.is_file():return target
  target=project.cache_root/'developed'/f"{row['image_id']}.png"
  if target.is_file():return target
  ident=row['image_id']
  if ident not in self._preparing:
   source=project.image_path(ident);self._preparing.add(ident)
   if source:
    def worker():
     try:
      with scoped_project(project):develop_full(source)
      if not self._closing.is_set():self._queue.put(('ready',ident,self._token))
     except Exception as exc:
      if not self._closing.is_set():self._queue.put(('error',ident,self._token,str(exc)))
     finally:self._workers.discard(threading.current_thread())
    thread=threading.Thread(target=worker,daemon=True,name='measurement-preview-image');self._workers.add(thread);thread.start()
  return None
 def poll(self):
  if self._destroyed:return
  try:
   while True:
    kind,ident,token,*detail=self._queue.get_nowait();self._preparing.discard(ident)
    if token!=self._token or ident!=self.requested_image_id or ident!=((self.context.current() or {}).get('image_id')):continue
    if kind=='ready':self.displayed_image_id=ident;self._stop_loading();self.render()
    else:self._stop_loading();self.canvas.delete('all');self.canvas.create_text(16,16,anchor='nw',fill='white',text=f'Could not prepare measurement preview: {detail[0]}')
  except queue.Empty:pass
  try:self._poll=self.canvas.after(60,self.poll)
  except tk.TclError:self._poll=None
 def render(self):
  self.canvas.delete('all');row=self.context.current()
  if not row:return
  self.requested_image_id=row['image_id'];target=self.path_for_row(row)
  if not target:
   self._show_loading();return
  self._stop_loading()
  try:
   if target!=self.path:
    with Image.open(target) as source:self.image=source.convert('RGB')
    self.path=target;self.displayed_image_id=row['image_id']
   width=max(1,self.canvas.winfo_width());height=max(1,self.canvas.winfo_height());scale=min((width-20)/self.image.width,(height-20)/self.image.height)
   shown=self.image.resize((max(1,round(self.image.width*scale)),max(1,round(self.image.height*scale))))
   self.photo=ImageTk.PhotoImage(shown,master=self.canvas);ox=(width-shown.width)/2;oy=(height-shown.height)/2;self.canvas.create_image(ox,oy,anchor='nw',image=self.photo)
   points=self.context.project.load_landmarks(row['image_id']);labels={int(item['id']):item.get('abbr') or str(item['id']) for item in self.context.project.schema}
   coords={}
   for ident,point in points.items():
    if point.get('state')=='missing' or point.get('x_standardized') is None:continue
    x=ox+float(point['x_standardized'])*scale;y=oy+float(point['y_standardized'])*scale;coords[int(ident)]=(x,y);self.canvas.create_oval(x-4,y-4,x+4,y+4,fill='#35d07f',outline='white');self.canvas.create_text(x+7,y-7,text=labels.get(int(ident),str(ident)),fill='white',anchor='sw')
   definitions=active_measurements(self.context.project)
   colors=('#ffcc00','#38bdf8','#fb7185','#a78bfa','#fb923c')
   for i,item in enumerate(definitions):
    a,b=coords.get(item['point1']),coords.get(item['point2'])
    if not a or not b:continue
    selected=not self.selected or item.get('abbr')==self.selected.get('abbr');color=colors[i%len(colors)] if selected else '#6b7280';width_line=3 if selected else 1
    self.canvas.create_line(*a,*b,fill=color,width=width_line);self.canvas.create_text((a[0]+b[0])/2,(a[1]+b[1])/2-8,text=item['abbr'],fill=color)
  except Exception as exc:self.canvas.create_text(16,16,anchor='nw',fill='white',text=f'Could not display measurement preview: {exc}')

class MeasurementsSection(SectionView):
 def render(self):
  panel=self.frame(padding=(6,6));panel.pack(fill='both',expand=True);panel.rowconfigure(1,weight=1);panel.columnconfigure(0,weight=1)

  overview=ttk.Frame(panel,style='Toolbar.TFrame');overview.grid(row=0,column=0,sticky='ew',pady=(0,4));overview.columnconfigure(1,weight=1)
  ttk.Label(overview,text='Measurement preview',style='SectionTitle.TLabel').grid(row=0,column=0,sticky='w')
  self.preview_choice=tk.StringVar();self.preview_images=self._eligible_images()
  self.preview_box=ttk.Combobox(overview,textvariable=self.preview_choice,values=[self._label(r) for r in self.preview_images],state='readonly',width=42)
  self.preview_box.grid(row=0,column=1,sticky='ew',padx=(8,12));self.preview_box.bind('<<ComboboxSelected>>',lambda _e:self.choose_other_image())
  self.summary=ttk.Label(overview,style='Muted.TLabel');self.summary.grid(row=0,column=2,sticky='e')

  self.preview_host=ttk.LabelFrame(panel,text='Preview',padding=2);self.preview_host.grid(row=1,column=0,sticky='nsew')
  self.preview=MeasurementPreview(self.preview_host,self.context)

  guide='Why: Measurements turns confirmed landmarks into quantitative traits that can be compared and analysed.\n\n1. Calibrate samples\nNeeded when results must be in physical units such as millimetres. Set one known reference distance for each sample.\n\n2. Define measurements\nCreate named distances by choosing the two landmarks that define each trait.\n\n3. Review and export\nInspect the preview, then export the measurements for statistical analysis.'
  dock=self.workflow_dock(panel,help_title='Measurements — quick guide',help_text=guide);dock.grid(row=2,column=0,sticky='ew',pady=(4,0))

  first=dock.add_card('1. Calibrate samples',icon='📏',help_text='Convert pixel distances to physical units for each sample.')
  ttk.Label(first,text='Needed for measurements in mm or other real units.',style='Muted.TLabel',wraplength=310,justify='left').pack(anchor='w')
  self.button(first,'Calibrate samples',self.shell.open_calibration,'Open sample calibration and set a known reference distance.').pack(anchor='w',pady=(7,0))

  second=dock.add_card('2. Define measurements',icon='✏️📏',help_text='Define each measurement as the distance between two landmarks.')
  ttk.Label(second,text='Choose landmark pairs and give each distance a short code and name.',style='Muted.TLabel',wraplength=310,justify='left').pack(anchor='w')
  self.button(second,'Measurement definitions…',self.shell.open_measurements,'Create, edit or disable measurement definitions.').pack(anchor='w',pady=(7,0))

  third=dock.add_card('3. Review and export',icon='📤',help_text='Check the measurement preview, then export project-level results.')
  ttk.Label(third,text='Preview the active definitions, then export them for analysis.',style='Muted.TLabel',wraplength=310,justify='left').pack(anchor='w')
  self.button(third,'Open Export',lambda:self.shell.select('export'),'Open the Export section for project-level output.').pack(anchor='w',pady=(7,0))

  self.refresh_definitions()
 def _eligible_images(self):
  """Keep the shared catalogue order so section changes never change the specimen."""
  return list(self.context.rows)
 def _label(self,row):return f"{row.get('sample_id',row.get('locality',''))} | {row.get('original_name','')}"
 def choose_other_image(self):
  choice=self.preview_choice.get();index=next((i for i,row in enumerate(self.preview_images) if self._label(row)==choice),None)
  if index is None:
   current=self.context.current();index=next((i for i,row in enumerate(self.preview_images) if current and row['image_id']==current['image_id']),0)
  if self.preview_images:
   row=self.preview_images[index];self.context.selected=next(i for i,item in enumerate(self.context.rows) if item['image_id']==row['image_id']);self.preview_choice.set(self._label(row));self.preview.load_current()
 def _sync_preview_to_current(self):
  current=self.context.current()
  if current is not None:
   match=next((row for row in self.preview_images if row.get('image_id')==current.get('image_id')),None)
   if match is not None:self.preview_choice.set(self._label(match))
  if hasattr(self,'preview'):self.preview.load_current()
 def refresh_definitions(self):
  summary=measurement_summary(self.context.project);self.summary.configure(text=f"Defined {summary['measurements']}   ·   Calibrated {summary['calibrated_samples']}/{summary['samples']}   ·   Complete {summary['complete']}")
  if hasattr(self,'preview'):self._sync_preview_to_current()
 def select_measurement(self,definition):
  if hasattr(self,'preview'):self.preview.selected=definition;self.preview.render()
 def on_image_selected(self):
  if hasattr(self,'preview'):self._sync_preview_to_current()