"""Blind Human Baseline pass editor; isolated from canonical landmark storage."""
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image
import time,traceback

from .operator_qc import blind_session_input,complete_repeat_session,reopen_repeat_session_for_correction,discard_repeat_session_correction,_load
from .landmark_annotation_ui import LandmarkAnnotationSurface,RepeatSessionAdapter,build_landmark_tree
from .ui.landmark_display import load_display_settings
from .gui_crop_debug import log,dump_threads
from .ui.batch_status import position_and_remaining


def _repeat_resolution_status(schema,points):
 required={int(row['id']) for row in schema};resolved={int(ident) for ident in points}
 return {'required':required,'resolved':resolved,'missing':required-resolved,'unexpected':resolved-required,'complete':required==resolved}

def _repeat_resolution_labels(schema,status):
 rows={int(row['id']):row for row in schema}
 labels=[]
 for ident in sorted(status.get('missing') or ()):
  row=rows.get(int(ident),{});abbr=str(row.get('abbr') or '').strip();name=str(row.get('name') or '').strip()
  suffix=' '.join(part for part in (abbr,('— '+name) if name else '') if part)
  labels.append(f"LM{ident}" + (f" {suffix}" if suffix else ''))
 return tuple(labels)

def _repeat_navigation_text(review_mode,index,total,dirty=False,attention_review=False):
 final=index+1>=total
 if attention_review:return {'batch':f'{index+1} / {total} suspicious image(s)','next':'Confirm & Finish' if final else 'Confirm & Next ›'}
 if review_mode:
  if dirty:return {'batch':f'{index+1} / {total}','next':'Save & Finish review' if final else 'Save & Next ›'}
  return {'batch':f'{index+1} / {total}','next':'Finish review' if final else 'Next ›'}
 remaining=max(0,total-index)
 return {'batch':f'{index+1} / {total}   Remaining {remaining}','next':'Confirm & Finish' if final else 'Confirm & Next ›'}


class HumanBaselineWindow(tk.Toplevel):
 def __init__(self,parent,project,run,on_complete,edit_completed=False,session_ids=None,pass_number=1,on_state_changed=None,on_review_modified=None,on_review_saved=None,on_review_closed=None,start_session_id=None,review_attention=None):
  started=time.monotonic();log('GLOBAL','WINDOW_CREATE_START','START')
  try:
   super().__init__(parent)
   self.project=project;self.run=run;self.on_complete=on_complete;self.on_state_changed=on_state_changed;self.on_review_modified=on_review_modified;self.on_review_saved=on_review_saved;self.on_review_closed=on_review_closed;self.edit_completed=edit_completed;self.pass_number=int(pass_number);self._dirty=False
   self.session_ids=list(session_ids if session_ids is not None else run.get('session_ids',()));self.review_attention=dict(review_attention or {});self.attention_review=bool(self.review_attention)
   self._tree_syncing=False;self._ignore_tree_event=False
   self.index=self.session_ids.index(start_session_id) if start_session_id in self.session_ids else next((i for i,s in enumerate(self.session_ids) if _load(project,s).get('status')=='in_progress'),0)

   self.title(f"Human repeatability — {'Check errors — ' if self.attention_review else 'Review ' if self.edit_completed else ''}Annotation {self.pass_number}")
   self.geometry('1180x800');self.minsize(860,560);self.resizable(True,True)

   header=ttk.Frame(self,padding=(10,8,10,6));header.pack(fill='x')
   left=ttk.Frame(header);left.pack(side='left',fill='x',expand=True)
   ttk.Label(left,text=f'Annotation {self.pass_number}',style='SectionTitle.TLabel').pack(anchor='w')
   mode_text='Check highlighted landmark(s). Correct if needed, then confirm this image.' if self.attention_review else 'Review existing annotation · browse freely; edit only what needs correction' if self.edit_completed else 'Independent blind annotation · the other pass is hidden'
   self.mode_label=ttk.Label(left,text=mode_text,style='Muted.TLabel');self.mode_label.pack(anchor='w',pady=(2,0))
   self.resolved_label=ttk.Label(left,text='',style='Muted.TLabel');self.resolved_label.pack(anchor='w',pady=(2,0))

   self.nav=ttk.Frame(header);self.nav.pack(side='right',anchor='ne')
   self.previous_button=ttk.Button(self.nav,text='‹ Previous',command=self.previous,style='Nav.TButton');self.previous_button.pack(side='left')
   self.batch_label=ttk.Label(self.nav,text='',padding=(8,0),font=('Segoe UI',9,'bold'));self.batch_label.pack(side='left')
   self.confirm_button=ttk.Button(self.nav,text='Confirm & Next ›',command=self.confirm,style='NavPrimary.TButton');self.confirm_button.pack(side='left')

   toolbar=ttk.Frame(self,padding=(10,4,10,6));toolbar.pack(fill='x')
   self.missing_button=ttk.Button(toolbar,text='Mark as missing',command=lambda:self.surface and self.surface.toggle_missing());self.missing_button.pack(side='left')
   ttk.Button(toolbar,text='Delete point',command=lambda:self.surface and self.surface.remove()).pack(side='left',padx=(5,0))
   ttk.Button(toolbar,text='Clear image…',command=self.clear_all).pack(side='left',padx=(5,0))
   ttk.Label(toolbar,text='Click to place · drag to correct · wheel to zoom · right-drag to pan',style='Muted.TLabel').pack(side='left',padx=(12,0))

   self.panes=ttk.Panedwindow(self,orient='horizontal');self.panes.pack(fill='both',expand=True)
   table_host=ttk.Frame(self.panes);canvas_host=ttk.Frame(self.panes)
   self.panes.add(table_host,weight=0);self.panes.add(canvas_host,weight=1)
   self.table_frame,self.landmark_table=build_landmark_tree(table_host,self.pick);self.table_frame.pack(fill='both',expand=True)
   self.canvas=tk.Canvas(canvas_host,bg='#262626',highlightthickness=0);self.canvas.pack(fill='both',expand=True)

   self.surface=None
   self.protocol('WM_DELETE_WINDOW',self.close_window)
   self.bind('<Return>',self._confirm_key,add='+');self.bind('<KP_Enter>',self._confirm_key,add='+')
   self.panes.bind('<ButtonRelease-1>',self._save_sash,add='+')
   self.panes.bind('<Configure>',self._restore_sash,add='+')
   self.load();log('GLOBAL','WINDOW_CREATE_END','END',time.monotonic()-started)
  except BaseException:
   log('GLOBAL','HUMAN_BASELINE_WINDOW_ERROR','ERROR',detail=traceback.format_exc());dump_threads('GLOBAL','human baseline window construction failed');raise

 def _sash_key(self):return 'human_baseline_annotation_sash'
 def _restore_sash(self,_event=None):
  try:
   width=self.panes.winfo_width()
   if width<500:return
   stored=self.project.get_ui_state(self._sash_key(),None)
   default=min(320,max(240,int(width*.25)))
   self.panes.sashpos(0,max(220,min(width-420,int(stored if stored is not None else default))))
  except Exception:pass
 def _save_sash(self,_event=None):
  try:self.project.set_ui_state(self._sash_key(),int(self.panes.sashpos(0)))
  except Exception:pass

 def _header(self):
  status=_repeat_resolution_status(self.schema,self.adapter.points())
  return f"Annotation {self.pass_number} · Image {self.index+1}/{len(self.session_ids)} · Resolved {len(status['required'] & status['resolved'])}/{len(status['required'])}"

 def _attention(self):
  return tuple(self.review_attention.get(self.sid,()) or ())

 def _attention_ids(self):
  return {int(value) for issue in self._attention() for value in issue.get('landmark_ids',())}

 def _table(self,current):
  if self._tree_syncing:return
  self._tree_syncing=True
  try:
   self.landmark_table.delete(*self.landmark_table.get_children())
   points=self.adapter.points();attention_ids=self._attention_ids()
   for row in self.schema:
    point=points.get(row['id']);tag='unresolved' if point is None else 'missing' if point.get('state')=='missing' else 'present';tags=(tag,'review_warning') if int(row['id']) in attention_ids else (tag,)
    self.landmark_table.insert('', 'end',iid=str(row['id']),values=({'present':'✓','missing':'●','unresolved':'○'}[tag],row['id'],row.get('role','BOTH'),row['abbr'],row['name']),tags=tags)
   self._ignore_tree_event=True;self.landmark_table.selection_set(str(current));self.landmark_table.see(str(current))
   selected_point=points.get(int(current)) or {};self.missing_button.configure(text='Unmark missing' if selected_point.get('state')=='missing' else 'Mark as missing')
   status=_repeat_resolution_status(self.schema,points);resolved=len(status['required'] & status['resolved']);suffix='original saved scheme' if getattr(self,'schema_changed',False) else 'review' if self.edit_completed else 'blind pass'
   attention=self._attention();warning=(' · CHECK: '+attention[0].get('message','possible point error')) if attention else ''
   unresolved=_repeat_resolution_labels(self.schema,status)
   unresolved_text=(f" · Unresolved: {unresolved[0]}" if unresolved else '')
   if len(unresolved)>1:unresolved_text+=f" (+{len(unresolved)-1})"
   self.resolved_label.configure(text=f"Image {self.index+1} of {len(self.session_ids)} · Resolved {resolved} of {len(status['required'])} · {suffix}{unresolved_text}{warning}")
   # Keep navigation actionable: confirm() explains unresolved landmarks instead
   # of silently disabling the button.
   self.confirm_button.configure(state='normal')
  finally:self._tree_syncing=False

 def clear_all(self):
  if not self.surface or not self.surface.points:return
  if messagebox.askyesno('Clear all landmarks','Clear all repeat-session landmarks for this image?',parent=self):self.surface.clear_all()

 def pick(self,_=None):
  if self._tree_syncing:return
  if self._ignore_tree_event:self._ignore_tree_event=False;return
  selected=self.landmark_table.selection()
  if selected and self.surface:self.surface.current=int(selected[0]);self.surface.render()

 def _confirm_key(self,_event=None):
  try:self.confirm()
  except tk.TclError:pass
  return 'break'

 def _update_navigation(self):
  nav=_repeat_navigation_text(self.edit_completed,self.index,len(self.session_ids),self._dirty,self.attention_review)
  self.batch_label.configure(text=nav['batch']);self.previous_button.configure(state='normal' if self.index else 'disabled');self.confirm_button.configure(text=nav['next'])

 def load(self):
  self.sid=self.session_ids[self.index];self._dirty=False
  data=blind_session_input(self.project,self.sid);self.schema=data['schema'];self.schema_changed=bool(data.get('schema_changed'));self.adapter=RepeatSessionAdapter(self.project,self.sid,self._header,before_edit=self._ensure_current_editable,after_edit=self._after_current_edit);points=self.adapter.points()
  with Image.open(data['standardized_image_path']) as source:image=source.convert('RGB')
  self.adapter.on_selected=self._table;self.adapter.on_redrawn=lambda _current:None
  self.surface=LandmarkAnnotationSurface(self,self.adapter,canvas=self.canvas,display_settings=load_display_settings(self.project))
  attention_ids=sorted(self._attention_ids());self.surface.load(image,self.schema,points,current=attention_ids[0] if attention_ids else None,highlight_ids=attention_ids);self._restore_sash();self._update_navigation()

 def _ensure_current_editable(self):
  data=_load(self.project,self.sid)
  if self.edit_completed and data.get('status')=='completed':reopen_repeat_session_for_correction(self.project,self.sid);return
  if data.get('status')!='in_progress':raise ValueError('repeat session is not open for editing')

 def _after_current_edit(self):
  if not self._dirty:
   self._dirty=True;self._update_navigation()
   callback=getattr(self,'on_review_modified',None)
   if callback:callback()
   self._notify_state_changed()

 def _save_review_current(self,show_warning=True):
  data=_load(self.project,self.sid)
  if data.get('status')=='completed':return True
  if data.get('status')!='in_progress':
   if show_warning:messagebox.showwarning('Human repeatability','This review image is not editable.',parent=self)
   return False
  status=_repeat_resolution_status(self.schema,self.adapter.points())
  if not status['complete']:
   if show_warning:
    details=list(_repeat_resolution_labels(self.schema,status))
    if status['unexpected']:details.append('Unexpected IDs: '+', '.join(map(str,sorted(status['unexpected']))))
    messagebox.showwarning('Human repeatability','Resolve all landmarks before continuing.\n\n'+'\n'.join(details)+'\n\nPlace each unresolved landmark or use Mark as missing.',parent=self)
   return False
  try:complete_repeat_session(self.project,self.sid)
  except ValueError as exc:
   if show_warning:messagebox.showwarning('Human repeatability',str(exc),parent=self)
   return False
  callback=getattr(self,'on_review_saved',None)
  if callback:callback()
  self._notify_state_changed();self._dirty=False;return True

 def previous(self):
  if not self.index:return
  if self.edit_completed:
   if not self._save_review_current():return
  else:
   target=self.session_ids[self.index-1]
   if _load(self.project,target).get('status')=='completed':reopen_repeat_session_for_correction(self.project,target)
  self.index-=1;self.load()

 def _notify_state_changed(self):
  callback=getattr(self,'on_state_changed',None)
  if callback:
   try:callback()
   except tk.TclError:pass

 def close_window(self):
  if self.edit_completed:
   data=_load(self.project,self.sid)
   if data.get('status')=='in_progress':
    if self._save_review_current(show_warning=False):pass
    elif messagebox.askyesno('Close review','The current image has unresolved corrections.\n\nDiscard those corrections and close?',parent=self):
     try:discard_repeat_session_correction(self.project,self.sid)
     except ValueError as exc:messagebox.showwarning('Human repeatability',str(exc),parent=self);return
     callback=getattr(self,'on_review_saved',None)
     if callback:callback()
    else:return
  callback=getattr(self,'on_review_closed',None)
  if callback:callback()
  self._notify_state_changed();self.destroy()

 def confirm(self):
  run_id=(getattr(self,'run',None) or {}).get('run_id','');sid=getattr(self,'sid','');pass_number=getattr(self,'pass_number','?');dirty=bool(getattr(self,'_dirty',False))
  try:session_status=_load(self.project,sid).get('status') if sid else 'unknown'
  except Exception:session_status='unknown'
  log(run_id,'REPEAT_CONFIRM','START',detail=f"pass={pass_number} index={self.index+1}/{len(self.session_ids)} sid={sid} edit_completed={self.edit_completed} dirty={dirty} session_status={session_status}")
  if self.edit_completed:
   if not self._save_review_current():
    log(run_id,'REPEAT_CONFIRM','BLOCKED',detail=f"pass={pass_number} sid={sid} reason=review_save_failed");return
  else:
   points=self.adapter.points();status=_repeat_resolution_status(self.schema,points)
   if not status['complete']:
    log(run_id,'REPEAT_CONFIRM','BLOCKED',detail=f"pass={pass_number} sid={sid} missing={sorted(status['missing'])} unexpected={sorted(status['unexpected'])}")
    details=list(_repeat_resolution_labels(self.schema,status))
    if status['unexpected']:details.append('Unexpected IDs: '+', '.join(map(str,sorted(status['unexpected']))))
    if status['missing'] and self.surface:
     first=min(status['missing']);self.surface.current=first;self.surface.render()
     try:self.landmark_table.selection_set(str(first));self.landmark_table.see(str(first))
     except tk.TclError:pass
    messagebox.showwarning('Human repeatability','Resolve all landmarks before continuing.\n\n'+'\n'.join(details)+'\n\nPlace each unresolved landmark or use Mark as missing.',parent=self);return
   try:complete_repeat_session(self.project,self.sid)
   except ValueError as exc:
    log(run_id,'REPEAT_SESSION_COMPLETE','ERROR',detail=f"pass={pass_number} sid={sid} error={exc!r}")
    messagebox.showwarning('Human repeatability',str(exc),parent=self);return
   log(run_id,'REPEAT_SESSION_COMPLETE','END',detail=f"pass={pass_number} sid={sid}")
   self._notify_state_changed()
  if self.index+1<len(self.session_ids):
   old_index=self.index;self.index+=1
   log(run_id,'REPEAT_NAVIGATE','END',detail=f"pass={pass_number} from={old_index+1} to={self.index+1}")
   self.load()
  else:
   log(run_id,'REPEAT_LAST_IMAGE','START',detail=f"pass={pass_number} sid={sid} calling_on_complete=1")
   try:result=self.on_complete()
   except BaseException as exc:
    log(run_id,'REPEAT_ON_COMPLETE','ERROR',detail=f"pass={pass_number} error={exc!r}\n{traceback.format_exc()}")
    raise
   log(run_id,'REPEAT_ON_COMPLETE','END',detail=f"pass={pass_number} result={result!r}")
   if result is False:
    log(run_id,'REPEAT_WINDOW','KEEP_OPEN',detail=f"pass={pass_number} reason=on_complete_false");return
   log(run_id,'REPEAT_WINDOW','DESTROY',detail=f"pass={pass_number}")
   self.destroy()
