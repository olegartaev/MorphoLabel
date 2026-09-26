import tempfile,unittest
from pathlib import Path
from app.project_storage import Project
class T(unittest.TestCase):
 def test_membership_breakdown(self):
  d=Path(tempfile.mkdtemp());s=d/'s';s.mkdir();(s/'a.jpg').write_bytes(b'x');f=d/'s.csv';f.write_text("id,abbr,name,role\n1,A,A,BOTH\n");p=Project.create('p',s,d,f,source_types=['jpg']);i=p.catalog_rows()[0]['image_id'];p.register_model('old','crop',path='models/old',active=False);p.record_crop_training_membership('old',[i]);x=p.crop_training_breakdown('old',[i,'new']);self.assertEqual(x['previous_training_count'],1);self.assertEqual(x['current_training_count'],2);self.assertEqual(x['delta_training_count'],1);self.assertEqual(x['added_to_training_now'],1)
 def test_no_previous(self):
  d=Path(tempfile.mkdtemp());s=d/'s';s.mkdir();(s/'a.jpg').write_bytes(b'x');f=d/'s.csv';f.write_text("id,abbr,name,role\n1,A,A,BOTH\n");p=Project.create('p',s,d,f,source_types=['jpg']);x=p.crop_training_breakdown(None,['x']);self.assertIsNone(x['previous_training_count']);self.assertEqual(x['current_training_count'],1)
