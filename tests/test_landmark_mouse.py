import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.editor_ready import ReadyEditor
from app.editor_state import EditorState

class LandmarkMouseTests(unittest.TestCase):
 def editor(self,points=None):
  e=SimpleNamespace(source_mode=False,calibration=None,record={"points":points or {}},profile=SimpleNamespace(landmarks=[SimpleNamespace(code=f"p{i}") for i in range(1,26)]),state=EditorState(25),pan=[0.,0.],zoom=1.,dragging=None)
  e.image_point=lambda x,y:(x,y);e.sync=lambda:None;e.render=lambda:None
  return e
 def event(self,x,y):return SimpleNamespace(x=x,y=y)
 def test_existing_click_drag_moves_same_id(self):
  e=self.editor({"2":{"x_standardized":10.,"y_standardized":10.,"state":"manual"}})
  with patch("app.editor_ready.save_record"):
   ReadyEditor.left_down(e,self.event(11,10));self.assertEqual(e.dragging,2);self.assertEqual(e.state.current_landmark,2)
   ReadyEditor.left_drag(e,self.event(30,40));ReadyEditor.left_up(e,self.event(30,40))
  self.assertEqual(set(e.record["points"]),{"2"});self.assertEqual((e.record["points"]["2"]["x_standardized"],e.record["points"]["2"]["y_standardized"]),(30,40));self.assertEqual(e.record["points"]["2"]["state"],"corrected")
 def test_blank_click_adds_lowest_missing(self):
  e=self.editor({"1":{},"2":{},"4":{},"5":{}})
  with patch("app.editor_ready.save_record"):ReadyEditor.left_down(e,self.event(200,200))
  self.assertIn("3",e.record["points"])
 def test_blank_click_after_all_points_does_nothing(self):
  e=self.editor({str(i):{"x_standardized":i,"y_standardized":i} for i in range(1,26)})
  with patch("app.editor_ready.save_record") as saved:ReadyEditor.left_down(e,self.event(500,500))
  self.assertEqual(len(e.record["points"]),25);saved.assert_not_called()
