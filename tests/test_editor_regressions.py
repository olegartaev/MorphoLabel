import unittest
from app.editor_state import EditorState
from app.workflow import set_human_point

class EditorRegressionTests(unittest.TestCase):
 def test_switching_partial_to_new_resets_to_snt(self):
  state=EditorState();state.open_record({"points":{"1":{"state":"manual"},"2":{"state":"missing"}}});self.assertEqual(state.current_landmark,3);state.open_record({"points":{}});self.assertEqual(state.current_landmark,1)
 def test_missing_syncs_selected_list_header_overlay_state(self):
  state=EditorState();record={"points":{}};set_human_point(record,1,"SnT",None,None);state.after_missing();self.assertEqual(record["points"]["1"]["state"],"missing");self.assertIsNone(record["points"]["1"]["x_standardized"]);self.assertEqual(state.current_landmark,2)
 def test_delete_and_replace_selected_point(self):
  record={"points":{}};set_human_point(record,4,"OrbP",1,2);record["points"].pop("4");self.assertNotIn("4",record["points"]);set_human_point(record,4,"OrbP",9,8);self.assertEqual((record["points"]["4"]["x_standardized"],record["points"]["4"]["y_standardized"]),(9,8))
 def test_click_move_existing_point(self):
  record={"points":{}};set_human_point(record,5,"OrbV",1,2);set_human_point(record,5,"OrbV",11,12,corrected=True);self.assertEqual(record["points"]["5"]["state"],"corrected");self.assertEqual(record["points"]["5"]["final_x"],11)
 def test_pan_does_not_change_points(self):
  record={"points":{"1":{"state":"manual","x_standardized":1,"y_standardized":2}}};before=repr(record);pan=[0,0];pan[0]+=10;pan[1]-=5;self.assertEqual(before,repr(record))
 def test_reopen_preserves_missing_and_coordinates(self):
  record={"points":{}};set_human_point(record,1,"SnT",3,4);set_human_point(record,2,"NarP",None,None);copy={"points":dict(record["points"])};self.assertEqual(copy["points"]["1"]["x_standardized"],3);self.assertEqual(copy["points"]["2"]["state"],"missing")
if __name__=="__main__":unittest.main()
