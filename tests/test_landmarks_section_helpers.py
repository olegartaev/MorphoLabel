import unittest

from app.ui.landmarks_section import _prediction_context_text


class _FakeProject:
 def __init__(self,points):self.points=points
 def load_landmarks(self,_image_id):return self.points


class LandmarkSectionHelperTests(unittest.TestCase):
 def test_prediction_stamp_ignores_model_ancestry_on_human_corrected_points(self):
  project=_FakeProject({
   1:{"provenance":"corrected_by_human","model_id":"rtmpose_v021","prediction_run_id":"old","updated_at":"2026-09-01T10:00:00+00:00"},
   2:{"provenance":"machine","model_id":"rtmpose_v035","prediction_run_id":"new","updated_at":"2026-10-01T10:00:00+00:00"},
  })
  text=_prediction_context_text(project,{"image_id":"fish","human_verified":False,"status_color":"yellow"})
  self.assertIn("rtmpose_v035",text)
  self.assertNotIn("rtmpose_v021",text)

 def test_prediction_stamp_can_show_real_mixed_machine_state(self):
  project=_FakeProject({
   1:{"provenance":"machine","model_id":"rtmpose_v021","prediction_run_id":"old","updated_at":"2026-09-01T10:00:00+00:00"},
   2:{"provenance":"machine","model_id":"rtmpose_v035","prediction_run_id":"new","updated_at":"2026-10-01T10:00:00+00:00"},
  })
  text=_prediction_context_text(project,{"image_id":"fish","human_verified":False,"status_color":"yellow"})
  self.assertIn("rtmpose_v021",text)
  self.assertIn("rtmpose_v035",text)


if __name__=="__main__":
 unittest.main()
