"""Prototype-style Landmarks workspace wired to existing Project, AI and Human Baseline services."""
from tkinter import ttk, messagebox, colorchooser
import tkinter as tk
import threading, queue
from app.landmark_training_workflow import available_training_parents, prepare_landmark_training, run_landmark_training, validation_metrics
from app.landmark_ai_workflow import begin_improvement, control_set_summary, add_control_image, create_stage, stage_summary, workflow_current
from app.ai_batch import BatchError, active_backend, create_batch_for_ids, run_batch
from app.landmark_ai_review import (active_review_session, activate_review_session, complete_or_advance_review, create_review_session, pending_review_session, review_summary, create_review_session_for_ids)
from app.landmark_ai_service import LandmarkAIService
from app.active_learning import select_ai_worst_first
from app.smart_selection import create_improvement_selection
from app.landmark_frames import landmark_frame_ready, crop_frame_record
from app.landmark_attention_queue import (
 active as active_attention_queue, classify as classify_attention_issue,
 complete_current as complete_attention_current, clear_failure as clear_attention_failure,
 move as move_attention_queue, record_failure as record_attention_failure,
 start as start_attention_queue,
)
from app.landmark_review import scan_project
from app.landmark_suspicious_review import (
 active as suspicious_active, current as suspicious_current, start as start_suspicious_review,
 move as move_suspicious_review, complete_current as complete_suspicious_review,
)
from app.human_baseline import start_or_continue_run, current_run, previous_runs, available_control_image_ids, complete_run, ensure_pass, pass_progress, complete_pass, pass_session_ids, pending_pass_session_ids, redo_repeatability_image, reset_pass, abandon_run, mark_completed_run_stale, recompute_completed_run, pass_qc_complete, repeatability_pass_qc_issues, finalize_repeatability_pass_qc, finish_repeatability_pass
from app.human_baseline_ui import HumanBaselineWindow
from app.gui_crop_debug import log
from .section_base import SectionView
from .landmark_canvas import LandmarkCanvasController
from .dialogs import center
from .landmark_display import load_display_settings, save_display_settings, SYMBOL_LABELS, SYMBOL_NAMES, LABEL_LABELS, LABEL_NAMES, HALO_LABELS, HALO_NAMES
from .complex_qc_dialog import open_complex_qc

def _confirm_complex_qc_image(project,image_id):
 """Confirm one current Complex-QC image without any catalogue-wide work.

 A pending landmark_crop_review_required flag is allowed here: the operator is
 explicitly reviewing the landmarks on this final Crop, and mark_checked()
 clears that flag after the complete current state is confirmed.
 """
 crop=crop_frame_record(project,image_id)
 if not crop or crop.get("provenance") not in {"manual","ai_accepted","ai_corrected"} or not crop.get("human_verified"):
  raise ValueError("This image does not have a final usable Crop. Open Crop, repair/apply it, then return to Complex QC.")
 status=project.annotation_status(image_id)
 if not status.get("complete"):
  unresolved=tuple(status.get("unresolved_ids") or ())
  raise ValueError("Resolve all landmarks before Verify & Next"+(f": {', '.join(map(str,unresolved))}" if unresolved else "."))
 project.mark_checked(image_id)
 return project.annotation_status(image_id)

def _format_percent(value,digits=2):
 if value is None:return 'not available'
 return f"{float(value):.{int(digits)}f}%"

def _prediction_candidate_ids(project,rows):
 """Empty or previously AI-predicted images that remain AI-editable.

 Frame/Crop readiness is not filtered here: blocked candidates must enter the
 attention queue instead of disappearing from Predict all.
 """
 result=[]
 for item in rows:
  image_id=str(item['image_id'])
  if item.get('excluded') or project.landmark_prediction_locked(image_id):continue
  points=project.load_landmarks(image_id)
  if not points:
   result.append(image_id);continue
  if any(point.get('provenance')=='machine' or point.get('model_id') is not None or point.get('prediction_run_id') is not None for point in points.values()):
   result.append(image_id)
 return tuple(result)

def _prediction_target_ids(project,rows):
 return tuple(image_id for image_id in _prediction_candidate_ids(project,rows) if landmark_frame_ready(project,image_id))

def _prediction_blocked_ids(project,rows):
 return tuple(image_id for image_id in _prediction_candidate_ids(project,rows) if not landmark_frame_ready(project,image_id))

def _next_prediction_candidates(project,rows,start_image_id,count):
 candidates=set(_prediction_candidate_ids(project,rows))
 order=[str(item['image_id']) for item in rows if str(item['image_id']) in candidates]
 if not order:return ()
 start=str(start_image_id) if start_image_id is not None else None
 if start in order:
  position=order.index(start);order=order[position:]+order[:position]
 return tuple(order[:max(0,int(count))])

def _repeatability_diagram(parent):
 """Small text-independent visual: the same specimen image is annotated twice."""
 canvas=tk.Canvas(parent,width=430,height=96,bg="#fbfcfd",highlightthickness=1,highlightbackground="#d8dde3")
 def specimen(cx,cy,dots):
  canvas.create_rectangle(cx-68,cy-26,cx+68,cy+26,fill="#f1f4f6",outline="#a5afb7",width=2)
  canvas.create_line(cx-48,cy+9,cx-22,cy-10,cx+4,cy+4,cx+28,cy-15,cx+49,cy+8,fill="#b3bdc5",width=2,smooth=True)
  for x,y in dots:canvas.create_oval(cx+x-4,cy+y-4,cx+x+4,cy+y+4,fill="#256d9e",outline="white",width=1)
 left=[(-42,8),(-20,-8),(4,5),(27,-12),(48,7)]
 right=[(-40,7),(-19,-7),(5,4),(29,-11),(47,8)]
 specimen(105,51,left);specimen(325,51,right)
 canvas.create_line(184,51,246,51,fill="#8b98a3",width=2,arrow="last")
 canvas.create_oval(92,7,116,31,fill="#ffffff",outline="#c6cdd3");canvas.create_text(104,19,text="1",fill="#27313a",font=("Segoe UI",9,"bold"))
 canvas.create_oval(312,7,336,31,fill="#ffffff",outline="#c6cdd3");canvas.create_text(324,19,text="2",fill="#27313a",font=("Segoe UI",9,"bold"))
 return canvas

def _prediction_failure_summary(batch):
 failures=list((batch.get('failures') or {}).values())
 if not failures:return ''
 lines=[line.strip() for line in str(failures[0]).splitlines() if line.strip()]
 preferred=next((line for line in lines if line.startswith(('ModuleNotFoundError:','ImportError:','RuntimeError:','ValueError:','FileNotFoundError:'))),lines[-1] if lines else str(failures[0]))
 return preferred[:400]

def _landmark_toolbar_state(state,selected_id):
 point=(state.points_by_id.get(int(selected_id)) if state is not None and selected_id is not None else None) or {}
 missing=point.get('state')=='missing'
 verified=bool(getattr(state,'human_verified',False))
 return {
  'missing_text':'Unmark missing' if missing else 'Mark missing',
  'verify_text':'Verified ✓' if verified else 'Verify image',
  'verify_enabled':not verified,
 }

def _dispatch_repeatability_stage(action,open_pass_qc,update_report,schedule=None):
 scheduler=schedule or (lambda callback:callback())
 if action in {'pass_qc_1','pass_qc_2'}:
  number=int(action.rsplit('_',1)[1]);scheduler(lambda:open_pass_qc(number));return action
 if action=='report_update':
  update_report();return 'report_update'
 return 'continue'

def _repeatability_ask_then_scan(ask,scan):
 """Ask first; only an affirmative answer is allowed to run the QC scan."""
 answer=bool(ask())
 if not answer:return False,()
 return True,tuple(scan())

def _repeatability_flagged_review_plan(session_ids,issues):
 attention={}
 for item in issues:attention.setdefault(item['session_id'],[]).append(item)
 flagged_ids=[sid for sid in session_ids if sid in attention]
 return flagged_ids,attention

def _repeatability_pass_controls(run,p1,p2,available):
 """Annotation buttons only annotate/review; QC is an automatic post-batch step."""
 p1_complete=bool(p1.get('complete'));p2_complete=bool(p2.get('complete'))
 p1_checked=pass_qc_complete(run,1) if run else False
 p2_exists=bool(run and pass_session_ids(run,2))
 return {
  'one_text':'Review Annotation 1' if p1_complete else ('Continue Annotation 1' if p1.get('completed') else 'Start Annotation 1'),
  'two_text':'Review Annotation 2' if p2_complete else ('Continue Annotation 2' if p2.get('completed') else 'Start Annotation 2'),
  'one_enabled':bool(run) or int(available or 0)>0,
  'two_enabled':bool(run) and p1_complete and (p1_checked or p2_exists),
 }

def _prediction_context_text(project,row):
 if not row or row.get("human_verified") or row.get("status_color")=="green":return ""
 points=project.load_landmarks(str(row.get("image_id")))
 ai=[point for point in points.values() if point.get("provenance")=="machine" or point.get("model_id") or point.get("prediction_run_id")]
 if not ai:return ""
 models=sorted({str(point.get("model_id")) for point in ai if point.get("model_id")})
 model=", ".join(models) if models else "AI model"
 stamps=sorted(str(point.get("updated_at")) for point in ai if point.get("updated_at"))
 when=""
 if stamps:
  try:
   from datetime import datetime
   dt=datetime.fromisoformat(stamps[-1].replace("Z","+00:00")).astimezone()
   when=dt.strftime("%Y-%m-%d %H:%M")
  except ValueError:when=stamps[-1][:16].replace("T"," ")
 return "AI prediction · "+model+(f" · {when}" if when else "")

class LandmarksSection(SectionView):
 def render(self):
  panel=self.frame(padding=(6,4));panel.pack(fill="both",expand=True);panel.rowconfigure(1,weight=1);panel.columnconfigure(0,weight=1)

  controls=ttk.Frame(panel,style="Toolbar.TFrame");controls.grid(row=0,column=0,sticky="ew",pady=(0,4))
  self.canvas_frame=ttk.Frame(panel);self.canvas_frame.grid(row=1,column=0,sticky="nsew")
  # The image canvas must consume only the space left after the workflow dock.
  # A packed Tk Canvas otherwise propagates its requested height upward and can
  # push the second workflow-card row below the visible window.
  self.canvas_frame.pack_propagate(False)
  self.canvas=LandmarkCanvasController(self.canvas_frame,self.context,self.refresh,self._landmark_selected);self.canvas.on_image_ready=self._image_ready
  ttk.Label(controls,text='Landmark actions:',style='SectionTitle.TLabel').pack(side='left',padx=(0,6))
  self.missing_button=self.button(controls,'Mark missing',self.canvas.toggle_missing,'Mark the selected landmark as deliberately missing; click again to undo missing.',icon='missing');self.missing_button.pack(side='left',padx=2)
  self.button(controls,'Delete',self.canvas.delete_current,'Remove this landmark so it can be placed again.',icon='delete').pack(side='left',padx=2)
  self.button(controls,'Clear all…',self.canvas.clear_all,'Clear all editable landmarks on this image.',icon='clear').pack(side='left',padx=2)
  ttk.Separator(controls,orient='vertical').pack(side='left',fill='y',padx=(6,4),pady=3)
  self.verify_button=self.button(controls,'Verify image',self.canvas.mark_checked,'Verify this completed landmark set after human review.',icon='verify');self.verify_button.pack(side='left',padx=2)
  self.button(controls,'Display…',self.open_display_settings,'Change landmark colours, marker size and marker style.',icon='display').pack(side='right',padx=(8,2))
  ttk.Label(controls,text='Click = place · drag = correct',style="Muted.TLabel").pack(side='right',padx=(6,8))

  batch=tk.IntVar(value=24);prediction=tk.IntVar(value=24)
  guide='Why: Landmarks turns specimen anatomy into comparable point coordinates for morphometric analysis.\n\n1. Repeatability\nOptional. Mark the same control images twice, with a break between passes, to estimate your own placement error.\n\n2. Training data\nMark every required point or choose Mark missing. Use Verify & Next to finish each image.\n\n3. Train model\nTrain from all human-verified images. Choose Bootstrap for the first model or a saved model as the parent.\n\n4. Predict & review\nPredict only unresolved images. Yellow images already have complete AI landmark sets and belong in Review AI predictions. Verify & Next confirms each reviewed image. Final data QC is a separate post-verification audit of human-verified landmark sets.'
  dock=self.workflow_dock(panel,help_title='Landmarks — quick guide',help_text=guide);dock.grid(row=2,column=0,sticky='ew',pady=(2,0))

  repeat_run=current_run(self.context.project)
  if repeat_run is None:
   repeat_run=next((item for item in reversed(previous_runs(self.context.project)) if item.get('status')=='completed'),None)
  if repeat_run:
   repeat_total=int(repeat_run.get('actual_count',len(repeat_run.get('image_ids',()))));p1=pass_progress(self.context.project,repeat_run,1);p2=pass_progress(self.context.project,repeat_run,2);repeat_label=f'Run images: {repeat_total}'
  else:
   repeat_total=len(available_control_image_ids(self.context.project));p1={'completed':0,'total':0};p2={'completed':0,'total':0};repeat_label=f'Eligible images: {repeat_total}'
  one=dock.add_card('1. Repeatability',icon='landmark_repeat',help_text='Estimate your placement error from two independent annotations of the same images.')
  self.repeat_pool_label=ttk.Label(one,text=repeat_label.replace('Run images: ','').replace('Eligible images: ','')+' images',style='Muted.TLabel');self.repeat_pool_label.grid(row=0,column=0,sticky='w')
  self.repeat_pass_label=ttk.Label(one,text=f"P1 {p1['completed']}/{p1['total']} · P2 {p2['completed']}/{p2['total']}",style='Muted.TLabel');self.repeat_pass_label.grid(row=0,column=1,sticky='e',padx=(8,0))
  one.columnconfigure(1,weight=1)
  self.button(one,'Repeat…',self.open_repeat,'Open the two independent blind annotation passes.').grid(row=1,column=0,columnspan=2,sticky='w',pady=(5,0))

  two=dock.add_card('2. Training data',icon='landmark_training',help_text='Create or continue the human-annotated image set used for model training.')
  ttk.Label(two,text='Batch').grid(row=0,column=0,sticky='w')
  ttk.Spinbox(two,from_=1,to=500,textvariable=batch,width=5).grid(row=0,column=1,sticky='w',padx=4)
  ttk.Label(two,text='20–30 recommended',style='Muted.TLabel').grid(row=0,column=2,sticky='w')
  batch_info=stage_summary(self.context.project,create_missing=False);batch_state=batch_info['state']
  label='Start first batch' if not batch_state.get('initial_image_ids') else 'Continue batch' if batch_info['stage']=='INITIAL_TRAINING' or (batch_info['stage']=='MODEL_IMPROVEMENT' and batch_info['verified']<batch_info['total']) else 'Add next batch'
  self.button(two,label,lambda:self.start_training_batch(batch.get()),'Create or continue the persistent landmark training batch.').grid(row=1,column=0,columnspan=3,sticky='w',pady=(5,0))

  three=dock.add_card('3. Train model',icon='landmark_train',help_text='Train a new Landmark model from all human-confirmed examples.')
  active_warning=None
  try:active=self.context.project.active_model_readonly('landmark') or {}
  except ValueError:
   active={};active_warning='No compatible active model'
  parents=available_training_parents(self.context.project);saved=self.context.project.get_ui_state('landmark_training_parent_model_id',None);valid={item['model_id'] for item in parents};chosen=saved if saved in valid else active.get('model_id') if active.get('model_id') in valid else None
  parent_choice=tk.StringVar(master=panel,value=chosen or 'Bootstrap / first model')
  ttk.Label(three,text=active_warning or f"Active: {active.get('model_id','None')}",style='StatusChip.TLabel',anchor='w').grid(row=0,column=0,columnspan=3,sticky='ew')
  ttk.Label(three,text='From').grid(row=1,column=0,sticky='w',pady=(4,0))
  parent_box=ttk.Combobox(three,textvariable=parent_choice,values=tuple(item['model_id'] for item in parents) or ('Bootstrap / first model',),width=17,state='readonly')
  parent_box.grid(row=1,column=1,columnspan=2,sticky='ew',padx=(5,0),pady=(4,0));three.columnconfigure(1,weight=1)
  parent_box.bind('<<ComboboxSelected>>',lambda _event:self.context.project.set_ui_state('landmark_training_parent_model_id',None if parent_choice.get()=='Bootstrap / first model' else parent_choice.get()))
  self.button(three,'Train',lambda:self.preflight(None if parent_choice.get()=='Bootstrap / first model' else parent_choice.get()),'Check then run Landmark model training.',style='Primary.TButton').grid(row=2,column=0,columnspan=2,sticky='w',pady=(5,0))
  self.button(three,'Models…',lambda:self.shell.show_models('landmark'),'Compare and select saved Landmark models.').grid(row=2,column=2,sticky='e',padx=(5,0),pady=(5,0))

  four=dock.add_card('4. Predict & review',icon='landmark_apply',help_text='Run AI prediction, review the saved results, then perform final data QC.')
  batch_row=ttk.Frame(four);batch_row.grid(row=1,column=0,columnspan=3,sticky='w',pady=(5,0))
  ttk.Label(batch_row,text='Next').pack(side='left')
  ttk.Spinbox(batch_row,from_=1,to=500,textvariable=prediction,width=5).pack(side='left',padx=4)
  ttk.Label(batch_row,text='images',style='Muted.TLabel').pack(side='left')
  predict_actions=ttk.Frame(four);predict_actions.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(5,0))
  prediction_state='normal' if active else 'disabled'
  predict_actions.columnconfigure(0,weight=1,uniform='prediction_actions');predict_actions.columnconfigure(1,weight=1,uniform='prediction_actions')
  self.button(predict_actions,'Predict next',lambda:self.predict(False,prediction.get()),'Predict the next empty or previously AI-predicted image. Human-confirmed images are never changed.',state=prediction_state).grid(row=0,column=0,sticky='ew',padx=(0,3))
  self.button(predict_actions,'Predict all',lambda:self.predict(True,prediction.get()),'Predict all empty and previously AI-predicted images. Human-confirmed images are never changed.',state=prediction_state).grid(row=0,column=1,sticky='ew',padx=(3,0))
  review_actions=ttk.Frame(four);review_actions.grid(row=3,column=0,columnspan=3,sticky='ew',pady=(5,0))
  review_actions.columnconfigure(0,weight=1,uniform='review_actions');review_actions.columnconfigure(1,weight=1,uniform='review_actions')
  self.button(
   review_actions,'Review AI predictions',lambda:self.review_worst(prediction.get()),
   'Before verification only: review complete AI landmark predictions that have not yet been human-verified, starting with the highest-risk cases.',
   icon='review_worst',style='ReviewAction.TButton'
  ).grid(row=0,column=0,sticky='ew',padx=(0,3))
  self.button(
   review_actions,'Final data QC',lambda:open_complex_qc(self),
   'After verification only: audit final human-verified landmark sets for structural, measurement and geometric-morphometric outliers.',
   icon='complex_qc',style='ReviewAction.TButton'
  ).grid(row=0,column=1,sticky='ew',padx=(3,0))

  self._refresh_prediction_info();self.canvas.redraw_cached();self._refresh_landmark_sidebar();self._refresh_action_buttons()
 def _refresh_prediction_info(self):
  if not hasattr(self,"canvas"):return
  self.canvas.set_context_message(_prediction_context_text(self.context.project,self.context.current() or {}))
 def _refresh_action_buttons(self,state=None):
  state=state or getattr(self.canvas,'state',None)
  selected=getattr(getattr(self.canvas,'choice',None),'get',lambda:None)()
  values=_landmark_toolbar_state(state,selected)
  missing=getattr(self,'missing_button',None);verify=getattr(self,'verify_button',None)
  if missing and missing.winfo_exists():missing.configure(text=values['missing_text'])
  if verify and verify.winfo_exists():verify.configure(text=values['verify_text'],state='normal' if values['verify_enabled'] else 'disabled')

 def _refresh_repeatability_summary(self):
  """Refresh the visible workflow-card counters from persisted repeatability state."""
  pool=getattr(self,'repeat_pool_label',None);passes=getattr(self,'repeat_pass_label',None)
  if not pool or not passes:
   return
  try:
   if not pool.winfo_exists() or not passes.winfo_exists():return
   run=current_run(self.context.project)
   if run is None:
    run=next((item for item in reversed(previous_runs(self.context.project)) if item.get('status')=='completed'),None)
   if run:
    total=int(run.get('actual_count',len(run.get('image_ids',()))));p1=pass_progress(self.context.project,run,1);p2=pass_progress(self.context.project,run,2)
    pool.configure(text=f'{total} images')
   else:
    total=len(available_control_image_ids(self.context.project));p1={'completed':0,'total':0};p2={'completed':0,'total':0}
    pool.configure(text=f'{total} eligible')
   passes.configure(text=f"P1 {p1['completed']}/{p1['total']} · P2 {p2['completed']}/{p2['total']}")
  except tk.TclError:return

 def open_display_settings(self):
  current=load_display_settings(self.context.project)
  dialog=tk.Toplevel(self.shell);dialog.title('Landmark display');dialog.transient(self.shell);dialog.resizable(False,False)
  frame=ttk.Frame(dialog,padding=14);frame.pack(fill='both',expand=True);frame.columnconfigure(0,weight=1)
  ttk.Label(frame,text='Landmark display',style='SectionTitle.TLabel').grid(row=0,column=0,sticky='w')
  ttk.Label(frame,text='Choose a clear marker and label style for the current project.',style='Muted.TLabel').grid(row=1,column=0,sticky='w',pady=(2,10))

  selected=tk.StringVar(master=dialog,value=current['selected_color'])
  other=tk.StringVar(master=dialog,value=current['other_color'])
  size=tk.IntVar(master=dialog,value=current['size'])
  symbol=tk.StringVar(master=dialog,value=SYMBOL_NAMES.get(current['symbol'],'Circle'))
  label_mode=tk.StringVar(master=dialog,value=LABEL_NAMES.get(current['label'],'Number'))
  label_size=tk.IntVar(master=dialog,value=current['label_size'])
  halo=tk.StringVar(master=dialog,value=HALO_NAMES.get(current['halo'],'None'))

  colors=ttk.LabelFrame(frame,text='Colors',padding=(10,8));colors.grid(row=2,column=0,sticky='ew');colors.columnconfigure(1,weight=1)
  def color_row(row,label,var):
   ttk.Label(colors,text=label).grid(row=row,column=0,sticky='w',pady=4)
   preview=tk.Canvas(colors,width=30,height=18,highlightthickness=1,highlightbackground='#9aa3aa');preview.grid(row=row,column=1,sticky='w',padx=(10,8),pady=4)
   def paint(*_):
    preview.delete('all');preview.create_rectangle(0,0,32,20,fill=var.get(),outline=var.get())
   var.trace_add('write',paint);paint()
   def choose():
    value=colorchooser.askcolor(color=var.get(),parent=dialog,title=label)[1]
    if value:var.set(value)
   ttk.Button(colors,text='Choose…',command=choose).grid(row=row,column=2,sticky='e',pady=4)
  color_row(0,'Selected landmark',selected);color_row(1,'Other landmarks',other)

  marker=ttk.LabelFrame(frame,text='Marker',padding=(10,8));marker.grid(row=3,column=0,sticky='ew',pady=(8,0));marker.columnconfigure(1,weight=1)
  ttk.Label(marker,text='Style').grid(row=0,column=0,sticky='w',pady=4)
  ttk.Combobox(marker,textvariable=symbol,values=tuple(SYMBOL_LABELS),state='readonly',width=16).grid(row=0,column=1,sticky='w',padx=(10,0),pady=4)
  ttk.Label(marker,text='Size').grid(row=1,column=0,sticky='w',pady=4)
  ttk.Spinbox(marker,from_=3,to=12,textvariable=size,width=5).grid(row=1,column=1,sticky='w',padx=(10,0),pady=4)
  ttk.Label(marker,text='Contrast halo').grid(row=2,column=0,sticky='w',pady=4)
  ttk.Combobox(marker,textvariable=halo,values=tuple(HALO_LABELS),state='readonly',width=16).grid(row=2,column=1,sticky='w',padx=(10,0),pady=4)

  labels=ttk.LabelFrame(frame,text='Label',padding=(10,8));labels.grid(row=4,column=0,sticky='ew',pady=(8,0));labels.columnconfigure(1,weight=1)
  ttk.Label(labels,text='Show').grid(row=0,column=0,sticky='w',pady=4)
  ttk.Combobox(labels,textvariable=label_mode,values=tuple(LABEL_LABELS),state='readonly',width=16).grid(row=0,column=1,sticky='w',padx=(10,0),pady=4)
  ttk.Label(labels,text='Font size').grid(row=1,column=0,sticky='w',pady=4)
  ttk.Spinbox(labels,from_=8,to=24,textvariable=label_size,width=5).grid(row=1,column=1,sticky='w',padx=(10,0),pady=4)

  status=tk.StringVar(master=dialog,value='')
  ttk.Label(frame,textvariable=status,style='Muted.TLabel').grid(row=5,column=0,sticky='w',pady=(8,0))
  actions=ttk.Frame(frame);actions.grid(row=6,column=0,sticky='e',pady=(10,0))
  def reset():
   selected.set('#ffb000');other.set('#00e5ff');size.set(5);symbol.set('Circle');label_mode.set('Number');label_size.set(10);halo.set('None');status.set('Defaults loaded. Click Apply to use them.')
  ttk.Button(actions,text='Reset',command=reset).pack(side='left')
  ttk.Button(actions,text='Close',command=dialog.destroy).pack(side='left',padx=(6,0))
  def apply():
   save_display_settings(self.context.project,{
    'selected_color':selected.get(),'other_color':other.get(),'size':size.get(),
    'symbol':SYMBOL_LABELS.get(symbol.get(),'circle'),'label':LABEL_LABELS.get(label_mode.get(),'number'),
    'label_size':label_size.get(),'halo':HALO_LABELS.get(halo.get(),'none'),
   })
   self.canvas.apply_display_settings();status.set('Applied.')
  ttk.Button(actions,text='Apply',command=apply,style='Primary.TButton').pack(side='left',padx=(6,0))
  center(self.shell,dialog)

 def refresh(self):
  # A persisted landmark edit refreshes one authoritative list row, never the catalogue.
  image_id=self.canvas.image_id or (self.context.current() or {}).get("image_id");self.context.refresh_landmark_state(image_id);self.context.update_landmark_counts(image_id);self.shell._update_status();panel=getattr(self.shell,"photo_panel",None);panel and panel.refresh(preserve_scroll=True);state=self.canvas.take_fresh_state() or self.canvas.refresh_authoritative(notify=False);self._refresh_prediction_info();self._refresh_landmark_sidebar(state);self._refresh_action_buttons(state)
 def cancel_pending_for_target(self,image_id):
  """Discard a deferred Next unless it belongs to this exact target image."""
  pending=getattr(self,'_pending_next_image_id',None)
  if pending and pending[0] != image_id:self._pending_next_image_id=None
 def on_image_selected(self):
  # ProductionShell calls this after idle, after the photo-list selection has painted.
  current=(self.context.current() or {}).get('image_id')
  self.cancel_pending_for_target(current)
  self._refresh_prediction_info()
  self.canvas.on_image_ready=self._image_ready
  request_epoch=getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0))
  self.canvas.load_current(request_epoch)
 def _image_ready(self,image_id,generation,request_epoch=None):
  if getattr(self,'_pending_next_image_id',None)==(image_id,request_epoch):
   self._pending_next_image_id=None
   self.navigate_training_batch(1);return
  if getattr(self,'_pending_review_next',None)==(image_id,request_epoch):
   self._pending_review_next=None
   self.navigate_prediction_review(1);return
  if not self._apply_review_worst_highlight():self._apply_suspicious_highlight()
  self._refresh_action_buttons(getattr(self.canvas,'state',None))
 def _inline_status(self,text):
  if hasattr(self.shell,'status_context'):self.shell.status_context.configure(text=text)

 def _apply_review_worst_highlight(self):
  session=active_review_session(self.context.project);current=(self.context.current() or {}).get('image_id')
  if not session or session.get('kind')!='review_worst_v2' or current not in session.get('image_ids',()):
   return False
  meta=(session.get('review_meta') or {}).get(str(current)) or {}
  reason=str(meta.get('reason') or 'Check AI prediction')
  display_reason='Inspect all landmarks' if reason.startswith('Correction history:') else reason
  # Review worst ranks whole images. Do not visually imply that suggested
  # landmarks are necessarily the only wrong ones.
  self.canvas.clear_review_landmarks()
  self._inline_status('Review AI predictions: '+display_reason)
  return True

 def _apply_suspicious_highlight(self):
  issue=suspicious_current(self.context.project)
  current=(self.context.current() or {}).get('image_id')
  if issue and issue.get('image_id')==current:
   self.canvas.set_review_landmarks(issue.get('landmark_ids',()),issue.get('message','Check suspicious landmark placement'))
   active=suspicious_active(self.context.project) or {}
   if active.get('source')=='Final data QC':
    self._inline_status('Final data QC — highlighted landmarks contribute to the outlier signal; they are not automatically errors. '+issue.get('message',''))
   else:self._inline_status('Check suspicious landmarks: '+issue.get('message',''))
  else:self.canvas.clear_review_landmarks()

 def _select_suspicious_issue(self):
  issue=suspicious_current(self.context.project)
  if not issue:return False
  try:self.context.selected=next(i for i,row in enumerate(self.context.rows) if row.get('image_id')==issue.get('image_id'))
  except StopIteration:return False
  self._sync_photo_selection();self.shell._selected_image(False);self.shell._update_status();return True

 def navigate_suspicious_review(self,step):
  review_state=suspicious_active(self.context.project)
  if not review_state:return False
  source=str(review_state.get('source') or '')
  complex_qc=source=='Final data QC'
  issue=suspicious_current(self.context.project);current=(self.context.current() or {}).get('image_id')
  # Never confirm a queue item while the operator is looking at another image.
  if issue and issue.get('image_id')!=current:return self._select_suspicious_issue()
  if int(step)>0:
   if complex_qc and current:
    ready=getattr(self.canvas,'ready_for',None)
    if ready is not None and not ready(current):
     self._pending_next_image_id=(current,getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0)));self._inline_status('Preparing image…');return True
    try:
     _confirm_complex_qc_image(self.context.project,current)
     self.context.refresh_landmark_state(current);self.context.update_landmark_counts(current);self.shell._update_status()
    except Exception as exc:
     messagebox.showwarning('Final data QC',str(exc),parent=self.shell);return True
   if issue and issue.get('kind')!='complex_qc_routine':
    try:self.context.project.accept_review_warning(issue['image_id'],issue.get('payload') or issue)
    except Exception as exc:
     messagebox.showerror('Landmark error check',str(exc),parent=self.shell);return True
   _state,finished=complete_suspicious_review(self.context.project)
  else:_state,finished=move_suspicious_review(self.context.project,-1)
  if finished:
   self.canvas.clear_review_landmarks()
   title='Final data QC' if complex_qc else 'Landmark error check'
   message='Final data QC review complete.' if complex_qc else 'Suspicious-landmark review complete.'
   messagebox.showinfo(title,message,parent=self.shell);self.shell._update_status();return True
  next_issue=suspicious_current(self.context.project);current=(self.context.current() or {}).get('image_id')
  if next_issue and next_issue.get('image_id')==current and self.canvas.ready_for(current):
   self._apply_suspicious_highlight();self.shell._update_status();return True
  return self._select_suspicious_issue()

 def _offer_batch_error_review(self,image_ids,title,summary):
  ids=tuple(dict.fromkeys(str(value) for value in image_ids))
  if not ids:
   messagebox.showinfo(title,summary,parent=self.shell);return
  answer=messagebox.askyesno(title,summary+'\n\nCheck suspicious landmark placements now?',parent=self.shell,default=messagebox.YES)
  if not answer:return
  dialog=tk.Toplevel(self.shell);dialog.title('Check landmark placements');dialog.transient(self.shell)
  frame=ttk.Frame(dialog,padding=14);frame.pack(fill='both',expand=True)
  label=ttk.Label(frame,text='Preparing landmark checks…',justify='left');label.pack(anchor='w')
  bar=ttk.Progressbar(frame,mode='indeterminate');bar.pack(fill='x',pady=(8,0));bar.start()
  events=queue.Queue();center(self.shell,dialog)
  def worker():
   try:
    result=scan_project(self.context.project,image_ids=ids,progress=lambda done,total:events.put(('progress',done,total)))
    events.put(('done',result))
   except Exception as exc:events.put(('error',exc))
  threading.Thread(target=worker,daemon=True,name='production-landmark-batch-qc').start()
  def poll():
   try:
    while True:
     kind,*value=events.get_nowait()
     if kind=='progress':
      bar.stop();bar.configure(mode='determinate',maximum=value[1],value=value[0]);label.configure(text=f'Checking landmark placements: {value[0]} / {value[1]}')
     elif kind=='error':
      dialog.destroy();messagebox.showerror('Landmark error check',str(value[0]),parent=self.shell);return
     else:
      dialog.destroy();issues=list(value[0].get('queue') or ())
      if not issues:messagebox.showinfo('Landmark error check','No suspicious landmark placements were found in this batch.',parent=self.shell);return
      start_suspicious_review(self.context.project,issues,source=title)
      first=issues[0]['image_id']
      try:self.context.selected=next(i for i,row in enumerate(self.context.rows) if row.get('image_id')==first)
      except StopIteration:pass
      self.shell.render();self.shell.after_idle(lambda:self.shell._selected_image(False));return
   except queue.Empty:self.shell.after(100,poll)
  poll()
 def select_landmark(self,ident): self.canvas.set_choice(ident)
 def _landmark_selected(self,ident):
  if hasattr(self,"canvas"): self._refresh_landmark_sidebar();self._refresh_action_buttons()
 def _refresh_landmark_sidebar(self,state=None):
  panel=getattr(self.shell,'photo_panel',None)
  if hasattr(panel,'refresh_landmarks'): panel.refresh_landmarks(self.canvas.choice.get(),state or self.canvas.state)
 def open_repeat(self):
  run=current_run(self.context.project)
  if run is None:
   run=next((item for item in reversed(previous_runs(self.context.project)) if item.get('status')=='completed'),None)
  self._show_repeatability_launcher(run)
 def _show_repeatability_launcher(self,run):
  dialog=tk.Toplevel(self.shell);dialog.title('Human repeatability');dialog.transient(self.shell);dialog.resizable(False,False)
  frame=ttk.Frame(dialog,padding=16);frame.pack(fill='both',expand=True);frame.columnconfigure(0,weight=1)
  ttk.Label(frame,text='Human repeatability',font=('Segoe UI',11,'bold')).grid(row=0,column=0,sticky='w')
  diagram=_repeatability_diagram(frame);diagram.grid(row=1,column=0,sticky='ew',pady=(8,8))
  ttk.Label(frame,text='Annotate the same images twice independently. The difference estimates your placement error.',justify='left',wraplength=560).grid(row=2,column=0,sticky='w',pady=(0,2))
  ttk.Label(frame,text='Annotation 2 never shows Annotation 1.',justify='left',wraplength=560,style='Muted.TLabel').grid(row=3,column=0,sticky='w',pady=(0,10))

  available=len(available_control_image_ids(self.context.project));default=min(10,available);count=tk.IntVar(master=dialog,value=default or 0)
  sample=ttk.LabelFrame(frame,text='Sample size',padding=(10,8));sample.grid(row=4,column=0,sticky='ew');sample.columnconfigure(3,weight=1)
  ttk.Label(sample,text='Images').grid(row=0,column=0,sticky='w')
  spin=ttk.Spinbox(sample,from_=1,to=max(1,available),textvariable=count,width=5);spin.grid(row=0,column=1,sticky='w',padx=(8,10))
  sample_note=ttk.Label(sample,text='',style='Muted.TLabel');sample_note.grid(row=1,column=0,columnspan=4,sticky='w',pady=(5,0))
  new_sample=self.button(sample,'Start new sample',lambda:None,'Start a new repeatability run with the selected number of images.')
  new_sample.grid(row=0,column=2,sticky='w');new_sample.grid_remove()
  repair=ttk.Frame(sample);repair.grid(row=2,column=0,columnspan=4,sticky='w',pady=(7,0));repair.grid_remove()
  ttk.Label(repair,text='Redo one image').pack(side='left')
  repair_position=tk.IntVar(master=dialog,value=1)
  repair_spin=ttk.Spinbox(repair,from_=1,to=1,textvariable=repair_position,width=5);repair_spin.pack(side='left',padx=(7,5))
  repair_button=self.button(repair,'Redo',lambda:None,'Replace only this image in Annotation 1 and Annotation 2; every other image stays unchanged.')
  repair_button.pack(side='left')

  passes=ttk.Frame(frame);passes.grid(row=5,column=0,sticky='ew',pady=(10,0));passes.columnconfigure(0,weight=1);passes.columnconfigure(1,weight=1)
  one_box=ttk.LabelFrame(passes,text='Annotation 1',padding=(10,8));one_box.grid(row=0,column=0,sticky='nsew',padx=(0,5))
  two_box=ttk.LabelFrame(passes,text='Annotation 2',padding=(10,8));two_box.grid(row=0,column=1,sticky='nsew',padx=(5,0))
  one_status=ttk.Label(one_box,text='',style='Muted.TLabel');one_status.pack(anchor='w')
  two_status=ttk.Label(two_box,text='',style='Muted.TLabel');two_status.pack(anchor='w')
  one_actions=ttk.Frame(one_box);one_actions.pack(anchor='w',pady=(8,0))
  two_actions=ttk.Frame(two_box);two_actions.pack(anchor='w',pady=(8,0))

  def clamp_count():
   try:value=int(count.get())
   except (TypeError,ValueError):value=default or 1
   value=max(1,min(max(1,available),value)) if available else 0
   count.set(value);return value

  def refresh(reset_count=True):
   nonlocal run
   if run:
    from app.human_baseline import _run_by_id
    _,run=_run_by_id(self.context.project,run['run_id'])
    p1=pass_progress(self.context.project,run,1);p2=pass_progress(self.context.project,run,2);actual=int(run.get('actual_count',len(run.get('image_ids',()))))
    if reset_count:count.set(actual)
    spin.configure(state='normal' if available else 'disabled');new_sample.grid()
    repair_spin.configure(from_=1,to=max(1,actual));repair.grid()
    sample_note.configure(text=f'Current run: {actual} images · recommended default: 10 · available: {available}. Change the number and use Start new sample to replace this run.')
   else:
    p1=p2={'completed':0,'total':0,'complete':False};clamp_count();spin.configure(state='normal' if available else 'disabled');new_sample.grid_remove();repair.grid_remove()
    sample_note.configure(text=f'Recommended default: 10 · available eligible images: {available}. Choose the number before Annotation 1.')
   one_status.configure(text=f"{p1['completed']} / {p1['total']} images complete" if p1['total'] else 'Not started')
   two_status.configure(text=f"{p2['completed']} / {p2['total']} images complete" if p2['total'] else 'Not started')
   controls=_repeatability_pass_controls(run,p1,p2,available)
   one_open.configure(text=controls['one_text']);one_open.state(['!disabled'] if controls['one_enabled'] else ['disabled'])
   two_open.configure(text=controls['two_text']);two_open.state(['!disabled'] if controls['two_enabled'] else ['disabled'])
   one_reset.configure(state='normal' if run and bool(pass_session_ids(run,1)) else 'disabled')
   two_reset.configure(state='normal' if run and bool(pass_session_ids(run,2)) else 'disabled')

  def start_new_sample():
   nonlocal run
   if not available:return
   wanted=clamp_count()
   if run and run.get('status')=='in_progress':
    p1=pass_progress(self.context.project,run,1);p2=pass_progress(self.context.project,run,2)
    if (p1['completed'] or p2['completed']) and not messagebox.askyesno('Start new sample','Start a new repeatability sample?\n\nThe current run will be retired from active use but kept in the audit history.',parent=dialog):return
    try:abandon_run(self.context.project,run['run_id'],reason='sample_size_changed')
    except Exception as exc:messagebox.showerror('Human repeatability',str(exc),parent=dialog);return
   try:run,_=start_or_continue_run(self.context.project,count=wanted)
   except Exception as exc:messagebox.showerror('Human repeatability',str(exc),parent=dialog);return
   refresh(reset_count=True);self._refresh_repeatability_summary();self.shell._update_status()
  new_sample.configure(command=start_new_sample)

  def redo_one_image():
   nonlocal run
   if not run:return
   total=len(run.get('image_ids',()))
   try:position=int(repair_position.get())
   except (TypeError,ValueError):position=0
   if position<1 or position>total:
    messagebox.showwarning('Redo one image',f'Choose an image number from 1 to {total}.',parent=dialog);return
   image_id=str(run['image_ids'][position-1])
   if not messagebox.askyesno('Redo one image',f'Redo image {position}/{total}?\n\nID: {image_id}\n\nOnly this image will be replaced in Annotation 1 and Annotation 2. All other images remain unchanged.',parent=dialog,default='yes'):return
   try:
    run,result=redo_repeatability_image(self.context.project,run['run_id'],position)
   except Exception as exc:messagebox.showerror('Redo one image',str(exc),parent=dialog);return
   refresh(reset_count=True);self._refresh_repeatability_summary();self.context.invalidate_counts();self.shell._update_status()
   messagebox.showinfo('Redo one image',f"Image {result['position']}/{result['total']} reset only.\nID: {result['image_id']}\n\nOpen Annotation 1 and redo that image, then Annotation 2.",parent=dialog)
  repair_button.configure(command=redo_one_image)

  def _after_pass_qc(number,issues,*,finished_with_warnings):
   nonlocal run
   run_id=run.get('run_id','')
   log(run_id,'REPEAT_PASS_QC_FINALIZE','START',detail=f"pass={number} issues={len(issues)} warnings={finished_with_warnings}")
   def worker(progress):
    progress('Saving point-check result…')
    if int(number)==2:progress('Calculating repeatability P90…')
    return finalize_repeatability_pass_qc(self.context.project,run_id,number,issues,finished_with_warnings=finished_with_warnings,include_model=False)
   def done(result):
    nonlocal run
    run,report=result
    log(run_id,'REPEAT_PASS_QC_FINALIZE','END',detail=f"pass={number} report={report is not None}")
    refresh(reset_count=True);self._refresh_repeatability_summary();self.context.invalidate_counts();self.shell._update_status()
    if int(number)==2 and report is not None:
     p90=(report.get('human') or {}).get('aggregate',{}).get('p90_error_percent')
     messagebox.showinfo('Human repeatability',f"Repeatability complete.\nP90: {_format_percent(p90)}",parent=dialog)
   self.shell._run_background_task('Human repeatability','Saving point-check result…',worker,done)
   return True

  def offer_pass_qc(number):
   nonlocal run
   number=int(number)
   if not run:return
   from app.human_baseline import _run_by_id
   try:
    _,run=_run_by_id(self.context.project,run['run_id']);progress=pass_progress(self.context.project,run,number)
    if not progress['complete']:
     messagebox.showwarning('Check possible errors',f'Finish Annotation {number} first.',parent=dialog);return
   except Exception as exc:
    messagebox.showerror('Check possible errors',str(exc),parent=dialog);return

   run_id=run.get('run_id','')
   log(run_id,'REPEAT_PASS_QC_PROMPT','START',detail=f"pass={number}")
   answer=messagebox.askyesno(
    'Check possible errors',
    f'Annotation {number} is complete.\n\nCheck for likely landmark-placement errors now?',
    parent=dialog,default='yes'
   )
   log(run_id,'REPEAT_PASS_QC_PROMPT','END',detail=f"pass={number} answer={answer}")
   if not answer:
    _after_pass_qc(number,(),finished_with_warnings=False);return

   def open_review(issues):
    issues=list(issues)
    if not issues:
     messagebox.showinfo('Check possible errors','Analysis complete.\n\nNo likely landmark-placement errors were found.',parent=dialog)
     _after_pass_qc(number,(),finished_with_warnings=False);return
    flagged_ids,attention=_repeatability_flagged_review_plan(pass_session_ids(run,number),issues)
    def review_modified():
     mark_completed_run_stale(self.context.project,run['run_id'],pass_number=number)
    def review_saved():
     refresh(reset_count=False);self._refresh_repeatability_summary();self.context.invalidate_counts();self.shell._update_status()
    def review_closed():
     review_saved()
    def review_done():
     start_scan(after_review=True);return True
    log(run.get('run_id',''),'REPEAT_PASS_QC_REVIEW','START',detail=f"pass={number} images={len(flagged_ids)}")
    HumanBaselineWindow(
     self.shell,self.context.project,run,review_done,edit_completed=True,
     session_ids=flagged_ids,pass_number=number,on_state_changed=review_saved,
     on_review_modified=review_modified,on_review_saved=review_saved,on_review_closed=review_closed,
     start_session_id=flagged_ids[0],review_attention=attention
    )

   def start_scan(after_review=False):
    def worker(progress):
     log(run_id,'REPEAT_PASS_QC_SCAN','START',detail=f"pass={number}")
     progress('Analyzing landmark placement errors…')
     found=repeatability_pass_qc_issues(self.context.project,run,number)
     log(run_id,'REPEAT_PASS_QC_SCAN','END',detail=f"pass={number} issues={len(found)}")
     return list(found)
    def done(issues):
     if after_review:_after_pass_qc(number,issues,finished_with_warnings=bool(issues))
     else:open_review(issues)
    self.shell._run_background_task('Check possible errors','Analyzing landmark placement errors…',worker,done)

   start_scan()


  def open_pass(number):
   try:
    nonlocal run
    if run is None:
     run,_=start_or_continue_run(self.context.project,count=clamp_count())
    live,ids=ensure_pass(self.context.project,run['run_id'],number)
    review_existing=pass_progress(self.context.project,live,number)['complete']
    pass_meta=(live.get('passes',{}).get(str(int(number)),{}) or {})
    review_mode=review_existing or bool(pass_meta.get('completed_at'))
    if not review_mode:
     ids=pending_pass_session_ids(self.context.project,live,number) or ids
    completed_run=live.get('status')=='completed'
   except Exception as exc:messagebox.showwarning('Human repeatability',str(exc),parent=dialog);return
   review_was_modified=False
   def state_changed():
    refresh(reset_count=False);self._refresh_repeatability_summary();self.context.invalidate_counts();self.shell._update_status()
   def review_modified():
    nonlocal review_was_modified
    review_was_modified=True
    mark_completed_run_stale(self.context.project,run['run_id'],pass_number=number)
   def review_saved():
    state_changed()
   def review_closed():
    state_changed()
   def finished():
    run_id=run.get('run_id','')
    log(run_id,'REPEAT_PASS_FINISHED_CALLBACK','START',detail=f"pass={number}")
    try:
     latest,action=finish_repeatability_pass(self.context.project,run['run_id'],number)
     log(run_id,'REPEAT_PASS_STATE','END',detail=f"pass={number} action={action} run_status={latest.get('status')} final_qc={bool(latest.get('final_qc'))} report_stale={bool(latest.get('report_stale'))}")
     refresh(reset_count=True);self._refresh_repeatability_summary();self.context.invalidate_counts();self.shell._update_status()
     log(run_id,'REPEAT_PASS_REFRESH','END',detail=f"pass={number}")
     def update_report():
      def worker(progress):
       log(run_id,'REPEAT_REPORT_UPDATE','START',detail=f"pass={number}");progress('Recalculating repeatability P90…')
       return recompute_completed_run(self.context.project,run['run_id'],include_model=False)
      def done(report):
       human=report['human']['aggregate'];p90=human.get('p90_error_percent')
       log(run_id,'REPEAT_REPORT_UPDATE','END',detail=f"pass={number} p90={p90}")
       messagebox.showinfo('Human repeatability',f"Annotation {number} updated.\nP90: {_format_percent(p90)}",parent=dialog)
      self.shell._run_background_task('Human repeatability','Recalculating repeatability P90…',worker,done)
     log(run_id,'REPEAT_STAGE_DISPATCH','START',detail=f"pass={number} action={action} scheduler=after_idle")
     dispatched=_dispatch_repeatability_stage(action,offer_pass_qc,update_report,schedule=self.shell.after_idle)
     log(run_id,'REPEAT_STAGE_DISPATCH','END',detail=f"pass={number} dispatched={dispatched}")
     return True
    except Exception as exc:
     log(run_id,'REPEAT_PASS_FINISHED_CALLBACK','ERROR',detail=f"pass={number} error={exc!r}")
     messagebox.showerror('Human repeatability',str(exc),parent=dialog);return False
   HumanBaselineWindow(self.shell,self.context.project,live,finished,edit_completed=review_mode,session_ids=ids,pass_number=number,on_state_changed=state_changed,on_review_modified=review_modified,on_review_saved=review_saved,on_review_closed=review_closed)

  def reset_annotation(number):
   if not run:return
   if not messagebox.askyesno('Delete annotation',f'Delete Annotation {number} and make it again?\n\nThe old pass will no longer be used, but remains in the audit history.',parent=dialog):return
   try:reset_pass(self.context.project,run['run_id'],number)
   except Exception as exc:messagebox.showerror('Human repeatability',str(exc),parent=dialog);return
   refresh(reset_count=True);self._refresh_repeatability_summary();self.shell._update_status()

  one_open=self.button(one_actions,'Start Annotation 1',lambda:open_pass(1),'Start, continue, or review Annotation 1.');one_open.pack(side='left')
  one_reset=self.button(one_actions,'Delete & redo',lambda:reset_annotation(1),'Replace Annotation 1 with a new blind pass on the same images.');one_reset.pack(side='left',padx=(6,0))
  two_open=self.button(two_actions,'Start Annotation 2',lambda:open_pass(2),'Start, continue, or review Annotation 2.');two_open.pack(side='left')
  two_reset=self.button(two_actions,'Delete & redo',lambda:reset_annotation(2),'Replace Annotation 2 with a new blind pass on the same images.');two_reset.pack(side='left',padx=(6,0))
  qc_resume_scheduled=set()
  def resume_pending_qc():
   nonlocal run
   if not run:return
   from app.human_baseline import _run_by_id
   try:_,run=_run_by_id(self.context.project,run['run_id'])
   except Exception:return
   for number in (1,2):
    progress=pass_progress(self.context.project,run,number)
    if progress.get('complete') and not pass_qc_complete(run,number) and number not in qc_resume_scheduled:
     qc_resume_scheduled.add(number);offer_pass_qc(number);return

  def close_launcher():
   dialog.destroy();self.context.invalidate_counts();self.shell.render()
  dialog.protocol('WM_DELETE_WINDOW',close_launcher)
  refresh(reset_count=True);center(self.shell,dialog);self.shell.after_idle(resume_pending_qc)

 def add_current_control(self):
  row=self.context.current()
  if not row:return
  try:
   _summary,added=add_control_image(self.context.project,row['image_id'])
   messagebox.showinfo('Control Set','Current image added to the Control Set.' if added else 'Current image is already in the Control Set.',parent=self.shell);self.shell.render()
  except (KeyError,ValueError) as exc:messagebox.showwarning('Control Set',str(exc),parent=self.shell)
 def manage_control(self):
  dialog=tk.Toplevel(self.shell);dialog.title('Control manual landmarks');dialog.transient(self.shell);frame=ttk.Frame(dialog,padding=12);frame.pack(fill='both',expand=True);status=ttk.Label(frame,justify='left');status.pack(anchor='w')
  def refresh():
   summary=control_set_summary(self.context.project);status.config(text=f"Control: {summary.get('verified',0)} / {summary.get('total',0)}\nHuman repeatability uses two independent blind annotation passes.")
  def add():
   row=self.context.current()
   try:add_control_image(self.context.project,row['image_id']);refresh()
   except (KeyError,ValueError) as exc:messagebox.showwarning('Control Set',str(exc),parent=dialog)
  self.button(frame,'Add current image',add,'Add this image to the persistent Control Set.').pack(fill='x',pady=(8,2));self.button(frame,'Edit repeat annotations...',self.open_repeat,'Open the two-pass blinded repeatability workflow.').pack(fill='x',pady=2);self.button(frame,'Close',dialog.destroy,'Close this window.').pack(fill='x',pady=(8,0));refresh();center(self.shell,dialog)
 def _accept_current_batch_landmarks(self,image_id):
  """Accept one completed finite-batch landmark result without a global recount."""
  self.context.project.mark_checked(image_id)
  self.context.refresh_landmark_state(image_id)
  self.context.update_landmark_counts(image_id)
  self.canvas.refresh_authoritative(notify=False)
  panel=getattr(self.shell,'photo_panel',None)
  if panel:panel.refresh(preserve_scroll=True)
  self.shell._update_status()
 def _sync_photo_selection(self):
  """Reveal the selected image for either plain or landmark-composite lists."""
  panel=getattr(self.shell,'photo_panel',None)
  sync=getattr(panel,'sync_current',None)
  if sync is None:sync=getattr(getattr(panel,'photos',None),'sync_current',None)
  if sync:sync(reveal=True)
 def _select_review_image(self,session):
  ids=list(session.get('image_ids',()))
  image_id=session.get('current_image_id')
  if image_id not in ids:return False
  try:self.context.selected=next(i for i,row in enumerate(self.context.rows) if row['image_id']==image_id)
  except StopIteration:return False
  self._sync_photo_selection()
  self.shell._selected_image(False);return True
 def navigate_attention_queue(self,step):
  current=(self.context.current() or {}).get('image_id')
  if not active_attention_queue(self.context.project) or not current:return False
  if int(step)<0:
   move_attention_queue(self.context.project,-1);self.shell.open_landmark_attention();return True
  issue=classify_attention_issue(self.context.project,current)
  if issue.get('stage')=='prediction':
   self.predict(False,1,explicit_ids=(current,),title='Retry landmark prediction',selection_mode='attention_retry',attention_retry=True)
   return True
  if issue.get('stage')=='crop':
   self.shell.open_landmark_attention();return True
  ready=getattr(self.canvas,'ready_for',None)
  if ready is not None and not ready(current):
   self._pending_review_next=(current,getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0)))
   self._inline_status('Preparing image…');return True
  from app.landmark_state import load_current_landmark_state
  state=load_current_landmark_state(self.context.project,current)
  if not state.complete:
   labels={int(item['id']):item.get('abbr') or str(item['id']) for item in self.context.project.schema}
   unresolved=', '.join(labels.get(int(ident),str(ident)) for ident in sorted(state.unresolved_ids)) or 'the remaining landmarks'
   self._inline_status(f'Remaining landmarks: {unresolved}');return True
  points=self.context.project.load_landmarks(current)
  has_ai=any(point.get('provenance')=='machine' or point.get('model_id') is not None or point.get('prediction_run_id') is not None for point in points.values())
  try:
   if has_ai:self.context.project.confirm_landmark_ai_review(current,(active_attention_queue(self.context.project) or {}).get('batch_id'))
   else:self.context.project.mark_checked(current)
  except ValueError as exc:
   self._inline_status(str(exc));return True
  self.context.refresh_landmark_state(current);self.context.invalidate_counts()
  complete_attention_current(self.context.project,current)
  self.shell.open_landmark_attention();return True

 def _start_prediction_attention(self,batch,blocked=()):
  failures={str(key):str(value) for key,value in (batch.get('failures') or {}).items()}
  selected=[str(item.get('image_id')) for item in batch.get('selected_images',())]
  failed=[image_id for image_id in selected if image_id in failures]
  successful=[image_id for image_id in selected if image_id in (batch.get('prediction_runs') or {})]
  ordered=[];seen=set()
  for image_id in tuple(blocked)+tuple(failed)+tuple(successful):
   if image_id and image_id not in seen:seen.add(image_id);ordered.append(image_id)
  if not ordered:
   self.shell.render();return False
  from app.landmark_ai_review import supersede_unfinished_reviews
  supersede_unfinished_reviews(self.context.project,'landmark attention queue')
  start_attention_queue(self.context.project,ordered,batch_id=batch.get('batch_id'),failure_reasons=failures)
  self.shell.open_landmark_attention();return True

 def enter_landmark_review_session(self,batch_id=None):
  """One explicit production transition; never rely on a list-selection event."""
  session=activate_review_session(self.context.project,batch_id)
  if session is None:
   messagebox.showinfo('Prediction review','No unfinished prediction review is available.',parent=self.shell);return False
  if not self._select_review_image(session):
   messagebox.showerror('Prediction review','The saved prediction-review image is unavailable in this project.',parent=self.shell);return False
  # Rebuild the visible Landmarks workspace before its asynchronous canvas
  # request.  This makes the Yes path visibly enter review even when prediction
  # completion left a stale view instance on screen.
  self.shell.render();self.shell._update_status();self.shell.after_idle(lambda:self.shell._selected_image(False));self.shell.lift();self.shell.focus_force();return True
 def _open_review_session(self,batch_id=None):
  return self.enter_landmark_review_session(batch_id)
 def review_pending(self):
  session=pending_review_session(self.context.project)
  if session is None:
   messagebox.showinfo('Prediction review','No unfinished prediction review is available.',parent=self.shell);return
  self._open_review_session(session['batch_id'])
 def navigate_prediction_review(self,step):
  session=active_review_session(self.context.project)
  current=(self.context.current() or {}).get('image_id')
  if not session or current not in session.get('image_ids',()):return False
  if int(step)>0:
   ready=getattr(self.canvas,'ready_for',None)
   if ready is not None and not ready(current):
    self._pending_review_next=(current,getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0)))
    self._inline_status('Preparing image…');return True
   from app.landmark_state import load_current_landmark_state
   state=load_current_landmark_state(self.context.project,current)
   if not state.complete:
    labels={int(item['id']):item.get('abbr') or str(item['id']) for item in self.context.project.schema}
    unresolved=', '.join(labels.get(int(ident),str(ident)) for ident in sorted(state.unresolved_ids)) or 'the remaining landmarks'
    self._inline_status(f'Remaining landmarks: {unresolved}');return True
   try:self.context.project.confirm_landmark_ai_review(current,session['batch_id'])
   except ValueError as exc:
    text=str(exc)
    if text=="canonical Crop frame is required before confirming AI landmarks":
     text="This image needs a verified Crop before landmark review can be confirmed. Open Crop, verify/apply it, then return to Landmarks."
    messagebox.showwarning('Prediction review',text,parent=self.shell);return True
   self.refresh()
   session,completed=complete_or_advance_review(self.context.project,session['batch_id'],current)
   if completed:
    ready_count=self.context.landmark_counts().get('New/changed',0)
    summary=f"Prediction batch review complete.\nReviewed: {len(session['image_ids'])} / {len(session['image_ids'])}\nNew/changed for next training: {ready_count}"
    self.shell._update_status()
    self._offer_batch_error_review(session['image_ids'],'Prediction review complete',summary)
    return True
  else:
   from app.landmark_ai_review import move_review_position
   session=move_review_position(self.context.project,session['batch_id'],current,step)
  return self._select_review_image(session)
 def navigate_training_batch(self,step):
  """Navigate persisted finite batches; forward movement accepts a completed item."""
  if suspicious_active(self.context.project):return self.navigate_suspicious_review(step)
  if active_review_session(self.context.project):return self.navigate_prediction_review(step)
  # This direct state read deliberately avoids stage_summary(), which may refresh global workflow/catalog state.
  from app.landmark_ai_workflow import load_state,save_state
  state_doc=load_state(self.context.project);stage=state_doc.get('stage')
  if state_doc.get('finite_editing_complete'):return False
  key='initial_image_ids' if stage=='INITIAL_TRAINING' else 'improvement_image_ids' if stage=='MODEL_IMPROVEMENT' else ''
  ids=list(state_doc.get(key,()))
  current=(self.context.current() or {}).get('image_id')
  if stage not in {'INITIAL_TRAINING','MODEL_IMPROVEMENT'} or current not in ids:return False
  if int(step)>0:
   ready=getattr(self.canvas,'ready_for',None)
   if ready is not None and not ready(current):
    self._pending_next_image_id=(current,getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0)));self._inline_status('Preparing image…');return True
   if ready is None: state=getattr(self.canvas,'state',None)
   else:
    from app.landmark_state import load_current_landmark_state
    state=load_current_landmark_state(self.context.project,current)
   if not state or not state.complete:
    labels={int(item['id']):item.get('abbr') or str(item['id']) for item in self.context.project.schema}
    unresolved=', '.join(labels.get(int(ident),str(ident)) for ident in sorted(getattr(state,'unresolved_ids',()))) or 'the remaining landmarks'
    self._inline_status(f'Remaining landmarks: {unresolved}');return True
   try:self._accept_current_batch_landmarks(current)
   except ValueError as exc:
    messagebox.showwarning('Training batch',str(exc),parent=self.shell);return True
  if int(step)<0:self._pending_next_image_id=None
  position=ids.index(current);target=max(0,min(len(ids)-1,position+int(step)))
  if target==position and int(step)>0:
   state_doc['current_image_id']=current;state_doc['current_position']=position;state_doc['finite_editing_complete']=True;save_state(self.context.project,state_doc)
   ready=self.context.landmark_counts().get('New/changed',0);title='Training batch complete' if stage=='INITIAL_TRAINING' else 'Improvement batch complete';message=f"{title}.\nReviewed: {len(ids)} / {len(ids)}\nNew/changed for next training: {ready}";self.shell._update_status();self._offer_batch_error_review(ids,title,message);return True
  self.context.selected=next(i for i,row in enumerate(self.context.rows) if row['image_id']==ids[target])
  state_doc['current_image_id']=ids[target];state_doc['current_position']=target
  save_state(self.context.project,state_doc);self._sync_photo_selection();self.shell._selected_image(False);return True
 def review_worst(self,count=24):
  if active_attention_queue(self.context.project):
   self.shell.open_landmark_attention();return
  try:count=max(1,int(count))
  except (TypeError,ValueError):count=24
  def worker(progress):
   return select_ai_worst_first(self.context.project,count,progress=progress)
  def done(items):
   if not items:
    messagebox.showinfo('Review AI predictions','No AI landmark predictions are waiting for review.',parent=self.shell);return
   import hashlib
   ids=[item['image_id'] for item in items]
   metadata={item['image_id']:{
    'reason':item.get('reason','Check AI prediction'),
    'landmark_ids':list(item.get('review_landmark_ids') or ()),
    'risk_score':round(float(item.get('risk_score',0.0)),4),
    'learned_samples':int(item.get('learned_samples') or 0),
   } for item in items}
   session_id='review_worst_v2_'+hashlib.sha256(('\0'.join(ids)).encode('utf8')).hexdigest()[:16]
   create_review_session_for_ids(self.context.project,session_id,ids,kind='review_worst_v2',metadata=metadata)
   self._open_review_session(session_id)
  self.shell._run_background_task('Review AI predictions','Ranking complete AI predictions for review…',worker,done)
 def predict(self,remaining,count,explicit_ids=None,title='Predict landmarks',selection_mode=None,attention_retry=False):
  row=self.context.current();active=self.context.project.active_model_readonly('landmark') or {}
  if not active or (explicit_ids is None and not row):messagebox.showwarning('Landmark prediction','No active landmark model.',parent=self.shell);return
  explicit_ids=tuple(map(str,explicit_ids)) if explicit_ids is not None else None
  dialog=tk.Toplevel(self.shell);dialog.title(title);dialog.transient(self.shell);frame=ttk.Frame(dialog,padding=14);frame.pack();label=ttk.Label(frame,text='Preparing prediction…');label.pack(anchor='w');bar=ttk.Progressbar(frame,mode='indeterminate');bar.pack(fill='x',pady=(8,0));bar.start();events=queue.Queue();center(self.shell,dialog)
  def worker():
   try:
    model,backend=active_backend(self.context.project)
    blocked=()
    if explicit_ids is not None:
     ids=tuple(image_id for image_id in explicit_ids if landmark_frame_ready(self.context.project,image_id));blocked=tuple(image_id for image_id in explicit_ids if image_id not in ids);mode=selection_mode or 'explicit'
    elif remaining:
     candidates=_prediction_candidate_ids(self.context.project,self.context.rows)
     ids=tuple(image_id for image_id in candidates if landmark_frame_ready(self.context.project,image_id));blocked=tuple(image_id for image_id in candidates if image_id not in ids);mode='all_prediction_targets'
    else:
     candidates=_next_prediction_candidates(self.context.project,self.context.rows,row['image_id'],int(count))
     ids=tuple(image_id for image_id in candidates if landmark_frame_ready(self.context.project,image_id));blocked=tuple(image_id for image_id in candidates if image_id not in ids);mode='next_prediction_targets'
    if not ids:
     if blocked:events.put(('attention_only',blocked));return
     events.put(('empty','No images need AI landmark prediction.'));return
    data,path=create_batch_for_ids(self.context.project,model['model_id'],ids,selection_mode=mode)
    data,path=run_batch(self.context.project,path,LandmarkAIService(self.context.project,backend),progress=lambda done,total,name,image_id=None:events.put(('progress',done,total,name,image_id)),status=lambda text:events.put(('status',text)),retry_failures=True);events.put(('done',data,blocked))
   except Exception as exc:events.put(('error',exc))
  threading.Thread(target=worker,daemon=True,name='production-landmark-predict').start()
  def poll():
   try:
    while True:
     kind,*value=events.get_nowait()
     if kind=='status':
      bar.stop();bar.configure(mode='indeterminate');bar.start();label.config(text=value[0])
     elif kind=='progress':
      bar.stop();bar.configure(mode='determinate',maximum=value[1],value=value[0]);label.config(text=f'Predicting {value[0]} / {value[1]}: {value[2]}')
      image_id=value[3] if len(value)>3 else None
      if image_id and self.context.refresh_landmark_state(image_id):
       photo_panel=getattr(self.shell,'photo_panel',None);photos=getattr(photo_panel,'photos',photo_panel)
       refresh_one=getattr(photos,'refresh_image',None)
       if refresh_one:refresh_one(image_id)
     elif kind=='done':
      batch=value[0];blocked=value[1] if len(value)>1 else ()
      for item in batch.get('selected_images',()):self.context.refresh_landmark_state(item['image_id'])
      self.context.invalidate_counts();dialog.destroy()
      if attention_retry:
       current_id=str((self.context.current() or {}).get('image_id') or '')
       if current_id in (batch.get('failures') or {}):record_attention_failure(self.context.project,current_id,batch['failures'][current_id])
       else:clear_attention_failure(self.context.project,current_id)
       self.shell.open_landmark_attention();return
      self._start_prediction_attention(batch,blocked);return
     elif kind=='attention_only':
      dialog.destroy();start_attention_queue(self.context.project,value[0],batch_id=None);self.shell.open_landmark_attention();return
     elif kind=='empty':
      dialog.destroy();messagebox.showinfo('Landmark prediction',str(value[0]),parent=self.shell);return
     else:
      dialog.destroy()
      if attention_retry:
       current_id=str((self.context.current() or {}).get('image_id') or '')
       if current_id:record_attention_failure(self.context.project,current_id,str(value[0]))
       self.shell.open_landmark_attention();return
      messagebox.showerror('Landmark prediction',str(value[0]),parent=self.shell);return
   except queue.Empty:self.shell.after(100,poll)
  poll()
 def start_training_batch(self,count):
  """Open/create a finite Landmark batch without blocking Tk on catalogue selection."""
  total_rows=len(self.context.rows);requested=int(count)
  def worker(progress):
   progress('Checking landmark workflow…')
   info=stage_summary(self.context.project,create_missing=False);state=info['state']
   if not state.get('initial_image_ids'):
    progress('Selecting a diverse training batch…')
    state=create_stage(self.context.project,'INITIAL_TRAINING',min(requested,total_rows),allow_small=True);message='Manual training images'
   elif info['stage']=='INITIAL_TRAINING' or (info['stage']=='MODEL_IMPROVEMENT' and info['verified']<info['total']):
    message='Continue current batch'
   else:
    return ('improvement',state)
   progress('Finding the next unfinished image…')
   state,image_id,position,_=workflow_current(self.context.project,state)
   ids=state['initial_image_ids'] if state.get('stage')=='INITIAL_TRAINING' else state.get('improvement_image_ids',[])
   return ('open',state,image_id,message,list(ids))
  def done(payload):
   if payload[0]=='improvement':
    self._start_improvement_batch(requested,payload[1]);return
   _kind,state,image_id,message,ids=payload
   if image_id is not None:
    try:self.context.selected=next(i for i,row in enumerate(self.context.rows) if row['image_id']==image_id)
    except StopIteration:image_id=None
   messagebox.showinfo('Training batch',f"{message}: {len(ids)}. The first unverified image is now open.",parent=self.shell)
   self.shell.render()
  self.shell._run_background_task('Landmark training batch','Checking landmark workflow…',worker,done)

 def _start_improvement_batch(self,count,state):
  active=self.context.project.active_model_readonly("landmark")
  if not active:messagebox.showwarning('Training batch','Train the completed initial batch before creating an improvement batch.',parent=self.shell);return
  dialog=tk.Toplevel(self.shell);dialog.title('Create improvement batch');dialog.transient(self.shell);frame=ttk.Frame(dialog,padding=14);frame.pack(fill='both',expand=True);label=ttk.Label(frame,text='Selecting representative uncertain images…',justify='left');label.pack(anchor='w');bar=ttk.Progressbar(frame,mode='indeterminate');bar.pack(fill='x',pady=(8,0));bar.start();events=queue.Queue();center(self.shell,dialog)
  def worker():
   try:
    blocked=set(state.get('control_image_ids',()))|set(state.get('initial_image_ids',()))|set(state.get('improvement_history_ids',()))|set(state.get('improvement_image_ids',()))
    data,path,_=create_improvement_selection(self.context.project,active['model_id'],count=count,seed=int(state['seed'])+2+len(blocked),excluded_image_ids=blocked,active_model=active,progress_callback=lambda stage,done,total:events.put(('progress',stage,done,total)))
    next_state=begin_improvement(self.context.project,state,count,selected_ids=[item['image_id'] for item in data['selected_images']],selection_artifact=str(path.relative_to(self.context.project.data_root).as_posix()))
    events.put(('done',next_state,data))
   except Exception as exc:events.put(('error',exc))
  threading.Thread(target=worker,daemon=True,name='production-landmark-improvement').start()
  def poll():
   try:
    while True:
     kind,*value=events.get_nowait()
     if kind=='progress':label.config(text=f"Selecting representative uncertain images…\n{value[0]} {value[1]} / {value[2]}")
     elif kind=='error':dialog.destroy();messagebox.showerror('Improvement batch',str(value[0]),parent=self.shell);return
     else:
      dialog.destroy();next_state,data=value;next_state,image_id,position,_=workflow_current(self.context.project,next_state)
      if image_id is not None:self.context.selected=next(i for i,row in enumerate(self.context.rows) if row['image_id']==image_id)
      messagebox.showinfo('Improvement batch',f"New improvement batch: {len(data['selected_images'])} images.",parent=self.shell);self.shell.render();return
   except queue.Empty:self.shell.after(100,poll)
  poll()
 def preflight(self,parent_model_id=None):
  dialog=tk.Toplevel(self.shell);dialog.title('Prepare landmark training');dialog.transient(self.shell);frame=ttk.Frame(dialog,padding=14);frame.pack(fill='both',expand=True);label=ttk.Label(frame,text='Checking training data and AI runtime…',justify='left');label.pack(anchor='w');bar=ttk.Progressbar(frame,mode='indeterminate');bar.pack(fill='x',pady=(8,0));bar.start();events=queue.Queue();center(self.shell,dialog)
  def update(stage,detail):events.put(('progress',stage,detail))
  def worker():
   try:events.put(('ready',prepare_landmark_training(self.context.project,parent_model_id=parent_model_id,progress_callback=update)))
   except Exception as exc:events.put(('error',exc))
  threading.Thread(target=worker,daemon=True,name='production-landmark-training-preflight').start()
  def poll():
   try:
    while True:
     kind,*value=events.get_nowait()
     if kind=='progress':label.config(text=f'{value[0]}\n{value[1]}')
     elif kind=='error':dialog.destroy();messagebox.showwarning('Landmark training',str(value[0]),parent=self.shell);return
     else:dialog.destroy();self._confirm_training(value[0]);return
   except queue.Empty:self.shell.after(100,poll)
  poll()
 def _confirm_training(self,plan):
  settings=plan.training_settings;auto_seconds=float((settings.get('preparation_timings_seconds') or {}).get('auto_performance',0.0) or 0.0);source=settings.get('tuning_source','heuristic');source_label={'probe':'measured now','cache':'cached for this machine','heuristic':'safe default','fallback':'safe fallback — calibration failed'}.get(source,str(source));device=settings.get('device','cpu');amp='on' if settings.get('mixed_precision') else 'off';errors=settings.get('tuning_errors') or ();cache_saved=settings.get('cache_saved');issue=(f"\nCalibration issue: {errors[0][:180]}" if errors else "");cache_note=("\nCache: saved" if source=='probe' and cache_saved is True else "\nCache: SAVE FAILED — next run will recalibrate" if source=='probe' and cache_saved is False else "")
  counts=self.context.landmark_counts();new_or_changed=counts.get('New/changed',0)
  summary=f"Training set: {len(plan.image_ids)} verified images\nNew or changed since the active model: {new_or_changed}\nNew model: {plan.model_id}\n\nPerformance settings\nDevice: {device}\nBatch: {settings.get('batch_size')}\nWorkers: {settings.get('workers')}\nAMP: {amp}\nSelection: {source_label}\nCalibration time: {auto_seconds:.1f} s{cache_note}{issue}\n\nThe new model is trained on the full current training set. The 'new or changed' count only shows how much of that set is not yet represented by the active model. Human annotations are not changed."
  dialog=tk.Toplevel(self.shell);dialog.title('Start landmark training');dialog.transient(self.shell);frame=ttk.Frame(dialog,padding=14);frame.pack(fill='both',expand=True);ttk.Label(frame,text=summary,justify='left',wraplength=460).pack(anchor='w');actions=ttk.Frame(frame);actions.pack(anchor='e',pady=(12,0));self.button(actions,'Cancel',dialog.destroy,'Return without starting training.').pack(side='right');self.button(actions,'Start training',lambda:(dialog.destroy(),self._run_training(plan)),'Start the prepared landmark model training.').pack(side='right',padx=(0,6));center(self.shell,dialog)
 def _run_training(self,plan):
  dialog=tk.Toplevel(self.shell);dialog.title('Train landmark model');dialog.transient(self.shell);frame=ttk.Frame(dialog,padding=14);frame.pack(fill='both',expand=True);label=ttk.Label(frame,text='Creating the training dataset…',justify='left');label.pack(anchor='w');bar=ttk.Progressbar(frame,mode='indeterminate');bar.pack(fill='x',pady=(8,0));bar.start();events=queue.Queue();center(self.shell,dialog)
  def update(stage,*details):events.put(('progress',stage,' '.join(str(item) for item in details)))
  def worker():
   try:events.put(('done',run_landmark_training(self.context.project,plan,progress_callback=update)))
   except Exception as exc:events.put(('error',exc))
  threading.Thread(target=worker,daemon=True,name='production-landmark-model-training').start()
  def poll():
   try:
    while True:
     kind,*value=events.get_nowait()
     if kind=='progress':label.config(text=f'{value[0]}\n{value[1]}')
     elif kind=='error':dialog.destroy();messagebox.showerror('Landmark training',str(value[0]),parent=self.shell);return
     else:
      dialog.destroy();model=self.context.project.model_metadata(plan.model_id) or value[0];p90=validation_metrics(model).get('p90_error_percent')
      self.context.invalidate_counts()
      messagebox.showinfo('Landmark training',f"Created model: {plan.model_id}\nValidation P90 error: {_format_percent(p90)}",parent=self.shell);self.shell.render();return
   except queue.Empty:self.shell.after(100,poll)
  poll()
