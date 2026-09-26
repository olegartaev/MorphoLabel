import shutil,tempfile,unittest
from pathlib import Path
import tkinter as tk
from PIL import Image
from app.project_storage import Project
from app.landmark_state import load_current_landmark_state
from app.editor_state import EditorState
from app.profile import load_schema_profile
from app.editor_ready_v11 import ReadyEditorV11

class CanonicalLandmarkStateIntegrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());raw=self.tmp/"raw";raw.mkdir();(raw/"a.jpg").write_bytes(b"x")
  schema=self.tmp/"schema.csv";schema.write_text("id,abbr,name\n"+"\n".join(f"{i},P{i},Point {i}" for i in range(1,19)),encoding="utf-8")
  self.project=Project.create("p",raw,self.tmp,schema,source_layout="direct");self.image_id=self.project.catalog_rows()[0]["image_id"]
  with self.project.transaction() as c:
   for ident in range(19,25):c.execute("INSERT INTO landmark_schema(landmark_id,abbr,name) VALUES (?,?,?)",(ident,f"L{ident}",f"Legacy {ident}"))
  for ident in range(1,25):self.project.save_landmark(self.image_id,ident,ident,ident,"manual")
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def test_one_snapshot_drives_status_canvas_and_reopen(self):
  state=load_current_landmark_state(self.project,self.image_id)
  self.assertEqual(state.placed_count,18);self.assertEqual(state.expected_count,18);self.assertEqual(state.color,"green");self.assertEqual(state.extra_ids,frozenset(range(19,25)))
  try:root=tk.Tk();root.withdraw()
  except tk.TclError as exc:self.skipTest(str(exc))
  try:
   class Fake:pass
   editor=Fake();editor.project=self.project;editor.landmark_state=state;editor.standard=Image.new("RGB",(100,60),"black");editor.source=editor.standard;editor.source_mode=False;editor.zoom=1.;editor.pan=[0.,0.];editor.state=EditorState(point_ids=tuple(range(1,19)));editor.profile=load_schema_profile(self.project.schema_path);editor.record={"points":{}};editor.index=0;editor.images=[{"image_id":self.image_id,"source_relpath":"a.jpg"}];editor._render_signature=None;editor._display_cache=None;editor._display_image_id=self.image_id;editor._load_token=1;editor.navigation_render_counts={};editor.canvas=tk.Canvas(root,width=100,height=60);editor.canvas.pack();editor.header=tk.Label(root);editor.header.pack();editor.image=lambda:editor.standard;editor.current=lambda:{"image_id":self.image_id,"source_relpath":"a.jpg"};editor._canonical_id=lambda *_args:self.image_id;editor._point=lambda ident:editor.profile.by_id(ident);editor.after_idle=lambda _fn:None
   ReadyEditorV11.render(editor);root.update_idletasks()
   self.assertEqual(len(editor.canvas.find_withtag("landmark_overlay")),36)
   self.assertEqual(len(editor.canvas.find_withtag("landmark:19")),0)
  finally:root.destroy()
  self.project.mark_checked(self.image_id);checked=load_current_landmark_state(self.project,self.image_id);self.assertTrue(checked.human_verified);self.assertEqual(checked.color,"green")
  reopened=Project.open(self.project.root);again=load_current_landmark_state(reopened,self.image_id);self.assertTrue(again.human_verified);self.assertEqual(again.placed_count,18);self.assertEqual(again.extra_ids,frozenset(range(19,25)))
  reopened.replace_landmarks(self.image_id,{str(i):{"x_standardized":i,"y_standardized":i,"state":"manual","provenance":"manual"} for i in range(1,25) if i!=7})
  removed=load_current_landmark_state(reopened,self.image_id);self.assertEqual(removed.missing_ids,frozenset({7}));self.assertEqual(removed.color,"red")
  reopened.save_landmark(self.image_id,7,None,None,"missing",provenance="manual");marked=load_current_landmark_state(reopened,self.image_id);self.assertIn(7,marked.explicitly_missing_ids);self.assertEqual(marked.color,"green")

if __name__=="__main__":unittest.main()
