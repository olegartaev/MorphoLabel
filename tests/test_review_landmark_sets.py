import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.editor_ready_v15 import ReadyEditorV15
from app.landmark_review import structural_warnings
from app.landmark_ai_workflow import create_stage
from app.project_storage import Project


class _Status:
 def __init__(self):self.text=""
 def config(self,**kwargs):self.text=kwargs.get("text",self.text)


class ReviewLandmarkSetsTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());source=self.root/"source";source.mkdir()
  for number in range(6):(source/f"fish_{number}.jpg").write_bytes(b"x")
  schema=self.root/"schema.csv";schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n",encoding="utf-8")
  self.project=Project.create("project",source,self.root,schema,source_layout="direct");self.control=list(create_stage(self.project,"CONTROL_SET",5)["control_image_ids"]);self.image_id=self.control[0]
  for landmark_id in (1,2):self.project.save_landmark(self.image_id,landmark_id,10,10,"present","manual")
  self.project.mark_checked(self.image_id);self.warning=structural_warnings(self.project,self.image_id,100,100)[0];self.warning.update({"image_id":self.image_id,"display_name":"fish.jpg","severity":"warning"})
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def test_control_set_entry_paths_start_same_scan_and_highlight_same_landmarks(self):
  editor=ReadyEditorV15.__new__(ReadyEditorV15);editor.project=self.project;editor.images=[{"image_id":self.image_id}];editor.current=lambda:{"image_id":self.image_id};editor._set_landmark_workflow_controls=lambda:None;editor._open_landmark_workflow_item=lambda position:None;started=[];editor._start_landmark_set_review_scan=lambda ids,problems_only:started.append((tuple(ids),problems_only))
  editor.review_landmark_set("CONTROL_SET");editor.review_control_set()
  self.assertEqual([(tuple(self.control),True),(tuple(self.control),True)],started)
  editor._landmark_set_review_active=True;editor._landmark_set_review_warnings={self.image_id:[self.warning]};editor._review_active_ids=set();editor._load_current_landmark_state=lambda:SimpleNamespace(image_id=self.image_id);editor._refresh_landmark_list=lambda state:setattr(editor,"highlighted",set(editor._review_active_ids));editor.render=lambda:None;editor.review_status=_Status();editor._render_signature=None
  editor._apply_landmark_set_review_warnings();self.assertEqual({1,2},editor.highlighted)
 def test_checked_accepts_warning_then_changed_coordinates_make_it_stale(self):
  editor=ReadyEditorV15.__new__(ReadyEditorV15);editor.project=self.project;editor.current=lambda:{"image_id":self.image_id,"source_relpath":"fish.jpg"};editor._load_current_landmark_state=lambda:SimpleNamespace(image_id=self.image_id,complete=True);editor._landmark_workflow_review_only=True;editor._landmark_set_review_warnings={self.image_id:[self.warning]};editor._review_active_ids={1,2};editor.refresh_project_ui=lambda state:None
  ReadyEditorV15.mark_checked(editor)
  self.assertTrue(self.project.review_warning_is_accepted(self.image_id,self.warning));self.assertNotIn(self.image_id,editor._landmark_set_review_warnings);self.assertEqual(set(),editor._review_active_ids)
  for landmark_id in (1,2):self.project.save_landmark(self.image_id,landmark_id,11,10,"present","corrected_by_human")
  self.assertFalse(self.project.review_warning_is_accepted(self.image_id,self.warning));self.assertTrue(any(item["kind"]=="duplicate" for item in structural_warnings(self.project,self.image_id,100,100)))
 def test_problems_only_zero_warning_branch_shows_completion_popup(self):
  source=(Path(__file__).parents[1]/"app"/"editor_ready_v15.py").read_text(encoding="utf-8")
  self.assertIn('messagebox.showinfo("Review complete",f"No suspicious landmarks found.\\nImages checked: {len(ids)}",parent=self)',source)
if __name__ == "__main__":unittest.main()