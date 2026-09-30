import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.landmark_attention_queue import (
 active, classify, complete_current, current, move, record_failure, remove_image, start
)


class FakeProject:
 def __init__(self):
  self.ui={}
  self.rows={image_id:{"image_id":image_id,"excluded":False} for image_id in ("a","b","c")}
  self.points={image_id:{} for image_id in self.rows}
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
   patch("app.landmark_attention_queue.landmark_frame_ready",side_effect=lambda _p,image_id:self.frame_ready.get(str(image_id),False)),
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

 def test_complete_current_advances_and_preserves_history(self):
  start(self.project,("a","b"),batch_id="batch")
  issue=complete_current(self.project,"a")
  self.assertEqual("b",issue["image_id"])
  self.assertIn("a",active(self.project)["completed_ids"])


if __name__=="__main__":
 unittest.main()
