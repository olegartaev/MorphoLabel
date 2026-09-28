import unittest, tempfile, shutil
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.crop_editor_async_v2 import load_project_developed
from app.crop_editor_async import AsyncCropEditor
class AsyncCropEditorTests(unittest.TestCase):
 def test_async_editor_type_exists(self):self.assertTrue(issubclass(AsyncCropEditor,object))
 def test_missing_project_cache_rebuilds_from_available_source(self):
  root=Path(tempfile.mkdtemp()); src=root/"source"; src.mkdir(); schema=root/"schema.csv"; schema.write_text("id,abbr,name\n1,A,Alpha\n")
  try:
   Image.new("RGB",(40,24),(10,20,30)).save(src/"one.jpg")
   project=Project.create("p",src,root,schema,source_types=["jpg"],source_layout="direct")
   ident=project.catalog_rows()[0]["image_id"]; target=project.cache_root/"developed"/f"{ident}.png"
   self.assertFalse(target.exists())
   full,proxy=load_project_developed(project,ident)
   self.assertEqual((40,24),full.size);self.assertEqual("RGB",proxy.mode);self.assertTrue(target.is_file())
  finally: shutil.rmtree(root,ignore_errors=True)
 def test_project_cache_load_does_not_require_raw(self):
  root=Path(tempfile.mkdtemp()); src=root/"raw"; src.mkdir(); schema=root/"schema.csv"; schema.write_text("id,abbr,name\n1,A,Alpha\n")
  try:
   (src/"s").mkdir(); (src/"s"/"one.nef").write_bytes(b"raw")
   project=Project.create("p",src,root,schema,source_types=["nef"]); conn=project.connect(); ident=conn.execute("select image_id from images").fetchone()[0]; conn.close()
   Image.new("RGB",(32,20),(1,2,3)).save(project.cache_root/"developed"/f"{ident}.png"); shutil.rmtree(src)
   full,proxy=load_project_developed(project,ident); self.assertEqual(full.size,(32,20)); self.assertEqual(proxy.mode,"RGB")
  finally: shutil.rmtree(root,ignore_errors=True)

if __name__=="__main__":unittest.main()
