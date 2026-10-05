"""Crop workspace backed by the production crop services."""
from tkinter import ttk, messagebox
import tkinter as tk
import threading, queue
from app.crop_training_batch import create_crop_prediction_batch, create_crop_training_batch, prepare_crop_training_images
from app.crop_training import train
from app.crop_auto import candidates, process as process_auto_crops
from app.landmark_attention_queue import active as active_attention_queue, classify as classify_attention_issue, move as move_attention_queue
from .section_base import SectionView
from .crop_canvas import CropCanvasController
from .dialogs import center
from .design import model_selector_width, FlowRow
from .workflow import add_command_separator


class CropSection(SectionView):
 def render(self):
  panel=self.frame(padding=(6,4));panel.pack(fill="both",expand=True);panel.rowconfigure(1,weight=1);panel.columnconfigure(0,weight=1)

  header=ttk.Frame(panel);header.grid(row=0,column=0,sticky="ew",pady=(0,4))
  actions=ttk.Frame(header,style="Toolbar.TFrame");actions.pack(fill="x")
  self.button(actions,"Apply crop",self.apply_current,"Save this reversible crop and stay on the current image.",style="Primary.TButton",icon="verify").pack(side="left")
  self.shell.build_queue_navigation(header)

  self.canvas_frame=ttk.Frame(panel);self.canvas_frame.grid(row=1,column=0,sticky="nsew")
  self.canvas=CropCanvasController(self.canvas_frame,self.context,self.refresh);self.canvas.on_image_ready=self._crop_ready

  batch=tk.IntVar(value=24);prediction=tk.IntVar(value=24)
  guide='Frame and orient each specimen before placing landmarks.\n\n1. Adjust a crop\nDrag the frame to move it or a corner to resize it. The yellow handle rotates it. Apply crop saves this image.\n\n2. Work through a batch\nCheck each crop and use Confirm & Next to save and move on.\n\n3. Train AI\nTeach a model using crops you have confirmed.\n\n4. Predict and review\nLet AI suggest crops for images that need them. Check and confirm each suggestion.'
  dock=self.workflow_dock(panel,help_title="Crop — quick guide",help_text=guide);dock.grid(row=2,column=0,sticky="ew",pady=(4,0))

  training_rows=self.context.project.crop_training_rows()
  one=dock.add_card("1. Training data",icon="crop_training",help_text="Start examples are the initial human-corrected Crop images used to establish the first Crop model; later batches add improvement examples.")
  ttk.Label(one,text="Manual corrected examples",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
  batch_actions=ttk.Frame(one);batch_actions.grid(row=1,column=0,sticky="w",pady=(4,0))
  ttk.Label(batch_actions,text="Batch size").pack(side="left")
  ttk.Spinbox(batch_actions,from_=1,to=500,textvariable=batch,width=5).pack(side="left",padx=(4,0))
  ttk.Label(batch_actions,text="20–30 recommended",style="Muted.TLabel").pack(side="left",padx=(5,0))
  add_command_separator(batch_actions)
  first=not bool(training_rows)
  self.button(batch_actions,"Start first batch" if first else "Add next batch",lambda:self.batch(batch.get()),"Create a persistent set of real images for manual crop correction.").pack(side="left")

  two=dock.add_card("2. Train model",icon="crop_train",help_text="Train a new Crop model from all human-confirmed Crop examples.")
  model_row=ttk.Frame(two);model_row.grid(row=0,column=0,sticky="ew");two.columnconfigure(0,weight=1)
  active_crop=self.context.project.active_model("crop") or {}
  active_crop_id=active_crop.get("model_id") or "None"
  self.crop_active_model_label=ttk.Label(model_row,text=f"Active: {active_crop_id}",style="StatusChip.TLabel");self.crop_active_model_label.pack(side="left")
  add_command_separator(model_row)
  ttk.Label(model_row,text="From").pack(side="left")
  crop_models=self.context.project.models("crop");crop_model_ids=tuple(item["model_id"] for item in crop_models)
  parent_values=crop_model_ids+("Bootstrap / first model",)
  parent_default=active_crop.get("model_id") if active_crop.get("model_id") in crop_model_ids else "Bootstrap / first model"
  source_choice=tk.StringVar(master=panel,value=parent_default)
  source_box=ttk.Combobox(model_row,textvariable=source_choice,values=parent_values,width=model_selector_width(parent_values),state="readonly");source_box.pack(side="left",padx=(4,0))
  self.shell.tip.bind(source_box,"Lineage parent recorded for this fully retrained Crop model. The training data are always all current human-verified Crop examples.")
  ttk.Label(model_row,text=f"Ready: {len(training_rows)}",style="Muted.TLabel").pack(side="right",padx=(10,0))
  train_actions=ttk.Frame(two);train_actions.grid(row=1,column=0,sticky="w",pady=(3,0))
  self.button(train_actions,"Train",lambda:self.train(None if source_choice.get()=="Bootstrap / first model" else source_choice.get()),"Train the Crop model from all verified examples.",style="Primary.TButton").pack(side="left")
  add_command_separator(train_actions)
  self.button(train_actions,"Models…",lambda:self.shell.show_models('crop'),"Compare and select saved Crop model versions.").pack(side="left")

  three=dock.add_card("3. Predict & review",icon="crop_apply",help_text="Predict only uncropped images. Pending AI Crop proposals are a separate review state and are not predicted again.")
  three.columnconfigure(0,weight=1)
  batch_row=ttk.Frame(three);batch_row.grid(row=0,column=0,sticky="ew")
  ttk.Label(batch_row,text="Next batch").pack(side="left")
  ttk.Spinbox(batch_row,from_=1,to=500,textvariable=prediction,width=5).pack(side="left",padx=(4,0))
  ttk.Label(batch_row,text="images",style="Muted.TLabel").pack(side="left",padx=(4,0))
  add_command_separator(batch_row)
  ttk.Label(batch_row,text="Model").pack(side="left")
  self.prediction_model_choice=tk.StringVar(master=three,value=active_crop.get("model_id") or "")
  self.prediction_model_box=ttk.Combobox(batch_row,textvariable=self.prediction_model_choice,values=crop_model_ids,width=model_selector_width(crop_model_ids),state="readonly" if crop_model_ids else "disabled")
  self.prediction_model_box.pack(side="left",fill="x",expand=True,padx=(4,0));self.prediction_model_box.bind("<<ComboboxSelected>>",self._activate_prediction_model)
  self.shell.tip.bind(self.prediction_model_box,"Active Crop model used by Predict next batch and Predict all. Choosing a model makes it active immediately.")
  apply_actions=FlowRow(three);apply_actions.grid(row=1,column=0,sticky="ew",pady=(3,0))
  self.button(apply_actions,"Predict next batch",lambda:self.auto_batch(prediction.get()),"Predict Crop for the next uncropped eligible images.",style="Primary.TButton").pack(side="left")
  self.button(apply_actions,"Predict all",lambda:self.auto_batch(None),"Predict Crop for every uncropped eligible image. Existing AI proposals are not rerun.").pack(side="left",padx=(4,0))
  add_command_separator(apply_actions)
  self.button(apply_actions,"Review AI",self.review_worst,"Review pending AI Crop proposals, worst first.").pack(side="left")
  self.button(apply_actions,"Review manual",self.review_manual,"Re-review crops that were created manually.").pack(side="left",padx=(4,0))
  add_command_separator(apply_actions)
  self.button(apply_actions,"Accept all AI",self.accept_all_ai_crops,"Accept every current pending AI Crop exactly as predicted, without recalculating it.").pack(side="left")
 def _activate_prediction_model(self,_event=None):
  model_id=str(self.prediction_model_choice.get() or "")
  if not model_id:return
  try:self.context.project.set_active_model("crop",model_id)
  except Exception as exc:
   messagebox.showerror("Crop model",str(exc),parent=self.shell);return
  self.crop_active_model_label.configure(text=f"Active: {model_id}")
  self.context.invalidate_counts();self.shell._update_status()

 def refresh(self,image_id=None):
  if image_id is not None:
   # Crop changes can also invalidate/reproject landmarks; refresh the whole
   # authoritative row so Crop and later Landmarks views never disagree.
   self.context.refresh_landmark_state(image_id);self.context.invalidate_counts()
  else:self.context.invalidate_counts()
  self.shell._update_status()
  panel=getattr(self.shell,'photo_panel',None)
  if panel:panel.refresh(preserve_scroll=True)
 def batch(self,count):
  getattr(self.shell,'resume_queue_navigation',lambda:None)()
  rows_by_id={row["image_id"]:dict(row) for row in self.context.rows}
  dialog=tk.Toplevel(self.shell);dialog.title("Prepare crop training batch");dialog.transient(self.shell)
  frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
  label=ttk.Label(frame,text="Selecting training images…",justify="left");label.pack(anchor="w")
  bar=ttk.Progressbar(frame,mode="indeterminate");bar.pack(fill="x",pady=(8,0));bar.start()
  events=queue.Queue();center(self.shell,dialog)
  def worker():
   try:
    data,_path=create_crop_training_batch(self.context.project,int(count))
    rows=[rows_by_id[item["image_id"]] for item in data["selected_images"] if item["image_id"] in rows_by_id]
    events.put(("stage","Preparing selected images…"))
    prepared=prepare_crop_training_images(self.context.project,rows,progress=lambda done,total,image_id,reason:events.put(("progress",done,total,image_id,reason)))
    events.put(("done",data,prepared))
   except Exception as exc:events.put(("error",exc))
  threading.Thread(target=worker,daemon=True,name="production-crop-batch-prepare").start()
  def poll():
   try:
    while True:
     kind,*value=events.get_nowait()
     if kind=="stage":
      label.configure(text=value[0])
     elif kind=="progress":
      bar.stop();bar.configure(mode="determinate",maximum=value[1],value=value[0])
      image_id=value[2];row=rows_by_id.get(image_id,{})
      filename=row.get("filename") or row.get("rel_path") or row.get("original_name") or image_id
      label.configure(text=f"Preparing {value[0]} of {value[1]}: {filename}")
     elif kind=="error":
      dialog.destroy();messagebox.showerror("Crop training batch",str(value[0]),parent=self.shell);return
     else:
      dialog.destroy();data,prepared=value
      ids=list(prepared["prepared_ids"]);self.context.project.set_ui_state("crop_active_batch",{"batch_id":data["batch_id"],"batch_type":"training","ids":ids,"prepared_ids":ids,"completed_ids":[],"position":0,"proposals":prepared.get("proposals",{})})
      if ids:self.context.selected=next(i for i,row in enumerate(self.context.rows) if row["image_id"]==ids[0])
      messagebox.showinfo("Crop training batch",f"Prepared {len(ids)} image(s). Correct them, then use Confirm & Next or Enter to move through this batch.",parent=self.shell);self.shell.render();return
   except queue.Empty:self.shell.after(100,poll)
  poll()
 def _pending_matches_current(self):
  pending=getattr(self,'_pending_crop_action',None);current=(self.context.current() or {}).get('image_id')
  return bool(pending and pending[0]==current and pending[1]==getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0)))
 def cancel_pending_for_target(self,image_id):
  pending=getattr(self,'_pending_crop_action',None)
  if pending and pending[0] != image_id:self._pending_crop_action=None
 def on_image_selected(self):
  current=(self.context.current() or {}).get('image_id')
  self.cancel_pending_for_target(current)
  self.canvas.on_image_ready=self._crop_ready
  request_epoch=getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0))
  self.canvas.load_current(request_epoch)
 def _defer_crop_action(self,advance):
  current=(self.context.current() or {}).get('image_id')
  if not current:return
  self._pending_crop_action=(current,getattr(self.shell,'selection_request_epoch',getattr(self.canvas,'requested_request_epoch',0)),advance)
  self.shell.status_context.configure(text='Preparing image…')
 def _crop_ready(self,image_id,generation,request_epoch=None):
  pending=getattr(self,'_pending_crop_action',None)
  if not pending or pending[:2] != (image_id,request_epoch):return
  self._pending_crop_action=None
  outcome=self.canvas.apply()
  if outcome=='DEFERRED':
   # A new request started between callback scheduling and apply; bind once to it.
   self._defer_crop_action(pending[2]);return
  if outcome=='SAVED' and pending[2]=='attention':self.navigate_attention_queue(1,_already_saved=True)
  elif outcome=='SAVED' and pending[2]:self._move_batch(1,_already_saved=True)
 def apply_current(self):
  outcome=self.canvas.apply()
  if outcome=='DEFERRED':self._defer_crop_action(False)
  if outcome=='SAVED' and getattr(self.canvas,'last_save_message','') and hasattr(self.shell,'status_context'):self.shell.status_context.configure(text=self.canvas.last_save_message)
  return outcome
 def _move_batch(self,step,_already_saved=False):
  state=self.context.project.get_ui_state("crop_active_batch",{});ids=list(state.get("ids",[]));current=(self.context.current() or {}).get("image_id")
  if current not in ids:return
  if int(step)>0 and not _already_saved:
   outcome=self.apply_current()
   if outcome!='SAVED':
    if outcome=='DEFERRED':self._defer_crop_action(True)
    return
  position=ids.index(current)+int(step)
  if position<0: position=0
  if position>=len(ids):
   batch_type=state.get("batch_type")
   announce=not state.get("completion_announced",False)
   # Keep the completed batch's identity but remove it from active navigation.
   state={"batch_id":state.get("batch_id"),"batch_type":batch_type,"ids":[],"finished":True,"completion_announced":True}
   self.context.project.set_ui_state("crop_active_batch",state);self.shell._update_status()
   if announce:
    if batch_type in {"prediction_review","manual_review"}: messagebox.showinfo("Crop review batch","Batch review complete.",parent=self.shell)
    else: messagebox.showinfo("Crop training batch",f"Batch complete\n{len(ids)} images prepared and corrected; ready for training.",parent=self.shell)
   return
  state["position"]=position;self.context.project.set_ui_state("crop_active_batch",state);self.context.selected=next(i for i,row in enumerate(self.context.rows) if row["image_id"]==ids[position]);self.shell._sync_photo_panel_current(align_top=True,refresh_rows=False);self.shell._selected_image()
 def navigate_attention_queue(self,step,_already_saved=False):
  current=(self.context.current() or {}).get('image_id')
  if not active_attention_queue(self.context.project) or not current:return False
  if int(step)<0:
   self._pending_crop_action=None;issue=move_attention_queue(self.context.project,-1);self.shell.open_landmark_attention(issue);return True
  issue=classify_attention_issue(self.context.project,current)
  if issue.get('stage')!='crop':
   self.shell.open_landmark_attention(issue);return True
  if not _already_saved:
   outcome=self.apply_current()
   if outcome=='DEFERRED':
    self._defer_crop_action('attention');return True
   if outcome!='SAVED':return True
  self.context.refresh_landmark_state(current)
  if getattr(self.context,'_counts_cache',None) is not None:self.context.update_image_counts(current)
  if getattr(self.context,'_landmark_counts_cache',None) is not None:self.context.update_landmark_counts(current)
  self.shell.open_landmark_attention();return True

 def navigate_batch(self,step):
  self._move_batch(step);return True
 def next_batch(self): self.navigate_batch(1)
 def previous(self):
  self._pending_crop_action=None;self.navigate_batch(-1)
 def on_enter(self): self.next_batch()
 def _start_review_batch(self,ids,batch_type,title):
  ids=[image_id for image_id in ids if any(row.get('image_id')==image_id and not row.get('excluded') for row in self.context.rows)]
  if not ids:messagebox.showinfo(title,"No matching crops are available for review.",parent=self.shell);return False
  self.context.project.set_ui_state("crop_active_batch",{"batch_id":f"{batch_type}-{int(__import__('time').time())}","batch_type":batch_type,"ids":ids,"prepared_ids":ids,"completed_ids":[],"position":0,"completion_announced":False})
  self.context.selected=next(i for i,row in enumerate(self.context.rows) if row['image_id']==ids[0]);self.shell.render();return True
 def review_worst(self):
  ids=self.context.project.crop_review_candidates()
  if not ids:messagebox.showinfo("Review AI crops","No AI crop proposals require review.",parent=self.shell);return
  self._start_review_batch(ids,"prediction_review","Review AI crops")
 def review_manual(self):
  ids=self.context.project.crop_manual_review_candidates()
  if not ids:messagebox.showinfo("Review manual","No human-made crops are available for review.",parent=self.shell);return
  self._start_review_batch(ids,"manual_review","Review manual")
 def accept_all_ai_crops(self):
  summary=self.context.project.pending_ai_crop_summary();total=int(summary.get("total",0))
  if not total:
   messagebox.showinfo("Accept all AI crops","No pending AI crops are available.",parent=self.shell);return False
  counts=summary.get("by_qc") or {}
  detail=", ".join(f"{key}: {counts[key]}" for key in ("BAD","REVIEW","OK","UNKNOWN") if counts.get(key))
  text=f"Accept all {total} pending AI crops exactly as they are?\n\nThis does not rerun the model or move any Crop. It marks the current AI proposals as human-confirmed."
  if detail:text+=f"\n\nQC: {detail}"
  if not messagebox.askyesno("Accept all AI crops",text,parent=self.shell,default=messagebox.NO):return False
  result=self.context.project.accept_all_ai_crops()
  self.context.invalidate_catalog();self.context.refresh(force=True)
  messagebox.showinfo("Accept all AI crops",f"Accepted: {result['accepted']}\nSkipped invalid: {result['skipped']}",parent=self.shell)
  self.shell.render()
  return True
 def auto_batch(self,count,rerun=False,explicit_ids=None,title="Predict Crop"):
  dialog=tk.Toplevel(self.shell);dialog.title(title);dialog.transient(self.shell)
  frame=ttk.Frame(dialog,padding=14);frame.pack()
  label=ttk.Label(frame,text="Selecting images for crop prediction…");label.pack(anchor="w")
  bar=ttk.Progressbar(frame,mode="indeterminate");bar.pack(fill="x",pady=(8,0));bar.start()
  events=queue.Queue();cancel=threading.Event();center(self.shell,dialog)
  self.button(frame,"Cancel",cancel.set,"Stop after the current crop operation.").pack(anchor="e",pady=(8,0))
  def worker():
   try:
    prediction_batch=None
    if explicit_ids is not None:
     ids=list(explicit_ids)
    elif count is None:
     ids,_protected=candidates(self.context.project,rerun=rerun)
     ids=list(ids)
    else:
     prediction_batch,_path=create_crop_prediction_batch(self.context.project,int(count))
     ids=[item["image_id"] for item in prediction_batch["selected_images"]]
    if not ids:
     events.put(("empty",));return
    events.put(("stage",f"Preparing crop predictions for {len(ids)} image(s)…"))
    result=process_auto_crops(self.context.project,rerun=rerun,image_ids=ids,cancel=cancel,progress=lambda done,total,image_id,result:events.put(("progress",done,total,image_id)))
    events.put(("done",result,prediction_batch))
   except Exception as exc:events.put(("error",exc))
  threading.Thread(target=worker,daemon=True,name="production-crop-auto").start()
  def poll():
   try:
    while True:
     kind,*value=events.get_nowait()
     if kind=="stage":
      label.config(text=value[0])
     elif kind=="progress":
      bar.stop();bar.configure(mode="determinate",maximum=value[1],value=value[0]);label.config(text=f"Predicting Crop: {value[0]} / {value[1]}")
     elif kind=="empty":
      dialog.destroy();counts=self.context.project.crop_section_counts();uncropped=int(counts.get('Uncropped',0));pending=int(counts.get('AI pending',0))
      message=f"No eligible uncropped images can be predicted. Uncropped: {uncropped}. AI review: {pending}."
      if uncropped:message+="\n\nSome uncropped images may be protected because downstream landmark data already exist."
      elif pending:message+="\n\nPending AI crops already have predictions; use Review AI crops."
      messagebox.showinfo(title,message,parent=self.shell);return
     elif kind=="done":
      dialog.destroy();result,prediction_batch=value;summary=f"Predicted: {result['success']}."
      failures=result.get("failures") or []
      if result.get("protected"):summary+=f" Protected: {result['protected']}."
      if failures:
       first=failures[0];reason=first.get("reason",str(first)) if isinstance(first,dict) else str(first)
       summary+=f"\nNeeds attention: {len(failures)}.\nFirst issue: {reason}\nThese images were not silently accepted; details are recorded in app.log."
      if result["success"] and messagebox.askyesno(title,summary+"\n\nReview this batch now?",parent=self.shell,default=messagebox.YES):
       ids=list(result.get("successful_ids",()))
       self.context.project.set_ui_state("crop_active_batch",{"batch_id":(prediction_batch or {}).get("batch_id","crop_prediction_review"),"batch_type":"prediction_review","ids":ids,"prepared_ids":ids,"completed_ids":[],"position":0,"model_id":result.get("model_id"),"completion_announced":False})
       if ids:self.context.selected=next(i for i,row in enumerate(self.context.rows) if row["image_id"]==ids[0])
       self.shell.render();return
      messagebox.showinfo(title,summary,parent=self.shell);self.shell.render();return
     else:
      dialog.destroy();messagebox.showerror(title,str(value[0]),parent=self.shell);return
   except queue.Empty:self.shell.after(100,poll)
  poll()
 def train(self,parent_model_id=None):
  dialog=tk.Toplevel(self.shell);dialog.title("Train crop model");dialog.transient(self.shell);frame=ttk.Frame(dialog,padding=14);frame.pack();ttk.Label(frame,text="Training crop model…").pack(anchor="w");bar=ttk.Progressbar(frame,mode="indeterminate");bar.pack(fill="x",pady=(8,0));bar.start();events=queue.Queue();center(self.shell,dialog)
  def worker():
   try:events.put(("done",train(project=self.context.project,parent_model_id=parent_model_id)))
   except Exception as exc:events.put(("error",exc))
  threading.Thread(target=worker,daemon=True,name="production-crop-training").start()
  def poll():
   try:kind,value=events.get_nowait()
   except queue.Empty:self.shell.after(100,poll);return
   dialog.destroy()
   if kind=="error":messagebox.showerror("Crop training",str(value),parent=self.shell);return
   metric=value.get("metrics",{}).get("validation_iou");text=f"Created candidate model: {value.get('model_id')}\nValidation IoU: {metric:.3f}" if value.get("trained") and metric is not None else str(value.get("reason","No model was created."));messagebox.showinfo("Crop training",text,parent=self.shell);self.shell.render()
  poll()
