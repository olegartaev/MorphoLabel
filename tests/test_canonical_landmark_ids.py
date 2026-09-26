import unittest
from pathlib import Path
from app.landmark_ids import (landmark_id, number_from_id, list_index_to_number,
                               number_to_list_index, record_key)
from app.workflow import set_human_point
from app.editor_state import EditorState
from app.editor_ready_v15 import ReadyEditorV15

class CanonicalLandmarkIdTests(unittest.TestCase):
 def test_ids_are_schema_values_and_round_trip(self):
  self.assertEqual([landmark_id(i) for i in range(1,26)], [str(i) for i in range(1,26)])
  self.assertEqual([number_from_id(str(i)) for i in range(1,26)], list(range(1,26)))
 def test_sidebar_index_p7_maps_to_visual_and_storage_p7(self):
  self.assertEqual(list_index_to_number(6),7)
  self.assertEqual(number_to_list_index(7),6)
  record={"points":{}}
  set_human_point(record,7,"p7",10,11)
  self.assertEqual(record["points"]["7"]["landmark_id"],"7")
  self.assertEqual(number_from_id(record["points"]["7"]["landmark_id"]),7)
 def test_p_key_record_moves_without_duplicate(self):
  points={"7":{"x_standardized":1,"y_standardized":2}}
  self.assertEqual(record_key(points,7),"7")
  record={"points":points};set_human_point(record,7,"p7",9,8,corrected=True)
  self.assertEqual(set(record["points"]),{"7"})
  self.assertEqual((record["points"]["7"]["x_standardized"],record["points"]["7"]["y_standardized"]),(9,8))
 def test_first_unplaced_p3_after_reload(self):
  record={"points":{"P1":{},"P2":{},"P4":{}}}
  state=EditorState(25);state.open_record(record)
  self.assertEqual(state.current_landmark,3)

class PrefetchDepthTests(unittest.TestCase):
 def test_prefetch_has_exactly_five_following_rows(self):
  editor=ReadyEditorV15.__new__(ReadyEditorV15)
  editor.index=0
  editor.images=[{"source_relpath":f"orig_photos/{i}.nef"} for i in range(8)]
  self.assertEqual(len(editor._prefetch_sources()),5)
  self.assertEqual(editor._prefetch_sources()[-1],Path("orig_photos/5.nef"))

if __name__=="__main__":unittest.main()

