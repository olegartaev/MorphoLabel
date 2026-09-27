"""Shared searchable photo list with a single Project-level exclusion action."""
from __future__ import annotations
from pathlib import Path
import inspect
import tkinter as tk
from tkinter import ttk,messagebox
from app.photo_list import PhotoListCanvas
from app.ui.icons import tk_icon, CONTROL_ICON_SIZE

DEFAULT_SHOW_EXCLUDED = True

def photo_search_cache(rows):
 """Precompute catalog-only strings used by compact photo filters."""
 return tuple((str(row.get("locality") or row.get("sample_id") or "").casefold(),(str(row.get("image_id") or "")+" "+Path(str(row.get("source_relpath") or "")).name).casefold()) for row in rows)

def filtered_photo_indices(rows, cache, image_query="", locality_query="", *, show_excluded=DEFAULT_SHOW_EXCLUDED):
 image_query=str(image_query or "").strip().casefold();locality_query=str(locality_query or "").strip().casefold()
 return [index for index,(row,(locality,name)) in enumerate(zip(rows,cache)) if (show_excluded or not row.get("excluded")) and (not image_query or image_query in name) and (not locality_query or locality_query in locality)]

def next_working_photo_index(rows, visible_indices, current_index, step):
 """Return the next non-excluded visible image while excluded rows stay inspectable."""
 visible=list(visible_indices)
 if not visible:return None
 direction=1 if int(step)>=0 else -1
 try:position=visible.index(int(current_index))
 except (ValueError,TypeError):position=(-1 if direction>0 else 0)
 for offset in range(1,len(visible)+1):
  candidate=visible[(position+direction*offset)%len(visible)]
  if not rows[candidate].get("excluded"):return candidate
 return None

class PhotoListPanel(ttk.Frame):
 def __init__(self,parent,context,on_select,tooltip,on_exclusion=None):
  super().__init__(parent,padding=(7,5));self.context,self.on_select,self.tooltip,self.on_exclusion=context,on_select,tooltip,on_exclusion;self.image_query=tk.StringVar(master=self);self.locality_query=tk.StringVar(master=self);self.show_excluded=tk.BooleanVar(master=self,value=DEFAULT_SHOW_EXCLUDED);self._icons={}
  search=ttk.Frame(self,padding=(0,0,0,4));search.pack(fill='x');search.columnconfigure(0,weight=1);search.columnconfigure(1,weight=1)
  ttk.Label(search,text='Sample',style='Muted.TLabel').grid(row=0,column=0,sticky='w')
  ttk.Label(search,text='Specimen',style='Muted.TLabel').grid(row=0,column=1,sticky='w',padx=(6,0))
  self.locality_entry=ttk.Entry(search,textvariable=self.locality_query);self.locality_entry.grid(row=1,column=0,sticky='ew',pady=(2,0))
  self.image_entry=ttk.Entry(search,textvariable=self.image_query);self.image_entry.grid(row=1,column=1,sticky='ew',padx=(6,0),pady=(2,0))
  tooltip.bind(self.locality_entry,'Find images in a sample.');tooltip.bind(self.image_entry,'Find an image by its filename.')
  self._build_legend()
  list_host=ttk.Frame(self);list_host.pack(fill='both',expand=True);self.canvas=PhotoListCanvas(list_host,height=24,bg='white');self.scrollbar=ttk.Scrollbar(list_host,orient='vertical',command=self.canvas.yview);self.canvas.configure(yscrollcommand=self.scrollbar.set);self.canvas.pack(side='left',fill='both',expand=True);self.scrollbar.pack(side='right',fill='y');self.canvas.bind('<<ListboxSelect>>',self._selected);self.visible_indices=[];self._cache=()
  action=ttk.Frame(self,padding=(0,5,0,0));action.pack(fill='x');self.exclude_button=ttk.Button(action,text='Exclude',image=self._action_icon('exclude'),compound='left',style='Icon.TButton',command=self.exclude_or_restore);self.exclude_button.pack(side='left');tooltip.bind(self.exclude_button,'Exclude this image from active workflows and review queues without deleting its scientific data. Restore keeps the data but does not silently re-add the image to a finite review queue.')
  for variable in (self.image_query,self.locality_query,self.show_excluded):variable.trace_add('write',lambda *_:self.refresh())
 def _action_icon(self,name):
  key=(name,CONTROL_ICON_SIZE)
  if key not in self._icons:self._icons[key]=tk_icon(self,name,CONTROL_ICON_SIZE)
  return self._icons[key]
 def _build_legend(self):
  legend=ttk.Frame(self);legend.pack(fill='x',pady=(0,4))
  meta=ttk.Frame(legend);meta.pack(fill='x')
  ttk.Label(meta,text='C').pack(side='left')
  ttk.Label(meta,text=' calibrated',style='Muted.TLabel').pack(side='left',padx=(0,7))
  square=tk.Canvas(meta,width=11,height=11,highlightthickness=0,bd=0);square.create_rectangle(2,2,9,9,fill='',outline='#5f6b76',width=1);square.pack(side='left')
  ttk.Label(meta,text=' crop applied',style='Muted.TLabel').pack(side='left',padx=(0,7))
  ttk.Label(meta,text='×').pack(side='left')
  ttk.Label(meta,text=' excluded',style='Muted.TLabel').pack(side='left')
  show=ttk.Checkbutton(meta,text='Show excluded',variable=self.show_excluded);show.pack(side='right');self.tooltip.bind(show,'Include excluded images in the list.')

  states=ttk.Frame(legend);states.pack(fill='x',pady=(2,0))
  for color,text in (('#d93025',' incomplete'),('#e6a700',' review'),('#188038',' ready')):
   dot=tk.Canvas(states,width=11,height=11,highlightthickness=0,bd=0);dot.create_oval(2,2,9,9,fill=color,outline=color);dot.pack(side='left')
   ttk.Label(states,text=text,style='Muted.TLabel').pack(side='left',padx=(0,7))
 def _row_data(self,index,row):
  excluded=bool(row.get('excluded'));status='excluded' if excluded else row.get('status_color','red');tip='Excluded: '+(row.get('exclusion_reason') or 'Other') if excluded else f"Incomplete: {len(row.get('missing_ids',()))} remaining" if status=='red' else 'Complete — needs review' if status=='yellow' else 'Ready';tip+=(' · calibrated' if row.get('calibrated') else '');path=row.get('source_relpath',row.get('relative_path',''));locality=row.get('locality') or row.get('sample_id') or ''
  return {'number':str(index+1),'cal':'C' if row.get('calibrated') else '','has_crop':bool(row.get('has_crop')),'excluded':excluded,'text':f"{locality} | {Path(str(path)).name} ({row.get('index_in_locality',1)} | {row.get('total_in_locality',1)})",'status':status,'tooltip':tip,'review_warning':bool(row.get('review_warning'))}
 def refresh(self,preserve_scroll=False):
  rows=self.context.rows
  if len(self._cache)!=len(rows):self._cache=photo_search_cache([row|{'source_relpath':row.get('source_relpath',row.get('relative_path',row.get('original_name','')))} for row in rows])
  yview=self.canvas.yview()[0] if preserve_scroll and self.canvas.rows else None;self.visible_indices=filtered_photo_indices(rows,self._cache,self.image_query.get(),self.locality_query.get(),show_excluded=self.show_excluded.get());self.canvas.set_rows([self._row_data(i,rows[i]) for i in self.visible_indices])
  if self.context.selected in self.visible_indices:self.canvas.selection_set(self.visible_indices.index(self.context.selected))
  if yview is not None:self.canvas.yview_moveto(yview)
  elif self.context.selected in self.visible_indices:self.canvas.see(self.visible_indices.index(self.context.selected))
  row=self.context.current() or {};excluded=bool(row.get('excluded'));self.exclude_button.configure(text='Restore' if excluded else 'Exclude',image=self._action_icon('restore' if excluded else 'exclude'),state='normal' if row else 'disabled')
 def sync_current(self,reveal=True):
  if self.context.selected in self.visible_indices:
   visible=self.visible_indices.index(self.context.selected);self.canvas.selection_set(visible)
   if reveal:self.canvas.see(visible)
  self.refresh(preserve_scroll=True)
 def _selected(self,_event=None):
  selection=self.canvas.curselection()
  if selection and 0<=selection[0]<len(self.visible_indices):self.context.selected=self.visible_indices[selection[0]];self._notify(True);self.refresh(preserve_scroll=True)
 def _notify(self,preserve_list):
  if len(inspect.signature(self.on_select).parameters):self.on_select(preserve_list)
  else:self.on_select()
 def navigate(self,step):
  target=next_working_photo_index(self.context.rows,self.visible_indices,self.context.selected,step)
  if target is None:return False
  self.context.selected=target;self.sync_current(reveal=True);self._notify(False);return True
 def exclude_or_restore(self):
  row=self.context.current()
  if not row:return
  project=self.context.project;image_id=row['image_id']
  if row.get('excluded'):
   if not messagebox.askyesno('Restore image','Restore this image to Project workflows? Existing scientific data are unchanged.',parent=self):return
   project.restore_image(image_id)
  else:
   # Exclusion changes workflow membership only; it never deletes source or
   # derived scientific data, so it is intentionally a single immediate action.
   project.exclude_image(image_id,'User excluded',None)
  if self.on_exclusion:self.on_exclusion(image_id)
  else:self.context.refresh_landmark_state(image_id);self.context.invalidate_counts();self.refresh(preserve_scroll=True)
