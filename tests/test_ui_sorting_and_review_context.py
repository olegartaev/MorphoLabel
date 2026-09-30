import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ui.project_section import sorted_project_samples
from app.ui.landmarks_section import _prediction_context_text, _prediction_candidate_ids


class UISortingAndReviewContextTests(unittest.TestCase):
 def test_project_sample_sorting_is_case_insensitive_and_numeric(self):
  rows=[{"sample":"B","images":2,"calibrated":False},{"sample":"a","images":10,"calibrated":True}]
  self.assertEqual(["a","B"],[row["sample"] for row in sorted_project_samples(rows,"sample",False)])
  self.assertEqual([10,2],[row["images"] for row in sorted_project_samples(rows,"images",True)])

 def test_prediction_context_hidden_for_green_and_identifies_pending_model(self):
  green={"image_id":"x","human_verified":True,"status_color":"green"}
  project=SimpleNamespace(load_landmarks=lambda _:{},schema=[1,2])
  self.assertEqual("",_prediction_context_text(project,green))
  pending={"image_id":"x","human_verified":False,"status_color":"yellow","placed":2,"expected_landmarks":2}
  project=SimpleNamespace(load_landmarks=lambda _:{1:{"provenance":"machine","model_id":"m1","updated_at":"2026-09-29T12:00:00+00:00"},2:{"provenance":"machine","model_id":"m1","updated_at":"2026-09-29T12:00:00+00:00"}},schema=[1,2])
  value=_prediction_context_text(project,pending)
  self.assertIn("m1",value);self.assertIn("2026-",value);self.assertNotIn("resolved",value);self.assertNotIn("review pending",value)

 def test_prediction_context_does_not_call_marked_missing_unresolved(self):
  pending={"image_id":"x","human_verified":False,"status_color":"yellow","placed":24,"expected_landmarks":25,"missing_ids":[]}
  project=SimpleNamespace(load_landmarks=lambda _:{1:{"provenance":"machine","model_id":"m1","updated_at":"2026-09-29T12:00:00+00:00"}},schema=list(range(25)))
  value=_prediction_context_text(project,pending)
  self.assertIn("m1",value);self.assertNotIn("unresolved",value);self.assertNotIn("resolved",value)

 def test_prediction_candidates_include_empty_and_ai_but_exclude_manual_only(self):
  rows=[{"image_id":"empty","excluded":False},{"image_id":"manual","excluded":False},{"image_id":"ai","excluded":False}]
  class P:
   def landmark_prediction_locked(self,_image_id):return False
   def load_landmarks(self,image_id):
    if image_id=="empty":return {}
    if image_id=="manual":return {1:{"provenance":"manual"}}
    return {1:{"provenance":"machine","model_id":"m1"}}
  self.assertEqual(("empty","ai"),_prediction_candidate_ids(P(),rows))

 def test_prediction_and_crop_labels_do_not_use_ambiguous_remaining_or_raw_failed(self):
  from pathlib import Path
  root=Path(__file__).resolve().parents[1]
  landmarks=(root/"app"/"ui"/"landmarks_section.py").read_text(encoding="utf-8")
  crop=(root/"app"/"ui"/"crop_section.py").read_text(encoding="utf-8")
  photos=(root/"app"/"ui"/"photo_list_panel.py").read_text(encoding="utf-8")
  self.assertIn("Predict all",landmarks);self.assertNotIn("'All remaining'",landmarks);self.assertNotIn("run All remaining again",landmarks)
  self.assertIn("Predict all uncropped",crop);self.assertNotIn('"Apply remaining"',crop)
  self.assertIn("Needs attention:",crop);self.assertNotIn("failed: {result['failed']}",crop)
  self.assertIn("' unresolved'",photos);self.assertIn("' verified'",photos);self.assertNotIn("Incomplete:",photos);self.assertNotIn(" else 'Ready'",photos)
  self.assertNotIn("Review worst",crop);self.assertNotIn("Applying crop model",crop)

 def test_landmarks_ui_reuses_established_overlay_and_has_no_reapply_button(self):
  from pathlib import Path
  root=Path(__file__).resolve().parents[1]
  section=(root/"app"/"ui"/"landmarks_section.py").read_text(encoding="utf-8")
  canvas=(root/"app"/"ui"/"landmark_canvas.py").read_text(encoding="utf-8")
  shell=(root/"app"/"ui"/"shell.py").read_text(encoding="utf-8")
  project=(root/"app"/"ui"/"project_section.py").read_text(encoding="utf-8")
  self.assertNotIn("self.prediction_info=ttk.Label",section)
  self.assertNotIn("predict_actions,'Reapply'",section)
  self.assertIn("set_context_message",section)
  self.assertIn('fill="#ffdf80",font=("Segoe UI",10,"bold")',canvas)
  self.assertIn('"Incomplete":"Unresolved"',shell)
  self.assertIn("def _repeatability_diagram",section)
  self.assertIn('text="Project overview"',project)



if __name__=="__main__":unittest.main()
