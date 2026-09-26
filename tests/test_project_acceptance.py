import shutil,tempfile,unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.project_runtime import open_project
from app.normalization_pipeline import normalize,paths
from app.workflow import image_catalog,load_record,set_human_point,save_record
from app.editor_state import EditorState
from app.editor_ready_v15 import ReadyEditorV15

class ProjectAcceptanceTests(unittest.TestCase):
 def test_external_project_without_legacy_work(self):
  temp=Path(tempfile.mkdtemp())
  try:
   raw=temp/"raw";raw.mkdir();(raw/"sample").mkdir();Image.new("RGB",(80,50),(210,210,210)).save(raw/"sample"/"one.png");Image.new("RGB",(90,60),(200,200,200)).save(raw/"sample"/"two.png")
   schema=temp/"schema.csv";schema.write_text("id,abbr,name\n2,A,Alpha\n7,B,Beta\n",encoding="utf-8")
   project=Project.create("outside",raw,temp,schema);open_project(project.root);rows=image_catalog();self.assertEqual(len(rows),2)
   first=rows[0];source=Path(first["source_path"]);meta=normalize(source,force=True);self.assertTrue((project.cache_root/"developed"/f"{first['image_id']}.png").exists());self.assertTrue((project.cache_root/"standardized"/f"{first['image_id']}.png").exists())
   record=load_record(first,"schema","1");set_human_point(record,2,"A",10,11);save_record(record);set_human_point(record,2,"A",12,13,corrected=True);save_record(record)
   restored=Project.open(project.root).load_landmarks(first["image_id"]);self.assertEqual((restored[2]["x_standardized"],restored[2]["y_standardized"]),(12,13))
   state=EditorState(point_ids=(2,7));state.open_record(load_record(first,"schema","1"));self.assertEqual(state.current_landmark,7)
   editor=ReadyEditorV15.__new__(ReadyEditorV15);editor.images=rows;editor.index=0;self.assertEqual(len(editor._prefetch_sources()),1)
   project.export_landmarks();shutil.rmtree(project.cache_root);(project.cache_root).mkdir();normalize(source,force=True);self.assertEqual(Project.open(project.root).load_landmarks(first["image_id"])[2]["x_standardized"],12)
  finally:shutil.rmtree(temp,ignore_errors=True)
if __name__=="__main__":unittest.main()
