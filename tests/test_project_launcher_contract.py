import inspect, tempfile, unittest, shutil
from pathlib import Path
from unittest.mock import patch
from app.project_storage import Project
from app.project_runtime import active_project, open_project
from app.editor_ready_v15 import ReadyEditorV15

class ProjectLauncherContractTests(unittest.TestCase):
 def test_v15_accepts_project_keyword_and_passes_context_to_base(self):
  self.assertIn("project", inspect.signature(ReadyEditorV15.__init__).parameters)
  temp=Path(tempfile.mkdtemp())
  try:
   raw=temp/"raw";raw.mkdir();schema=temp/"schema.csv";schema.write_text("id,abbr,name\n2,A,Alpha\n7,B,Beta\n",encoding="utf-8");p=Project.create("p",raw,temp,schema)
   with patch("app.editor_ready_v15.PrefetchManager"), patch("app.editor_ready_v11.ReadyEditorV11.__init__",return_value=None) as base:
    ReadyEditorV15(project=p)
   self.assertIs(active_project(),p);base.assert_called_once_with(project=p)
  finally:shutil.rmtree(temp,ignore_errors=True)
 def test_start_screen_keeps_schema_editor_inside_project(self):
  source=Path('app/project_gui.py').read_text(encoding='utf-8')
  self.assertIn('text="New Project"',source);self.assertIn('text="Open Project"',source)
  self.assertNotIn('text="Landmark Schema Editor"',source)
 def test_modular_landmark_training_has_confirmed_real_start(self):
  source=Path('app/ui/landmarks_section.py').read_text(encoding='utf-8')
  self.assertIn('run_landmark_training',source);self.assertIn('Start training',source)
  self.assertIn('production-landmark-model-training',source)
 def test_project_reopen_context_restores_schema_and_images(self):
  temp=Path(tempfile.mkdtemp())
  try:
   raw=temp/"raw";raw.mkdir();(raw/"a.jpg").write_bytes(b"x");schema=temp/"schema.csv";schema.write_text("id,abbr,name\n11,X,Xray\n",encoding="utf-8");p=Project.create("p",raw,temp,schema);reopened=Project.open(p.root);open_project(reopened.root)
   self.assertEqual([(r["id"],r["abbr"]) for r in reopened.schema],[(1,"X")]);self.assertEqual(reopened.count("images"),1);self.assertEqual(reopened.source_root,raw.resolve())
  finally:shutil.rmtree(temp,ignore_errors=True)
if __name__=="__main__":unittest.main()



