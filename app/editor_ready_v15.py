"""Project editor: one SQLite-backed landmark state feeds every annotation view."""
from pathlib import Path
import json
import queue
import re
import threading
from threading import Timer
import time
import traceback
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog
from .editor_ready_v14 import ReadyEditorV14
from .prefetch import PrefetchManager
from .gui_crop_debug import log, dump_threads
from .photo_list import PhotoListCanvas
from .project_runtime import landmark_state as load_landmark_state, open_project
from .project_storage import schema_file_signature, load_schema, schema_hash
from .workflow import load_record, save_record, set_human_point
from .landmark_ids import record_key, number_from_id
from .crop_training import correction_count, current_label
from .crop_training_batch import CropBatchDiagnostics, create_crop_training_batch, prepare_crop_training_images
from .crop_auto import candidates as crop_auto_candidates, process as process_auto_crops
from .crop_evaluation import evaluate as evaluate_crop_model, previous as previous_crop_evaluation, comparison as compare_crop_evaluation
from .ai_training_status import format_training_status, training_status
from .landmark_training_workflow import activate_landmark_model, prepare_landmark_training, run_landmark_training, validation_metrics
from .landmark_dataset import v2_human_final_eligible_image_ids, model_seen_image_ids
def photo_search_cache(rows):
 """Precompute catalog-only strings used by compact photo filters."""
 return tuple((str(row.get("locality") or row.get("sample_id") or "").casefold(),(str(row.get("image_id") or "")+" "+Path(str(row.get("source_relpath") or "")).name).casefold()) for row in rows)

def filtered_photo_indices(rows, cache, image_query="", locality_query="", *, show_excluded=True):
 image_query=str(image_query or "").strip().casefold();locality_query=str(locality_query or "").strip().casefold()
 return [index for index,(row,(locality,name)) in enumerate(zip(rows,cache)) if (show_excluded or not row.get("excluded")) and (not image_query or image_query in name) and (not locality_query or locality_query in locality)]

def format_internal_validation(metrics):
 def percent(key):
  value=metrics.get(key)
  return "Unavailable" if value is None else f"{value:.2f}%"
 epoch=metrics.get("best_epoch")
 best_checkpoint="Unavailable" if epoch is None else f"epoch {epoch}"
 ema=metrics.get("ema_used")
 ema_text="Unavailable" if ema is None else ("Yes" if ema else "No")
 return f"Internal validation:\nMedian: {percent('median_error_percent')} of reference span\nP90: {percent('p90_error_percent')}\nP95: {percent('p95_error_percent')}\nBest checkpoint: {best_checkpoint}\nEMA: {ema_text}"

def _quality_rows(profile):
 return sorted((value for value in (profile or {}).get("per_landmark",{}).values() if value.get("p90_error_percent") is not None and value.get("median_error_percent") is not None),key=lambda value:(-value["p90_error_percent"],-value["median_error_percent"],value["landmark_id"]))
def format_landmark_quality_summary(profile, persistent_ids=()):
 if not profile:return "Landmark quality profile is not available yet."
 rows=_quality_rows(profile)[:5];lines=["Landmark quality:","Weakest landmarks:"]
 lines.extend(f"LM{int(row['landmark_id']):02d}  P90: {row['p90_error_percent']:.2f}%  Median: {row['median_error_percent']:.2f}%" for row in rows)
 persistent=tuple(sorted(map(int,persistent_ids)))
 if not persistent:lines.extend(("","No persistent weak landmarks detected."))
 else:lines.extend(("",f"Persistent weak landmarks: {', '.join(f'LM{ident:02d}' for ident in persistent)}","Next Smart Improvement Batch will focus ~30% on these landmarks."))
 return "\n".join(lines)
def format_landmark_quality_table(profile, schema, persistent_ids=(), human_report=None, model_id=None):
 if not profile:return "Landmark quality profile is not available yet."
 labels={int(row.get("id",row.get("landmark_id"))):(row.get("abbr") or row.get("name") or "") for row in schema};persistent={int(value) for value in persistent_ids};current={int(value) for value in profile.get("weak_landmark_ids",())}
 human_rows={};comparable=bool(human_report and str(human_report.get("model_id"))==str(model_id))
 if comparable:human_rows={int(row["landmark_id"]):row for row in human_report.get("per_landmark",())}
 lines=["LM | Abbr | P90 | Median | Status"]
 if human_report:lines[0]="LM | Abbr | P90 | Median | Training status | Human P90 | AI/Human | Human status"
 for row in _quality_rows(profile):
  ident=int(row["landmark_id"]);training_status="Persistent weak" if ident in persistent else "Currently weak" if ident in current else "Normal";line=f"LM{ident:02d} | {labels.get(ident,'')} | {row['p90_error_percent']:.2f}% | {row['median_error_percent']:.2f}% | {training_status}"
  if human_report:
   human=human_rows.get(ident,{});human_p90=human.get("human_p90_error_percent");ratio=human.get("ratio");human_status=human.get("status","Unavailable") if comparable else "Unavailable (different model)"
   line+=f" | {'Unavailable' if human_p90 is None else f'{human_p90:.2f}%'} | {'Unavailable' if ratio is None else f'{ratio:.2f}x'} | {human_status}"
  lines.append(line)
 return "\n".join(lines)
from .ai_package import AIPackageError, export_ai_package, export_model_package, import_ai_package, import_model_package
from .normalization_pipeline import paths
from .landmark_review import review_warnings, scan_project
from .ai_batch import BatchError, active_backend, create_batch, create_batch_for_ids, load_batch, preflight_backend, prospective_candidates, reviewed_count, run_batch
from .landmark_ai_service import LandmarkAIService
from .ai_hardware import format_hardware_profile
try:
 from .active_learning import select_ai_worst_first
except ImportError:
 select_ai_worst_first=None
from .landmark_ai_workflow import add_control_image, begin_improvement, control_set_summary, create_stage, repair_excluded_stage_members, stage_summary, start_or_continue, workflow_current
from .smart_selection import create_improvement_selection
from .landmark_frames import landmark_frame_ready
from .landmark_qc import evaluate_control_set, compare_control_models, control_landmark_quality_profile, persist_control_landmark_quality_profile, stored_control_landmark_quality_profile, stable_weak_landmark_profile
from .landmark_resolution_experiment import prepare_experiment, run_experiment
from .annotation_check import check_annotation
from .operator_qc import create_repeat_session, select_repeat_candidates
from .human_baseline import start_or_continue_run, complete_run, previous_runs, latest_completed_report, comparison_for_model, landmark_model_rows, refresh_first_marking_reference, recompute_completed_run
from .human_baseline_ui import HumanBaselineWindow
from .quality_report_ui import PALETTE, report_dialog, status_label, level_for_status
from .calibration_workflow import CalibrationWorkflow
from .measurements import active_measurements, export_measurements, measurement_summary
from .measurements_ui import MeasurementsWindow


_TRAINING_PROGRESS_LINE = re.compile(r"Epoch(?:\([^)]*\))?\s*\[(\d+)\]\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]", re.IGNORECASE)


def center_child_window(window):
 try:
  if not isinstance(window, tk.Toplevel) or bool(window.overrideredirect()): return window
  window.update_idletasks(); width,height=window.winfo_width(),window.winfo_height()
  x=max(0,(window.winfo_screenwidth()-width)//2); y=max(0,(window.winfo_screenheight()-height)//2); window.geometry(f"+{x}+{y}")
 except (tk.TclError,TypeError,ValueError): pass
 return window

def set_progress_dialog_progress(dialog, done, total):
 bar=getattr(dialog,"_simm_progressbar",None)
 if bar is None or total is None or total <= 0: return
 try: bar.stop(); bar.configure(mode="determinate",maximum=int(total),value=min(int(done),int(total)))
 except tk.TclError: pass
def parse_training_progress_line(line):
 """Extract epoch and batch counters from an MMEngine training line."""
 match = _TRAINING_PROGRESS_LINE.search(str(line))
 if not match:
  return None
 return {"epoch": int(match.group(1)), "batch": int(match.group(2)), "batches": int(match.group(3))}

def review_item_landmark_ids(item):
 """Return canonical landmark IDs referenced by one review queue item."""
 values=item.get("landmark_ids") or ()
 if not values:
  values=(item.get("landmark_id"),item.get("other_landmark_id"),item.get("first_landmark_id"),item.get("second_landmark_id"))
 return tuple(sorted({int(value) for value in values if value is not None}))


def review_warning_image_ids(queue, completed_indices=()):
 """Image IDs with still-unreviewed UI queue entries (temporary UI state only)."""
 completed=set(completed_indices)
 return {item.get("image_id") for index,item in enumerate(queue) if index not in completed and item.get("image_id")}


def review_warning_label_layout(x, y, canvas_width, canvas_height):
 """Default warning helper label is top-left; use the nearest readable corner at edges."""
 offset=9
 if x>=30 and y>=24:return x-offset,y-offset,"se"
 if y>=24 and x+30<=canvas_width:return x+offset,y-offset,"sw"
 if x>=30 and y+24<=canvas_height:return x-offset,y+offset,"ne"
 return x+offset,y+offset,"nw"

class ReadyEditorV15(ReadyEditorV14):
 def __init__(self, project=None):
  if project is not None: open_project(project)
  self.prefetch=PrefetchManager();self.landmark_state=None;self.calibration_mode="NORMAL";self._calibration_drag_index=None;self._orphan_landmark_logged=set();self._results_after_id=None;self._results_worker=False;self._results_pending=False;self._canvas_image_id=None;self._canvas_zoom=None;self._zoom_after_id=None;self._last_landmark_state=None;self._photo_click_started={};self._schema_cache_signature=None;self._schema_error_signature=None;self._review_scan_worker=False;self._review_cancel=False;self._review_queue=[];self._review_queue_index=0;self._review_completed_indices=set();self._review_active_ids=set();self._review_pending_image_id=None;self.review_mode=False;self._review_swap_first=None;self._review_undo=None;self._review_warnings=[];self._review_warning_index=0;self._ai_batch=None;self._ai_batch_path=None;self._ai_batch_index=0;self._ai_batch_worker=False;self._crop_batch_preparing=False;self._crop_batch_diagnostics=None;self._crop_batch_completed=False;self._crop_training_editor=None;self._crop_training_summary=None;self._workflow_target_image_id=None;self._workflow_prediction_inflight_ids=set();self._workflow_prediction_generation=0;self._ai_worst_review_active=False;self._ai_worst_review_items=[];self._ai_worst_review_index=0;self._canvas_landmark_input_ready=False
  super().__init__(project=project)
  self._install_canvas_event_diagnostics()
  self._log_canvas_event_path("normal_editor_startup")
  if "tk" in self.__dict__: self._build_ai_menu()
  if project is not None:
   self._log_project_startup()
   try:self.after_idle(self._log_project_startup)
   except Exception:pass

 def _build_ai_menu(self):
  menu=tk.Menu(self);ai=tk.Menu(menu,tearoff=False);ai.add_command(label="Hardware",command=self.show_ai_hardware);ai.add_command(label="AI Model Transfer...",command=self.show_model_transfer);menu.add_cascade(label="AI",menu=ai);self.config(menu=menu)

 def _canvas_event_detail(self, event):
  """Stable, side-effect-free context for raw Canvas event diagnostics."""
  current=self.current() if getattr(self,"images",None) else {}
  return (f"x={event.x} y={event.y} widget={event.widget} "
          f"workflow_state={bool(getattr(self,'_landmark_workflow_active',False))} "
          f"editable={not bool(getattr(self,'source_mode',False))} "
          f"image_id={current.get('image_id')}")

 def _canvas_raw_button1(self, event):
  self._canvas_raw_event_counts["button1"]=self._canvas_raw_event_counts.get("button1",0)+1
  log(self.current().get("image_id","GLOBAL"),"canvas_raw_button1","END",detail=self._canvas_event_detail(event))

 def _canvas_raw_b1_motion(self, event):
  self._canvas_raw_event_counts["b1_motion"]=self._canvas_raw_event_counts.get("b1_motion",0)+1
  now=time.monotonic()
  if now-getattr(self,"_last_canvas_raw_motion_log",0)>=.15:
   self._last_canvas_raw_motion_log=now
   log(self.current().get("image_id","GLOBAL"),"canvas_raw_b1_motion","END",detail=self._canvas_event_detail(event))

 def _canvas_raw_button1_release(self, event):
  self._canvas_raw_event_counts["button1_release"]=self._canvas_raw_event_counts.get("button1_release",0)+1
  log(self.current().get("image_id","GLOBAL"),"canvas_raw_button1_release","END",detail=self._canvas_event_detail(event))

 def _install_canvas_event_diagnostics(self):
  """Put a permanent observer before, never instead of, base Canvas handlers."""
  canvas=self.__dict__.get("canvas")
  if canvas is None:return
  if getattr(self,"_canvas_event_diagnostics_installed",False):return
  self._canvas_event_diagnostics_installed=True
  self._canvas_raw_event_counts={}
  self._last_canvas_raw_motion_log=0.
  self._canvas_event_diagnostic_tag=f"SIMMCanvasRawEvents_{id(self)}"
  tags=tuple(canvas.bindtags())
  canvas.bindtags((self._canvas_event_diagnostic_tag,)+tags)
  self.bind_class(self._canvas_event_diagnostic_tag,"<Button-1>",self._canvas_raw_button1)
  self.bind_class(self._canvas_event_diagnostic_tag,"<B1-Motion>",self._canvas_raw_b1_motion)
  self.bind_class(self._canvas_event_diagnostic_tag,"<ButtonRelease-1>",self._canvas_raw_button1_release)

 def _log_canvas_event_path(self, phase):
  """Log actual Tk bindings; this is deliberately called before/after Control Set prediction."""
  canvas=self.__dict__.get("canvas")
  if canvas is None:return
  current=self.current() if getattr(self,"images",None) else {}
  bindings={sequence:canvas.bind(sequence) for sequence in ("<Button-1>","<B1-Motion>","<ButtonRelease-1>","<Button-3>","<MouseWheel>")}
  detail=(f"phase={phase} canvas_widget_path={canvas} bindtags={canvas.bindtags()} "
          f"button1={bindings['<Button-1>']!r} b1_motion={bindings['<B1-Motion>']!r} "
          f"button1_release={bindings['<ButtonRelease-1>']!r} button3={bindings['<Button-3>']!r} "
          f"mousewheel={bindings['<MouseWheel>']!r} workflow_state={bool(getattr(self,'_landmark_workflow_active',False))} "
          f"editable={not bool(getattr(self,'source_mode',False))} current_image_id={current.get('image_id')}")
  log(current.get("image_id","GLOBAL"),"canvas_event_path","END",detail=detail)
 def show_model_transfer(self):
  dialog=tk.Toplevel(self);dialog.title("AI Model Transfer");dialog.transient(self);dialog.resizable(False,False)
  frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True)
  for row,(kind,label) in enumerate((("crop","Crop model"),("landmark","Landmark model"))):
   current=(self.project.active_model(kind) or {}).get("model_id") or "None"
   ttk.Label(frame,text=f"{label}: {current}").grid(row=row,column=0,columnspan=2,sticky="w",pady=(0,4))
   ttk.Button(frame,text=f"Export {label}",command=lambda k=kind:self._export_single_model(k)).grid(row=row,column=2,padx=(12,3),pady=(0,4))
   ttk.Button(frame,text=f"Import {label}",command=lambda k=kind:self._import_single_model(k)).grid(row=row,column=3,pady=(0,4))
  ttk.Button(frame,text="Close",command=dialog.destroy).grid(row=2,column=3,sticky="e",pady=(10,0))
 def _export_single_model(self,kind):
  model=self.project.active_model(kind)
  if not model:messagebox.showinfo("AI Model Transfer",f"No active {kind} model to export.",parent=self);return
  target=filedialog.asksaveasfilename(parent=self,title=f"Export {kind.title()} Model",initialfile=f"MorphoLabel_{kind}_model_{model['model_id']}.zip",defaultextension=".zip",filetypes=[("MorphoLabel model package","*.zip")])
  if not target:return
  try:export_model_package(self.project,kind,target)
  except Exception as exc:messagebox.showerror("AI Model Transfer",str(exc),parent=self);return
  messagebox.showinfo("AI Model Transfer",f"{kind.title()} model package created:\n{target}",parent=self)
 def _import_single_model(self,kind):
  source=filedialog.askopenfilename(parent=self,title=f"Import {kind.title()} Model",filetypes=[("MorphoLabel model package","*.zip")])
  if not source:return
  try:model_id=import_model_package(self.project,source,kind)
  except Exception as exc:messagebox.showwarning("AI Model Transfer",str(exc),parent=self);return
  if messagebox.askyesno("AI Model Transfer",f"Imported {kind} model: {model_id}\n\nUse it as the active {kind} model?",parent=self):
   try:self.project.set_active_model(kind,model_id)
   except Exception as exc:messagebox.showwarning("AI Model Transfer",f"Imported but not activated: {exc}",parent=self);return
   messagebox.showinfo("AI Model Transfer",f"Active {kind} model: {model_id}",parent=self)
 def export_ai_package(self):
  target=filedialog.asksaveasfilename(parent=self,title="Export AI Package",defaultextension=".zip",filetypes=[("MorphoLabel AI package","*.zip")])
  if not target:return
  try:export_ai_package(self.project,target)
  except Exception as exc:messagebox.showerror("Export AI Package",str(exc),parent=self);return
  messagebox.showinfo("Export AI Package",f"AI package created:\n{target}",parent=self)
 def import_ai_package(self):
  source=filedialog.askopenfilename(parent=self,title="Import AI Package",filetypes=[("MorphoLabel AI package","*.zip")])
  if not source:return
  try:models=import_ai_package(self.project,source)
  except Exception as exc:messagebox.showwarning("Import AI Package",str(exc),parent=self);return
  messagebox.showinfo("Import AI Package","Imported models: "+(", ".join(models) or "none"),parent=self)

 def _log_project_startup(self):
  if not getattr(self,"project",None):return
  canvas=self.__dict__.get("canvas");table=self.__dict__.get("landmark_table")
  image_items=sum(1 for item in canvas.find_all() if canvas.type(item)=="image") if canvas is not None else 0
  rows=len(self.__dict__.get("images",()))
  columns=",".join(table["columns"]) if table is not None else "none"
  current_id=self.current().get("image_id") if rows else None
  log("GLOBAL","project_gui_diagnostic","END",path=str(self.project.root),detail=f"gui_mode=project landmark_widget=Treeview project_root={self.project.root} project_db={self.project.path} schema_path={self.project.schema_path} source_root={self.project.source_root} photo_catalog_count={rows} landmark_columns={columns} canvas_image_item_count={image_items} current_image_id={current_id} initial_image_loaded={bool(self.__dict__.get('standard'))}")

 def _layout(self):
  super()._layout()
  self.images_box.destroy();self.photo_scrollbar.destroy()
  self.images_box=PhotoListCanvas(self.photo_list_frame,bg="white");self.images_box.pack(side="left",fill="both",expand=True)
  self.photo_scrollbar=ttk.Scrollbar(self.photo_list_frame,orient="vertical",command=self.images_box.yview);self.photo_scrollbar.pack(side="right",fill="y");self.images_box.configure(yscrollcommand=self.photo_scrollbar.set)
  self._show_excluded_var=tk.BooleanVar(master=self,value=True);self._visible_image_indices=[];self._photo_search_cache=photo_search_cache(self.images);self._filter_after_id=None;self._locality_filter_var=tk.StringVar(master=self);self._image_filter_var=tk.StringVar(master=self)
  self._build_photo_filters()
  self.images_box.bind("<<ListboxSelect>>",self.pick_image);self._build_photo_legend();self._refresh_visible_photo_rows();self.images_box.selection_set(0)
  # Lightweight landmark table: the photo list remains unchanged.
  old_landmarks=self.landmarks
  landmark_parent=old_landmarks.master
  old_landmarks.destroy()
  table_frame=ttk.Frame(landmark_parent);table_frame.pack(fill="both",expand=True,padx=0,pady=(0,3))
  self.landmark_table=ttk.Treeview(table_frame,columns=("status","id","role","abbr","name"),show="headings",selectmode="browse")
  for column,heading,width,stretch in (("status","",28,False),("id","#",34,False),("role","Use",42,False),("abbr","Abbr",58,False),("name","Landmark",180,True)):
   self.landmark_table.heading(column,text=heading);self.landmark_table.column(column,width=width,minwidth=width,stretch=stretch,anchor="w")
  table_scroll=ttk.Scrollbar(table_frame,orient="vertical",command=self.landmark_table.yview);self.landmark_table.configure(yscrollcommand=table_scroll.set)
  self.landmark_table.pack(side="left",fill="both",expand=True);table_scroll.pack(side="right",fill="y")
  self.landmark_table.tag_configure("present",foreground="#188038");self.landmark_table.tag_configure("missing",foreground="#c88700");self.landmark_table.tag_configure("unresolved",foreground="#d93025");self.landmark_table.tag_configure("review_warning",background="#fde8e8")
  self.landmark_table.bind("<<TreeviewSelect>>",self.pick_landmark)
  self.landmarks=self.landmark_table
  self.status_bar=ttk.Frame(self.header.master);self.status_bar.pack(fill="x",before=self.canvas)
  self.annotation_status=ttk.Label(self.status_bar,text="Landmarks: —");self.annotation_status.pack(side="left")
  self.status_dot=tk.Canvas(self.status_bar,width=14,height=14,highlightthickness=0);self.status_dot.pack(side="left",padx=5)
  self.checked_button=ttk.Button(self.status_bar,text="✓ Checked",command=self.mark_checked);self.checked_button.pack(side="left",padx=8)
  self.review_status=ttk.Label(self.status_bar,text="");self.review_status.pack(side="left",padx=6);self.ai_batch_status=ttk.Label(self.status_bar,text="");self.ai_batch_status.pack(side="right",padx=6)
  self.attribute_frame=ttk.Frame(self.landmarks.master,padding=3);self.attribute_frame.pack(fill="x");self.attribute_vars={}
  for spec in self.project.attributes_schema() if self.project else []:
   ttk.Label(self.attribute_frame,text=spec["label"]+":").pack(anchor="w");var=tk.StringVar();box=ttk.Combobox(self.attribute_frame,textvariable=var,values=spec["values"],state="readonly",width=18);box.pack(fill="x");box.bind("<<ComboboxSelected>>",lambda _e,key=spec["key"],v=var:self.project.set_attribute(self.current()["image_id"],key,v.get()));self.attribute_vars[spec["key"]]=var
  self.bind("v",lambda _e:self.mark_checked())
  self._build_compact_controls();self._restore_splitter();self.left_split.bind("<ButtonRelease-1>",self._save_splitter,add="+");self.protocol("WM_DELETE_WINDOW",self._close_project)


 def _draw_calibration_overlays(self):
  canvas=self.__dict__.get("canvas")
  if canvas is None:return
  canvas.delete("calibration_overlay")
  points=getattr(self,"calibration",None)
  if not points:return
  coords=[]
  for i,(x,y) in enumerate(points[:2],1):
   sx=self.pan[0]+x*self.zoom;sy=self.pan[1]+y*self.zoom;coords.append((sx,sy))
   canvas.create_oval(sx-6,sy-6,sx+6,sy+6,outline="#ff4d4d",width=2,tags=("calibration_overlay",f"calibration_point_{i}"))
   canvas.create_text(sx+10,sy-10,text=str(i),fill="#ff4d4d",font=("Segoe UI",10,"bold"),tags=("calibration_overlay",f"calibration_label_{i}"))
  if len(coords)==2:canvas.create_line(*coords[0],*coords[1],fill="#ff4d4d",width=2,tags=("calibration_overlay","calibration_line"))

 def _clear_calibration_overlay(self,reason):
  self.canvas.delete("calibration_overlay");self.calibration=None;self._calibration_drag_index=None;self.calibration_mode="NORMAL"
  remaining=len(self.canvas.find_withtag("calibration_overlay"));log(self.current().get("image_id") if getattr(self,"images",None) else "GLOBAL","calibration_overlay_cleared","END",detail=f"reason={reason} remaining_items={remaining}");log(self.current().get("image_id") if getattr(self,"images",None) else "GLOBAL","calibration_mode_exit","END",detail="state=NORMAL overlay_count=0")

 def start_calibration(self):
  if self.source_mode:
   messagebox.showinfo("Calibration","Return to standardized master first.",parent=self)
   return
  # Route through the permanent Canvas bindings; calibration never binds/unbinds events.
  self.canvas.delete("calibration_overlay")
  self.dragging=None
  self.calibration=[]
  self.calibration_mode="WAIT_POINT_1"
  image_id=self.current().get("image_id","GLOBAL")
  log(image_id,"calibration_mode_enter","END",detail="state=WAIT_POINT_1 overlay_count=0")
  self.header.config(text="Calibration: select point 1")

 def _calibration_button_down(self,event):
  if self.source_mode:return
  if self.calibration_mode=="NORMAL":self.left_down(event);return
  points=self.calibration or []
  if self.calibration_mode=="CAL_WAIT_POINT_2" and len(points)>=1:
   for i,(x,y) in enumerate(points[:2]):
    sx=self.pan[0]+x*self.zoom;sy=self.pan[1]+y*self.zoom
    if ((event.x-sx)**2+(event.y-sy)**2)**.5<=12:self._calibration_drag_index=i;return
  self._calibration_drag_index=None;self.left_down(event)

 def _calibration_motion(self,event):
  if self.calibration_mode=="NORMAL":return self.left_drag(event)
  index=getattr(self,"_calibration_drag_index",None)
  if index is None:return
  x,y=self.image_point(event.x,event.y);self.calibration[index]=(x,y);sx=self.pan[0]+x*self.zoom;sy=self.pan[1]+y*self.zoom
  self.canvas.coords(f"calibration_point_{index+1}",sx-6,sy-6,sx+6,sy+6);self.canvas.coords(f"calibration_label_{index+1}",sx+10,sy-10)
  if len(self.calibration)>=2:self.canvas.coords("calibration_line",*(sum(([self.pan[0]+px*self.zoom,self.pan[1]+py*self.zoom] for px,py in self.calibration[:2]),[])))

 def _calibration_button_up(self,event):
  index=getattr(self,"_calibration_drag_index",None);self._calibration_drag_index=None
  if self.calibration_mode=="NORMAL":return self.left_up(event)
  if index is not None:
   log(self.current().get("image_id","GLOBAL"),"calibration_point_dragged","END",detail=f"point={index+1}");self._save_dragged_calibration()

 def check_landmarks(self):
  if self._review_scan_worker:return
  # Last successful queue remains visible while a new read-only scan is computed.
  self._review_cancel=False;self._review_scan_worker=True;self.check_landmarks_button.config(state="disabled");self.review_status.config(text="Checking landmarks…")
  def progress(done,total):
   try:self.after(0,lambda:self.review_status.config(text=f"Checking landmarks… {done} / {total}"))
   except (tk.TclError,RuntimeError):pass
  def commit(result):self._commit_review_scan_result(result)
  def failed(exc):
   self._review_scan_worker=False;self.check_landmarks_button.config(state="normal");log("GLOBAL","landmark_review_scan","ERROR",detail=repr(exc));self.review_status.config(text="Landmark check failed — previous review results retained")
  def work():
   try:result=scan_project(self.project,progress=progress,cancelled=lambda:self._review_cancel)
   except Exception as exc:
    try:self.after(0,lambda exc=exc:failed(exc))
    except (tk.TclError,RuntimeError):pass
    return
   try:self.after(0,lambda:commit(result))
   except (tk.TclError,RuntimeError):pass
  threading.Thread(target=work,daemon=True,name="project-landmark-review").start()
 def _commit_review_scan_result(self,result):
  """Atomically replace temporary Review visuals only after a successful scan."""
  self._review_scan_worker=False;self.check_landmarks_button.config(state="normal")
  if result.get("cancelled"):
   self.review_status.config(text="Landmark check cancelled — previous review results retained");return
  self._review_queue=list(result["queue"]);self._review_queue_index=-1;self._review_completed_indices.clear();self._review_active_ids.clear();self._review_pending_image_id=None;self.review_mode=bool(self._review_queue)
  self._refresh_visible_photo_rows();self._refresh_landmark_list(self._load_current_landmark_state());self._render_signature=None;self.render();self._set_review_controls()
  cross=(f"{result['manual_annotations_available']} manual annotations available"+(f"\n{len(result['trusted_reference_ids'])} Checked manual reference used for identity checking" if result["trusted_reference_identity"] else (f"\n{result['early_annotated_images']} annotated images compared for neutral consistency" if result["early_cross_image"] else "\nCross-image consistency requires at least 2 annotated manual images")))
  reference="Statistical variability checking available" if result["statistical_reference"] else "Statistical variability checking requires 8 Checked manual references"
  message=f"Structural check complete\n{result['scanned']} images scanned\n{cross}\n{reference}\n{result['images_needing_review']} images need review\n{len(result['queue'])} warnings found";self.review_status.config(text=message.replace("\n"," — "));messagebox.showinfo("Landmark check complete",message,parent=self)
  if self._review_queue:self._open_review_queue_item(0)
 def _review_issue_label(self,item):
  filename=Path(self.current()["source_relpath"]).name
  return f"Issue {self._review_queue_index+1} of {len(self._review_queue)} | {filename} | {item['message']}"

 def _apply_review_issue_if_loaded(self):
  """Apply display-only Review styling after V12 installed the requested image."""
  if not self.review_mode or not self._review_queue:return False
  item=self._review_queue[self._review_queue_index]
  if self.current()["image_id"]!=item["image_id"] or getattr(self,"_display_image_id",None)!=item["image_id"]:return False
  self._review_pending_image_id=None;self._review_active_ids=set(review_item_landmark_ids(item))
  landmark_id=next(iter(self._review_active_ids),None)
  if landmark_id:self.state.select(landmark_id)
  self._render_signature=None;self.sync();self._refresh_visible_photo_rows();self.review_status.config(text=self._review_issue_label(item))
  return True

 def _open_review_queue_item(self,index):
  if not self._review_queue:return
  self._review_queue_index=index%len(self._review_queue);item=self._review_queue[self._review_queue_index];target=next((i for i,row in enumerate(self.images) if row["image_id"]==item["image_id"]),None)
  if target is None:return
  self._review_active_ids=set(review_item_landmark_ids(item));self.index=target;self._review_pending_image_id=item["image_id"]
  self._refresh_visible_photo_rows();self.review_status.config(text=self._review_issue_label(item))
  if getattr(self,"_display_image_id",None)==item["image_id"]:
   self._apply_review_issue_if_loaded();return
  row=self.images[target];self.open_image(row=row,source=Path(row.get("source_path",row["source_relpath"])),listbox_index=target,user_selection=False)
 def apply_suggested_reassignment(self):
  if not self._review_queue or self._review_queue_index<0:return
  item=self._review_queue[self._review_queue_index];group=item.get("landmark_ids");permutation=item.get("best_permutation")
  if not group or not permutation:return
  if not messagebox.askyesno("Apply Suggested Reassignment",f"Apply the suggested reassignment for LM{group[0]}–LM{group[-1]}?",parent=self):return
  image_id=self.current()["image_id"];state=self._load_current_landmark_state();assignment=dict(zip(group,permutation))
  try:snapshot=self.project.reassign_present_landmarks(image_id,assignment)
  except ValueError as exc:messagebox.showwarning("Reassignment",str(exc),parent=self);return
  self._review_undo=(image_id,snapshot,bool(state.human_verified));self._render_signature=None;self.sync();self._refresh_review()
 def accept_review_warning(self):
  """Record an explicit human acceptance; never alter landmark coordinates."""
  if not self._review_queue or self._review_queue_index<0:return
  item=self._review_queue[self._review_queue_index]
  if item.get("image_id")!=self.current().get("image_id"):return
  self.project.accept_review_warning(item["image_id"],item)
  self._review_completed_indices.add(self._review_queue_index);self._review_active_ids.clear();self._refresh_visible_photo_rows();self._refresh_landmark_list(self._load_current_landmark_state())
  pending=[index for index in range(len(self._review_queue)) if index not in self._review_completed_indices]
  if pending:self._open_review_queue_item(next((index for index in pending if index>self._review_queue_index),pending[0]));return
  self.review_status.config(text="REVIEW — all current issues handled")
 def previous_review_warning(self):
  if self._review_queue:self._open_review_queue_item(self._review_queue_index-1)
 def _set_review_controls(self):
  active=bool(self.review_mode)
  if hasattr(self,"landmark_review_context") and not self.landmark_review_context.winfo_manager():self.landmark_review_context.pack(fill="x",pady=(1,2))
  for button in (self.swap_button,self.previous_review_button,self.next_warning_button,self.review_done_button,self.exit_review_button,self.apply_reassignment_button,self.accept_review_button):
   button.config(state="normal" if active else "disabled")
   (button.grid if active else button.grid_remove)()
  self.undo_swap_button.config(state="normal" if active and self._review_undo else "disabled")
  (self.undo_swap_button.grid if active else self.undo_swap_button.grid_remove)()
 def _set_landmark_workflow_controls(self):
  active=bool(getattr(self,"_landmark_workflow_active",False))
  if not hasattr(self,"landmark_workflow_context"):return
  if not self.landmark_workflow_context.winfo_manager():self.landmark_workflow_context.pack(fill="x",pady=(1,2))
  info=getattr(self,"_landmark_ai_info",None) or stage_summary(self.project,create_missing=False)
  ready=info["verified"]>=info["total"] and info["total"]>0 and bool(info["active_model_id"])
  self.landmark_train_button.grid();self.landmark_train_button.config(state="normal")
  self.landmark_improvement_button.grid();self.landmark_improvement_button.config(state="normal")
 def _save_workflow_draft(self):
  """Canonical rows are already saved; this durable marker keeps workflow work unfinished."""
  if not getattr(self,"_landmark_workflow_active",False) or not getattr(self,"project",None) or not getattr(self,"images",None):return
  stage=(getattr(self,"_landmark_ai_info",{}) or {}).get("stage")
  self.project.save_annotation_draft(self.current()["image_id"],stage,getattr(self,"_landmark_workflow_index",None))
 def _annotation_check_for_current(self):
  image=getattr(self,"standard",None);width,height=image.size if image else (0,0)
  return check_annotation(self.project,self.current()["image_id"],width,height)
 def _show_annotation_findings(self,findings,heading):
  ids=set()
  for finding in findings: ids.update(review_item_landmark_ids(finding))
  self.review_mode=True;self._review_active_ids=ids;self.review_status.config(text="ANNOTATION CHECK — "+heading);self._refresh_landmark_list(self._load_current_landmark_state());self.render();self._set_review_controls()
 def exit_landmark_ai_workflow(self):
  self._landmark_workflow_active=False;self._landmark_workflow_review_only=False;self._ai_worst_review_active=False;self._ai_worst_review_items=[];self._review_active_ids.clear();self.review_mode=False
  if getattr(self,"_landmark_set_review_active",False):self._landmark_set_review_active=False;self._landmark_set_review_warnings={};self._review_active_ids.clear();self.review_mode=False
  if hasattr(self,"ai_worst_next_button"):self.ai_worst_next_button.grid_remove()
  self._set_landmark_workflow_controls();self.review_status.config(text="");self._refresh_landmark_ai_panel()
 def _refresh_review(self):
  if not self.review_mode:return
  image=getattr(self,"standard",None);width,height=image.size if image else (1,1)
  self._review_warnings=review_warnings(self.project,self.current()["image_id"],width,height);self._review_warning_index=0
  self.review_status.config(text="REVIEW — "+(self._review_warnings[0]["message"] if self._review_warnings else "No suspicious landmark inconsistencies detected"));self._set_review_controls()
 def toggle_review(self):
  self.review_mode=not self.review_mode;self._review_swap_first=None;self._review_undo=None
  if self.review_mode:self._refresh_review()
  else:
   self._review_active_ids.clear();self._review_completed_indices.clear();self.review_status.config(text="");self._set_review_controls();self._refresh_visible_photo_rows();self._refresh_landmark_list(self._load_current_landmark_state())
  self._render_signature=None;self.render()
 def start_review_swap(self):
  if self.review_mode:self._review_swap_first=None;self.review_status.config(text="REVIEW — select the first present landmark")
 def _review_swap_click(self,event):
  state=self._load_current_landmark_state();hit=None
  for landmark_id in state.present_ids:
   row=state.points_by_id[landmark_id];sx=self.pan[0]+row["x_standardized"]*self.zoom;sy=self.pan[1]+row["y_standardized"]*self.zoom
   if (event.x-sx)**2+(event.y-sy)**2<=144:hit=landmark_id;break
  if hit is None:self.review_status.config(text="REVIEW — swap requires two present landmarks");return True
  if self._review_swap_first is None:self._review_swap_first=hit;self.review_status.config(text=f"REVIEW — select the second landmark for LM{hit}");return True
  if hit==self._review_swap_first:self.review_status.config(text="REVIEW — select a different landmark");return True
  image_id=self.current()["image_id"];verified=bool(state.human_verified)
  try:snapshot=self.project.swap_present_landmarks(image_id,self._review_swap_first,hit)
  except ValueError as exc:self.review_status.config(text=f"REVIEW — {exc}");self._review_swap_first=None;return True
  self._review_undo=(image_id,snapshot,verified);self._review_swap_first=None;self._render_signature=None;self.sync();self._refresh_review();return True
 def undo_review_swap(self):
  if not self._review_undo:return
  image_id,snapshot,verified=self._review_undo
  if image_id==self.current()["image_id"]:self.project.restore_landmark_finals(image_id,snapshot,human_verified=verified);self._review_undo=None;self._render_signature=None;self.sync();self._refresh_review()
 def next_review_warning(self):
  if self._review_queue:
   self._open_review_queue_item(self._review_queue_index+1);return
  if not self.review_mode:self.toggle_review()
  if not self._review_warnings:self._refresh_review();return
  warning=self._review_warnings[self._review_warning_index%len(self._review_warnings)];self._review_warning_index+=1
  if warning.get("landmark_id"):self.state.select(warning["landmark_id"]);self.sync()
  self.review_status.config(text="REVIEW — "+warning["message"])
 def finish_review(self):
  state=self._load_current_landmark_state()
  if not state.complete:self.review_status.config(text="REVIEW — unresolved landmarks: "+", ".join(map(str,sorted(state.unresolved_ids))));return
  self.mark_checked();self._review_swap_first=None;self._review_undo=None
  if self._review_queue:
   self._review_completed_indices.add(self._review_queue_index);self._refresh_visible_photo_rows()
   pending=[index for index in range(len(self._review_queue)) if index not in self._review_completed_indices]
   if pending:self._open_review_queue_item(next((index for index in pending if index>self._review_queue_index),pending[0]));return
   self._review_active_ids.clear()
  self._review_active_ids.clear();self._refresh_landmark_list(self._load_current_landmark_state())
  self.review_mode=False;self.review_status.config(text="");self._set_review_controls()
 def _editable_landmark_hit(self,event):
  """Canonical hit-test: manual and machine rows are equally editable."""
  state=self._load_current_landmark_state()
  if state is None:return None
  candidates=[]
  for landmark_id in state.present_ids:
   row=state.points_by_id[landmark_id];sx=self.pan[0]+row["x_standardized"]*self.zoom;sy=self.pan[1]+row["y_standardized"]*self.zoom
   distance=((event.x-sx)**2+(event.y-sy)**2)**.5
   if distance<=12:candidates.append((distance,landmark_id))
  return min(candidates)[1] if candidates else None
 def _near_current_landmark(self,event,state,radius=18):
  """Guard only a true current visible point; immutable prediction history is irrelevant."""
  candidates=[]
  for landmark_id in state.present_ids:
   row=state.points_by_id[landmark_id];sx=self.pan[0]+row["x_standardized"]*self.zoom;sy=self.pan[1]+row["y_standardized"]*self.zoom
   distance=((event.x-sx)**2+(event.y-sy)**2)**.5
   if distance<=radius:candidates.append((distance,landmark_id))
  return min(candidates)[1] if candidates else None
 def _place_next_workflow_unresolved(self,event,state,image_id):
  """Workflow-only empty-click path using current unresolved state, not row existence."""
  near=self._near_current_landmark(event,state)
  if near is not None:
   log(image_id,"landmark_empty_click_decision","WARNING",detail=f"workflow_mode=true current_present_count={len(state.present_ids)} unresolved_count={len(state.unresolved_ids)} near_visible_landmark={near} decision=suppress_near_visible blocked_reason=state_hit_disagrees")
   return True
  number=next((point.number for point in self.profile.landmarks if point.number in state.unresolved_ids),None)
  if number is None:
   log(image_id,"landmark_empty_click_decision","END",detail=f"workflow_mode=true current_present_count={len(state.present_ids)} unresolved_count=0 near_visible_landmark=None decision=blocked_reason=no_unresolved_landmark")
   return True
  x,y=self.image_point(event.x,event.y);self.state.select(number);point=self._point(number)
  set_human_point(self.record,number,point.code,x,y,corrected=False);save_record(self.record);self.state.after_place_new(False);self._save_workflow_draft();self._render_signature=None
  log(image_id,"landmark_empty_click_decision","END",detail=f"workflow_mode=true current_present_count={len(state.present_ids)} unresolved_count={len(state.unresolved_ids)} near_visible_landmark=None decision=place_next")
  log(image_id,"landmark_manual_place","END",detail=f"landmark_id={number} x={x:.3f} y={y:.3f} workflow_mode=true")
  self.sync();return True
 def left_down(self,event):
  if not getattr(self,"_canvas_landmark_input_ready",False):
   log("GLOBAL","landmark_input_suppressed","END",detail="reason=image_not_ready")
   return
  self._ensure_editable_record_complete()
  image_id=self.current().get("image_id","GLOBAL") if getattr(self,"images",None) else "GLOBAL"
  log(image_id,"landmark_mouse_press","END",detail=f"x={event.x} y={event.y} workflow_mode={bool(getattr(self,'_landmark_workflow_active',False))} review_mode={self.review_mode} source_mode={self.source_mode} editable={not self.source_mode}")
  if not self.source_mode and self.calibration_mode=="NORMAL" and not (self.review_mode and self._review_swap_first is not None):
   state=self._load_current_landmark_state();hit=self._editable_landmark_hit(event)
   log(image_id,"landmark_hit_test","END",detail=f"hit_landmark_id={hit} x={event.x} y={event.y} workflow_mode={bool(getattr(self,'_landmark_workflow_active',False))}")
   if hit is not None:
    self.state.select(hit);self.dragging=hit;self._last_landmark_drag_log=0.;log(image_id,"landmark_drag_start","END",detail=f"landmark_id={hit} workflow_mode={bool(getattr(self,'_landmark_workflow_active',False))}");self.sync();return
   if getattr(self,"_landmark_workflow_active",False) and state is not None:
    if self._place_next_workflow_unresolved(event,state,image_id):return
  if self.review_mode and self._review_swap_first is not None:
   if self._review_swap_click(event):return
  if self.calibration_mode=="WAIT_POINT_1":
   self.calibration=[tuple(self.image_point(event.x,event.y))]
   self.calibration_mode="WAIT_POINT_2"
   log(self.current().get("image_id","GLOBAL"),"calibration_point_set","END",detail="point=1")
   self._draw_calibration_overlays()
   self.header.config(text="Calibration: select point 2")
   return
  if self.calibration_mode=="WAIT_POINT_2":
   self.calibration.append(tuple(self.image_point(event.x,event.y)))
   log(self.current().get("image_id","GLOBAL"),"calibration_point_set","END",detail="point=2")
   self._draw_calibration_overlays()
   log(self.current().get("image_id","GLOBAL"),"calibration_segment_created","END",detail="point1_point2_visible=true")
   self.canvas.update_idletasks()
   self.finish_calibration()
   return
  result=super().left_down(event);self._save_workflow_draft();return result

 def _draw_landmark_number_label(self, landmark_id, sx, sy, warning=False):
  """Draw a Review-mode landmark number: black text with a 1-pixel white outline."""
  x,y,anchor=review_warning_label_layout(sx,sy,max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height()))
  tags=("landmark_overlay","landmark_label","landmark_label_outline",f"landmark:{landmark_id}")
  if warning:tags=tags+("review_warning_label",f"review_warning_label_{landmark_id}")
  # Tk Canvas text has no stroke API: these are exactly one pixel from the text.
  for dx,dy in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
   self.canvas.create_text(x+dx,y+dy,text=str(landmark_id),anchor=anchor,fill="white",font=("Segoe UI",10,"bold"),tags=tags)
  self.canvas.create_text(x,y,text=str(landmark_id),anchor=anchor,fill="black",font=("Segoe UI",10,"bold"),tags=tags)

 def _draw_review_warning_label(self, landmark_id, sx, sy):
  # Kept as a narrow alias for focused Review tests and existing callers.
  self._draw_landmark_number_label(landmark_id,sx,sy,warning=True)

 def _draw_universal_landmark_number_labels(self):
  # ReadyEditorV11 owns ordinary annotation labels. Review alone replaces
  # them so its labels remain consistently readable over warning overlays.
  if not self.review_mode or self.source_mode or not getattr(self,"project",None):return
  state=self._load_current_landmark_state()
  if state is None:return
  self.canvas.delete("landmark_label")
  for landmark_id in state.present_ids:
   row=state.points_by_id[landmark_id];sx=self.pan[0]+row["x_standardized"]*self.zoom;sy=self.pan[1]+row["y_standardized"]*self.zoom
   self._draw_landmark_number_label(landmark_id,sx,sy,warning=bool(self.review_mode and landmark_id in self._review_active_ids))

 def _draw_review_overlays(self):
  self.canvas.delete("review_overlay")
  self.canvas.delete("review_warning_overlay")
  if not self.review_mode or not getattr(self,"project",None):return
  state=self._load_current_landmark_state()
  for landmark_id in self._review_active_ids & state.present_ids:
   row=state.points_by_id[landmark_id];sx=self.pan[0]+row["x_standardized"]*self.zoom;sy=self.pan[1]+row["y_standardized"]*self.zoom
   self.canvas.create_oval(sx-12,sy-12,sx+12,sy+12,outline="#d93025",width=3,tags=("review_warning_overlay",f"review_warning_landmark_{landmark_id}"))

 def render(self):
  result=super().render();self._draw_calibration_overlays();self._draw_universal_landmark_number_labels();self._draw_review_overlays();return result
 def right_drag(self,event):
  result=super().right_drag(event);self._draw_calibration_overlays();return result

 def _load_last_ai_batch(self):
  if not self.project:return
  batch_id=self.project.get_ui_state("active_ai_batch")
  if not batch_id:return
  try:self._ai_batch,self._ai_batch_path=load_batch(self.project,batch_id)
  except Exception:return
  self._update_ai_batch_status()
  self.after_idle(lambda:self._open_ai_batch_item(0))

 def _update_ai_batch_status(self):
  if not getattr(self,"_ai_batch",None):
   if hasattr(self,"ai_batch_status"):self.ai_batch_status.config(text="")
   return
  total=len(self._ai_batch["selected_images"]);reviewed=reviewed_count(self.project,self._ai_batch)
  if hasattr(self,"ai_batch_status"):self.ai_batch_status.config(text=f"AI Batch: {self._ai_batch_index+1} / {total} | Reviewed: {reviewed} / {total}")

 def _open_ai_batch_item(self,index):
  if not self._ai_batch:return
  items=self._ai_batch["selected_images"];self._ai_batch_index=index%len(items);image_id=items[self._ai_batch_index]["image_id"]
  target=next((i for i,row in enumerate(self.images) if row["image_id"]==image_id),None)
  if target is None:return
  self.index=target;self._update_ai_batch_status();self._refresh_visible_photo_rows()
  if getattr(self,"_display_image_id",None)==image_id:return
  row=self.images[target];self.open_image(row=row,source=Path(row.get("source_path",row["source_relpath"])),listbox_index=target,user_selection=False)

 def start_ai_predict_all_remaining(self):
  active=self.project.active_model_readonly("landmark") or {};model_id=active.get("model_id")
  if not model_id:messagebox.showerror("AI Predict All Remaining","No active landmark model.",parent=self);return
  ids=[r["image_id"] for r in self.project.catalog_rows() if not r.get("excluded") and not self.project.load_landmarks(r["image_id"]) and landmark_frame_ready(self.project,r["image_id"])]
  if not ids:messagebox.showinfo("AI Predict All Remaining","No eligible remaining images.",parent=self);return
  if messagebox.askyesno("AI Predict All Remaining",f"Apply {model_id} to {len(ids)} remaining images?",parent=self): self.start_ai_predict_batch(image_ids=ids)
 def start_ai_repredict_machine_only(self):
  human={"manual","corrected","corrected_by_human","reviewed_by_human"};ids=[]
  for row in self.project.catalog_rows():
   if row.get("excluded"):continue
   ident=row["image_id"];status=self.project.annotation_status(ident)
   if status.get("verified"):continue
   points=self.project.load_landmarks(ident)
   if points and landmark_frame_ready(self.project,ident) and all(point.get("provenance")=="machine" for point in points.values()):ids.append(ident)
  if not ids:messagebox.showinfo("Re-predict AI-only","No AI-only images are eligible.",parent=self);return
  active=(self.project.active_model_readonly("landmark") or {}).get("model_id","active model")
  if messagebox.askyesno("Re-predict AI-only",f"Re-predict {len(ids)} AI-only images using {active}?",parent=self):self.start_ai_predict_batch(image_ids=ids)
 def previous_ai_batch(self):
  if self._ai_batch:self._open_ai_batch_item(self._ai_batch_index-1)
 def next_ai_batch(self):
  if self._ai_batch:self._open_ai_batch_item(self._ai_batch_index+1)

 def start_ai_predict_batch(self,count=None,image_ids=None):
  if self._ai_batch_worker:return
  count=len(image_ids) if image_ids is not None else (count if count is not None else simpledialog.askinteger("AI Predict Batch","Number of images",initialvalue=10,minvalue=1,parent=self))
  if count is None:return
  start_id=self.current()["image_id"];self._ai_batch_model_id=(self.project.active_model_readonly("landmark") or {}).get("model_id","active model");self._ai_batch_worker=True
  self.ai_predict_button.config(state="disabled");self.ai_batch_status.config(text="AI Batch: preparing…")
  progress,label=self._show_nonmodal_progress("Predicting landmarks",f"Predicting landmarks with {self._ai_batch_model_id}\nPreparing...");started=time.monotonic();events=queue.Queue()
  def finish(data,path):
   self._ai_batch_worker=False;self.ai_predict_button.config(state="normal");self._close_nonmodal_progress(progress);self._ai_batch=data;self._ai_batch_path=path;self._ai_batch_index=0;self.project.set_ui_state("active_ai_batch",data["batch_id"]);self._open_ai_batch_item(0)
   self.review_status.config(text=f"Completed: {len(data['prediction_runs'])} | Failed: {len(data['failures'])} | Elapsed: {int(time.monotonic()-started)} s")
  def failed(exc):
   self._ai_batch_worker=False;self.ai_predict_button.config(state="normal");self._close_nonmodal_progress(progress);self.ai_batch_status.config(text="");messagebox.showerror("AI Predict Batch",str(exc),parent=self)
  def work():
   try:
    model,backend=active_backend(self.project);ids,_=prospective_candidates(self.project,model["model_id"],start_id,count);preflight_backend(self.project,backend,ids[0]);data,path=create_batch_for_ids(self.project,model["model_id"],image_ids) if image_ids is not None else create_batch(self.project,model["model_id"],start_id,count)
    def report(done,total,name):events.put((done,total,name,time.monotonic()))
    data,path=run_batch(self.project,path,LandmarkAIService(self.project,backend),progress=report)
   except Exception as exc:
    self.after(0,lambda exc=exc:failed(exc));return
   self.after(0,lambda:finish(data,path))
  threading.Thread(target=work,daemon=True,name="project-ai-batch").start()
  def poll_progress():
   try:
    while True:
     done,total,name,stamp=events.get_nowait();elapsed=max(.001,stamp-started);eta=elapsed/done*(total-done) if done>1 else None;label.config(text=f"Predicting landmarks with {self._ai_batch_model_id}\n{done} / {total}\n{name}\nElapsed: {int(elapsed)//60:02d}:{int(elapsed)%60:02d}"+(f"\nETA: {int(eta)//60:02d}:{int(eta)%60:02d}" if eta is not None else ""));set_progress_dialog_progress(progress,done,total)
   except queue.Empty:
    if self._ai_batch_worker and progress.winfo_exists():self.after(100,poll_progress)
  poll_progress()
 def _show_landmark_ai_more(self):
  dialog=tk.Toplevel(self);dialog.title("Landmark AI");dialog.transient(self);dialog.resizable(False,False);frame=ttk.Frame(dialog,padding=10);frame.pack(fill="both",expand=True)
  ttk.Button(frame,text="Check AI Quality",command=lambda:(dialog.destroy(),self.check_ai_quality())).pack(fill="x",pady=1)
  ttk.Button(frame,text="Landmark Quality",command=lambda:(dialog.destroy(),self.show_landmark_quality())).pack(fill="x",pady=1)
  ttk.Button(frame,text="Optimize Resolution",command=lambda:(dialog.destroy(),self.optimize_landmark_resolution())).pack(fill="x",pady=1)
  ttk.Button(frame,text="Human Baseline",command=lambda:(dialog.destroy(),self.check_operator_repeatability())).pack(fill="x",pady=1)
  ttk.Button(frame,text="View Previous Human Baselines",command=lambda:(dialog.destroy(),self.show_human_baseline_history())).pack(fill="x",pady=1)
  ttk.Button(frame,text="Landmark Models...",command=lambda:(dialog.destroy(),self.show_landmark_models())).pack(fill="x",pady=1)
  ttk.Button(frame,text="Review AI Worst First...",command=lambda:(dialog.destroy(),self.start_review_ai_worst_first())).pack(fill="x",pady=1)
  ttk.Button(frame,text="Close",command=dialog.destroy).pack(fill="x",pady=(6,0))
 def show_landmark_models(self):
  dialog=tk.Toplevel(self);dialog.title("Landmark Models");dialog.transient(self);dialog.resizable(True,True);center_child_window(dialog)
  outer=ttk.Frame(dialog,padding=10);outer.pack(fill="both",expand=True);columns=("model","status","parent","resolution","images","batch","epochs","photo","best","ema","median","p90","p95","schema")
  table=ttk.Treeview(outer,columns=columns,show="headings",height=12);labels={"model":"Model ID","status":"Status","parent":"Parent","resolution":"Input size","images":"Images","batch":"Batch","epochs":"Epochs","photo":"Photo aug","best":"Best epoch","ema":"EMA","median":"Internal Median","p90":"Internal P90","p95":"Internal P95","schema":"Schema"}
  for c in columns: table.heading(c,text=labels[c]);table.column(c,width=90,anchor="w")
  table.grid(row=0,column=0,sticky="nsew");vs=ttk.Scrollbar(outer,orient="vertical",command=table.yview);vs.grid(row=0,column=1,sticky="ns");table.configure(yscrollcommand=vs.set);outer.rowconfigure(0,weight=1);outer.columnconfigure(0,weight=1)
  active=(self.project.active_model_readonly("landmark") or {}).get("model_id");root=Path(self.project.data_root)/"ai"/"models";records=[]
  for path in sorted(root.glob("rtmpose_v*")) if root.exists() else ():
   try:meta=json.loads((path/"model.json").read_text(encoding="utf-8")) if (path/"model.json").is_file() else {}
   except Exception:meta={}
   mid=meta.get("model_id",path.name)
   settings=meta.get("training_settings",{}) or {};result=meta.get("result",{}) or {};ev=result.get("engineering_validation",{}) or {};ctrl=result.get("control",result.get("control_set",{})) or {};registered=self.project.model_metadata(mid) or {};schema_ok=registered.get("schema_sha256")==schema_hash(self.project.schema_path)
   manifest=registered.get("dataset_manifest_path") or meta.get("dataset_manifest")
   if manifest:
    try:
     manifest_path=Path(manifest)
     if not manifest_path.is_absolute(): manifest_path=Path(self.project.data_root)/manifest_path
     manifest_data=json.loads(manifest_path.read_text(encoding="utf-8"));meta["training_image_count"]=len(manifest_data.get("images",()))
     meta["training_split_counts"]={split:sum(1 for image in manifest_data.get("images",()) if image.get("split")==split) for split in ("train","validation","test")}
    except Exception: pass
    except Exception:pass
   row=(mid,"Active" if mid==active else "Inactive",meta.get("parent_model_id","—"),meta.get("input_size",settings.get("input_size","—")),meta.get("training_image_count",meta.get("training_images","—")),settings.get("batch_size","—"),settings.get("max_epochs","—"),"ON" if settings.get("photometric_augmentation") else "OFF" if "photometric_augmentation" in settings else "—",result.get("best_epoch","—"),"Yes" if result.get("ema_used") is True else "No" if result.get("ema_used") is False else "—",ev.get("median_error_percent","—"),ev.get("p90_error_percent","—"),ev.get("p95_error_percent","—"),"Compatible" if schema_ok else "Incompatible");records.append((row,meta,mid,bool(schema_ok)))
  def fmt(v): return "—" if v is None else str(v)
  def fmt_row(row):
   out=[]
   for col,v in zip(columns,row):
    if col in ("median","p90","p95") and isinstance(v,(int,float)): out.append(f"{v:.2f}%")
    elif col=="resolution" and isinstance(v,(list,tuple)): out.append(f"{v[0]} x {v[1]}")
    else: out.append(fmt(v))
   return tuple(out)
  def populate(items):
   for i in table.get_children():table.delete(i)
   for row,_,_,_ in items:table.insert("","end",values=fmt_row(row))
  populate(records);details=ttk.Label(dialog,text="Select a model",justify="left");details.pack(fill="x",padx=10,pady=5);actions=ttk.Frame(dialog);actions.pack(fill="x",padx=10,pady=(0,10))
  def current():
   item=table.focus();return next((r for r in records if r[0][0]==table.item(item,"values")[0]),None) if item else None
  def select(_=None):
   rec=current();details.config(text=(f"Model: {rec[2]} | {rec[0][1]} | Parent: {rec[0][2]} | Input: {fmt_row(rec[0])[3]} | Images: {rec[0][4]}\nDataset: {rec[0][4]} images | Batch: {rec[0][5]} | Epochs: {rec[0][6]} | Photo aug: {rec[0][7]}\nBest epoch: {rec[0][8]} | EMA: {rec[0][9]} | Internal: Median {fmt_row(rec[0])[10]} | P90 {fmt_row(rec[0])[11]} | P95 {fmt_row(rec[0])[12]} | Schema: {rec[0][13]}" if rec else "Select a model"));use_btn.config(state="normal" if rec and rec[3] else "disabled")
  def use():
   rec=current()
   if rec and rec[3] and messagebox.askyesno("Use Landmark Model",f"Activate {rec[2]}?",parent=dialog): activate_landmark_model(self.project,rec[2]);self._refresh_landmark_ai_panel();self._set_landmark_workflow_controls();dialog.destroy()
  def compare():
   rec=current()
   if not rec:return
   if not rec[3]:messagebox.showwarning("Evaluate / Compare","Selected model is schema-incompatible.",parent=dialog);return
   try:
    aid=active
    if not aid:raise ValueError("No current active landmark model.")
    comparison=compare_control_models(self.project,aid,rec[2])
    metrics=comparison["metrics"]
    def value(name):
     item=metrics[name];delta=item.get("delta_percent");return f"{item['previous']:.2f}%       {item['new']:.2f}%       {'—' if delta is None else f'{delta:+.1f}%'}"
    text=f"Current model: {aid}\nSelected model: {rec[2]}\n\nCONTROL SET — same fixed images\nMetric            Current       Selected      Change\nMedian            {value('median_error_percent')}\nP90               {value('p90_error_percent')}\nP95               {value('p95_error_percent')}\n\nResult: {comparison['result']}"
    human=latest_completed_report(self.project);human_rows=[]
    if human:
     ids=human["image_ids"];current_eval=evaluate_control_set(self.project,aid,image_ids=ids);selected_eval=evaluate_control_set(self.project,rec[2],image_ids=ids);current_human=comparison_for_model(human,current_eval);selected_human=comparison_for_model(human,selected_eval);human_rows=landmark_model_rows(human,current_eval,selected_eval);ha=human['human']['aggregate'];ca=current_human['model']['aggregate'];sa=selected_human['model']['aggregate']
     text+=f"\n\nHUMAN BASELINE — same fixed images\nMetric        Human       Current       Selected\nMedian        {ha.get('median_error_percent',0):.2f}%       {ca.get('median_error_percent',0):.2f}%       {sa.get('median_error_percent',0):.2f}%\nP90           {ha.get('p90_error_percent',0):.2f}%       {ca.get('p90_error_percent',0):.2f}%       {sa.get('p90_error_percent',0):.2f}%\nP95           {ha.get('p95_error_percent',0):.2f}%       {ca.get('p95_error_percent',0):.2f}%       {sa.get('p95_error_percent',0):.2f}%\n\nCurrent / Human P90: {current_human['ratios']['p90']:.2f}x\nSelected / Human P90: {selected_human['ratios']['p90']:.2f}x\nCurrent grade: {current_human['grade']}\nSelected grade: {selected_human['grade']}"
    result_dialog=tk.Toplevel(dialog);result_dialog.title("Landmark Model Comparison");result_dialog.transient(dialog);result_dialog.resizable(True,True);center_child_window(result_dialog);ttk.Label(result_dialog,text=text,justify="left",padding=14).pack(fill="both",expand=True)
    actions=ttk.Frame(result_dialog,padding=(14,0,14,14));actions.pack(fill="x")
    if human_rows:ttk.Button(actions,text="View All Landmarks",command=lambda:self._show_human_landmarks(human_rows,load_schema(self.project.schema_path),result_dialog)).pack(side="left")
    ttk.Button(actions,text="Close",command=result_dialog.destroy).pack(side="right")
   except Exception as exc:messagebox.showerror("Evaluate / Compare",str(exc),parent=dialog)
  table.bind("<<TreeviewSelect>>",select);use_btn=ttk.Button(actions,text="Use This Model",command=use,state="disabled");use_btn.pack(side="left");ttk.Button(actions,text="Evaluate / Compare",command=compare).pack(side="left",padx=6);ttk.Button(actions,text="Close",command=dialog.destroy).pack(side="right")
 def show_landmark_quality(self):
  model=(self.project.active_model("landmark") or {}).get("model_id")
  profile=stored_control_landmark_quality_profile(self.project,model) if model else None
  if not profile:messagebox.showinfo("Landmark Quality","Landmark quality profile is not available yet.",parent=self);return
  persistent=stable_weak_landmark_profile(self.project,model) or {};dialog=tk.Toplevel(self);dialog.title("Landmark Quality");dialog.transient(self);dialog.resizable(False,False)
  human_report=latest_completed_report(self.project)
  ttk.Label(dialog,text=format_landmark_quality_table(profile,load_schema(self.project.schema_path),persistent.get("weak_landmark_ids",()),human_report,model),justify="left",padding=14).pack(fill="both")
  status_label(dialog,"Persistent weak landmarks" if persistent.get("weak_landmark_ids") else "Normal landmarks").pack(padx=14,anchor="w")
  ttk.Button(dialog,text="Close",command=dialog.destroy).pack(padx=14,pady=(0,14),fill="x")
 def optimize_landmark_resolution(self):
  dialog=tk.Toplevel(self);dialog.title("Optimize Landmark Resolution");dialog.transient(self);frame=ttk.Frame(dialog,padding=12);frame.pack();ttk.Label(frame,text="MorphoLabel will compare 3 landmark resolutions:\n512 x 256\n640 x 320\n768 x 384\n\nThe same training images and Control Set will be used.\nThis takes about three training runs.",justify="left").pack()
  def start():
   dialog.destroy();seed=stage_summary(self.project,create_missing=False)["state"]["seed"];progress, label=self._show_nonmodal_progress("OPTIMIZING LANDMARK RESOLUTION","Preparing resolution experiment...")
   def work():
    try:
     plan=prepare_experiment(self.project,seed=seed)
     def callback(ordinal,size,model_id):self.after(0,lambda:label.config(text=f"OPTIMIZING LANDMARK RESOLUTION\nTesting {size[0]} x {size[1]} ({ordinal} of 3)\nDevice: CUDA\nTraining model: {model_id}"))
     result=run_experiment(self.project,plan,progress_callback=callback)
    except Exception as exc:self.after(0,lambda exc=exc:(self._close_nonmodal_progress(progress),messagebox.showerror("Optimize Landmark Resolution",str(exc),parent=self)));return
    self.after(0,lambda:self._resolution_complete(progress,result))
   threading.Thread(target=work,daemon=True,name="landmark-resolution-experiment").start()
  ttk.Button(frame,text="Start",command=start).pack(side="left",padx=4,pady=(10,0));ttk.Button(frame,text="Cancel",command=dialog.destroy).pack(side="left",padx=4,pady=(10,0))
 def _resolution_complete(self,progress,result):
  self._close_nonmodal_progress(progress);rows=result["candidates"];base=next(x["inference_seconds"] for x in rows if tuple(x["input_size"])==(512,256));text="RESOLUTION CHECK COMPLETE\n\nResolution      Median    P90     P95     Speed\n"+"\n".join(f"{x['input_size'][0]} x {x['input_size'][1]}    {x['median_error_percent']:.2f}%    {x['p90_error_percent']:.2f}%    {x['p95_error_percent']:.2f}%    {x['inference_seconds']/base:.2f}x" for x in rows);recommendation=result['recommendation'];text+=f"\n\nRecommended: {recommendation['input_size'][0]} x {recommendation['input_size'][1]}\n"+("P90 and P95 improved meaningfully." if recommendation['input_size']!=(512,256) else "Higher resolution did not improve large landmark errors enough.")
  dialog=tk.Toplevel(self);dialog.title("Resolution Check Complete");frame=ttk.Frame(dialog,padding=12);frame.pack();ttk.Label(frame,text=text,justify="left").pack()
  ttk.Button(frame,text="Use Recommended Model",command=lambda:(activate_landmark_model(self.project,recommendation['model_id']),dialog.destroy(),self._refresh_landmark_ai_panel(),self._set_landmark_workflow_controls(),messagebox.showinfo("Resolution Check",f"Active landmark model: {recommendation['model_id']}\nResolution: {recommendation['input_size'][0]} x {recommendation['input_size'][1]}",parent=self))).pack(side="left",padx=4,pady=(10,0));ttk.Button(frame,text="Keep Current Model",command=dialog.destroy).pack(side="left",padx=4,pady=(10,0))
 def _show_crop_ai_more(self):
  dialog=tk.Toplevel(self);dialog.title("Crop AI");dialog.transient(self);dialog.resizable(False,False);frame=ttk.Frame(dialog,padding=10);frame.pack(fill="both",expand=True)
  for text,command in (("AI Training Status",self.show_ai_training_status),("Crop Training Batch",self.start_crop_training_batch),("Re-run Unreviewed AI Crops",self.start_rerun_unreviewed_crops),("Evaluate Crop Model",self.evaluate_crop_holdout),("Review Bad Crops",lambda:self.start_crop_qc_review(False))):ttk.Button(frame,text=text,command=lambda callback=command:(dialog.destroy(),callback())).pack(fill="x",pady=1)
  ttk.Button(frame,text="Close",command=dialog.destroy).pack(fill="x",pady=(6,0))
 def _build_compact_controls(self):
  left=self.landmark_pane
  for child in tuple(left.winfo_children()):
   if isinstance(child,ttk.Button):child.pack_forget()
  if hasattr(self,"crop_train_status"):self.crop_train_status.master.pack_forget()
  scroll_host=ttk.Frame(left);scroll_host.pack(fill="both",expand=True,pady=(2,0));canvas=tk.Canvas(scroll_host,highlightthickness=0);scrollbar=ttk.Scrollbar(scroll_host,orient="vertical",command=canvas.yview);canvas.configure(yscrollcommand=scrollbar.set);canvas.pack(side="left",fill="both",expand=True);scrollbar.pack(side="right",fill="y");self.control_panel=ttk.Frame(canvas,padding=(0,3));window_id=canvas.create_window((0,0),window=self.control_panel,anchor="nw");self.control_panel.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")));canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window_id,width=e.width));canvas.bind("<MouseWheel>",lambda e:canvas.yview_scroll(int(-e.delta/120),"units"));self.control_panel.bind("<MouseWheel>",lambda e:canvas.yview_scroll(int(-e.delta/120),"units"))
  def section(title):
   frame=ttk.LabelFrame(self.control_panel,text=title,padding=(5,3));frame.pack(fill="x",pady=(1,2));return frame
  def grid_button(parent,text,command,row,column,**kwargs):
   control=ttk.Button(parent,text=text,command=command,**kwargs);control.grid(row=row,column=column,sticky="ew",padx=1,pady=1);return control
  def two_columns(parent):parent.columnconfigure(0,weight=1);parent.columnconfigure(1,weight=1)
  landmark_ai=section("LANDMARK AI");self.landmark_ai_context=landmark_ai;self.active_model_status=ttk.Label(landmark_ai,text="Model: None",foreground="#606060");self.active_model_status.grid(row=0,column=0,columnspan=2,sticky="w");self.landmark_ai_stage=ttk.Label(landmark_ai,text="Workflow: Control set",foreground="#606060");self.landmark_ai_stage.grid(row=1,column=0,columnspan=2,sticky="w");self.landmark_ai_progress=ttk.Label(landmark_ai,text="Progress: 0 / 0",foreground="#606060");self.landmark_ai_progress.grid(row=2,column=0,columnspan=2,sticky="w",pady=(0,2));two_columns(landmark_ai)
  grid_button(landmark_ai,"Continue Marking",self.continue_landmark_ai,3,0);grid_button(landmark_ai,"Review Landmark Sets",self.show_review_landmark_sets,3,1);grid_button(landmark_ai,"Manage Control Set",self.manage_control_set,4,0);grid_button(landmark_ai,"More…",self._show_landmark_ai_more,4,1);self.landmark_predict_batch_button=grid_button(landmark_ai,"Predict Batch...",self.start_ai_predict_batch,5,0);self.landmark_predict_all_button=grid_button(landmark_ai,"Predict All Remaining",self.start_ai_predict_all_remaining,5,1);grid_button(landmark_ai,"Re-predict AI-only...",self.start_ai_repredict_machine_only,6,0);self.landmark_improvement_button=ttk.Button(self.landmark_ai_context,text="New Improvement Batch",command=self.new_improvement_batch);self.landmark_improvement_button.grid(row=6,column=0,columnspan=2,sticky="ew",padx=1,pady=1);self.landmark_improvement_button.grid_remove();self.landmark_train_button=ttk.Button(self.landmark_ai_context,text="Train Landmark Model",command=self.start_landmark_training);self.landmark_train_button.grid(row=7,column=0,columnspan=2,sticky="ew",padx=1,pady=1);self.landmark_train_button.grid_remove()
  editing=section("LANDMARKS");[editing.columnconfigure(index,weight=1) for index in range(3)];grid_button(editing,"Mark missing (M)",self.missing,0,0);grid_button(editing,"Remove (Del)",self.remove,0,1);grid_button(editing,"Clear all…",self.clear_all,0,2)
  review=section("LANDMARK REVIEW");self.landmark_review_context=review;two_columns(review);self.check_landmarks_button=grid_button(review,"Check Landmarks",self.check_landmarks,0,0);grid_button(review,"",lambda:None,0,1,state="disabled").grid_remove();self.previous_review_button=grid_button(review,"Previous Issue",self.previous_review_warning,1,0,state="disabled");self.next_warning_button=grid_button(review,"Next Issue",self.next_review_warning,1,1,state="disabled");self.swap_button=grid_button(review,"Swap 2 Landmarks",self.start_review_swap,2,0,state="disabled");self.undo_swap_button=grid_button(review,"Undo Reassignment",self.undo_review_swap,2,1,state="disabled");self.apply_reassignment_button=grid_button(review,"Apply Suggested Reassignment",self.apply_suggested_reassignment,3,0,state="disabled");self.accept_review_button=grid_button(review,"Accept as Correct",self.accept_review_warning,3,1,state="disabled");self.review_done_button=grid_button(review,"Done",self.finish_review,4,0,state="disabled");self.exit_review_button=grid_button(review,"Exit Review",self.toggle_review,4,1,state="disabled")
  workflow=section("LANDMARK AI WORKFLOW");self.landmark_workflow_context=workflow;self.workflow_instruction=ttk.Label(workflow,text="",wraplength=245,justify="left");self.workflow_instruction.grid(row=0,column=0,columnspan=3,sticky="ew",pady=(0,3));[workflow.columnconfigure(index,weight=1) for index in range(3)];self.workflow_previous_button=grid_button(workflow,"Previous",lambda:self._open_landmark_workflow_item(getattr(self,"_landmark_workflow_index",0)-1),1,0);self.workflow_confirm_button=grid_button(workflow,"Confirm & Next",self.workflow_confirm_next,1,1);self.workflow_exit_button=grid_button(workflow,"Exit Workflow",self.exit_landmark_ai_workflow,1,2);self.workflow_retry_button=ttk.Button(workflow,text="Retry AI",command=self.retry_workflow_prediction);self.workflow_retry_button.grid(row=2,column=0,sticky="ew",padx=1,pady=1);self.workflow_mark_manually_button=ttk.Button(workflow,text="Mark Manually",command=self.mark_workflow_manually);self.workflow_mark_manually_button.grid(row=2,column=1,sticky="ew",padx=1,pady=1);self.ai_worst_next_button=ttk.Button(workflow,text="Next",command=self.ai_worst_next);self.ai_worst_next_button.grid(row=2,column=2,sticky="ew",padx=1,pady=1);self.workflow_retry_button.grid_remove();self.workflow_mark_manually_button.grid_remove();self.ai_worst_next_button.grid_remove()
  image=section("IMAGE");two_columns(image);self.calibrate_button=grid_button(image,"Calibrate samples",lambda:CalibrationWorkflow(self,self.project),0,1);grid_button(image,"Crop / rotation",self.correct_normalization,0,0);grid_button(image,"Source / standardized",self.toggle_source,1,0);self.exclude_button=grid_button(image,"Exclude…",self.exclude_or_restore,1,1)
  measurements=section("MEASUREMENTS");two_columns(measurements);self.measurements_status=ttk.Label(measurements,text="");self.measurements_status.grid(row=0,column=0,columnspan=2,sticky="w");grid_button(measurements,"Measurements…",self.open_measurements,1,0);grid_button(measurements,"Export measurements CSV",self.export_measurements_csv,1,1);self.refresh_measurements_status()
  ai=section("CROP AI");two_columns(ai);self.crop_train_status=ttk.Label(ai,text="",foreground="#606060");self.crop_train_status.grid(row=0,column=0,columnspan=2,sticky="w");self.auto_crop_button=grid_button(ai,"Auto Crop Remaining",self.start_auto_crop_remaining,1,0);grid_button(ai,"Review Crops",lambda:self.start_crop_qc_review(True),1,1);self.crop_train_button=grid_button(ai,"Train Crop Model",self.train_crop_model,2,0);grid_button(ai,"More…",self._show_crop_ai_more,2,1);self.crop_training_batch_button=ttk.Button(ai,text="Crop Training Batch",command=self.start_crop_training_batch);self.rerun_crop_button=ttk.Button(ai,text="Re-run Unreviewed AI Crops",command=self.start_rerun_unreviewed_crops);self.ai_predict_button=ttk.Button(ai,text="AI Predict Batch",command=self.start_ai_predict_batch);self.previous_ai_button=ttk.Button(ai,text="Previous AI",command=self.previous_ai_batch);self.next_ai_button=ttk.Button(ai,text="Next AI",command=self.next_ai_batch)
  self._refresh_landmark_ai_panel();self._set_review_controls();self.refresh_crop_training_status();self._load_last_ai_batch()
 def refresh_measurements_status(self):
  if not hasattr(self,"measurements_status"): return
  rows=[row for row in self.project.catalog_rows() if not row.get("excluded")]
  localities={row.get("locality") or row.get("sample_id") for row in rows}
  calibrated=sum(bool(self.project.locality_calibration(locality)) for locality in localities)
  self.measurements_status.config(text=f"Calibration: {calibrated} / {len(localities)} samples\nMeasurements: {len(active_measurements(self.project))} defined")
 def open_measurements(self):
  MeasurementsWindow(self,self.project,on_saved=self.refresh_measurements_status)
 def export_measurements_csv(self):
  preview=measurement_summary(self.project)
  text=f"Images: {preview['rows']}\nMeasurements: {preview['measurements']}\nCalibrated samples: {preview['calibrated_samples']} / {preview['samples']}\nComplete specimens: {preview['complete']}\nSpecimens with NA: {preview['na']}"
  if not messagebox.askokcancel("Export measurements CSV",text,parent=self): return
  result=export_measurements(self.project)
  messagebox.showinfo("Measurements exported",f"Exported Rows: {result['rows']}\nFile: {result['path']}",parent=self)
  self.refresh_measurements_status()
 def _refresh_landmark_ai_panel(self):
  if not hasattr(self,"landmark_ai_stage"):return
  info=stage_summary(self.project,create_missing=False);self._landmark_ai_info=info
  self.active_model_status.config(text=f"Model: {info['active_model_id'] or 'None'}")
  self.landmark_ai_stage.config(text=f"Workflow: {info['friendly_stage']}")
  self.landmark_ai_progress.config(text=f"Progress: {info['verified']} / {info['total']}")
 def manage_control_set(self):
  """Small persistent-Control-Set dialog; it does not alter training data."""
  dialog=tk.Toplevel(self);dialog.title("Manage Control Set");dialog.transient(self);dialog.resizable(False,False)
  frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True)
  summary=ttk.Label(frame,justify="left");summary.pack(fill="x",pady=(0,8))
  def refresh():
   info=control_set_summary(self.project);summary.config(text=f"Control Set: {info['verified']} / {info['total']} checked\nCurrent image: {Path(self.current()['source_relpath']).name}")
   self._refresh_landmark_ai_panel()
  def add_current():
   try:info,added=add_control_image(self.project,self.current()["image_id"])
   except (KeyError,ValueError) as exc:messagebox.showwarning("Manage Control Set",str(exc),parent=dialog);return
   refresh();messagebox.showinfo("Manage Control Set",("Image added to the permanent Control Set." if added else "This image is already in the Control Set."),parent=dialog)
  def review():dialog.destroy();self.review_control_set()
  ttk.Button(frame,text="Review Control Set",command=review).pack(fill="x",pady=1)
  ttk.Button(frame,text="Add Current Image",command=add_current).pack(fill="x",pady=1)
  ttk.Button(frame,text="Close",command=dialog.destroy).pack(fill="x",pady=(8,0))
  refresh()
 def review_control_set(self):
  self.review_landmark_set("CONTROL_SET")
 def show_review_landmark_sets(self):
  dialog=tk.Toplevel(self);dialog.title("Review Landmark Sets");dialog.transient(self);dialog.resizable(False,False)
  frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);problems_only=tk.BooleanVar(master=dialog,value=True)
  ttk.Label(frame,text="Open saved landmarks for review:").pack(anchor="w",pady=(0,4));ttk.Checkbutton(frame,text="Problems only",variable=problems_only).pack(anchor="w",pady=(0,6))
  for key,label in (("CONTROL_SET","Control Set"),("INITIAL_TRAINING","Initial Training"),("MODEL_IMPROVEMENT","Improvement"),("ALL_CHECKED","All checked images")):
   ttk.Button(frame,text=label,command=lambda value=key:(dialog.destroy(),self.review_landmark_set(value,problems_only.get()))).pack(fill="x",pady=1)
  ttk.Button(frame,text="Cancel",command=dialog.destroy).pack(fill="x",pady=(8,0))
 def _accept_current_landmark_set_warnings(self,image_id):
  warnings=list(getattr(self,"_landmark_set_review_warnings",{}).pop(image_id,()))
  for warning in warnings:self.project.accept_review_warning(image_id,warning)
  self._review_active_ids.clear()
  return len(warnings)
 def _apply_landmark_set_review_warnings(self):
  if not getattr(self,"_landmark_set_review_active",False) or not getattr(self,"images",None):return
  image_id=self.current()["image_id"];warnings=list(getattr(self,"_landmark_set_review_warnings",{}).get(image_id,()))
  self._review_warnings=warnings;self._review_warning_index=0;self._review_active_ids={landmark_id for warning in warnings for landmark_id in review_item_landmark_ids(warning)}
  state=self._load_current_landmark_state()
  if state:self._refresh_landmark_list(state);self._render_signature=None;self.render()
  message="; ".join(warning["message"] for warning in warnings)
  self.review_status.config(text=("LANDMARK REVIEW — "+message) if message else "LANDMARK REVIEW — no current warnings")
 def _start_landmark_set_review_scan(self,ids,problems_only):
  show_completion_notice=bool(self.__dict__.get("_landmark_set_review_completion_notice",False));self._landmark_set_review_completion_notice=False
  self._landmark_set_review_active=True;self._landmark_set_review_ids=frozenset(ids);self._landmark_set_review_warnings={};self._landmark_set_review_problems_only=bool(problems_only);self.review_mode=True;self.review_status.config(text="Checking landmarks…");self._set_review_controls()
  def finish(result):
   warnings={}
   for item in result.get("queue",()):
    if item.get("image_id") in self._landmark_set_review_ids:warnings.setdefault(item["image_id"],[]).append(item)
   self._landmark_set_review_warnings=warnings
   if self._landmark_set_review_problems_only:
    queue=[image_id for image_id in ids if warnings.get(image_id)];self._landmark_workflow_ids=queue;self._landmark_workflow_index=0
    if not queue:
     self._review_active_ids.clear();self._landmark_workflow_active=False;self.review_mode=False;self._set_landmark_workflow_controls();self._set_review_controls();self.review_status.config(text="No suspicious landmarks found");messagebox.showinfo("Review complete",f"No suspicious landmarks found.\nImages checked: {len(ids)}",parent=self);return
    if show_completion_notice:messagebox.showinfo("Landmark check complete",f"Suspicious images found: {len(queue)}.\nReview them now; Confirm & Next moves to the next problem.",parent=self)
    self._open_landmark_workflow_item(0);return
   self._apply_landmark_set_review_warnings()
  def failed(exc):
   log("GLOBAL","landmark_set_review_scan","ERROR",detail=repr(exc));self.review_status.config(text="Landmark review scan failed")
  def work():
   try:result=scan_project(self.project)
   except Exception as exc:
    try:self.after(0,lambda exc=exc:failed(exc))
    except (tk.TclError,RuntimeError):pass
    return
   try:self.after(0,lambda:finish(result))
   except (tk.TclError,RuntimeError):pass
  threading.Thread(target=work,daemon=True,name="landmark-set-review").start()
 def review_landmark_set(self,group,problems_only=True):
  state=control_set_summary(self.project)["state"]
  groups={"CONTROL_SET":("control_image_ids","Control set","Control image"),"INITIAL_TRAINING":("initial_image_ids","Initial training","Training image"),"MODEL_IMPROVEMENT":("improvement_image_ids","Improvement","Improvement image")}
  if group=="ALL_CHECKED":
   ids=[row["image_id"] for row in self.project.catalog_rows() if self.project.annotation_status(row["image_id"])["verified"]];friendly="All checked images";item_label="Checked image";stage="REVIEW_LANDMARK_SETS"
  else:
   key,friendly,item_label=groups[group];ids=list(state[key]);stage=group
  if not ids:messagebox.showinfo("Review Landmark Sets",f"No images are saved for {friendly}.",parent=self);return
  current_id=self.current().get("image_id") if getattr(self,"images",None) else None;position=ids.index(current_id) if current_id in ids else 0
  self._landmark_workflow_active=True;self._landmark_workflow_review_only=True;self._landmark_ai_info={"state":state,"stage":stage,"friendly_stage":friendly,"current_ids":tuple(ids),"verified":sum(bool(self.project.annotation_status(image_id)["verified"]) for image_id in ids),"total":len(ids),"active_model_id":(self.project.active_model("landmark") or {}).get("model_id"),"review_item_label":item_label};self._landmark_workflow_ids=ids;self._landmark_workflow_index=position;self._set_landmark_workflow_controls();
  if "review_status" not in self.__dict__:self._open_landmark_workflow_item(position);return
  self._start_landmark_set_review_scan(ids,problems_only)
  if not problems_only:self._open_landmark_workflow_item(position)
 def new_improvement_batch(self):
  info=stage_summary(self.project,create_missing=False)
  if info["stage"]=="MODEL_IMPROVEMENT" and info["verified"]<info["total"]:
   messagebox.showwarning("Improvement batch unfinished",f"Current batch progress: {info['verified']} / {info['total']} complete. Finish it before starting another batch.",parent=self);return
  if info["stage"] not in {"READY_FOR_FULL_PREDICTION","MODEL_IMPROVEMENT"}:return
  count=simpledialog.askinteger("New Improvement Batch","Number of improvement images:\n\nRecommended: 20",initialvalue=20,minvalue=5,parent=self)
  if count is None:return
  log("GLOBAL","NEW_IMPROVEMENT_CLICK","START",detail=f"count={count}")
  def main_marker(name):
   log("GLOBAL",name,"START")
   timer=Timer(5,lambda:dump_threads("GLOBAL",f"new improvement main-thread step exceeded 5 seconds: {name}"));timer.daemon=True;timer.start();return timer
  timer=main_marker("PROGRESS_TOPLEVEL")
  progress=tk.Toplevel(self);timer.cancel();log("GLOBAL","PROGRESS_TOPLEVEL","END")
  progress.title("Selecting improvement images");progress.transient(self)
  timer=main_marker("PROGRESS_STRINGVAR")
  progress_text=tk.StringVar(master=progress,value="Preparing candidate pool...");timer.cancel();log("GLOBAL","PROGRESS_STRINGVAR","END")
  timer=main_marker("PROGRESS_LABEL")
  ttk.Label(progress,textvariable=progress_text,justify="left",padding=18).pack();timer.cancel();log("GLOBAL","PROGRESS_LABEL","END")
  progress_bar=ttk.Progressbar(progress,mode="indeterminate",length=320);progress_bar.pack(fill="x",padx=18,pady=(0,12));progress_bar.start(12);progress._simm_progressbar=progress_bar;center_child_window(progress)
  timer=main_marker("PROGRESS_RESIZABLE")
  progress.resizable(False,False);timer.cancel();log("GLOBAL","PROGRESS_RESIZABLE","END")
  timer=main_marker("MAIN_STATUS_UPDATE")
  self.annotation_status.config(text="Preparing candidate pool...");timer.cancel();log("GLOBAL","MAIN_STATUS_UPDATE","END")
  timer=main_marker("QUEUE_CREATE")
  events=queue.Queue();timer.cancel();log("GLOBAL","QUEUE_CREATE","END")
  def worker():
   rank_started=threading.Event()
   def trace(marker,*values):
    if marker=="RANK_START":rank_started.set()
    detail=" ".join(str(value) for value in values)
    log("GLOBAL",marker,"END",detail=detail)
   def pre_rank_watchdog():
    if not rank_started.is_set():
     log("GLOBAL","PRE_RANK_STALL","WARNING",detail="no rank start after 30 seconds")
     dump_threads("GLOBAL","improvement selection pre-rank stage exceeded 30 seconds")
   watchdog=Timer(30,pre_rank_watchdog) if threading.Thread.__module__=='threading' else None
   if watchdog:watchdog.daemon=True;watchdog.start()
   def rank_progress(stage,done,total):events.put(("progress",stage,done,total))
   trace("WORKER_START")
   try:
    trace("ACTIVE_MODEL_START");active_model=self.project.active_model_readonly("landmark");trace("ACTIVE_MODEL_END")
    if not active_model:raise BatchError("no active landmark model")
    active=active_model["model_id"]
    blocked=set(info["state"].get("control_image_ids",()))|set(info["state"].get("initial_image_ids",()))|set(info["state"].get("improvement_history_ids",()))|set(info["state"].get("improvement_image_ids",()))
    data,path,_=create_improvement_selection(self.project,active,count=count,seed=int(info["state"]["seed"])+2+len(blocked),excluded_image_ids=blocked,progress_callback=rank_progress,active_model=active_model,diagnostic_callback=trace)
    trace("BATCH_COMMIT_START");begin_improvement(self.project,info["state"],count,selected_ids=[item["image_id"] for item in data["selected_images"]],selection_artifact=str(path.relative_to(self.project.data_root).as_posix()));trace("BATCH_COMMIT_END")
   except BaseException as exc:
    log("GLOBAL","IMPROVEMENT_WORKER_ERROR","ERROR",detail=traceback.format_exc())
    events.put(("error",exc));return
   finally:
    if watchdog:watchdog.cancel()
    trace('WORKER_END')
   events.put(("complete",data,path))
  def failed(exc):
   if progress.winfo_exists():progress.destroy()
   messagebox.showerror("New Improvement Batch",str(exc),parent=self)
  def complete(data,path):
   if progress.winfo_exists():progress.destroy()
   self._refresh_landmark_ai_panel();self._set_landmark_workflow_controls();self.annotation_status.config(text=f"Improvement batch ready: {len(data['selected_images'])}");self.continue_landmark_ai()
  def poll():
   try:
    while True:
     event=events.get_nowait();kind=event[0]
     if kind=="progress":
      _,stage,done,total=event
      if stage=="CANDIDATES":text=f"Preparing candidate pool...\nCandidates: {done}"
      elif stage=="SELECTING":text="Selecting diverse training images..."
      else:text=f"Selecting useful training images...\nScoring candidates: {done} / {total}\nSIMM is checking uncertainty and diversity."
      progress_text.set(text);self.annotation_status.config(text=text.split("\n")[0])
      if stage=="CANDIDATES": set_progress_dialog_progress(progress,0,done)
      elif total: set_progress_dialog_progress(progress,done,total)
     elif kind=="error":failed(event[1]);return
     else:complete(event[1],event[2]);return
   except queue.Empty:
    if progress.winfo_exists():self.after(50,poll)
  timer=main_marker("THREAD_CREATE")
  selection_thread=threading.Thread(target=worker,name="simm-improvement-selection",daemon=True);timer.cancel();log("GLOBAL","THREAD_CREATE","END")
  log("GLOBAL","THREAD_START_CALL","START")
  selection_thread.start()
  log("GLOBAL","THREAD_STARTED","END",detail=f"ident={selection_thread.ident}")
  self.after(50,poll)
 def start_review_ai_worst_first(self):
  count=simpledialog.askinteger("Review AI Worst First","How many images to review?",initialvalue=25,minvalue=1,parent=self)
  if count is None:return
  progress,label=self._show_nonmodal_progress("Review AI Worst First","Finding worst AI predictions...")
  self._ai_worst_selection_worker=True
  def failed(exc):
   self._ai_worst_selection_worker=False;self._close_nonmodal_progress(progress);messagebox.showerror("Review AI Worst First",str(exc),parent=self)
  def finished(items):
   self._ai_worst_selection_worker=False;self._close_nonmodal_progress(progress)
   if not items:messagebox.showinfo("Review AI Worst First","No eligible unreviewed AI predictions found.",parent=self);return
   self._ai_worst_review_active=True;self._ai_worst_review_items=items;self._ai_worst_review_index=0
   self._landmark_workflow_review_only=False;self._landmark_workflow_active=True
   self._landmark_workflow_ids=[item["image_id"] for item in items];self._landmark_workflow_index=0
   self._landmark_ai_info={"stage":"AI_WORST_FIRST","friendly_stage":"AI review","active_model_id":(self.project.active_model_readonly("landmark") or {}).get("model_id"),"verified":0,"total":len(items),"review_item_label":"Worst AI review"}
   self.review_mode=True;self._set_landmark_workflow_controls();self.ai_worst_next_button.grid();self._open_landmark_workflow_item(0)
  def work():
   try:items=select_ai_worst_first(self.project,count)
   except BaseException as exc:
    self.after(0,lambda exc=exc:failed(exc));return
   self.after(0,lambda items=items:finished(items))
  threading.Thread(target=work,daemon=True,name="landmark-ai-worst-selection").start()
 def _apply_ai_worst_review_loaded(self):
  if not self._ai_worst_review_active:return
  item=self._ai_worst_review_items[self._ai_worst_review_index]
  ids=item.get("warning_landmark_ids") or item.get("low_confidence_landmark_ids") or ()
  self._review_active_ids=set(ids);self.review_mode=True
  self.workflow_instruction.config(text=self._workflow_instruction_text())
  self.review_status.config(text=f"AI review: {self._ai_worst_review_index+1} / {len(self._ai_worst_review_items)} — worst first | {item.get('reason','AI review')}")
  self._refresh_landmark_list(self._load_current_landmark_state());self._render_signature=None;self.render()
 def ai_worst_next(self):
  if not self._ai_worst_review_active:return
  self._open_landmark_workflow_item(self._ai_worst_review_index+1)
 def continue_landmark_ai(self):
  info=stage_summary(self.project,create_missing=False)
  if info["stage"] in {"CONTROL_SET","INITIAL_TRAINING","MODEL_IMPROVEMENT"} and not info["current_ids"]:
   recommended={"CONTROL_SET":25,"INITIAL_TRAINING":30,"MODEL_IMPROVEMENT":20}[info["stage"]]
   label={"CONTROL_SET":"Control Set","INITIAL_TRAINING":"Initial Training","MODEL_IMPROVEMENT":"Improvement Batch"}[info["stage"]]
   count=simpledialog.askinteger(label,f"Number of {label.lower()} images:\n\nRecommended: {recommended}",initialvalue=recommended,minvalue=5,parent=self)
   if count is None:return
   try:create_stage(self.project,info["stage"],count)
   except ValueError as exc:messagebox.showwarning(label,str(exc),parent=self);return
   info=stage_summary(self.project,create_missing=False);log("GLOBAL","landmark_workflow_stage_created","END",detail=f"stage={info['stage']} target={count} image_ids_count={len(info['current_ids'])}")
  self._landmark_workflow_review_only=False;self._landmark_ai_info=info;self._refresh_landmark_ai_panel();self._set_landmark_workflow_controls()
  state,image_id,position,restored=workflow_current(self.project,info["state"])
  ids=info["current_ids"]
  if not image_id:
   messagebox.showinfo("Landmark AI",f"{info['friendly_stage']} is ready.",parent=self);return
  self._landmark_workflow_active=True;self._landmark_workflow_ids=list(ids);self._landmark_workflow_index=position;self._set_landmark_workflow_controls()
  log(image_id,"landmark_workflow_loaded","END",detail=f"stage={info['stage']} target={len(ids)} ordered_count={len(ids)} verified_count={info['verified']} current_image_id={image_id} current_position={position+1} restored_draft={restored}")
  self._open_landmark_workflow_item(position)
 def _workflow_instruction_text(self):
  info=self._landmark_ai_info;model=info["active_model_id"]
  if self.__dict__.get("_ai_worst_review_active",False):
   item=self._ai_worst_review_items[self._ai_worst_review_index]
   return f"AI REVIEW — Worst AI review: {self._ai_worst_review_index+1} / {len(self._ai_worst_review_items)}\nReview highlighted AI landmarks, then press Confirm & Next.\nReason: {item.get('reason', 'AI review')}"
  purpose={"CONTROL_SET":"These control images are never used for training.","INITIAL_TRAINING":"These images will be used to adapt and train the model.","MODEL_IMPROVEMENT":"Correct informative AI errors, then confirm the image."}.get(info["stage"],"")
  action="Review or correct landmarks, then press Confirm & Next." if self.__dict__.get("_landmark_workflow_review_only",False) else ("Check the AI landmarks. Correct any mistakes, then press Confirm & Next." if model else "Place all required landmarks manually, then press Confirm & Next.")
  item_label=info.get("review_item_label") or ("Control image" if info["stage"]=="CONTROL_SET" else "Training image" if info["stage"]=="INITIAL_TRAINING" else "Improvement image")
  restored="\nUnfinished annotation restored." if self.project.annotation_draft(self.current()["image_id"]) else ""
  return f"{info['friendly_stage'].upper()} — {item_label}: {getattr(self,'_landmark_workflow_index',0)+1} / {len(getattr(self,'_landmark_workflow_ids',()))}\n{action}\n{purpose}{restored}"
 def _open_landmark_workflow_item(self,index):
  ids=getattr(self,"_landmark_workflow_ids",[])
  if not ids:return
  previous=getattr(self,"_display_image_id",None);self._landmark_workflow_index=index%len(ids);image_id=ids[self._landmark_workflow_index]
  target=next((i for i,row in enumerate(self.images) if row['image_id']==image_id),None)
  if target is None:return
  self._workflow_target_image_id=image_id;self._workflow_prediction_generation+=1
  if self.__dict__.get("_ai_worst_review_active",False): self._ai_worst_review_index=self._landmark_workflow_index
  log(previous or "GLOBAL","landmark_workflow_next_requested","END",detail=f"from_image_id={previous} target_image_id={image_id} target_position={self._landmark_workflow_index+1}")
  self.index=target;self._refresh_visible_photo_rows();self.workflow_instruction.config(text=self._workflow_instruction_text());self.review_status.config(text=f"LANDMARK AI — {self._landmark_ai_info['friendly_stage']} | {self._landmark_workflow_index+1} / {len(ids)}")
  if getattr(self,'_display_image_id',None)==image_id and getattr(self,'standard',None) is not None:
   self._workflow_target_ready(image_id);return
  row=self.images[target];self.open_image(row=row,source=Path(row.get('source_path',row['source_relpath'])),listbox_index=target,user_selection=False)
 def _workflow_draft_requires_restore(self,image_id,state):
  """Only real working annotation or Clear All intent suppresses automatic prediction."""
  draft=self.project.annotation_draft(image_id) or {};manual_rebuild=bool(draft.get("manual_rebuild",False))
  meaningful=bool(state.present_ids) or bool(state.explicitly_missing_ids) or manual_rebuild
  decision="restore_draft" if meaningful else "auto_predict"
  log(image_id,"landmark_workflow_draft_decision","END",detail=f"image_id={image_id} present_count={len(state.present_ids)} explicit_missing_count={len(state.explicitly_missing_ids)} manual_rebuild={manual_rebuild} decision={decision}")
  return meaningful
 def _workflow_target_ready(self,target_image_id):
  displayed=getattr(self,'_display_image_id',None);current=self.current().get('image_id') if getattr(self,'images',None) else None
  if target_image_id!=getattr(self,'_workflow_target_image_id',None) or displayed!=target_image_id or current!=target_image_id or getattr(self,'standard',None) is None:
   log(target_image_id,"landmark_workflow_prediction_stale_discarded","END",detail=f"expected_image_id={target_image_id} actual_image_id={displayed} current_image_id={current} reason=target_not_render_ready");return False
  log(target_image_id,"landmark_workflow_target_ready","END",detail=f"target_image_id={target_image_id} displayed_image_id={displayed}")
  if self.__dict__.get("_landmark_workflow_review_only",False):
   self._apply_landmark_set_review_warnings();return True
  status=self.project.annotation_status(target_image_id)
  if status.get('verified'):return True
  state=self._load_current_landmark_state()
  if self._workflow_draft_requires_restore(target_image_id,state):
   if bool((self.project.annotation_draft(target_image_id) or {}).get('manual_rebuild',False)):self.workflow_retry_button.grid()
   return True
  self._request_workflow_prediction(target_image_id);return True
 def _request_workflow_prediction(self,image_id,force=False):
  model=(self.project.active_model('landmark') or {}).get('model_id')
  if not model:
   self.workflow_retry_button.grid_remove();self.workflow_mark_manually_button.grid_remove();return
  displayed=getattr(self,'_display_image_id',None);current=self.current().get('image_id') if getattr(self,'images',None) else None
  if not force and (image_id!=getattr(self,'_workflow_target_image_id',None) or displayed!=image_id or current!=image_id or getattr(self,'standard',None) is None):
   log(image_id,"landmark_workflow_prediction_stale_discarded","END",detail=f"expected_image_id={image_id} actual_image_id={displayed} current_image_id={current} reason=prediction_requested_before_target_ready");return
  existing=self.project.load_landmarks(image_id)
  if not force and any(row.get('state') not in {'unresolved',None} for row in existing.values()):return
  pending=getattr(self,'_workflow_prediction_inflight_ids',set())
  if image_id in pending:return
  pending.add(image_id);self._workflow_prediction_inflight_ids=pending;generation=getattr(self,'_workflow_prediction_generation',0)
  self.workflow_instruction.config(text=self._workflow_instruction_text()+"\nPreparing AI landmarks…")
  log(image_id,"landmark_workflow_prediction_start","START",detail=f"target_image_id={image_id} model_id={model}")
  def work():
   try:
    _,backend=active_backend(self.project);result=LandmarkAIService(self.project,backend).predict_one(image_id)
   except Exception as exc:
    def failed():
     self._workflow_prediction_inflight_ids.discard(image_id)
     displayed=getattr(self,'_display_image_id',None)
     if image_id!=getattr(self,'_workflow_target_image_id',None) or displayed!=image_id:
      log(image_id,"landmark_workflow_prediction_stale_discarded","END",detail=f"expected_image_id={image_id} actual_image_id={displayed} reason=failed_result_stale");return
     self.workflow_instruction.config(text=self._workflow_instruction_text()+"\nAI prediction failed for this image. You can mark it manually or retry.");self.workflow_retry_button.grid();self.workflow_mark_manually_button.grid()
    self.after(0,failed);return
   def complete():
    self._workflow_prediction_inflight_ids.discard(image_id);displayed=getattr(self,'_display_image_id',None);current=self.current().get('image_id') if getattr(self,'images',None) else None
    log(image_id,"landmark_workflow_prediction_complete","END",detail=f"target_image_id={image_id} predicted_count={result.saved_landmarks} result_image_id={result.image_id}")
    if result.image_id!=image_id or image_id!=getattr(self,'_workflow_target_image_id',None) or displayed!=image_id or current!=image_id or generation!=getattr(self,'_workflow_prediction_generation',0):
     log(image_id,"landmark_workflow_prediction_stale_discarded","END",detail=f"expected_image_id={image_id} actual_image_id={displayed} current_image_id={current} result_image_id={result.image_id} reason=late_result");return
    self.workflow_retry_button.grid_remove();self.workflow_mark_manually_button.grid_remove();self._reload_editable_record_from_project();self._save_workflow_draft();self._render_signature=None;self.sync();present=len(self._load_current_landmark_state().present_ids);log(image_id,"landmark_workflow_prediction_applied","END",detail=f"target_image_id={image_id} present_count={present}");self._log_canvas_event_path("control_set_prediction_rendered")
   self.after(0,complete)
  threading.Thread(target=work,daemon=True,name=f"landmark-workflow-predict-{image_id}").start()
 def retry_workflow_prediction(self):
  image_id=getattr(self,'_workflow_target_image_id',None) or self.current()['image_id'];draft=self.project.annotation_draft(image_id) or {};self.project.save_annotation_draft(image_id,draft.get('workflow_stage'),draft.get('workflow_position'),manual_rebuild=False);log(image_id,'landmark_workflow_retry_ai','END',detail='manual_rebuild=false force=true');self._request_workflow_prediction(image_id,force=True)
 def mark_workflow_manually(self):
  self.workflow_retry_button.grid_remove();self.workflow_mark_manually_button.grid_remove();self.workflow_instruction.config(text=self._workflow_instruction_text())
 def workflow_confirm_next(self):
  result=self._annotation_check_for_current()
  if result.hard:
   messagebox.showwarning("Annotation incomplete","\n".join(f["message"] for f in result.hard),parent=self);self._show_annotation_findings(result.hard,"review required");return
  if result.suspicious:
   text="\n".join(f["message"] for f in result.suspicious)
   accept=not messagebox.askyesno("Annotation check",f"{len(result.suspicious)} landmarks need attention:\n{text}\n\nReview now?\nChoose No to Accept Anyway.",parent=self)
   if not accept:self._show_annotation_findings(result.suspicious,"review recommended");return
   for warning in result.suspicious:self.project.accept_review_warning(self.current()["image_id"],warning)
  state=self._load_current_landmark_state()
  if not state or not state.complete:return
  self.mark_checked();confirmed=self.project.annotation_status(state.image_id)
  if not confirmed.get("verified"):
   excluded=bool(self.current().get("excluded"));log(state.image_id,"landmark_workflow_confirm_failed","WARNING",detail=f"image_id={state.image_id} excluded={excluded} complete={state.complete} verified={confirmed.get('verified')}")
   if excluded:
    self._landmark_ai_info=stage_summary(self.project,create_missing=False);self._landmark_workflow_ids=list(self._landmark_ai_info["current_ids"])
    _,replacement,position,_=workflow_current(self.project)
    if replacement is not None:self._open_landmark_workflow_item(position)
    return
   messagebox.showwarning("Landmark AI","Could not confirm this image; workflow did not advance.",parent=self);return
  self.project.clear_annotation_draft(state.image_id)
  if self.__dict__.get("_ai_worst_review_active",False):
   ids=self._landmark_workflow_ids
   next_index=next((i for i in range(self._landmark_workflow_index+1,len(ids)) if not self.project.annotation_status(ids[i]).get("verified")),None)
   if next_index is None:
    self.exit_landmark_ai_workflow();self.review_status.config(text="AI review complete");messagebox.showinfo("Review AI Worst First","All selected AI predictions were reviewed.",parent=self);return
   self._open_landmark_workflow_item(next_index);return
  if self.__dict__.get("_landmark_workflow_review_only",False):
   ids=self._landmark_workflow_ids
   if self.__dict__.get("_landmark_set_review_problems_only",False):
    next_index=self._landmark_workflow_index;ids=[image_id for image_id in ids if getattr(self,"_landmark_set_review_warnings",{}).get(image_id)];self._landmark_workflow_ids=ids
    if not ids:self._landmark_workflow_active=False;self.review_mode=False;self._set_landmark_workflow_controls();self._set_review_controls();self.review_status.config(text="Review complete");messagebox.showinfo("Review complete","All suspicious landmark cases have been reviewed.",parent=self);return
    self._open_landmark_workflow_item(next_index%len(ids));return
   if ids:self._open_landmark_workflow_item((self._landmark_workflow_index+1)%len(ids))
   return
  self._landmark_ai_info=stage_summary(self.project,create_missing=False);self._landmark_workflow_ids=list(self._landmark_ai_info["current_ids"]);self._refresh_landmark_ai_panel()
  ids=self._landmark_workflow_ids
  if all(self.project.annotation_status(image_id)["verified"] for image_id in ids):
   completed_stage=self._landmark_ai_info["stage"];finished=self._landmark_ai_info["friendly_stage"];self._landmark_workflow_active=False;self._set_landmark_workflow_controls()
   if completed_stage in {"INITIAL_TRAINING","MODEL_IMPROVEMENT"}:
    messagebox.showinfo("Marking complete",f"{len(ids)} images completed.\nNow MorphoLabel will check this batch for suspicious landmarks.",parent=self);self._landmark_set_review_completion_notice=True;self.review_landmark_set(completed_stage,problems_only=True);return
   messagebox.showinfo("Landmark AI",f"{finished.upper()} COMPLETE\n\n{len(ids)} / {len(ids)} verified.\n\nNext step: Continue Marking.",parent=self);return
  current_image_id=state.image_id;previous_position=ids.index(current_image_id) if current_image_id in ids else getattr(self,"_landmark_workflow_index",0)
  next_index=next(((previous_position+offset)%len(ids) for offset in range(1,len(ids)+1) if not self.project.annotation_status(ids[(previous_position+offset)%len(ids)])["verified"]),None)
  if next_index is None:return
  log(current_image_id,"landmark_workflow_advance","END",detail=f"previous_position={previous_position+1} new_position={next_index+1} verified_count={self._landmark_ai_info['verified']}");self._open_landmark_workflow_item(next_index);self._set_landmark_workflow_controls()
 def check_ai_quality(self):
  model=(self.project.active_model('landmark') or {}).get('model_id')
  if not model:messagebox.showinfo("AI Quality","No active landmark model.",parent=self);return
  progress,_=self._show_nonmodal_progress("Checking AI quality on Control Set...","Checking AI quality on Control Set...")
  def work():
   try:result=evaluate_control_set(self.project,model)
   except Exception as exc:
    self.after(0,lambda exc=exc:(self._close_nonmodal_progress(progress),messagebox.showerror("AI Quality",str(exc),parent=self)));return
   metrics=result["aggregate"]
   message=f"AI QUALITY\n\nControl images: {metrics['n_images']}\nScale-independent error:\nMedian: {metrics['median_error_percent']:.2f}% of reference span\nP90: {metrics['p90_error_percent']:.2f}% of reference span\nP95: {metrics['p95_error_percent']:.2f}% of reference span\n\nReference span = distance between the two farthest valid human landmarks in each image."
   self.after(0,lambda:(self._close_nonmodal_progress(progress),report_dialog(self,"AI Quality",message,"Quality metrics available")))
  threading.Thread(target=work,daemon=True,name="landmark-control-quality").start()
 def check_operator_repeatability(self):
  try:run,created=start_or_continue_run(self.project)
  except Exception as exc:messagebox.showinfo("Human Baseline",str(exc),parent=self);return
  def done():
   progress,_=self._show_nonmodal_progress("Human Baseline","Comparing the same 10 Control images with the current model...")
   def work():
    try: report=complete_run(self.project,run["run_id"])
    except Exception as exc:self.after(0,lambda exc=exc:(self._close_nonmodal_progress(progress),messagebox.showerror("Human Baseline",str(exc),parent=self)));return
    h=report["human"]["aggregate"];m=report["model"]["aggregate"];r=report["ratios"]["p90"]
    text=f"HUMAN BASELINE\n\nHuman repeatability     Current model\nMedian   {h.get('median_error_percent',0):.2f}%           {m.get('median_error_percent',0):.2f}%\nP90      {h.get('p90_error_percent',0):.2f}%           {m.get('p90_error_percent',0):.2f}%\nP95      {h.get('p95_error_percent',0):.2f}%           {m.get('p95_error_percent',0):.2f}%\n\nModel / Human P90: {r:.2f}x\n\n{report['grade']}"
    self.after(0,lambda:(self._close_nonmodal_progress(progress),self.show_human_baseline_report(report)))
   threading.Thread(target=work,daemon=True,name="human-baseline-qc").start()
  HumanBaselineWindow(self,self.project,run,done)
 def show_human_baseline_report(self, report, parent=None):
  parent=parent or self;human=report["human"]["aggregate"];model=report["model"]["aggregate"];ratio=report["ratios"].get("p90");dialog=tk.Toplevel(parent);dialog.title("Human Baseline");dialog.transient(parent);frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
  def metric(value):return "Unavailable" if value is None else f"{value:.2f}%"
  ttk.Label(frame,text=f"OVERALL\n\n                    Human     Current model\nMedian             {metric(human.get('median_error_percent')):<10}{metric(model.get('median_error_percent'))}\nP90                {metric(human.get('p90_error_percent')):<10}{metric(model.get('p90_error_percent'))}\nP95                {metric(human.get('p95_error_percent')):<10}{metric(model.get('p95_error_percent'))}\n\nModel / Human P90: {'Unavailable' if ratio is None else f'{ratio:.2f}x'}",justify="left").pack(anchor="w")
  status_label(frame,report.get("grade","Unavailable")).pack(anchor="w",pady=(8,6))
  ttk.Label(frame,text="PER LANDMARK").pack(anchor="w")
  labels={int(row.get("id",row.get("landmark_id"))):(row.get("abbr") or row.get("name") or "") for row in load_schema(self.project.schema_path)};columns=("lm","abbr","human","ai","ratio","status");table=ttk.Treeview(frame,columns=columns,show="headings",height=min(25,max(1,len(report.get("per_landmark",())))))
  for key,label,width in (("lm","LM",55),("abbr","Abbr",80),("human","Human P90",95),("ai","AI P90",90),("ratio","Ratio",80),("status","Status",180)):
   table.heading(key,text=label);table.column(key,width=width,anchor="w")
  rows=sorted(report.get("per_landmark",()),key=lambda row:(row.get("ratio") is None,-(row.get("ratio") or 0),row["landmark_id"]))
  for row in rows:
   level=level_for_status(row.get("status"));table.tag_configure(level,foreground=PALETTE[level]);table.insert("","end",values=(f"LM{row['landmark_id']:02d}",labels.get(int(row["landmark_id"]),""),metric(row.get("human_p90_error_percent")),metric(row.get("model_p90_error_percent")),"Unavailable" if row.get("ratio") is None else f"{row['ratio']:.2f}x",row.get("status","Unavailable")),tags=(level,))
  table.pack(fill="both",expand=True,pady=(0,8))
  run=next((item for item in previous_runs(self.project) if item.get("run_id")==report.get("run_id")),None)
  actions=ttk.Frame(frame);actions.pack(fill="x")
  if run:
   ttk.Button(actions,text="Edit First Marking",command=lambda:self._edit_baseline_first(run,dialog)).pack(side="left",padx=(0,5))
   ttk.Button(actions,text="Edit Second Marking",command=lambda:self._edit_baseline_second(run,dialog)).pack(side="left")
  ttk.Button(frame,text="Close",command=dialog.destroy).pack(fill="x",pady=(8,0))
 def _edit_baseline_second(self,run,dialog):
  dialog.destroy()
  def finished():
   try:report=recompute_completed_run(self.project,run["run_id"]);self.show_human_baseline_report(report)
   except Exception as exc:messagebox.showerror("Human Baseline",str(exc),parent=self)
  HumanBaselineWindow(self,self.project,run,finished,edit_completed=True)
 def _edit_baseline_first(self,run,dialog):
  dialog.destroy();self._baseline_first_edit_run=run
  first_id=run["image_ids"][0];target=next((i for i,row in enumerate(self.images) if row.get("image_id")==first_id),None)
  if target is None:messagebox.showerror("Human Baseline","A fixed baseline image is not available in the editor.",parent=self);return
  self.index=target;self.open_image(row=self.images[target],source=Path(self.images[target].get("source_path",self.images[target]["source_relpath"])),listbox_index=target,user_selection=False)
  messagebox.showinfo("Edit First Marking","The fixed Human Baseline images are open in the normal landmark editor. Correct and check each image; the baseline reference and report are refreshed after each checked image.",parent=self)
 def show_human_baseline_history(self):
  runs=[r for r in previous_runs(self.project) if r.get("status")=="completed" and r.get("report_path")]
  if not runs:messagebox.showinfo("Human Baseline","No completed Human Baseline runs are available yet.",parent=self);return
  dialog=tk.Toplevel(self);dialog.title("Human Baseline — Previous Runs");dialog.transient(self);frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);table=ttk.Treeview(frame,columns=("date","model","human","model_p90","ratio","status"),show="headings",height=min(10,len(runs)))
  for key,label in (("date","Date"),("model","Model"),("human","Human P90"),("model_p90","Model P90"),("ratio","Ratio"),("status","Status")):table.heading(key,text=label);table.column(key,width=120,anchor="w")
  root=self.project.data_root/"ai"/"qc"/"operator"
  for run in reversed(runs):
   try:r=json.loads((root/run["report_path"]).read_text(encoding="utf-8"));h=r["human"]["aggregate"].get("p90_error_percent");m=r["model"]["aggregate"].get("p90_error_percent");q=r["ratios"].get("p90");table.insert("","end",iid=run["run_id"],values=((run.get("completed_at") or run.get("created_at") or "")[:19],run.get("model_id") or "Unavailable",f"{h:.2f}%" if h is not None else "Unavailable",f"{m:.2f}%" if m is not None else "Unavailable",f"{q:.2f}x" if q is not None else "Unavailable",r.get("grade","Unavailable")))
   except (OSError,json.JSONDecodeError,KeyError):pass
  table.pack(fill="both",expand=True)
  def open_report(_=None):
   selected=table.selection()
   if not selected:return
   run=next(r for r in runs if r["run_id"]==selected[0]);r=json.loads((root/run["report_path"]).read_text(encoding="utf-8"));self.show_human_baseline_report(r,dialog)
  table.bind("<Double-1>",open_report);ttk.Button(frame,text="Open Selected Run",command=open_report).pack(fill="x",pady=(8,0));ttk.Button(frame,text="Close",command=dialog.destroy).pack(fill="x",pady=(5,0))

 def _show_nonmodal_progress(self,title,message):
  dialog=tk.Toplevel(self);dialog.title(title);dialog.transient(self);dialog.resizable(True,True)
  label=ttk.Label(dialog,text=message,justify="left",padding=(14,14,14,6));label.pack(fill="both")
  bar=ttk.Progressbar(dialog,mode="indeterminate",length=260);bar.pack(fill="x",padx=14,pady=(0,14));bar.start(12);dialog._simm_progressbar=bar
  center_child_window(dialog)
  return dialog,label
 def _close_nonmodal_progress(self,dialog):
  try:
   if dialog and dialog.winfo_exists():dialog.destroy()
  except tk.TclError:pass
 def start_landmark_training(self):
  if getattr(self,"_landmark_preparing",False): return
  self._landmark_preparing=True; self.landmark_train_button.config(state="disabled")
  progress,label=self._show_nonmodal_progress("Preparing landmark training...","Preparing landmark training...\nChecking training images...\nChecking AI runtime...\nChecking GPU...\nOptimizing batch size for this computer...")
  def prep_update(stage, detail):
   self.after(0,lambda stage=stage,detail=detail: label.config(text=f"{stage}\n{detail}"))
  def work():
   try:
    active=self.project.active_model_readonly("landmark")
    eligible=set(v2_human_final_eligible_image_ids(self.project)); seen=set(model_seen_image_ids(self.project,active["model_id"])) if active else set()
    if not eligible-seen:
     self.after(0,lambda:self._landmark_preparation_no_new(progress)); return
    plan=prepare_landmark_training(self.project, progress_callback=prep_update)
   except BaseException as exc:
    self.after(0,lambda exc=exc:self._landmark_preparation_failed(exc,progress)); return
   self.after(0,lambda:self._landmark_preparation_ready(plan,progress))
  threading.Thread(target=work,daemon=True,name="landmark-training-preparation").start()
 def _landmark_preparation_no_new(self,progress):
  self._close_nonmodal_progress(progress); self._landmark_preparing=False
  if messagebox.askyesno("No new training images","No new human-verified images are available. Training will reuse the same image set. Continue?",parent=self):
   self._start_landmark_preparation()
  else: self.landmark_train_button.config(state="normal")
 def _start_landmark_preparation(self):
  self._landmark_preparing=True; self.landmark_train_button.config(state="disabled")
  progress,label=self._show_nonmodal_progress("Preparing landmark training...","Preparing landmark training...\nChecking training images...\nChecking AI runtime...\nChecking GPU...\nOptimizing batch size for this computer...")
  def prep_update(stage, detail):
   self.after(0,lambda stage=stage,detail=detail: label.config(text=f"{stage}\n{detail}"))
  def work():
   try: plan=prepare_landmark_training(self.project, progress_callback=prep_update)
   except BaseException as exc: self.after(0,lambda exc=exc:self._landmark_preparation_failed(exc,progress)); return
   self.after(0,lambda:self._landmark_preparation_ready(plan,progress))
  threading.Thread(target=work,daemon=True,name="landmark-training-preparation").start()
 def _landmark_preparation_failed(self,exc,progress):
  self._close_nonmodal_progress(progress); self._landmark_preparing=False; self.landmark_train_button.config(state="normal"); messagebox.showerror("AI Training Ready",str(exc),parent=self)
 def _landmark_preparation_ready(self,plan,progress):
  self._close_nonmodal_progress(progress); self._landmark_preparing=False; self._show_landmark_training_settings(plan)
 def _show_landmark_training_settings(self,plan):
  dialog=tk.Toplevel(self);dialog.title("AI Training Ready");dialog.transient(self);dialog.grab_set();dialog.resizable(False,False)
  settings=plan.training_settings;hardware=settings["hardware"];gpu=hardware.get("gpu_model") or "CPU";vram="Unknown" if hardware.get("gpu_vram_mib") is None else f"{hardware['gpu_vram_mib']/1024:.0f} GB";device="CUDA" if str(settings["device"]).startswith("cuda") else "CPU"
  batch=tk.StringVar(master=dialog,value="Auto (recommended)");epochs=tk.StringVar(master=dialog,value="210 (recommended)");photo=tk.BooleanVar(master=dialog,value=False)
  ttk.Label(dialog,text=f"Training images: {len(plan.image_ids)}\nCurrent model: {plan.parent_model_id}\nNew model ID: {plan.model_id}\n\nInput resolution: {settings.get('input_size',getattr(getattr(plan,'spec',None),'input_size','current model resolution'))} (change via Optimize Resolution)\nHardware: {gpu}, {vram} VRAM\nDevice: {device}",justify="left",padding=14).pack(fill="both")
  form=ttk.Frame(dialog,padding=(14,0,14,8));form.pack(fill="x");form.columnconfigure(1,weight=1)
  ttk.Label(form,text="Batch size:").grid(row=0,column=0,sticky="w");ttk.Combobox(form,textvariable=batch,values=("Auto (recommended)","1","2","4","8"),state="readonly").grid(row=0,column=1,sticky="ew",padx=6)
  ttk.Label(form,text="Epochs:").grid(row=1,column=0,sticky="w");ttk.Combobox(form,textvariable=epochs,values=("100","150","210 (recommended)","300"),state="readonly").grid(row=1,column=1,sticky="ew",padx=6)
  ttk.Checkbutton(form,text="Experimental photometric augmentation (not recommended; prior result was mixed)",variable=photo).grid(row=2,column=0,columnspan=2,sticky="w",pady=(4,0))
  actions=ttk.Frame(dialog,padding=(14,0,14,14));actions.pack(fill="x")
  def start():
   selected_batch=None if batch.get().startswith("Auto") else int(batch.get());selected_epochs=210 if epochs.get().startswith("210") else int(epochs.get());settings["max_epochs"]=selected_epochs;settings["photometric_augmentation"]=photo.get()
   if selected_batch is not None:settings["batch_size"]=selected_batch
   dialog.destroy();self.landmark_train_button.config(state="disabled");self._landmark_training_progress,self._landmark_training_progress_label=self._show_nonmodal_progress("Training landmark model...","Training landmark model...\nPlease wait. MorphoLabel is training the model.");self._start_landmark_training_progress_poll(plan);self._run_landmark_training_worker(plan)
  ttk.Button(actions,text="Start Training",command=start).pack(side="left");ttk.Button(actions,text="Cancel",command=dialog.destroy).pack(side="right")
 def _start_landmark_training_progress_poll(self,plan):
  self._landmark_training_polling=True;self._landmark_training_started_at=time.monotonic();self._landmark_training_last_output_at=self._landmark_training_started_at;self._landmark_training_log_offset=0;self._landmark_training_progress_state={}
  self._landmark_training_log_path=Path(self.project.data_root)/"ai"/"models"/plan.model_id/"training.log"
  self._poll_landmark_training_progress(plan)
 def _poll_landmark_training_progress(self,plan):
  if not getattr(self,"_landmark_training_polling",False):return
  now=time.monotonic();path=getattr(self,"_landmark_training_log_path",None);new_lines=[]
  try:
   if path and path.is_file():
    with path.open("r",encoding="utf-8",errors="replace") as handle:
     handle.seek(getattr(self,"_landmark_training_log_offset",0));new_lines=handle.readlines();self._landmark_training_log_offset=handle.tell()
  except OSError:pass
  if new_lines:
   self._landmark_training_last_output_at=now
   for line in new_lines:
    parsed=parse_training_progress_line(line)
    if parsed:self._landmark_training_progress_state=parsed
  progress=getattr(self,"_landmark_training_progress",None);label=getattr(self,"_landmark_training_progress_label",None)
  if label is not None and progress is not None:
   elapsed=int(now-getattr(self,"_landmark_training_started_at",now));last=int(now-getattr(self,"_landmark_training_last_output_at",now));state=getattr(self,"_landmark_training_progress_state",{});epoch=state.get("epoch","?");batch=state.get("batch","?");batches=state.get("batches","?");settings=getattr(plan,"training_settings",{});device=str(settings.get("device","CUDA")).upper()
   warning="\nNo training output for 60 s — training may be waiting or stalled." if last>=60 else ""
   try:label.config(text=f"Training landmark model...\\nEpoch: {epoch} / {settings.get('max_epochs',210)}\\nBatch: {batch} / {batches}\\nElapsed: {elapsed//60:02d}:{elapsed%60:02d}\\nDevice: {device}\\nLast update: {last} sec ago{warning}"); (set_progress_dialog_progress(progress,(epoch-1)*batches+batch,int(settings.get("max_epochs",210))*batches) if isinstance(epoch,int) and isinstance(batch,int) and isinstance(batches,int) else None)
   except tk.TclError:return
  try:self.after(500,lambda:self._poll_landmark_training_progress(plan))
  except (tk.TclError,RuntimeError):pass
 def _run_landmark_training_worker(self,plan):
  def work():
   def stage(name,current,total):
    def update():
     label=getattr(self,"_landmark_training_progress_label",None)
     if label is not None: label.config(text=(f"Checking saved models: {current} / {total}" if name=="VALIDATING CHECKPOINTS" else "Best epoch selected.\nCreating final EMA model..." if name=="CREATING FINAL EMA CHECKPOINT" else "Registering model..." if name=="REGISTERING MODEL" else name))
    self.after(0,update)
   try:result=run_landmark_training(self.project,plan,progress_callback=stage);self.after(0,lambda:self._landmark_training_complete(plan,result))
   except Exception as exc:self.after(0,lambda exc=exc:self._landmark_training_failed(exc))
  threading.Thread(target=work,daemon=True,name="landmark-model-training").start()
 def _landmark_training_failed(self,exc):
  self._landmark_training_polling=False
  self._close_nonmodal_progress(getattr(self,"_landmark_training_progress",None));self.landmark_train_button.config(state="normal");messagebox.showerror("Landmark Training",str(exc),parent=self)
 def _landmark_training_complete(self,plan,result):
  self._landmark_training_polling=False
  self.landmark_train_button.config(state="normal")
  progress=getattr(self,"_landmark_training_progress",None);label=getattr(self,"_landmark_training_progress_label",None)
  if progress is None or not progress.winfo_exists():progress,label=self._show_nonmodal_progress("Training landmark model...","Training complete.\nEvaluating old and new models on 25 Control Set images...")
  else:progress.title("Training complete");label.config(text="Training complete.\nEvaluating old and new models on 25 Control Set images...")
  def work():
   try:comparison=compare_control_models(self.project,plan.parent_model_id,plan.model_id)
   except Exception as exc:comparison={"error":str(exc)}
   human_report=latest_completed_report(self.project);human_comparison=None
   if human_report:
    try:
     ids=human_report["image_ids"];previous=evaluate_control_set(self.project,plan.parent_model_id,image_ids=ids);new=evaluate_control_set(self.project,plan.model_id,image_ids=ids);human_comparison={"report":human_report,"previous":comparison_for_model(human_report,previous),"new":comparison_for_model(human_report,new),"landmarks":landmark_model_rows(human_report,previous,new)}
    except Exception as exc:human_comparison={"error":str(exc),"report":human_report}
   self.after(0,lambda:(self._close_nonmodal_progress(progress),self._show_landmark_training_complete(plan,result,comparison,human_comparison)))
  threading.Thread(target=work,daemon=True,name="landmark-control-evaluation").start()
 def _show_human_landmarks(self, rows, schema, parent):
  labels={int(row.get("id",row.get("landmark_id"))):(row.get("abbr") or row.get("name") or "") for row in schema};dialog=tk.Toplevel(parent);dialog.title("Landmarks vs Human");dialog.transient(parent);frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True)
  columns=("lm","abbr","human","previous","new","ratio","change","status");table=ttk.Treeview(frame,columns=columns,show="headings",height=min(25,max(1,len(rows))))
  for key,label,width in (("lm","LM",55),("abbr","Abbr",80),("human","Human P90",95),("previous","Previous P90",105),("new","New P90",95),("ratio","New/Human",95),("change","Change",80),("status","Status",180)):
   table.heading(key,text=label);table.column(key,width=width,anchor="w")
  def value(number,suffix="%"):
   return "Unavailable" if number is None else f"{number:.2f}{suffix}"
  ordered=sorted(rows,key=lambda row:(row.get("new_human_ratio") is None,-(row.get("new_human_ratio") or 0),-abs(row.get("change_percent") or 0),row["landmark_id"]))
  for row in ordered:
   level=level_for_status(row["status"]);table.tag_configure(level,foreground=PALETTE[level]);table.insert("","end",values=(f"LM{row['landmark_id']:02d}",labels.get(row["landmark_id"],""),value(row.get("human_p90_error_percent")),value(row.get("previous_p90_error_percent")),value(row.get("new_p90_error_percent")),value(row.get("new_human_ratio"),"x"),"Unavailable" if row.get("change_percent") is None else f"{row['change_percent']:+.1f}%",row["status"]),tags=(level,))
  table.pack(fill="both",expand=True);ttk.Button(frame,text="Close",command=dialog.destroy).pack(fill="x",pady=(8,0))
 def _show_landmark_training_complete(self,plan,result,comparison=None,human_comparison=None):
  self.landmark_train_button.config(state="normal");metrics=validation_metrics(result);quality_profile=stored_control_landmark_quality_profile(self.project,plan.model_id);persistent=stable_weak_landmark_profile(self.project,plan.model_id) or {};quality_text=format_landmark_quality_summary(quality_profile,persistent.get("weak_landmark_ids",()))
  dialog=tk.Toplevel(self);dialog.title("Training Complete");dialog.transient(self);dialog.grab_set();dialog.resizable(False,False)
  internal_validation_text=format_internal_validation(metrics);control_text="\n\nControl Set comparison unavailable."
  if comparison and not comparison.get("error"):
   def control_value(key):
    value=comparison["metrics"][key];delta=value["delta_percent"];suffix="n/a" if delta is None else f"{delta:+.1f}%";return f"{value['previous']:.3f} -> {value['new']:.3f} ({suffix})"
   control_text=f"\n\nControl Set scale-independent error — Previous -> New\nMedian: {control_value('median_error_percent')}% of reference span\nP90: {control_value('p90_error_percent')}% of reference span\nP95: {control_value('p95_error_percent')}% of reference span\nResult: {comparison['result']}"
  elif comparison:control_text=f"\n\nControl Set comparison unavailable: {comparison['error']}"
  human_text="\n\nHuman baseline: Not measured yet";human_status=None;landmark_rows=[]
  if human_comparison and not human_comparison.get("error"):
   report=human_comparison["report"];human=report["human"]["aggregate"];previous=human_comparison["previous"]["model"]["aggregate"];new=human_comparison["new"]["model"]["aggregate"];previous_ratio=human_comparison["previous"]["ratios"]["p90"];new_ratio=human_comparison["new"]["ratios"]["p90"];human_status=human_comparison["new"]["grade"];landmark_rows=human_comparison.get("landmarks",[])
   def metric(value):return "Unavailable" if value is None else f"{value:.2f}%"
   def ratio(value):return "Unavailable" if value is None else f"{value:.2f}x"
   human_text=f"\n\nHUMAN BASELINE COMPARISON\n                 Human     Previous     New\nMedian           {metric(human.get('median_error_percent')):<9}{metric(previous.get('median_error_percent')):<13}{metric(new.get('median_error_percent'))}\nP90              {metric(human.get('p90_error_percent')):<9}{metric(previous.get('p90_error_percent')):<13}{metric(new.get('p90_error_percent'))}\nP95              {metric(human.get('p95_error_percent')):<9}{metric(previous.get('p95_error_percent')):<13}{metric(new.get('p95_error_percent'))}\n\nPrevious / Human P90: {ratio(previous_ratio)} | {human_comparison['previous']['grade']}\nNew / Human P90:      {ratio(new_ratio)} | {human_status}\n\nNEW MODEL VS HUMAN\n{ratio(new_ratio)} human repeatability\n{human_status}"
   labels={int(row.get("id",row.get("landmark_id"))):(row.get("abbr") or row.get("name") or "") for row in load_schema(self.project.schema_path)}
   top=sorted(landmark_rows,key=lambda row:(row.get("new_human_ratio") is None,-(row.get("new_human_ratio") or 0),-abs(row.get("change_percent") or 0),row["landmark_id"]))[:5]
   human_text+="\n\nLANDMARKS VS HUMAN\nLM | Abbr | Human P90 | Previous P90 | New P90 | New/Human | Change | Status"
   for row in top:
    change="Unavailable" if row.get("change_percent") is None else f"{row['change_percent']:+.1f}%"
    human_text+=f"\nLM{row['landmark_id']:02d} | {labels.get(row['landmark_id'],'')} | {metric(row.get('human_p90_error_percent'))} | {metric(row.get('previous_p90_error_percent'))} | {metric(row.get('new_p90_error_percent'))} | {ratio(row.get('new_human_ratio'))} | {change} | {row['status']}"
  elif human_comparison and human_comparison.get("report"):human_text=f"\n\nHuman baseline comparison unavailable: {human_comparison.get('error','Unavailable')}"
  ttk.Label(dialog,text=f"Previous model:\n{plan.parent_model_id}\n\nNew model:\n{plan.model_id}\n\nTraining images: {len(plan.image_ids)}\n\n{internal_validation_text}"+control_text+f"\n\n{quality_text}"+human_text,justify="left",padding=14).pack(fill="both")
  status_label(dialog,comparison.get("result","Mixed") if comparison else "Mixed").pack(padx=14,anchor="w")
  if human_status:status_label(dialog,human_status).pack(padx=14,anchor="w")
  actions=ttk.Frame(dialog,padding=(14,0,14,14));actions.pack(fill="x")
  if landmark_rows:ttk.Button(actions,text="View All Landmarks",command=lambda:self._show_human_landmarks(landmark_rows,load_schema(self.project.schema_path),dialog)).pack(side="left")
  def activate():
   try:activate_landmark_model(self.project,plan.model_id)
   except Exception as exc:messagebox.showerror("Activate New Model",str(exc),parent=dialog);return
   quality_error=None
   try:
    comparison_new=comparison.get("new") if comparison and not comparison.get("error") else None
    if comparison_new and comparison_new.get("model_id")==plan.model_id:
     persist_control_landmark_quality_profile(self.project,comparison_new,activated=True)
    else:
     control_landmark_quality_profile(self.project,plan.model_id,recalculate=True)
   except Exception as exc:
    quality_error=exc
    log(plan.model_id,"landmark_quality_profile_persist","ERROR",detail=str(exc))
   dialog.destroy();self._refresh_landmark_ai_panel();self._set_landmark_workflow_controls()
   if quality_error:messagebox.showwarning("Training Complete",f"Active landmark model: {plan.model_id}\nLandmark Quality profile unavailable: {quality_error}",parent=self)
   else:messagebox.showinfo("Training Complete",f"Active landmark model: {plan.model_id}",parent=self)
  ttk.Button(actions,text="Activate New Model",command=activate).pack(side="left",padx=(8,0));ttk.Button(actions,text="Keep Previous Model",command=dialog.destroy).pack(side="right")
 def show_ai_training_status(self):
  messagebox.showinfo("AI Training Status",format_training_status(training_status(self.project)),parent=self)
 def show_ai_hardware(self):
  messagebox.showinfo("AI Hardware",format_hardware_profile(),parent=self)

 def create_crop_holdout(self):
  if self.project.crop_holdout_id():messagebox.showinfo("Crop Holdout",f"Crop holdout: {len(self.project.crop_holdout_images())} images",parent=self);return
  count=simpledialog.askinteger("Create Crop Holdout","Number of images",initialvalue=50,minvalue=1,parent=self)
  if count is None:return
  holdout_id,ids=self.project.create_crop_holdout(count);log("GLOBAL","crop_holdout_created","END",detail=f"holdout_id={holdout_id} holdout_count={len(ids)} image_ids={list(ids)}");messagebox.showinfo("Crop Holdout",f"Crop holdout: {len(ids)} images",parent=self)
 def review_crop_holdout(self):
  holdout=self.project.crop_holdout_id()
  if not holdout:messagebox.showwarning("Crop Holdout","Create Crop Holdout first.",parent=self);return
  ids=[r['image_id'] for r in self.project.crop_holdout_images(holdout) if not self.project.crop_holdout_reference(r['image_id'],holdout)]
  if not ids:messagebox.showinfo("Crop Holdout","All holdout references are ready.",parent=self);return
  self._holdout_review_id=holdout;self._crop_training_queue=list(ids);self._crop_training_positions={v:i+1 for i,v in enumerate(ids)};self._crop_training_total=len(ids);self._crop_training_summary={"selected":len(ids),"prepared_ids":list(ids),"skipped":[]};self._crop_batch_diagnostics=None;self._open_next_crop_training()
 def evaluate_crop_holdout(self):
  try:r=evaluate_crop_model(self.project);prior=previous_crop_evaluation(self.project,r['model_id']);cmp=compare_crop_evaluation(r,prior);worst=sorted((x for x in r['images'] if x['iou'] is not None),key=lambda x:x['iou'])[:10]
  except Exception as exc:messagebox.showerror("Evaluate Crop Model",str(exc),parent=self);return
  text=f"Model: {r['model_id']}\nEvaluated: {r['n_evaluated']} | Failures: {r['failures']}\nMedian IoU: {r['median_iou']:.3f}\nMean IoU: {r['mean_iou']:.3f}\nIoU ≥ 0.90: {r['iou90_pct']:.1f}%\nQC BAD: {r['qc_bad_pct']:.1f}%\nAccept proxy (IoU ≥ 0.90): {r['accept_proxy_pct']:.1f}%"
  if cmp:text+=f"\n\nCompared with {cmp['previous_model_id']}: {cmp['conclusion']} (median IoU {cmp['median_iou_delta']:+.3f})"
  if worst:text+="\n\nWorst images:\n"+"\n".join(f"{x['original_name']}: {x['iou']:.3f} ({x['qc']})" for x in worst)
  report_dialog(self,"Crop Model Evaluation",text,(cmp or {}).get("conclusion","No material change"))

 def _start_auto_crops(self,rerun):
  try:ids,protected=crop_auto_candidates(self.project,rerun=rerun)
  except Exception as exc:messagebox.showerror("Crop AI",str(exc),parent=self);return
  title="Re-run Unreviewed AI Crops" if rerun else "Auto Crop Remaining"
  if not ids:messagebox.showinfo(title,"No eligible images. Human-reviewed crops are protected.",parent=self);return
  if not messagebox.askokcancel(title,f"Active model: {current_label()}\nEligible images: {len(ids)}\nHuman-protected crops: {protected}",parent=self):return
  dialog=tk.Toplevel(self);dialog.title(title);dialog.transient(self);text=tk.StringVar(master=dialog,value=f"Processed 0 / {len(ids)}")
  ttk.Label(dialog,textvariable=text,padding=14).pack();bar=ttk.Progressbar(dialog,mode="determinate",maximum=max(1,len(ids)));bar.pack(fill="x",padx=14,pady=(0,8));dialog._simm_progressbar=bar;center_child_window(dialog);cancel=threading.Event();ttk.Button(dialog,text="Cancel",command=cancel.set).pack(pady=(0,12))
  events=queue.Queue()
  def progress(i,n,_id,_result):events.put(("progress",i,n))
  def worker():
   try:events.put(("done",process_auto_crops(self.project,rerun=rerun,cancel=cancel,progress=progress)))
   except Exception as exc:events.put(("error",exc))
  threading.Thread(target=worker,daemon=True,name="crop-auto").start()
  def poll():
   try:
    while True:
     kind,*data=events.get_nowait()
     if kind=="progress":text.set(f"Processed {data[0]} / {data[1]}");set_progress_dialog_progress(dialog,data[0],data[1])
     elif kind=="done":
      dialog.destroy();r=data[0];messagebox.showinfo(title,f"Success: {r['success']}\nFailed: {r['failed']}\nSkipped: {r['skipped']}\nCancelled: {r['cancelled']}",parent=self);return
     else:dialog.destroy();messagebox.showerror(title,str(data[0]),parent=self);return
   except queue.Empty:self.after(60,poll)
  poll()
 def start_auto_crop_remaining(self):self._start_auto_crops(False)
 def start_rerun_unreviewed_crops(self):self._start_auto_crops(True)
 def start_crop_qc_review(self,include_ok=False):
  ids=self.project.crop_review_candidates(include_ok=include_ok)
  if not ids:messagebox.showinfo("Review Crops","No AI crop proposals require review.",parent=self);return
  self._crop_training_queue=list(ids);self._crop_training_positions={v:i+1 for i,v in enumerate(ids)};self._crop_training_total=len(ids);self._crop_training_summary={"selected":len(ids),"prepared_ids":list(ids),"skipped":[]};self._crop_batch_diagnostics=None;self._open_next_crop_training()

 def start_crop_training_batch(self):
  if self._crop_batch_preparing:return
  count=simpledialog.askinteger("Crop Training Batch","Number of images",initialvalue=20,minvalue=1,parent=self)
  if count is None:return
  try:
   if not self.winfo_exists():return
   dialog=tk.Toplevel(self)
  except tk.TclError:return
  dialog.title("Crop Training Batch");dialog.transient(self);dialog.resizable(False,False)
  progress_text=tk.StringVar(master=dialog,value="Selecting images...")
  ttk.Label(dialog,text="Preparing crop training batch...",padding=(16,12,16,3)).pack();bar=ttk.Progressbar(dialog,mode="determinate",length=320);bar.pack(fill="x",padx=16,pady=(0,4));dialog._simm_progressbar=bar;center_child_window(dialog);ttk.Label(dialog,textvariable=progress_text,padding=(16,3,16,12)).pack();dialog.update_idletasks()
  try:data,_=create_crop_training_batch(self.project,count)
  except ValueError as exc:
   dialog.destroy();messagebox.showwarning("Crop Training Batch",str(exc),parent=self);return
  rows=tuple(data['selected_images'])
  if not rows:
   dialog.destroy();messagebox.showinfo("Crop Training Batch","No crop-editable images are currently available.",parent=self);return
  by_id={row['image_id']:row for row in self.project.catalog_rows()};selected_rows=[by_id[item['image_id']] for item in rows if item['image_id'] in by_id]
  progress_text.set(f"Preparing: 0 / {len(selected_rows)} images")
  self._crop_training_batch_id=data["batch_id"];self._crop_training_positions={row["image_id"]:index for index,row in enumerate(selected_rows,1)};self._crop_training_total=len(selected_rows);self._crop_batch_completed=False
  self._crop_batch_diagnostics=CropBatchDiagnostics(data["batch_id"],requested_count=count,selected_rows=selected_rows,active_model_id=current_label())
  self._crop_batch_diagnostics.begin("crop_batch_preparation",detail=f"selected_count={len(selected_rows)}")
  self._crop_batch_preparing=True;self.crop_training_batch_button.config(state="disabled")
  events=queue.Queue()
  def progress(index,total,_image_id,_reason):events.put(("progress",index,total))
  def worker():
   try:events.put(("complete",prepare_crop_training_images(self.project,selected_rows,progress=progress,diagnostics=self._crop_batch_diagnostics)))
   except Exception as exc:
    self._crop_batch_diagnostics.failure("crop_batch_preparation",exc);events.put(("error",str(exc)))
  threading.Thread(target=worker,daemon=True,name="crop-training-batch-prepare").start()
  self._poll_crop_training_preparation(dialog,progress_text,events,count)
 def _poll_crop_training_preparation(self,dialog,progress_text,events,requested):
  try:
   while True:
    event=events.get_nowait()
    if event[0]=="progress":progress_text.set(f"Preparing: {event[1]} / {event[2]} images");set_progress_dialog_progress(dialog,event[1],event[2])
    elif event[0]=="complete":
     progress_text.set("Opening crop editor...");dialog.update_idletasks();return self._finish_crop_training_preparation(dialog,event[1],requested)
    else:
     self._crop_batch_preparing=False;self.crop_training_batch_button.config(state="normal")
     if self._crop_batch_diagnostics:self._crop_batch_diagnostics.event("crop_batch_preparation","ERROR",detail=event[1]);self._crop_batch_diagnostics.close()
     dialog.destroy();messagebox.showerror("Crop Training Batch",event[1],parent=self);return
  except queue.Empty:pass
  try:self.after(40,lambda:self._poll_crop_training_preparation(dialog,progress_text,events,requested))
  except tk.TclError:pass
 def _finish_crop_training_preparation(self,dialog,summary,requested):
  self._crop_batch_preparing=False;self.crop_training_batch_button.config(state="normal")
  if self._crop_batch_diagnostics:
   details=f"selected={summary['selected']} prepared={len(summary['prepared_ids'])} skipped={len(summary['skipped'])} proposal_failures={len(summary.get('proposal_failures',()))}"
   self._crop_batch_diagnostics.end("crop_batch_preparation",detail=details);self._crop_batch_diagnostics.event("crop_batch_preparation_complete","END",detail=details)
  try:dialog.destroy()
  except tk.TclError:pass
  self._crop_training_summary=summary;self._crop_training_queue=list(summary['prepared_ids'])
  if self._crop_batch_diagnostics:
   self._crop_batch_diagnostics.event("crop_batch_editor_sequence_start","START",detail=f"prepared_count={len(self._crop_training_queue)}");self._crop_batch_diagnostics.event("crop_batch_review_start","START",detail=f"prepared_count={len(self._crop_training_queue)}")
  # Do not show a modal summary while any crop editor is open.  The only
  # batch summary is shown after the last editor has fully closed.
  self._open_next_crop_training()
 def _show_crop_training_batch_summary(self):
  summary=getattr(self,"_crop_training_summary",None)
  if not summary:return
  self._crop_training_summary=None
  messagebox.showinfo("Crop Training Batch",f"Selected: {summary['selected']}\nPrepared: {len(summary['prepared_ids'])}\nSkipped: {len(summary['skipped'])}",parent=self)
 def _crop_training_editor_finished(self,image_id):
  # Called after the editor destruction callback; no editor/grab remains.
  if getattr(self,"_holdout_review_id",None) and getattr(self._crop_training_editor,"_applied",False):
   record=self.project.crop_record(image_id)
   if record and record.get("crop_json"):
    self.project.save_crop_holdout_reference(image_id,record["crop_json"],self._holdout_review_id);log(image_id,"crop_holdout_reference_saved","END",detail=f"holdout_id={self._holdout_review_id}")
  self._crop_training_editor=None
  diagnostics=getattr(self,"_crop_batch_diagnostics",None)
  if diagnostics:diagnostics.event("crop_batch_next_image_requested","END",image_id=image_id,detail="previous_editor_closed")
  self.after_idle(self._open_next_crop_training)
 def _open_next_crop_training(self):
  diagnostics=getattr(self,"_crop_batch_diagnostics",None)
  editor=getattr(self,"_crop_training_editor",None)
  if editor is not None:
   try:
    if editor.winfo_exists():
     if diagnostics:diagnostics.event("crop_batch_editor_overlap_blocked","WARNING",detail="existing_editor_still_open")
     return
   except tk.TclError:pass
   self._crop_training_editor=None
  if not getattr(self,'_crop_training_queue',[]):
   if diagnostics and not self._crop_batch_completed:
    self._crop_batch_completed=True;diagnostics.event("crop_batch_complete","END",detail="all_prepared_editors_completed");diagnostics.close()
   self._show_crop_training_batch_summary()
   if getattr(self,"_holdout_review_id",None):self._holdout_review_id=None
   return
  image_id=self._crop_training_queue.pop(0);batch_index=getattr(self,"_crop_training_positions",{}).get(image_id);batch_total=getattr(self,"_crop_training_total",None)
  if diagnostics:diagnostics.event("crop_batch_next_image_requested","START",image_id=image_id,batch_index=batch_index,batch_total=batch_total,detail=f"next_image_id={image_id}")
  if diagnostics:diagnostics.begin("crop_batch_next_image_load",image_id=image_id,batch_index=batch_index,batch_total=batch_total)
  target=next((i for i,r in enumerate(self.images) if r['image_id']==image_id),None)
  if target is None:
   if diagnostics:diagnostics.end("crop_batch_next_image_load",image_id=image_id,batch_index=batch_index,batch_total=batch_total,detail="result=image_not_in_editor_catalog")
   return self._open_next_crop_training()
  self.index=target;row=self.images[target];source=Path(row.get('source_path',row['source_relpath']))
  if diagnostics:
   diagnostics.end("crop_batch_next_image_load",image_id=image_id,path=str(source),batch_index=batch_index,batch_total=batch_total,detail="result=loaded")
   diagnostics.event("crop_batch_next_image_requested","END",image_id=image_id,path=str(source),batch_index=batch_index,batch_total=batch_total)
   diagnostics.event("crop_batch_editor_open_requested","START",image_id=image_id,path=str(source),batch_index=batch_index,batch_total=batch_total)
   diagnostics.begin("crop_batch_editor_open",image_id=image_id,path=str(source),batch_index=batch_index,batch_total=batch_total,detail="editor_open_requested")
  from .crop_editor_async_v2 import AsyncCropEditorV2
  self._crop_training_editor=AsyncCropEditorV2(self,source,lambda:self._crop_training_editor_finished(image_id),project=self.project,image_id_value=image_id,batch_diagnostics=diagnostics,batch_index=batch_index,batch_total=batch_total)
 def refresh_crop_training_status(self):
  self.crop_train_status.config(text=f"Crop model: {current_label()} | examples: {correction_count()}")

 def _restore_splitter(self):
  if not self.project:return
  position=self.project.get_ui_state("photo_landmark_sash")
  if position is not None:self.after_idle(lambda:self._place_splitter(position))
 def _place_splitter(self,position):
  try:self.left_split.sash_place(0,0,max(140,int(position)))
  except tk.TclError:pass
 def _save_splitter(self,_event=None):
  if self.project:
   try:self.project.set_ui_state("photo_landmark_sash",self.left_split.sash_coord(0)[1])
   except tk.TclError:pass
 def _schedule_results_sync(self):
  if not self.project:return
  if self._results_after_id is not None:self.after_cancel(self._results_after_id)
  self._results_after_id=self.after(1000,self._flush_results_sync)
 def _flush_results_sync(self):
  self._results_after_id=None
  if self.project:self.project.sync_results()
 def _close_project(self):
  self._save_splitter();self._flush_results_sync();self.destroy()

 def _row_data(self,index,row):
  return {"number":str(index+1),"cal":"C" if row.get("calibrated") else "","text":f"{row.get('locality',row['sample_id'])} | {Path(row['source_relpath']).name} ({row.get('index_in_locality',1)} | {row.get('total_in_locality',1)})","status":row.get("status_color","red")}

 def _reload_editable_record_from_project(self):
  """Refresh the one editable record from canonical rows after AI writes."""
  if not self.project or not getattr(self,"images",None):return
  self.record=load_record(self.current(),self.profile.profile_id,self.profile.version)
  self.state.open_record(self.record)
 def _ensure_editable_record_complete(self):
  if not self.project or not getattr(self,"images",None):return
  canonical=set(self.project.load_landmarks(self.current()["image_id"]))
  editable={number_from_id(key) for key in self.record.get("points",{})}
  if canonical-editable:self._reload_editable_record_from_project()
 def _load_current_landmark_state(self):
  if not self.project or not self.images or "record" not in self.__dict__: return None
  image_id=self.current()["image_id"];previous=self.landmark_state
  state=load_landmark_state(self.project,image_id);self.landmark_state=state
  provenance={ident:point.get("provenance") for ident,point in sorted(state.points_by_id.items())}
  detail=f"schema_ids={sorted(state.schema_ids)} present_ids={sorted(state.present_ids)} unresolved_ids={sorted(state.unresolved_ids)} extra_ids={sorted(state.extra_ids)} human_verified={state.human_verified} provenance={provenance}"
  if previous is None or previous.image_id!=image_id:
   log(image_id,"landmark_state_loaded","END",path=str(self.current()["source_relpath"]),detail=detail)
  elif previous.fingerprint!=state.fingerprint:
   log(image_id,"landmark_state_changed","END",path=str(self.current()["source_relpath"]),detail=detail)
  if state.extra_ids:
   key=(image_id,tuple(sorted(state.extra_ids)))
   if key not in self._orphan_landmark_logged:
    self._orphan_landmark_logged.add(key);log(image_id,"orphan_landmarks_found","WARNING",path=str(self.current()["source_relpath"]),detail=f"extra_ids={sorted(state.extra_ids)}")
  return state

 def _refresh_schema_if_changed(self):
  if not self.project:return False
  path=self.project.schema_path
  try: signature=schema_file_signature(path)
  except OSError:return False
  # The schema is tiny; read it on every image transition so edits are authoritative.
  try:
   from .profile import load_schema_profile
   profile=load_schema_profile(path)
  except Exception as exc:
   if self._schema_error_signature!=signature:
    self._schema_error_signature=signature
    log("GLOBAL","schema_reload_error","ERROR",path=str(path),detail=str(exc))
    try: messagebox.showerror("Invalid landmark schema",str(exc),parent=self)
    except tk.TclError: pass
   return False
  self.profile=profile;self._schema_cache_signature=signature;self._schema_error_signature=None
  self._landmark_list_image_id=None;self._last_landmark_state=None;self._render_signature=None
  return True

 def _refresh_landmark_list(self,state):
  current=self.state.current_landmark;self.landmarks.delete(0,"end")
  for point in self.profile.landmarks:
   marker="✓" if point.number in state.present_ids else "●" if point.number in state.explicitly_missing_ids else "○"
   self.landmarks.insert("end",f"{marker} {point.number} {point.code} — {point.name}")
   self.landmarks.itemconfig(self.landmarks.size()-1,foreground="#188038" if marker=="✓" else "#c88700" if marker=="●" else "#d93025")
  try:index=self.state.point_ids.index(current);self.landmarks.selection_set(index);self.landmarks.see(index)
  except ValueError:pass

 def refresh_project_ui(self,state=None):
  state=state or self.landmark_state
  if state is None or not self.images:return
  row=self.current()
  if row["image_id"]!=state.image_id:
   log(row["image_id"],"landmark_qc_updated","ERROR",detail=f"row_image_id={row['image_id']} state_image_id={state.image_id}");return
  skipped=(f" | Skipped: {len(state.explicitly_missing_ids)}" if state.explicitly_missing_ids else "")
  extra=(f" | Extra IDs: {len(state.extra_ids)}" if state.extra_ids else "")
  self.annotation_status.config(text=f"Resolved: {state.resolved_count}/{state.expected_count} | Remaining: {len(state.unresolved_ids)}"+skipped+extra)
  self.status_dot.delete("all");color={"red":"#d93025","yellow":"#e6a700","green":"#188038"}[state.color];self.status_dot.create_oval(2,2,12,12,fill=color,outline=color)
  self.checked_button.state(["!disabled"] if not state.unresolved_ids else ["disabled"])
  row.update({"status_color":state.color,"human_verified":state.human_verified,"status_image_id":state.image_id});row["calibrated"]=bool(self.project.locality_calibration(row.get("locality") or row["sample_id"]))
  self.images_box.set_row(self.index,self._row_data(self.index,row));self.images_box.selection_set(self.index);self.images_box.see(self.index)
  self._refresh_landmark_list(state)
  for key,var in self.attribute_vars.items():var.set(self.project.attributes_for_image(row["image_id"]).get(key,""))
  log(state.image_id,"landmark_qc_updated","END",path=str(row["source_relpath"]),detail=f"placed={state.placed_count} expected={state.expected_count} unresolved_ids={sorted(state.unresolved_ids)} extra_ids={sorted(state.extra_ids)} color={state.color} human_verified={state.human_verified}")

 def pick_landmark(self, _=None):
  selection=self.landmarks.selection()
  if not selection or getattr(self,"_syncing",False):return
  number=int(selection[0])
  if number==self.state.current_landmark:return
  self.state.select(number);self.sync()

 def sync(self):
  if getattr(self,"_syncing",False):return
  state=self._load_current_landmark_state()
  self._syncing=True
  try:
   iid=str(self.state.current_landmark)
   if iid in self.landmarks.get_children():
    self.landmarks.selection_set(iid);self.landmarks.see(iid)
   self.render()
  finally:self._syncing=False
  self.refresh_project_ui(state);self._schedule_results_sync()

 def mark_checked(self):
  state=self._load_current_landmark_state()
  if state is None or not state.complete:return
  self.project.mark_checked(state.image_id)
  log(state.image_id,"human_verified_set","END",path=str(self.current()["source_relpath"]),detail="value=true db_write_ok=true")
  self._render_signature=None;state=self._load_current_landmark_state();self.refresh_project_ui(state)


 def missing(self):
  self._ensure_editable_record_complete()
  if self.source_mode:return
  state=self._load_current_landmark_state();number=self.state.current_landmark
  if state and number in state.explicitly_missing_ids:self.record.setdefault("points",{}).pop(record_key(self.record.get("points",{}),number),None)
  else:
   point=self._point(number);set_human_point(self.record,number,point.code,None,None,corrected=False)
  save_record(self.record);self._save_workflow_draft();self._render_signature=None;self.sync()

 def remove(self):
  self._ensure_editable_record_complete()
  if self.source_mode:return
  number=self.state.current_landmark;self.record.setdefault("points",{}).pop(record_key(self.record.get("points",{}),number),None);save_record(self.record);self._save_workflow_draft();self._render_signature=None;self.sync()

 def clear_all(self):
  if not getattr(self,"_landmark_workflow_active",False):return super().clear_all()
  if not self.record.get("points") or not messagebox.askyesno("Clear all landmarks",f"Clear all {len(self.profile.landmarks)} landmarks for this image?",parent=self):return
  self.project.clear_landmark_finals_for_draft(self.current()["image_id"],(getattr(self,"_landmark_ai_info",{}) or {}).get("stage"),getattr(self,"_landmark_workflow_index",None));self._reload_editable_record_from_project();self._save_workflow_draft();self._render_signature=None;self.sync()
 def left_drag(self,e):
  self._ensure_editable_record_complete()
  if self.calibration_mode!="NORMAL":return
  if not self.dragging or self.source_mode:return
  x,y=self.image_point(e.x,e.y);number=self.dragging;point=self._point(number)
  set_human_point(self.record,number,point.code,x,y,corrected=True);save_record(self.record)
  now_monotonic=time.monotonic()
  if now_monotonic-getattr(self,"_last_landmark_drag_log",0)>=.15:
   self._last_landmark_drag_log=now_monotonic;log(self.current().get("image_id","GLOBAL"),"landmark_drag_motion","END",detail=f"landmark_id={number} x={x:.3f} y={y:.3f} workflow_mode={bool(getattr(self,'_landmark_workflow_active',False))}")
  self._render_signature=None;self.sync()

 def left_up(self,e):
  dragging=self.dragging
  if self.calibration_mode!="NORMAL":
   self.dragging=None;return
  result=super().left_up(e)
  if dragging is not None:log(self.current().get("image_id","GLOBAL"),"landmark_drag_release","END",detail=f"landmark_id={dragging} x={e.x} y={e.y} workflow_mode={bool(getattr(self,'_landmark_workflow_active',False))}");self._save_workflow_draft()
  return result
 def _save_calibration_with_length(self,length,locality,reference_image_id):
  (x1,y1),(x2,y2)=self.calibration[:2];distance=((x2-x1)**2+(y2-y1)**2)**.5;payload={"physical_length_mm":length,"points_standardized":[[x1,y1],[x2,y2]],"pixels_per_mm":distance/length,"state":"manual"}
  self.project.set_locality_calibration(locality,reference_image_id,distance/length,"mm",payload);log(reference_image_id,"locality_calibration_saved","END",detail=f"locality_id={locality} reference_mm={length} pixel_distance={distance} mm_per_pixel={distance/length}");self._clear_calibration_overlay("saved");self.refresh_project_ui()

 def _save_dragged_calibration(self):
  if not self.project or not self.calibration or len(self.calibration)<2:return
  row=self.current();locality=row.get("locality") or row.get("sample_id");saved=self.project.locality_calibration(locality);data=saved.get("calibration_data") if saved else {}
  if isinstance(data,str):
   try:data=__import__("json").loads(data)
   except Exception:data={}
  previous=data.get("physical_length_mm",10.) if isinstance(data,dict) else 10.;log(row["image_id"],"calibration_length_prompt","START",detail=f"reason=drag locality_id={locality}")
  length=simpledialog.askfloat("Calibration","Reference length (mm):",initialvalue=previous,minvalue=.001,parent=self)
  if not length:self._clear_calibration_overlay("cancelled");return
  self._save_calibration_with_length(length,locality,row["image_id"])

 def finish_calibration(self):
  if not self.calibration or len(self.calibration)<2:return
  row=self.current();locality=row.get("locality") or row.get("sample_id");log(row["image_id"],"calibration_length_prompt","START",detail=f"reason=new locality_id={locality}")
  length=simpledialog.askfloat("Calibration","Reference length (mm):",initialvalue=10.,minvalue=.001,parent=self)
  if not length:
   self._clear_calibration_overlay("cancelled");return
  self._save_calibration_with_length(length,locality,row["image_id"])

 def toggle_source(self):
  if self.source_mode:
   self.source_mode=False;self._render_signature=None;self.render();return
  if self.source is None:
   started=time.perf_counter();from PIL import Image
   source_path=Path(self.current().get("source_path",self.current()["source_relpath"]))
   self.source=Image.open(paths(source_path)[2]).convert("RGB")
   self._profile("source_png_decode_ms",started,self.current().get("image_id"))
  self.source_mode=True;self._render_signature=None;self.render()

 def _crop_target_row(self):
  """Return the image actually painted in the editor, never a pending list index."""
  row=getattr(self,"_display_row",None);source=getattr(self,"_display_source",None)
  if row is None:
   row=self.current();source=Path(row.get("source_path",row["source_relpath"]))
  ident=str(row.get("image_id") or self._canonical_id(row,source))
  index=next((i for i,candidate in enumerate(self.images) if str(candidate.get("image_id"))==ident),self.index)
  return row,int(index),Path(source),ident
 def correct_normalization(self):
  """Open crop correction for the visibly rendered image."""
  _row,_index,source,ident=self._crop_target_row()
  from .crop_editor_async_v2 import AsyncCropEditorV2
  AsyncCropEditorV2(self,source,lambda target_id=ident:self.post_crop_apply_refresh(target_id),project=self.project,image_id_value=ident)
 def post_crop_apply_refresh(self,image_id=None):
  image_id=image_id or self._crop_target_row()[3]
  self._post_crop_refresh_token=getattr(self,"_post_crop_refresh_token",0)+1;token=self._post_crop_refresh_token
  self.after_idle(lambda:self._run_post_crop_apply_refresh(token,image_id))
 def _run_post_crop_apply_refresh(self,token,image_id):
  if token!=getattr(self,"_post_crop_refresh_token",0):return
  target=next((i for i,row in enumerate(self.images) if str(row.get("image_id"))==str(image_id)),None)
  if target is None:return
  self.index=target;row=self.images[target];source=Path(row.get("source_path",row["source_relpath"]))
  self._refresh_visible_photo_rows();super().open_image(row=row,source=source,listbox_index=target,user_selection=False)
  self.after(5000,lambda:self._post_crop_navigation_watchdog(token,image_id))
 def _post_crop_navigation_watchdog(self,token,image_id):
  if token!=getattr(self,"_post_crop_refresh_token",0):return
  if getattr(self,"_display_image_id",None)!=image_id:
   log(image_id or "GLOBAL","navigation_stall_detected","WARNING",detail=f"post_crop_token={token} load_token={getattr(self,'_load_token',None)} results_sync={self._results_worker}");dump_threads(image_id or "GLOBAL",f"post_crop_navigation_stall token={token}")

 def open_image(self,row=None,source=None,listbox_index=None,user_selection=False):
  self._canvas_landmark_input_ready=False
  self._review_swap_first=None;self._review_undo=None
  if user_selection:self._review_pending_image_id=None;self._review_active_ids.clear()
  if getattr(self,"calibration_mode","NORMAL")!="NORMAL" or getattr(self,"calibration",None):self._clear_calibration_overlay("navigation")
  self._refresh_schema_if_changed()
  if source is None:source=Path(self.images[self.index].get("source_path",self.images[self.index]["source_relpath"]))
  self._flush_results_sync();self.prefetch.claim_user(source);return super().open_image(row=row,source=source,listbox_index=listbox_index,user_selection=user_selection)
 def _prefetch_sources(self):return [Path(row.get("source_path",row["source_relpath"])) for row in self.images[self.index+1:self.index+6]]
 def _poll_selected_v12(self,token):
  before=len(self.navigation_results);super()._poll_selected_v12(token)
  if len(self.navigation_results)>before:
   # V12 has completed normal image installation, sync and render at this point.
   displayed=getattr(self,"_display_image_id",None)
   if displayed==getattr(self,"_workflow_target_image_id",None):self._workflow_target_ready(displayed)
   self._canvas_landmark_input_ready=True
   self._apply_review_issue_if_loaded()
   self.prefetch.schedule(self._prefetch_sources())
   image_items=sum(1 for item in self.canvas.find_all() if self.canvas.type(item)=="image")
   log("GLOBAL","initial_image_loaded","END",path=str(self.project.root) if self.project else "",detail=f"gui_mode=project canvas_image_item_count={image_items} current_image_id={self.current().get('image_id')} landmark_widget=Treeview")

 def _profile(self, operation, started, image_id=None, **detail):
  elapsed=(time.perf_counter()-started)*1000
  ident=image_id or (self.current().get("image_id") if getattr(self,"images",None) else "GLOBAL")
  suffix=" ".join(f"{key}={value}" for key,value in detail.items())
  log(ident,operation,"END",elapsed/1000,detail=f"{operation}={elapsed:.1f}ms {suffix}".strip())
  if elapsed>50: log(ident,"gui_slow_operation","WARNING",detail=f"operation={operation} elapsed_ms={elapsed:.1f}")
  return elapsed

 def _save_current_record(self, operation):
  started=time.perf_counter();save_record(self.record);self._profile("sqlite_save_ms",started,operation=operation)

 def _flush_results_sync(self, final=False):
  self._results_after_id=None
  if not self.project:return
  if self._results_worker:
   self._results_pending=True;return
  self._results_worker=True;project=self.project
  def work():
   started=time.perf_counter()
   try: project.sync_results()
   finally:
    elapsed=(time.perf_counter()-started)*1000
    log("GLOBAL","results_sync_ms","END",elapsed/1000,detail=f"results_sync_ms={elapsed:.1f}ms background=true")
    if elapsed>50: log("GLOBAL","gui_slow_operation","WARNING",detail=f"operation=results_sync_ms elapsed_ms={elapsed:.1f} background=true")
    if final:return
    def completed():
     self._results_worker=False
     if self._results_pending:
      self._results_pending=False;self._flush_results_sync()
    try:self.after(0,completed)
    except (tk.TclError,RuntimeError):pass
  threading.Thread(target=work,daemon=not final,name="project-results-sync").start()

 def _close_project(self):
  self._save_splitter();self._flush_results_sync(final=True);self.destroy()

 def _reload_editable_record_from_project(self):
  """Refresh the one editable record from canonical rows after AI writes."""
  if not self.project or not getattr(self,"images",None):return
  self.record=load_record(self.current(),self.profile.profile_id,self.profile.version)
  self.state.open_record(self.record)
 def _ensure_editable_record_complete(self):
  if not self.project or not getattr(self,"images",None):return
  canonical=set(self.project.load_landmarks(self.current()["image_id"]))
  editable={number_from_id(key) for key in self.record.get("points",{})}
  if canonical-editable:self._reload_editable_record_from_project()
 def _load_current_landmark_state(self):
  started=time.perf_counter()
  if not self.project or not self.images or "record" not in self.__dict__: return None
  image_id=self.current()["image_id"];previous=self.landmark_state
  state=load_landmark_state(self.project,image_id);self.landmark_state=state
  provenance={ident:point.get("provenance") for ident,point in sorted(state.points_by_id.items())}
  detail=f"schema_ids={sorted(state.schema_ids)} present_ids={sorted(state.present_ids)} unresolved_ids={sorted(state.unresolved_ids)} extra_ids={sorted(state.extra_ids)} human_verified={state.human_verified} provenance={provenance}"
  if previous is None or previous.image_id!=image_id:
   log(image_id,"landmark_state_loaded","END",path=str(self.current()["source_relpath"]),detail=detail)
  elif previous.fingerprint!=state.fingerprint:
   log(image_id,"landmark_state_changed","END",path=str(self.current()["source_relpath"]),detail=detail)
  if state.extra_ids:
   key=(image_id,tuple(sorted(state.extra_ids)))
   if key not in self._orphan_landmark_logged:
    self._orphan_landmark_logged.add(key);log(image_id,"orphan_landmarks_found","WARNING",path=str(self.current()["source_relpath"]),detail=f"extra_ids={sorted(state.extra_ids)}")
  self._profile("landmark_state_load_ms",started,state.image_id)
  return state

 def _landmark_row_text(self, point, state):
  marker="✓" if point.number in state.present_ids else "●" if point.number in state.explicitly_missing_ids else "○"
  role_code={"CLASSICAL":"CL","GM":"GM","BOTH":"BT"}.get(getattr(point,"role","BOTH"),"BT")
  return marker, f"{marker} {role_code} {point.number} {point.code} — {point.name}"

 def _refresh_landmark_list(self,state):
  selected=self.state.current_landmark
  self.landmarks.delete(*self.landmarks.get_children())
  for point in self.profile.landmarks:
   marker="✓" if point.number in state.present_ids else "●" if point.number in state.explicitly_missing_ids else "○"
   role_code={"CLASSICAL":"CL","GM":"GM","BOTH":"BT"}.get(getattr(point,"role","BOTH"),"BT")
   tag="present" if marker=="✓" else "missing" if marker=="●" else "unresolved"
   tags=(tag,"review_warning") if point.number in self._review_active_ids else (tag,)
   self.landmarks.insert("","end",iid=str(point.number),values=(marker,point.number,role_code,point.code,point.name),tags=tags)
  iid=str(selected)
  if iid in self.landmarks.get_children():
   self.landmarks.selection_set(iid);self.landmarks.see(iid)
  self._landmark_list_image_id=state.image_id;self._last_landmark_state=state

 def refresh_project_ui(self,state=None):
  state=state or self.landmark_state
  if state is None or not self.images:return
  row=self.current()
  if row["image_id"]!=state.image_id:
   log(row["image_id"],"landmark_qc_updated","ERROR",detail=f"row_image_id={row['image_id']} state_image_id={state.image_id}");return
  excluded=bool(row.get("excluded"));reason=row.get("exclusion_reason") or "Other"
  if excluded:
   self.annotation_status.config(text=f"EXCLUDED — {reason}");self.status_dot.delete("all");self.checked_button.state(["disabled"])
  else:
   skipped=(f" | Skipped: {len(state.explicitly_missing_ids)}" if state.explicitly_missing_ids else "")
   ready=" | Ready" if state.color=="green" else ""
   self.annotation_status.config(text=f"Resolved: {state.resolved_count}/{state.expected_count} | Remaining: {len(state.unresolved_ids)}"+skipped+ready)
   self.status_dot.delete("all");color={"red":"#d93025","yellow":"#e6a700","green":"#188038"}[state.color];self.status_dot.create_oval(2,2,12,12,fill=color,outline=color)
   self.checked_button.state(["!disabled"] if not state.unresolved_ids else ["disabled"])
  row.update({"status_color":"excluded" if excluded else state.color,"human_verified":state.human_verified,"status_image_id":state.image_id,"has_crop":self.project.crop_exists(row["image_id"]),"calibrated":bool(self.project.locality_calibration(row.get("locality") or row["sample_id"]))})
  if self.index in self._visible_image_indices:
   visible=self._visible_image_indices.index(self.index);self.images_box.set_row(visible,self._row_data(self.index,row));self.images_box.selection_set(visible);self.images_box.see(visible)
  self._refresh_landmark_list(state)
  for key,var in self.attribute_vars.items():var.set(self.project.attributes_for_image(row["image_id"]).get(key,""))
  if hasattr(self,"exclude_button"):self.exclude_button.config(text="Restore image" if excluded else "Exclude…")
  self._update_ai_batch_status()

 def exclude_or_restore(self):
  row=self.current()
  if row.get("excluded"):
   self.project.restore_image(row["image_id"]);row.update({"excluded":0,"exclusion_reason":None,"exclusion_note":None})
  else:
   reason=simpledialog.askstring("Exclude image","Reason (Bent specimen, Bad orientation, Damaged specimen, Bad image, Duplicate, Other):",initialvalue="Bent specimen",parent=self)
   if reason is None:return
   note=simpledialog.askstring("Exclude image","Optional note:",parent=self)
   self.project.exclude_image(row["image_id"],reason,note);row.update({"excluded":1,"exclusion_reason":reason.strip() or "Other","exclusion_note":note})
  if getattr(self,"_landmark_workflow_active",False):repair_excluded_stage_members(self.project);self._landmark_ai_info=stage_summary(self.project,create_missing=False);self._landmark_workflow_ids=list(self._landmark_ai_info["current_ids"])
  self.refresh_project_ui(self._load_current_landmark_state());self._schedule_results_sync()
  if not self._show_excluded_var.get():self._refresh_visible_photo_rows()

 def mark_checked(self):
  if self.current().get("excluded"):return
  state=self._load_current_landmark_state()
  if state is None or not state.complete:return
  if self.__dict__.get("_landmark_workflow_review_only",False):self._accept_current_landmark_set_warnings(state.image_id)
  self.project.mark_checked(state.image_id)
  baseline_run=getattr(self,"_baseline_first_edit_run",None)
  if baseline_run and state.image_id in baseline_run.get("image_ids",()):
   try:refresh_first_marking_reference(self.project,baseline_run["run_id"],state.image_id);recompute_completed_run(self.project,baseline_run["run_id"])
   except Exception as exc:messagebox.showerror("Human Baseline",str(exc),parent=self)
  log(state.image_id,"human_verified_set","END",path=str(self.current()["source_relpath"]),detail="value=true db_write_ok=true")
  self.refresh_project_ui(self._load_current_landmark_state())

 def _build_photo_filters(self):
  bar=ttk.Frame(self.photo_list_frame);bar.pack(fill="x",before=self.images_box,pady=(0,1));self.photo_filter_bar=bar
  ttk.Label(bar,text="Sample").pack(side="left",padx=(0,2))
  self._locality_filter_entry=ttk.Entry(bar,textvariable=self._locality_filter_var,width=14);self._locality_filter_entry.pack(side="left",padx=(0,4))
  ttk.Label(bar,text="Image").pack(side="left",padx=(0,2))
  self._image_filter_entry=ttk.Entry(bar,textvariable=self._image_filter_var,width=14);self._image_filter_entry.pack(side="left",padx=(0,4))
  self._photo_filter_clear=ttk.Button(bar,text="×",width=2,command=self.clear_photo_filters);self._photo_filter_clear.pack(side="left")
  self._install_filter_entry_clipboard(self._locality_filter_entry)
  self._install_filter_entry_clipboard(self._image_filter_entry)
 def _install_filter_entry_clipboard(self, entry):
  """Keep native Entry clipboard semantics available in the filter row."""
  menu=tk.Menu(entry, tearoff=False)
  menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
  menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
  menu.add_command(label="Paste", command=lambda: entry.event_generate("<<Paste>>"))
  menu.add_separator()
  menu.add_command(label="Select All", command=lambda: (entry.selection_range(0, "end"), entry.icursor("end")))
  entry._simm_filter_menu=menu
  entry.bind("<Button-3>", lambda event, m=menu: (m.tk_popup(event.x_root, event.y_root), m.grab_release()))
  def paste(_event=None):
   try:
    if entry.selection_present(): entry.delete("sel.first", "sel.last")
   except tk.TclError: pass
   try: entry.insert(entry.index("insert"), entry.clipboard_get())
   except tk.TclError: pass
   return "break"
  entry.bind("<Control-v>", paste);entry.bind("<Control-V>", paste);entry.bind("<Shift-Insert>", paste)
  self._locality_filter_var.trace_add("write",self._schedule_photo_filter);self._image_filter_var.trace_add("write",self._schedule_photo_filter)
 def _schedule_photo_filter(self,*_):
  pending=getattr(self,"_filter_after_id",None)
  if pending is not None:
   try:self.after_cancel(pending)
   except tk.TclError:pass
  self._filter_after_id=self.after(120,self._apply_photo_filter)
 def _apply_photo_filter(self):
  self._filter_after_id=None;self._refresh_visible_photo_rows()
 def clear_photo_filters(self):
  self._locality_filter_var.set("");self._image_filter_var.set("")
  pending=getattr(self,"_filter_after_id",None)
  if pending is not None:
   try:self.after_cancel(pending)
   except tk.TclError:pass
  self._filter_after_id=None;self._refresh_visible_photo_rows()

 def _build_photo_legend(self):
  legend=ttk.Frame(self.photo_pane);legend.pack(fill="x",before=self.photo_list_frame,pady=(0,3));self.photo_legend=legend
  square=tk.Canvas(legend,width=11,height=11,highlightthickness=0);square.create_rectangle(2,2,10,10,fill="#7b8794",outline="#59636d");square.pack(side="left")
  ttk.Label(legend,text=" cropped").pack(side="left",padx=(0,8))
  for color,text in (("#d93025","incomplete"),("#e6a700","review"),("#188038","ready")):
   dot=tk.Canvas(legend,width=11,height=11,highlightthickness=0);dot.create_oval(2,2,10,10,fill=color,outline=color);dot.pack(side="left")
   ttk.Label(legend,text=" "+text).pack(side="left",padx=(0,7))
  ttk.Label(legend,text="×",foreground="#6b7280",font=("Segoe UI",10,"bold")).pack(side="left")
  ttk.Label(legend,text=" excluded").pack(side="left",padx=(0,7))
  ttk.Checkbutton(legend,text="Show excluded",variable=self._show_excluded_var,command=self._toggle_show_excluded).pack(side="right")

 def _row_data(self,index,row):
  excluded=bool(row.get("excluded"));status="excluded" if excluded else row.get("status_color","red")
  if excluded: tooltip="Excluded: "+(row.get("exclusion_reason") or "Other")
  elif status=="red": tooltip=f"Incomplete: {len(row.get('missing_ids',()))} remaining"
  elif status=="yellow": tooltip="Complete — needs review"
  else: tooltip="Ready"
  return {"number":str(index+1),"cal":"C" if row.get("calibrated") else "","has_crop":bool(row.get("has_crop")),"excluded":excluded,"text":f"{row.get('locality',row['sample_id'])} | {Path(row['source_relpath']).name} ({row.get('index_in_locality',1)} | {row.get('total_in_locality',1)})","status":status,"tooltip":tooltip,"review_warning":bool(self.review_mode and row["image_id"] in review_warning_image_ids(self._review_queue,self._review_completed_indices))}

 def _refresh_visible_photo_rows(self):
  shown=bool(self._show_excluded_var.get()) if hasattr(self,"_show_excluded_var") else True
  if len(getattr(self,"_photo_search_cache",()))!=len(self.images):self._photo_search_cache=photo_search_cache(self.images)
  self._visible_image_indices=filtered_photo_indices(self.images,self._photo_search_cache,self._image_filter_var.get(),self._locality_filter_var.get(),show_excluded=shown)
  self.images_box.set_rows([self._row_data(i,self.images[i]) for i in self._visible_image_indices])
  if self.index in self._visible_image_indices:
   visible=self._visible_image_indices.index(self.index);self.images_box.selection_set(visible);self.images_box.see(visible)

 def _toggle_show_excluded(self): self._refresh_visible_photo_rows()

 def pick_image(self,_=None):
  selection=self.images_box.curselection()
  if not selection or selection[0]>=len(self._visible_image_indices):return
  actual=self._visible_image_indices[selection[0]]
  if actual==self.index:return
  self.index=actual;row=self.images[actual];source=Path(row.get("source_path",row["source_relpath"]))
  self.open_image(row=row,source=source,listbox_index=actual,user_selection=True)

def run():ReadyEditorV15().mainloop()
if __name__=="__main__":run()

