import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.landmark_attention_queue import (
 active, classify, complete_current, current, move, record_failure, remove_image, start, stage_counts, user_copy
)


class FakeProject:
 def __init__(self):
  self.ui={}
  self.rows={image_id:{"image_id":image_id,"excluded":False} for image_id in ("a","b","c")}
  self.points={image_id:{} for image_id in self.rows}
  self.schema=[{"id":1}]
  self.locked=set();self.review_ready=set();self.crop_review=set()
 def get_ui_state(self,key,default=None):return self.ui.get(key,default)
 def set_ui_state(self,key,value):self.ui[key]=value
 def catalog_row(self,image_id):return self.rows.get(str(image_id))
 def landmark_prediction_locked(self,image_id):return str(image_id) in self.locked
 def landmark_ai_review_ready(self,image_id):return str(image_id) in self.review_ready
 def landmark_crop_review_required(self,image_id):return str(image_id) in self.crop_review
 def load_landmarks(self,image_id):return self.points[str(image_id)]


class LandmarkAttentionQueueTests(unittest.TestCase):
 def setUp(self):
  self.project=FakeProject()
  self.crops={image_id:{"provenance":"manual","human_verified":1} for image_id in self.project.rows}
  self.complete={image_id:False for image_id in self.project.rows}
  self.frame_ready={image_id:True for image_id in self.project.rows}
  self.patches=[
   patch("app.landmark_attention_queue.crop_frame_record",side_effect=lambda _p,image_id:self.crops.get(str(image_id))),
   patch("app.landmark_attention_queue.landmark_prediction_frame_ready",side_effect=lambda _p,image_id:self.frame_ready.get(str(image_id),False)),
   patch("app.landmark_attention_queue.load_current_landmark_state",side_effect=lambda _p,image_id:SimpleNamespace(complete=self.complete[str(image_id)])),
  ]
  for item in self.patches:item.start()
 def tearDown(self):
  for item in reversed(self.patches):item.stop()

 def test_queue_stage_rederives_from_authoritative_state(self):
  start(self.project,("a",),batch_id="batch")
  self.assertEqual("prediction",current(self.project)["stage"])
  self.project.points["a"]={1:{"provenance":"machine","model_id":"m"}}
  self.complete["a"]=True
  self.assertEqual("landmarks",current(self.project)["stage"])
  self.project.review_ready.add("a")
  self.assertIsNone(current(self.project))
  self.assertIsNone(active(self.project))

 def test_crop_problem_stays_same_item_until_crop_is_fixed(self):
  self.crops["a"]=None
  start(self.project,("a","b"))
  self.assertEqual(("a","crop"),(current(self.project)["image_id"],current(self.project)["stage"]))
  self.crops["a"]={"provenance":"manual","human_verified":1}
  self.assertEqual(("a","prediction"),(current(self.project)["image_id"],current(self.project)["stage"]))
  self.assertEqual("b",move(self.project,1)["image_id"])

 def test_confirmed_crop_with_landmark_review_flag_goes_to_landmarks_not_crop(self):
  self.project.crop_review.add("a")
  self.project.points["a"]={1:{"provenance":"machine","model_id":"m"}}
  self.complete["a"]=True
  issue=classify(self.project,"a")
  self.assertEqual("landmarks",issue["stage"])
  self.assertIn("Crop change",issue["reason"])
  copy=user_copy(issue)
  self.assertIn("not be sent back to Crop",copy["message"])

 def test_incomplete_machine_state_on_confirmed_changed_crop_retries_ai(self):
  self.project.crop_review.add("a")
  self.project.points["a"]={1:{"provenance":"machine","model_id":"old-model","state":"unresolved"}}
  self.complete["a"]=False
  issue=classify(self.project,"a")
  self.assertEqual("prediction",issue["stage"])
  self.assertIn("refresh non-human landmarks",issue["reason"])
  self.assertEqual("Retry AI",user_copy(issue)["action"])

 def test_only_protected_human_gap_does_not_repredict_finished_machine_slots(self):
  self.project.schema=[{"id":1},{"id":2}]
  self.project.crop_review.add("a")
  self.project.points["a"]={
   1:{"provenance":"manual","state":"unresolved","x_standardized":None,"y_standardized":None},
   2:{"provenance":"machine","model_id":"new-model","state":"auto","x_standardized":10.0,"y_standardized":10.0},
  }
  self.complete["a"]=False
  issue=classify(self.project,"a")
  self.assertEqual("landmarks",issue["stage"])
  self.assertIn("protected human",issue["reason"])

 def test_prediction_result_stage_counts_match_next_actions(self):
  self.crops["a"]=None
  self.project.points["b"]={1:{"provenance":"machine","model_id":"m"}}
  self.complete["b"]=True
  counts=stage_counts(self.project,("a","b","c"))
  self.assertEqual(1,counts["crop"])
  self.assertEqual(1,counts["landmarks"])
  self.assertEqual(1,counts["prediction"])
  self.assertEqual(3,counts["total"])

 def test_exclusion_removes_current_without_collapsing_queue(self):
  start(self.project,("a","b","c"))
  next_issue=remove_image(self.project,"a")
  self.assertEqual("b",next_issue["image_id"])
  self.assertEqual(["b","c"],active(self.project)["image_ids"])

 def test_failure_reason_persists_until_retry_succeeds(self):
  start(self.project,("a",))
  record_failure(self.project,"a","backend failure")
  self.assertEqual("backend failure",current(self.project)["reason"])
  self.project.points["a"]={1:{"provenance":"machine","model_id":"m"}}
  self.complete["a"]=True
  self.assertEqual("Review the AI landmark prediction",current(self.project)["reason"])

 def test_display_summary_is_persisted_and_does_not_reclassify_whole_queue(self):
  from app.landmark_attention_queue import display_summary
  start(self.project,("a","b","c"))
  first=current(self.project)
  self.assertEqual("a",first["image_id"])
  with patch("app.landmark_attention_queue.classify",side_effect=AssertionError("status repaint must not classify")):
   shown=display_summary(self.project)
  self.assertEqual(("a",3),(shown["image_id"],shown["remaining"]))

 def test_user_copy_explains_why_the_queue_changed_workspace(self):
  crop_copy=user_copy({"stage":"crop","reason":"Crop is missing or invalid"})
  self.assertEqual("Crop needs attention",crop_copy["title"])
  self.assertEqual("Confirm crop & continue",crop_copy["action"])
  self.assertIn("review queue",crop_copy["message"])
  retry_copy=user_copy({"stage":"prediction","reason":"trace\\nValueError: coordinates outside frame"})
  self.assertEqual("Retry AI",retry_copy["action"])
  self.assertIn("ValueError: coordinates outside frame",retry_copy["message"])
  landmark_copy=user_copy({"stage":"landmarks","reason":"Review the AI landmark prediction"})
  self.assertEqual("Verify & continue",landmark_copy["action"])

 def test_complete_current_advances_and_preserves_history(self):
  start(self.project,("a","b"),batch_id="batch")
  issue=complete_current(self.project,"a")
  self.assertEqual("b",issue["image_id"])
  self.assertIn("a",active(self.project)["completed_ids"])


if __name__=="__main__":
 unittest.main()
