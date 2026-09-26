import unittest
from app.editor_state import EditorState

class EditorStateTests(unittest.TestCase):
 def test_open_new_resets_to_snt(self):self.assertEqual(EditorState().open_record({"points":{}}),1)
 def test_open_partial_uses_first_unplaced_not_prior_selection(self):self.assertEqual(EditorState(current_landmark=20).open_record({"points":{"1":{"state":"manual"},"2":{"state":"missing"}}}),3)
 def test_missing_advances_single_authoritative_state(self):
  s=EditorState(current_landmark=5);self.assertEqual(s.after_missing(),6);self.assertEqual(s.current_landmark,6)
 def test_existing_click_does_not_advance(self):
  s=EditorState(current_landmark=4);self.assertEqual(s.after_place_new(True),4)

if __name__=="__main__":unittest.main()
