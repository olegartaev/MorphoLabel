import shutil, tempfile, unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.landmark_dataset import v2_human_final_eligible_image_ids
from app.ai_batch import reviewed_count

class AutoCheckedTests(unittest.TestCase):
 def setUp(self):
  self.t=Path(tempfile.mkdtemp());src=self.t/'src';src.mkdir();Image.new('RGB',(60,40)).save(src/'fish.jpg');schema=self.t/'schema.csv';schema.write_text('id,abbr,name\n1,A,One\n2,B,Two\n',encoding='utf8');self.p=Project.create('p',src,self.t,schema,source_layout='direct');self.id=self.p.catalog_rows()[0]['image_id']
 def tearDown(self):shutil.rmtree(self.t,ignore_errors=True)
 def _rows(self,provenances):
  for i,prov in enumerate(provenances,1):self.p.save_landmark(self.id,i,10*i,20*i,'auto' if prov=='machine' else 'manual',provenance=prov,predicted_x=10*i if prov=='machine' else None,predicted_y=20*i if prov=='machine' else None,model_id='v2' if prov=='machine' else None,confidence=.5 if prov=='machine' else None,prediction_run_id='r' if prov=='machine' else None)
 def test_01_fully_manual_resolved_auto_checks(self):self._rows(('manual','manual'));self.assertTrue(self.p.annotation_status(self.id)['verified'])
 def test_02_ai_only_resolved_does_not_auto_check(self):self._rows(('machine','machine'));self.assertFalse(self.p.annotation_status(self.id)['verified'])
 def test_03_mixed_manual_machine_does_not_auto_check(self):self._rows(('manual','machine'));self.assertFalse(self.p.annotation_status(self.id)['verified'])
 def test_04_reopen_backfill_does_not_auto_check_ai(self):self._rows(('machine','machine'));self.p=Project.open(self.p.root);self.assertFalse(self.p.annotation_status(self.id)['verified'])
 def test_05_navigation_is_read_only_for_review_flag(self):
  self._rows(('machine','machine'));batch={'selected_images':[{'image_id':self.id}]};self.assertEqual(reviewed_count(self.p,batch),0);self.assertFalse(self.p.annotation_status(self.id)['verified'])
 def test_06_explicit_checked_allows_ai_final(self):
  self._rows(('machine','machine'));self.p.mark_checked(self.id);self.assertTrue(self.p.annotation_status(self.id)['verified'])
 def test_07_checked_ai_is_v2_eligible_without_provenance_rewrite(self):
  self._rows(('machine','machine'));before=self.p.load_landmarks(self.id)[1].copy();self.p.mark_checked(self.id);self.assertNotIn(self.id,v2_human_final_eligible_image_ids(self.p));self.assertEqual(self.p.load_landmarks(self.id)[1]['provenance'],before['provenance'])
 def test_08_manual_missing_counts_as_human_auto_checked(self):
  self.p.save_landmark(self.id,1,10,20,'manual',provenance='manual');self.p.save_landmark(self.id,2,None,None,'missing',provenance='missing');self.assertTrue(self.p.annotation_status(self.id)['verified'])
 def test_09_batch_flag_repair_only_changes_human_verified(self):
  self._rows(('machine','machine'));before={i:self.p.load_landmarks(self.id)[i].copy() for i in (1,2)};self.p.mark_checked(self.id);self.p.clear_checked(self.id);after=self.p.load_landmarks(self.id);self.assertFalse(self.p.annotation_status(self.id)['verified']);self.assertEqual({i:(after[i]['x_standardized'],after[i]['y_standardized'],after[i]['predicted_x'],after[i]['predicted_y'],after[i]['provenance'],after[i]['model_id'],after[i]['confidence'],after[i]['prediction_run_id']) for i in (1,2)},{i:(before[i]['x_standardized'],before[i]['y_standardized'],before[i]['predicted_x'],before[i]['predicted_y'],before[i]['provenance'],before[i]['model_id'],before[i]['confidence'],before[i]['prediction_run_id']) for i in (1,2)})
if __name__=='__main__':unittest.main()