import math
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.landmark_review import early_identity_warnings, scan_project

BASE={1:(10,10),2:(90,10),3:(20,45),4:(75,50),5:(50,90)}
def transform(point, angle=.0, scale=1., shift=(0,0)):
 x,y=point;c,s=math.cos(angle),math.sin(angle);return (scale*(c*x-s*y)+shift[0],scale*(s*x+c*y)+shift[1])
class EarlyIdentityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());source=self.tmp/'source';source.mkdir()
  for n in range(5):(source/f'{n}.jpg').write_bytes(b'x')
  schema=self.tmp/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,A,BOTH\n2,B,B,BOTH\n3,C,C,BOTH\n4,D,D,BOTH\n5,E,E,CLASSICAL\n',encoding='utf8')
  self.p=Project.create('p',source,self.tmp,schema,source_layout='direct');self.ids=[r['image_id'] for r in self.p.catalog_rows()]
  for ident in self.ids:Image.new('RGB',(200,200)).save(self.p.cache_root/'standardized'/f'{ident}.png')
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def put(self,ident,angle=0,scale=1,shift=(0,0),swap=False):
  for n,point in BASE.items():
   source=BASE[2 if n==1 else 1] if swap and n in (1,2) else point;x,y=transform(source,angle,scale,shift);self.p.save_landmark(ident,n,x,y,'manual',provenance='manual')
 def test_two_images_swapped_are_neutral_and_both_queued(self):
  self.put(self.ids[0]);self.put(self.ids[1],angle=.35,scale=1.2,shift=(20,15),swap=True)
  result=early_identity_warnings(self.p);warnings=[w for w in result['warnings'] if {w['landmark_id'],w['other_landmark_id']}=={1,2}]
  self.assertTrue(result['available']);self.assertEqual({w['image_id'] for w in warnings},{self.ids[0],self.ids[1]});self.assertTrue(all(w['kind']=='early_identity_inconsistency' for w in warnings))
 def test_three_images_identify_swapped_specimen(self):
  self.put(self.ids[0]);self.put(self.ids[1],angle=.1,shift=(3,7));self.put(self.ids[2],angle=-.2,scale=.8,shift=(15,6),swap=True)
  warnings=early_identity_warnings(self.p)['warnings'];self.assertTrue(any(w['image_id']==self.ids[2] and w['kind']=='early_swap_suggestion' for w in warnings))
 def test_flexible_landmarks_moving_together_do_not_suggest_swap(self):
  self.put(self.ids[0]);self.put(self.ids[1]);
  # A/ B move together, preserving their identity relationship.
  self.p.save_landmark(self.ids[1],1,10,70,'manual',provenance='manual');self.p.save_landmark(self.ids[1],2,90,70,'manual',provenance='manual')
  self.assertFalse(early_identity_warnings(self.p)['warnings'])
 def test_one_image_reports_cross_image_unavailable(self):
  self.put(self.ids[0]);result=scan_project(self.p);self.assertFalse(result['early_cross_image']);self.assertEqual(result['early_annotated_images'],1)
 def test_two_clean_images_have_no_identity_warning(self):
  self.put(self.ids[0]);self.put(self.ids[1],angle=.35,scale=1.2,shift=(20,15));self.assertEqual(early_identity_warnings(self.p)['warnings'],())
 def test_scan_is_read_only(self):
  self.put(self.ids[0]);self.put(self.ids[1],swap=True);before=self.p.load_landmarks(self.ids[0]);scan_project(self.p);self.assertEqual(self.p.load_landmarks(self.ids[0]),before)
if __name__=='__main__':unittest.main()