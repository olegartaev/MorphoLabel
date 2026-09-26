"""V13 navigation plus explicit, user-triggered crop-model training."""
import threading
from tkinter import ttk, messagebox
from .crop_training import correction_count, current_label, train, activate
from .editor_ready_v13 import ReadyEditorV13
from .gui_crop_debug import error, log


class ReadyEditorV14(ReadyEditorV13):
 def _layout(self):
  super()._layout()
  frame=ttk.Frame(self.landmark_pane,padding=4);frame.pack(fill="x")
  self.crop_train_status=ttk.Label(frame,text="")
  self.crop_train_status.pack(fill="x")
  self.crop_train_button=ttk.Button(frame,text="Train crop model",command=self.train_crop_model)
  self.crop_train_button.pack(fill="x")
  self.refresh_crop_training_status()
 def refresh_crop_training_status(self):
  self.crop_train_status.config(text=f"Training examples: {correction_count()} | Current crop model: {current_label(getattr(self,'project',None))}")
 def train_crop_model(self):
  self.crop_train_button.state(["disabled"]); self.crop_train_status.config(text="Training crop model locally…")
  log("GLOBAL","training_examples","END",detail=f"training_examples={correction_count()} crop_model_version={current_label(getattr(self,'project',None))}")
  threading.Thread(target=self._train_worker,daemon=True,name="crop-model-training").start()
 def _train_worker(self):
  try: result=train(project=getattr(self,"project",None))
  except Exception as exc:
   error("GLOBAL","training_finished","",exc);result={"error":str(exc)}
  self.after(0,lambda:self._train_done(result))
 def _train_done(self,result):
  self.crop_train_button.state(["!disabled"]);self.refresh_crop_training_status()
  if result.get("error"): messagebox.showerror("Crop training",result["error"])
  elif not result.get("trained"): messagebox.showinfo("Crop training",result["reason"])
  else:self._show_crop_candidate_dialog(result)
 def _show_crop_candidate_dialog(self,result):
  previous=result.get("previous_model_id") or "None";evaluation=None
  project=getattr(self,"project",None)
  if project and project.crop_holdout_ready_count()>=20:
   try:
    from .crop_evaluation import evaluate,comparison
    evaluation=evaluate(project,result["model_id"]);prior=evaluate(project,previous) if previous not in {None,"None","rule-based"} else None;comparison_result=comparison(evaluation,prior)
   except Exception as exc:error("GLOBAL","crop_posttrain_evaluation","",exc);comparison_result=None
  else:comparison_result=None
  dialog=ttk.Frame(self);window=__import__('tkinter').Toplevel(self);window.title("Crop Model Training");window.transient(self);window.grab_set();window.resizable(False,False)
  summary=result.get("dataset_summary",{});previous_count=summary.get("previous_training_count");delta=summary.get("delta_training_count");previous_text="None" if previous_count is None else str(previous_count);delta_text="N/A" if delta is None else f"{delta:+d}";text=f"Crop model training complete\n\nNew model: {result['model_id']}\nPrevious model: {previous}\n\nTraining examples:\nPrevious: {previous_text}\nCurrent: {summary.get('current_training_count',result['training_examples'])}\nDelta: {delta_text}\n\nSince previous model:\nNew considered verified crops: {summary.get('new_considered_verified_crops',summary.get('new_human_verified_since_previous','N/A'))}\nAdded to training: {summary.get('added_to_training_now',0)}\nAlready seen in lineage: {summary.get('already_seen_in_lineage',0)}\nHoldout reserved: {summary.get('holdout_reserved',0)}\nInvalid / no developed cache: {summary.get('invalid_or_missing_cache',0)}\nNo valid final crop: {summary.get('no_valid_final_crop',0)}\nDuplicates: {summary.get('duplicates',0)}\nOther excluded: {summary.get('other_excluded',0)}\n\nInternal validation\nIoU: {result['metrics']['validation_iou']:.3f}"
  if evaluation:text+=f"\n\nIndependent evaluation: {evaluation['n_evaluated']} images\nMedian IoU: {evaluation['median_iou']:.3f}\nIoU ≥ 0.90: {evaluation['iou90_pct']:.1f}%\nQC BAD: {evaluation['qc_bad_pct']:.1f}%\nFailures: {evaluation['failures']}\nResult: {(comparison_result or {}).get('conclusion','No previous evaluation')}"
  else:text+="\n\nIndependent evaluation unavailable\nClean unseen images: fewer than 20 / 20 minimum"
  ttk.Label(window,text=text,justify="left",padding=14).pack(fill="both")
  actions=ttk.Frame(window,padding=(14,0,14,14));actions.pack(fill="x")
  def use():
   activate(result['model_id'],path=(getattr(self,'project',None).models_root/result['model_id']) if getattr(self,'project',None) else None);
   if getattr(self,'project',None):self.project.set_active_model('crop',result['model_id']);log("GLOBAL","crop_model_activation_decision","END",detail=f"selected_model_id={result['model_id']} decision=use_new");window.destroy();self.refresh_crop_training_status()
  def keep():
   log("GLOBAL","crop_model_activation_decision","END",detail=f"selected_model_id={previous} decision=keep_previous");window.destroy();self.refresh_crop_training_status()
  ttk.Button(actions,text="Use New Model",command=use).pack(side="left");ttk.Button(actions,text="Keep Previous",command=keep).pack(side="right")


def run():
 ReadyEditorV14().mainloop()


if __name__ == "__main__":
 run()
