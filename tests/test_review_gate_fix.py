import shutil,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.landmark_review import scan_project, trusted_identity_warnings
from app.active_learning import _ai_worst_first_eligible
class ReviewGateFixTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());src=self.tmp/'src';src.mkdir()
  for n in range(10):(src/f'{n}.jpg').write_bytes(b'x')
  s=self.tmp/'s.csv';s.write_text('id,abbr,name,role\n1,A,A,BOTH\n2,B,B,BOTH\n3,C,C,BOTH\n4,D,D,BOTH\n5,E,E,BOTH\n6,F,F,BOTH\n',encoding='utf8');self.p=Project.create('p',src,self.tmp,s,source_layout='direct');self.ids=[r['image_id'] for r in self.p.catalog_rows()]
  for i in self.ids:Image.new('RGB',(100,100)).save(self.p.cache_root/'standardized'/f'{i}.png')
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def put(self,ident,swap=False,missing=False,auto=False):
  xy={1:(10,10),2:(90,10),3:(10,90),4:(90,90),5:(50,50),6:(55,65)}
  for i in xy:
   if missing and i==5:self.p.save_landmark(ident,i,None,None,'missing',provenance='manual');continue
   source=2 if swap and i==1 else 1 if swap and i==2 else i;self.p.save_landmark(ident,i,*xy[source],'auto' if auto else 'manual',provenance='machine' if auto else 'manual')
 def test_review_worst_excludes_generic_human_verified_ai_origin(self):
  image_id=self.ids[0]
  class Snapshot:
   def annotation_status(self,_image_id):return {'verified':True,'complete':True}
  class ProjectGate:
   def landmark_ai_review_ready(self,_image_id):return False
  rows={1:{'provenance':'machine','model_id':'m','prediction_run_id':'r','state':'present','x_standardized':10.0,'y_standardized':11.0}}
  self.assertFalse(_ai_worst_first_eligible(ProjectGate(),Snapshot(),image_id,rows))

 def test_review_worst_keeps_unverified_ai_origin(self):
  image_id=self.ids[0]
  class Snapshot:
   def annotation_status(self,_image_id):return {'verified':False,'complete':True}
  class ProjectGate:pass
  rows={1:{'provenance':'machine','model_id':'m','prediction_run_id':'r','state':'present','x_standardized':10.0,'y_standardized':11.0}}
  with patch('app.active_learning.landmark_frame_ready',return_value=True):
   self.assertTrue(_ai_worst_first_eligible(ProjectGate(),Snapshot(),image_id,rows))

 def test_review_worst_excludes_all_unresolved_ai_placeholders(self):
  image_id=self.ids[0]
  class Snapshot:
   def annotation_status(self,_image_id):return {'verified':False,'complete':False}
  class ProjectGate:pass
  rows={1:{'provenance':'machine','model_id':'m','prediction_run_id':'r','state':'unresolved','x_standardized':None,'y_standardized':None}}
  self.assertFalse(_ai_worst_first_eligible(ProjectGate(),Snapshot(),image_id,rows))

 def test_review_worst_excludes_complete_ai_without_canonical_crop(self):
  image_id=self.ids[0]
  class Snapshot:
   def annotation_status(self,_image_id):return {'verified':False,'complete':True}
  class ProjectGate:pass
  rows={1:{'provenance':'machine','model_id':'m','prediction_run_id':'r','state':'present','x_standardized':10.0,'y_standardized':11.0}}
  with patch('app.active_learning.landmark_frame_ready',return_value=False):
   self.assertFalse(_ai_worst_first_eligible(ProjectGate(),Snapshot(),image_id,rows))

 def test_eight_manual_one_checked_has_trusted_identity_mode(self):
  for ident in self.ids[:8]:self.put(ident,swap=ident==self.ids[1])
  [self.p.clear_checked(i) for i in self.ids[1:8]];self.p.mark_checked(self.ids[0]);result=scan_project(self.p);self.assertTrue(result['trusted_reference_identity']);self.assertFalse(result['early_cross_image']);self.assertEqual(len(result['trusted_reference_ids']),1);self.assertTrue(any(x['image_id']==self.ids[1] for x in result['queue']))
 def test_manual_missing_still_usable_for_other_group(self):
  self.put(self.ids[0]);self.p.mark_checked(self.ids[0]);self.put(self.ids[1],swap=True,missing=True);self.p.clear_checked(self.ids[1]);warnings=trusted_identity_warnings(self.p)['warnings'];self.assertTrue(any(x['image_id']==self.ids[1] for x in warnings))
 def test_three_cycle_and_reassignment_preserves_machine_history_and_undo(self):
  self.put(self.ids[0]);self.p.save_landmark(self.ids[0],1,10,10,'auto',provenance='machine',predicted_x=10,predicted_y=10,model_id='m',confidence=.9,prediction_run_id='r');self.p.save_landmark(self.ids[0],2,90,10,'auto',provenance='machine',predicted_x=90,predicted_y=10,model_id='m',confidence=.8,prediction_run_id='r')
  before=self.p.reassign_present_landmarks(self.ids[0],{1:2,2:1});rows=self.p.load_landmarks(self.ids[0]);self.assertEqual((rows[1]['x_standardized'],rows[1]['predicted_x'],rows[1]['prediction_run_id']),(90,10,'r'));self.assertEqual(rows[1]['provenance'],'corrected_by_human');self.p.restore_landmark_finals(self.ids[0],before);self.assertEqual(self.p.load_landmarks(self.ids[0])[1]['x_standardized'],10)
 def test_auto_checked_human_and_missing_but_not_ai(self):
  self.put(self.ids[0],missing=True);self.assertTrue(self.p.annotation_status(self.ids[0])['verified']);self.p.save_landmark(self.ids[0],1,11,11,'corrected',provenance='corrected_by_human');self.assertTrue(self.p.annotation_status(self.ids[0])['verified']);self.put(self.ids[1],auto=True);self.assertFalse(self.p.annotation_status(self.ids[1])['verified'])
 def test_eight_manual_zero_checked_runs_neutral_early_mode(self):
  for ident in self.ids[:8]:self.put(ident)
  [self.p.clear_checked(i) for i in self.ids[:8]];result=scan_project(self.p);self.assertFalse(result['trusted_reference_identity']);self.assertTrue(result['early_cross_image'])
 def test_gui_summary_uses_actual_mode_words(self):
  source=(Path(__file__).parents[1]/'app'/'editor_ready_v15.py').read_text(encoding='utf8');self.assertIn('Checked manual reference used for identity checking',source);self.assertIn('Statistical variability checking requires 8 Checked manual references',source)
 def test_scan_remains_read_only(self):
  self.put(self.ids[0]);self.p.mark_checked(self.ids[0]);self.put(self.ids[1],swap=True);before=self.p.load_landmarks(self.ids[1]);scan_project(self.p);self.assertEqual(before,self.p.load_landmarks(self.ids[1]))
if __name__=='__main__':unittest.main()