import tempfile,unittest
from pathlib import Path
from app.project_storage import Project
from app.crop_evaluation import iou
class T(unittest.TestCase):
 def p(self):
  d=Path(tempfile.mkdtemp());s=d/'s';s.mkdir();[(s/f'{n}.jpg').write_bytes(b'x') for n in ('a','b')];f=d/'x.csv';f.write_text("id,abbr,name,role\n1,A,A,BOTH\n");return Project.create('p',s,d,f,source_types=['jpg'])
 def test_holdout_persists_and_excludes_training(self):
  p=self.p();h,ids=p.create_crop_holdout(1,7);self.assertEqual(p.crop_holdout_id(),h);self.assertEqual(tuple(x['image_id'] for x in p.crop_holdout_images()),ids)
 def test_iou(self):self.assertEqual(iou([0,0,10,10],[0,0,10,10]),1.0);self.assertEqual(iou([0,0,10,10],[10,10,20,20]),0.0)
 def test_unknown_old_crop_is_not_auto_holdout(self):
  p=self.p();i=p.catalog_rows()[0]['image_id'];p.save_crop(i,{"crop_bounds":[1,1,9,9]},'manual');self.assertIsNone(p.crop_holdout_id())
 def test_holdout_excluded_from_training(self):
  p=self.p();h,ids=p.create_crop_holdout(1);i=ids[0];p.save_crop(i,{"crop_bounds":[1,1,9,9]},'manual');self.assertNotIn(i,p.crop_training_eligible_ids())
