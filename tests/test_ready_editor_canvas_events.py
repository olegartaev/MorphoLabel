import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import tkinter as tk
from PIL import Image

from app.ai import MockBackend
from app.editor_ready_v15 import ReadyEditorV15
from app.landmark_ai_service import LandmarkAIService
from app.project_storage import Project, schema_hash


class ReadyEditorCanvasEventIntegrationTests(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp(prefix="simm_canvas_events_"));source=self.temp/"source";source.mkdir()
  Image.new("RGB",(240,160),(40,50,60)).save(source/"fish.jpg")
  schema=self.temp/"schema.csv";schema.write_text("id,abbr,name,role\n"+"\n".join(f"{i},L{i},Landmark {i},BOTH" for i in range(1,26))+"\n",encoding="utf-8")
  self.project=Project.create("project",source,self.temp,schema,source_layout="direct");self.image_id=self.project.catalog_rows()[0]["image_id"]
  cache=self.project.cache_root/"standardized"/f"{self.image_id}.png";cache.parent.mkdir(parents=True,exist_ok=True);Image.new("RGB",(240,160),(40,50,60)).save(cache)
  try:self.editor=ReadyEditorV15(project=self.project);self.editor.geometry("900x700");self.editor.update();self.editor.update_idletasks()
  except tk.TclError as exc:self.skipTest(str(exc))
 def tearDown(self):
  if hasattr(self,"editor"):
   try:
    if self.editor._results_after_id is not None:self.editor.after_cancel(self.editor._results_after_id)
    self.editor._flush_results_sync(final=True);self.editor.destroy()
   except (tk.TclError,RuntimeError):pass
  shutil.rmtree(self.temp,ignore_errors=True)
 def test_control_set_ai_landmarks_follow_real_canvas_mouse_events(self):
  LandmarkAIService(self.project,MockBackend(schema_hash(self.project.schema_path))).predict_one(self.image_id)
  self.editor._landmark_workflow_active=True;self.editor._reload_editable_record_from_project();self.editor._render_signature=None;self.editor.sync();self.editor._log_canvas_event_path("control_set_prediction_rendered");self.editor.update();self.editor.update_idletasks()
  before=self.project.load_landmarks(self.image_id);row=before[5];x=int(self.editor.pan[0]+row["x_standardized"]*self.editor.zoom);y=int(self.editor.pan[1]+row["y_standardized"]*self.editor.zoom)
  self.editor.canvas.event_generate("<ButtonPress-1>",x=x,y=y);self.editor.update()
  self.editor.canvas.event_generate("<B1-Motion>",x=x+31,y=y+19);self.editor.update()
  self.editor.canvas.event_generate("<ButtonRelease-1>",x=x+31,y=y+19);self.editor.update()
  after=self.project.load_landmarks(self.image_id)
  self.assertGreaterEqual(self.editor._canvas_raw_event_counts.get("button1",0),1)
  self.assertGreaterEqual(self.editor._canvas_raw_event_counts.get("b1_motion",0),1)
  self.assertGreaterEqual(self.editor._canvas_raw_event_counts.get("button1_release",0),1)
  self.assertNotEqual((before[5]["x_standardized"],before[5]["y_standardized"]),(after[5]["x_standardized"],after[5]["y_standardized"]))
  self.assertTrue(all((before[i]["x_standardized"],before[i]["y_standardized"])==(after[i]["x_standardized"],after[i]["y_standardized"]) for i in range(1,26) if i!=5))
  self.assertFalse(self.project.annotation_status(self.image_id)["verified"])

 def _clear_all_then_rebuild_manually(self,stage):
  LandmarkAIService(self.project,MockBackend(schema_hash(self.project.schema_path))).predict_one(self.image_id)
  before=self.project.load_landmarks(self.image_id)
  self.editor._landmark_workflow_active=True;self.editor._landmark_workflow_ids=[self.image_id];self.editor._landmark_ai_info={"stage":stage,"friendly_stage":"Control set" if stage=="CONTROL_SET" else "Initial training","verified":0}
  self.editor._reload_editable_record_from_project()
  with patch("app.editor_ready_v15.messagebox.askyesno",return_value=True):self.editor.clear_all()
  cleared=self.project.load_landmarks(self.image_id)
  self.assertEqual(set(),set(load for load,row in cleared.items() if row["x_standardized"] is not None))
  self.assertEqual(set(range(1,26)),set(self.project.annotation_status(self.image_id)["unresolved_ids"]))
  self.assertEqual((before[1]["predicted_x"],before[1]["predicted_y"],before[1]["model_id"],before[1]["prediction_run_id"]),(cleared[1]["predicted_x"],cleared[1]["predicted_y"],cleared[1]["model_id"],cleared[1]["prediction_run_id"]))
  positions=[]
  for index in range(25):
   ix=20+(index%5)*40;iy=20+(index//5)*28;positions.append((ix,iy))
   sx=int(self.editor.pan[0]+ix*self.editor.zoom);sy=int(self.editor.pan[1]+iy*self.editor.zoom)
   self.editor.canvas.event_generate("<ButtonPress-1>",x=sx,y=sy);self.editor.update()
  rebuilt=self.project.load_landmarks(self.image_id)
  self.assertEqual(set(range(1,26)),{ident for ident,row in rebuilt.items() if row["x_standardized"] is not None})
  self.assertEqual((positions[0][0],positions[0][1]),(rebuilt[1]["x_standardized"],rebuilt[1]["y_standardized"]))
  self.assertEqual(("manual",False),(rebuilt[1]["provenance"],self.project.annotation_status(self.image_id)["verified"]))
  self.assertEqual((before[1]["predicted_x"],before[1]["predicted_y"],before[1]["model_id"],before[1]["prediction_run_id"]),(rebuilt[1]["predicted_x"],rebuilt[1]["predicted_y"],rebuilt[1]["model_id"],rebuilt[1]["prediction_run_id"]))
  sx=int(self.editor.pan[0]+rebuilt[1]["x_standardized"]*self.editor.zoom);sy=int(self.editor.pan[1]+rebuilt[1]["y_standardized"]*self.editor.zoom)
  self.editor.canvas.event_generate("<ButtonPress-1>",x=sx,y=sy);self.editor.canvas.event_generate("<B1-Motion>",x=sx+11,y=sy+7);self.editor.canvas.event_generate("<ButtonRelease-1>",x=sx+11,y=sy+7);self.editor.update()
  self.assertNotEqual((positions[0][0],positions[0][1]),(self.project.load_landmarks(self.image_id)[1]["x_standardized"],self.project.load_landmarks(self.image_id)[1]["y_standardized"]))
  from app.annotation_check import AnnotationCheckResult
  self.editor._annotation_check_for_current=lambda:AnnotationCheckResult(self.image_id,(),())
  with patch("app.editor_ready_v15.messagebox.showinfo"),patch("app.editor_ready_v15.messagebox.showwarning"),patch("app.editor_ready_v15.messagebox.askyesno",return_value=False):
   self.editor.workflow_confirm_next()
  self.assertTrue(self.project.annotation_status(self.image_id)["verified"])
 def test_control_set_clear_all_allows_real_canvas_manual_rebuild(self):
  self._clear_all_then_rebuild_manually("CONTROL_SET")
 def test_initial_training_clear_all_allows_real_canvas_manual_rebuild(self):
  self._clear_all_then_rebuild_manually("INITIAL_TRAINING")
if __name__=="__main__":unittest.main()











