import unittest
from pathlib import Path
from types import SimpleNamespace
from app.editor_ready_v15 import ReadyEditorV15
from app.editor_ready_v11 import ReadyEditorV11

class ProjectNavigationIdentityTests(unittest.TestCase):
 def test_project_canonical_id_never_rehashed_from_path(self):
  e=ReadyEditorV15.__new__(ReadyEditorV15)
  e.project=object()
  row={"image_id":"fa002e472ddb475d","source_relpath":"sample/orig/img_0011047.nef"}
  self.assertEqual(ReadyEditorV11._canonical_id(e,row,Path("G:/other-root/img_0011047.nef")),row["image_id"])

 def test_legacy_mode_still_uses_path_id(self):
  e=ReadyEditorV15.__new__(ReadyEditorV15)
  e.project=None
  row={"image_id":"legacy","source_relpath":"sample/img.png"}
  self.assertNotEqual(ReadyEditorV11._canonical_id(e,row,Path("sample/img.png")),"legacy")

 def test_navigation_record_id_is_canonical(self):
  e=ReadyEditorV15.__new__(ReadyEditorV15)
  e.project=object(); e.images=[]; e.index=0
  row={"image_id":"sqlite-id-3","source_relpath":"x/img.nef"}
  self.assertEqual(ReadyEditorV11._canonical_id(e,row,Path("x/img.nef")),"sqlite-id-3")

if __name__ == "__main__": unittest.main()
