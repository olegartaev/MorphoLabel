import hashlib
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.crop_workflow import apply_reviewed_crop

class CropWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);self.source=root/'source';(self.source/'sample').mkdir(parents=True);self.image=self.source/'sample'/'fish.jpg';Image.new('RGB',(40,30),'white').save(self.image);schema=root/'schema.csv';schema.write_text('id,abbr,name\n1,A,Anterior\n',encoding='utf-8');self.project=Project.create('p',self.source,root,schema,source_layout='direct');self.row=self.project.catalog_rows()[0];self.before=hashlib.sha256(self.image.read_bytes()).hexdigest()
 def tearDown(self):self.temp.cleanup()
 def test_main_workspace_crop_service_preserves_source_and_writes_reversible_crop(self):
  base=Image.open(self.image).convert('RGB');target=self.project.cache_root/'standardized'/f"{self.row['image_id']}.png";apply_reviewed_crop(self.project,self.row['image_id'],base,(3,2,34,27),0,target,self.image)
  crop=self.project.crop_record(self.row['image_id']);self.assertTrue(target.is_file());self.assertEqual([3,2,34,27],crop['crop_json']);self.assertIsNotNone(crop['transform_json']);self.assertEqual(self.before,hashlib.sha256(self.image.read_bytes()).hexdigest())
if __name__=='__main__':unittest.main()