import tempfile,unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
class T(unittest.TestCase):
 def test_project_rows_exclude_unreviewed_and_holdout(self):
  d=Path(tempfile.mkdtemp());src=d/'s';src.mkdir();[(src/f'{x}.jpg').write_bytes(b'x') for x in ('a','b')];f=d/'s.csv';f.write_text("id,abbr,name,role\n1,A,A,BOTH\n");p=Project.create('p',src,d,f,source_types=['jpg']);ids=[r['image_id'] for r in p.catalog_rows()]
  for i in ids:
   q=p.data_root/'cache/developed'/f'{i}.png';q.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(100,100)).save(q);p.save_crop(i,{"developed_full_relpath":f'cache/developed/{i}.png',"crop_bounds":[10,10,90,90]},'manual');p.save_reviewed_crop(i,{"developed_full_relpath":f'cache/developed/{i}.png',"crop_bounds":[10,10,90,90]})
  self.assertEqual(len(p.crop_training_rows()),2);p.create_crop_holdout(1);self.assertEqual(len(p.crop_training_rows()),1)
