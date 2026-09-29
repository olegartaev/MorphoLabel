import unittest
from types import SimpleNamespace

from app.ui.project_section import sorted_project_samples
from app.ui.landmarks_section import _prediction_context_text


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
  self.assertIn("m1",value);self.assertIn("2/2 landmarks",value);self.assertIn("review pending",value)


if __name__=="__main__":unittest.main()
