import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import tkinter as tk
from PIL import Image

from app.ai import MockBackend
from app.editor_ready_v15 import ReadyEditorV15
from app.project_storage import Project, schema_hash


class WorkflowNavigationPredictionIntegrationTests(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp(prefix="simm_workflow_navigation_"));source=self.temp/"source";source.mkdir()
  for index in range(5):Image.new("RGB",(240,160),(40+index,50,60)).save(source/f"fish_{index}.jpg")
  schema=self.temp/"schema.csv";schema.write_text("id,abbr,name,role\n"+"\n".join(f"{i},L{i},Landmark {i},BOTH" for i in range(1,26))+"\n",encoding="utf-8")
  self.project=Project.create("project",source,self.temp,schema,source_layout="direct");self.ids=[row["image_id"] for row in self.project.catalog_rows()]
  for image_id in self.ids:
   cache=self.project.cache_root/"standardized"/f"{image_id}.png";cache.parent.mkdir(parents=True,exist_ok=True);Image.new("RGB",(240,160),(40,50,60)).save(cache)
  self.backend=MockBackend(schema_hash(self.project.schema_path),model_id="imported-test-model");self.calls=[];original=self.backend.predict
  def record(request):self.calls.append(request.image_id);return original(request)
  self.backend.predict=record
  self.project.register_model(self.backend.model_id,"landmark",metrics=self.backend.model_info(),schema_digest=schema_hash(self.project.schema_path),active=True)
  state={"version":2,"stage":"CONTROL_SET","seed":1,"control_target":5,"initial_target":30,"improvement_target":20,"control_image_ids":self.ids,"initial_image_ids":[],"improvement_image_ids":[],"full_prediction_done":False,"created_at":"test","stage_created_at":{"CONTROL_SET":"test"},"current_image_id":None,"current_position":None,"unfinished_image_id":None};self.project.set_ui_state("landmark_ai_workflow",state);self.project.reserve_permanent_test(self.ids)
  try:self.editor=ReadyEditorV15(project=self.project);self.editor.geometry("900x700");self._wait(lambda:getattr(self.editor,"_display_image_id",None)==self.ids[0])
  except tk.TclError as exc:self.skipTest(str(exc))
 def tearDown(self):
  if hasattr(self,"editor"):
   try:
    # The production prefetch worker is intentionally asynchronous. Stop its
    # test instance before removing the temporary project it still references.
    with self.editor.prefetch._cv:
     self.editor.prefetch._stop=True;self.editor.prefetch._heap.clear();self.editor.prefetch._cv.notify_all()
    if self.editor._results_after_id is not None:self.editor.after_cancel(self.editor._results_after_id)
    self.editor.update_idletasks();self.editor.update()
    self.editor._flush_results_sync(final=True)
    for after_id in self.editor.tk.call("after","info"):self.editor.after_cancel(after_id)
    self.editor.destroy()
   except (tk.TclError,RuntimeError):pass
  shutil.rmtree(self.temp,ignore_errors=True)
 def _wait(self,predicate,seconds=8):
  deadline=time.monotonic()+seconds;state={"done":False}
  def poll():
   if predicate():state["done"]=True;self.editor.quit();return
   if time.monotonic()>=deadline:self.editor.quit();return
   self.editor.after(10,poll)
  self.editor.after(0,poll);self.editor.mainloop()
  if not state["done"]:self.fail("timed out waiting for asynchronous editor state")
 def _confirm(self):
  from app.annotation_check import AnnotationCheckResult
  self.editor._annotation_check_for_current=lambda:AnnotationCheckResult(self.editor.current()["image_id"],(),())
  with patch("app.editor_ready_v15.messagebox.showinfo"):
   self.editor.workflow_confirm_next()
 def test_three_confirm_transitions_predict_explicit_ready_targets(self):
  from app.landmark_ai_workflow import stage_summary
  self.editor._landmark_workflow_active=True;self.editor._landmark_workflow_ids=list(self.ids);self.editor._landmark_workflow_index=0;self.editor._landmark_ai_info=stage_summary(self.project,create_missing=False)
  with patch("app.editor_ready_v15.active_backend",return_value=("test",self.backend)):
   self.editor._open_landmark_workflow_item(0)
   self._wait(lambda:len(self.project.load_landmarks(self.ids[0]))==25 and not self.editor._workflow_prediction_inflight_ids)
   self.assertEqual((self.ids[0],self.ids[0]),(self.editor.current()["image_id"],self.editor._display_image_id))
   self._confirm();self.assertTrue(self.project.annotation_status(self.ids[0])["verified"])
   self._wait(lambda:len(self.project.load_landmarks(self.ids[1]))==25 and self.editor._display_image_id==self.ids[1] and not self.editor._workflow_prediction_inflight_ids)
   first=self.project.load_landmarks(self.ids[1])[1];sx=int(self.editor.pan[0]+first["x_standardized"]*self.editor.zoom);sy=int(self.editor.pan[1]+first["y_standardized"]*self.editor.zoom)
   self.editor.canvas.event_generate("<ButtonPress-1>",x=sx,y=sy);self.editor.canvas.event_generate("<B1-Motion>",x=sx+9,y=sy+6);self.editor.canvas.event_generate("<ButtonRelease-1>",x=sx+9,y=sy+6);self.editor.update()
   self._confirm();self.assertTrue(self.project.annotation_status(self.ids[1])["verified"])
   self._wait(lambda:len(self.project.load_landmarks(self.ids[2]))==25 and self.editor._display_image_id==self.ids[2] and not self.editor._workflow_prediction_inflight_ids)
   self._confirm();self.assertTrue(self.project.annotation_status(self.ids[2])["verified"])
   self._wait(lambda:len(self.project.load_landmarks(self.ids[3]))==25 and self.editor._display_image_id==self.ids[3] and not self.editor._workflow_prediction_inflight_ids)
  self.assertEqual(self.ids[:4],self.calls)
  self.assertEqual(self.ids[3],self.editor.current()["image_id"])
  self.assertEqual(3,self.editor._landmark_workflow_index)
  self.assertFalse(self.project.annotation_status(self.ids[3])["verified"])

 def _activate_workflow(self):
  from app.landmark_ai_workflow import stage_summary
  self.editor._landmark_workflow_active=True;self.editor._landmark_workflow_ids=list(self.ids);self.editor._landmark_workflow_index=0;self.editor._landmark_ai_info=stage_summary(self.project,create_missing=False)
 def test_empty_stale_draft_with_unresolved_manual_history_auto_predicts(self):
  for landmark_id in range(1,26):
   self.project.save_landmark(self.ids[0],landmark_id,None,None,"unresolved",provenance="manual" if landmark_id in {1,2} else "machine")
  self.project.save_annotation_draft(self.ids[0],"CONTROL_SET",0);self._activate_workflow()
  with patch("app.editor_ready_v15.active_backend",return_value=("test",self.backend)):
   self.editor._open_landmark_workflow_item(0)
   self._wait(lambda:self.calls==[self.ids[0]] and not self.editor._workflow_prediction_inflight_ids)
  self.assertEqual([self.ids[0]],self.calls)
 def test_human_draft_is_restored_without_auto_prediction(self):
  self.project.save_landmark(self.ids[0],1,31,32,"manual",provenance="manual");self.project.save_annotation_draft(self.ids[0],"CONTROL_SET",0);self._activate_workflow()
  with patch("app.editor_ready_v15.active_backend",return_value=("test",self.backend)):
   self.editor._open_landmark_workflow_item(0)
  row=self.project.load_landmarks(self.ids[0])[1]
  self.assertEqual(("manual",31,32),(row["provenance"],row["x_standardized"],row["y_standardized"]))
  self.assertEqual([],self.calls)
 def test_explicit_manual_missing_draft_is_restored_without_auto_prediction(self):
  self.project.save_landmark(self.ids[0],1,None,None,"missing",provenance="manual");self.project.save_annotation_draft(self.ids[0],"CONTROL_SET",0);self._activate_workflow()
  with patch("app.editor_ready_v15.active_backend",return_value=("test",self.backend)):
   self.editor._open_landmark_workflow_item(0)
  self.assertEqual([],self.calls)
  self.assertIn(1,self.editor._load_current_landmark_state().explicitly_missing_ids)
 def test_existing_machine_prediction_is_restored_without_repeat_prediction(self):
  from app.landmark_ai_service import LandmarkAIService
  LandmarkAIService(self.project,self.backend).predict_one(self.ids[0]);self.calls.clear();self.project.save_annotation_draft(self.ids[0],"CONTROL_SET",0);self._activate_workflow()
  with patch("app.editor_ready_v15.active_backend",return_value=("test",self.backend)):
   self.editor._open_landmark_workflow_item(0)
  self.assertEqual([],self.calls)
  self.assertEqual(25,len(self.editor._load_current_landmark_state().present_ids))
 def test_clear_all_manual_rebuild_intent_suppresses_auto_prediction(self):
  from app.landmark_ai_service import LandmarkAIService
  LandmarkAIService(self.project,self.backend).predict_one(self.ids[0]);self.calls.clear();self._activate_workflow();self.editor._reload_editable_record_from_project()
  with patch("app.editor_ready_v15.messagebox.askyesno",return_value=True):self.editor.clear_all()
  self.editor._workflow_target_image_id=self.ids[0]
  with patch("app.editor_ready_v15.active_backend",return_value=("test",self.backend)):
   self.editor._workflow_target_ready(self.ids[0])
  draft=self.project.annotation_draft(self.ids[0]);self.assertTrue(draft["manual_rebuild"])
  self.assertEqual([],self.calls)
  self.assertEqual([], [row for row in self.project.load_landmarks(self.ids[0]).values() if row["x_standardized"] is not None])
  with patch("app.editor_ready_v15.active_backend",return_value=("test",self.backend)):
   self.editor.retry_workflow_prediction()
   self._wait(lambda:self.calls==[self.ids[0]] and not self.editor._workflow_prediction_inflight_ids)
  self.assertFalse(self.project.annotation_draft(self.ids[0])["manual_rebuild"])
if __name__=="__main__":unittest.main()





