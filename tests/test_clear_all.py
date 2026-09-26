import tempfile,unittest
from pathlib import Path
from app.editor_state import EditorState
from app.landmark_actions import clear_all_landmarks
import app.recovery as recovery

class ClearAllTests(unittest.TestCase):
 def make_record(self,image="a"):
  return {"sample_id":"s","image_id":image,"points":{str(i):{"state":"missing" if i%2 else "manual","x_standardized":None if i%2 else i} for i in range(1,26)}}
 def test_clear_resets_all_and_current_to_snt(self):
  r=self.make_record();clear_all_landmarks(r);s=EditorState();s.open_record(r);self.assertEqual(r["points"],{});self.assertEqual(s.current_landmark,1)
 def test_undo_after_clear_restores_complete_state(self):
  old=recovery.WORK
  try:
   with tempfile.TemporaryDirectory() as d:
    recovery.WORK=Path(d);r=self.make_record();recovery.snapshot(r,"before_clear");clear_all_landmarks(r);restored=recovery.restore_latest(r);self.assertEqual(len(restored["points"]),25);self.assertEqual(restored["points"]["1"]["state"],"missing")
  finally:recovery.WORK=old
 def test_clear_only_current_record(self):
  a=self.make_record("a");b=self.make_record("b");clear_all_landmarks(a);self.assertEqual(len(a["points"]),0);self.assertEqual(len(b["points"]),25)
if __name__=="__main__":unittest.main()
