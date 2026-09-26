import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.landmark_review import root_v1_eligible_image_ids, scan_project, v1_training_preflight

class ReviewAcceptanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());src=self.tmp/'src';src.mkdir()
  for name in ('one.jpg','two.jpg'):(src/name).write_bytes(b'x')
  schema=self.tmp/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,A,BOTH\n2,B,B,BOTH\n',encoding='utf8')
  self.p=Project.create('p',src,self.tmp,schema,source_layout='direct');self.ids=[row['image_id'] for row in self.p.catalog_rows()]
  for ident in self.ids:Image.new('RGB',(100,100)).save(self.p.cache_root/'standardized'/f'{ident}.png')
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def fill_manual(self,image_id,*,duplicate=False,corrected=False,missing=False):
  provenance='corrected_by_human' if corrected else 'manual';state='corrected' if corrected else 'manual'
  self.p.save_landmark(image_id,1,10,10,state,provenance=provenance)
  if missing:self.p.save_landmark(image_id,2,None,None,'missing',provenance='manual')
  else:self.p.save_landmark(image_id,2,10 if duplicate else 80,10,state,provenance=provenance)
 def warning(self,image_id):
  return next(item for item in scan_project(self.p,workers=1)['queue'] if item['image_id']==image_id and item['kind']=='duplicate')
 def test_fully_manual_resolved_is_auto_checked_on_open_backfill(self):
  self.fill_manual(self.ids[0]);self.p.clear_checked(self.ids[0]);reopened=Project.open(self.p.root)
  self.assertTrue(reopened.annotation_status(self.ids[0])['verified'])
 def test_corrected_by_human_qualifies_as_human_provenance(self):
  self.fill_manual(self.ids[0],corrected=True)
  self.assertIn(self.ids[0],root_v1_eligible_image_ids(self.p))
 def test_manual_missing_qualifies_as_human_resolved(self):
  self.fill_manual(self.ids[0],missing=True)
  self.assertTrue(self.p.annotation_status(self.ids[0])['verified']);self.assertIn(self.ids[0],root_v1_eligible_image_ids(self.p))
 def test_ai_containing_image_is_not_admitted_to_root_v1(self):
  self.p.save_landmark(self.ids[0],1,10,10,'manual',provenance='manual');self.p.save_landmark(self.ids[0],2,80,10,'auto',provenance='machine');self.p.mark_checked(self.ids[0])
  self.assertNotIn(self.ids[0],root_v1_eligible_image_ids(self.p))
 def test_warning_initially_blocks_training_preflight(self):
  self.fill_manual(self.ids[0],duplicate=True)
  self.assertTrue(v1_training_preflight(self.p,workers=1)['unresolved_review_warnings'])
 def test_accept_as_correct_changes_no_landmark_coordinates(self):
  self.fill_manual(self.ids[0],duplicate=True);before=self.p.load_landmarks(self.ids[0]);self.p.accept_review_warning(self.ids[0],self.warning(self.ids[0]))
  self.assertEqual(before,self.p.load_landmarks(self.ids[0]))
 def test_accepted_unchanged_warning_no_longer_blocks_training_preflight(self):
  self.fill_manual(self.ids[0],duplicate=True);warning=self.warning(self.ids[0]);self.p.accept_review_warning(self.ids[0],warning)
  self.assertFalse(v1_training_preflight(self.p,workers=1)["unresolved_review_warnings"])
 def test_accepted_unchanged_warning_does_not_reappear_on_rescan(self):
  self.fill_manual(self.ids[0],duplicate=True);warning=self.warning(self.ids[0]);self.p.accept_review_warning(self.ids[0],warning)
  self.assertFalse(scan_project(self.p,workers=1)["queue"])
 def test_involved_landmark_change_invalidates_acceptance(self):
  self.fill_manual(self.ids[0],duplicate=True);self.p.accept_review_warning(self.ids[0],self.warning(self.ids[0]));self.p.save_landmark(self.ids[0],1,11,10,'manual',provenance='manual');self.p.save_landmark(self.ids[0],2,11,10,'manual',provenance='manual')
  self.assertTrue(v1_training_preflight(self.p,workers=1)['unresolved_review_warnings'])
 def test_schema_change_invalidates_acceptance(self):
  self.fill_manual(self.ids[0],duplicate=True);self.p.accept_review_warning(self.ids[0],self.warning(self.ids[0]));self.p.schema_path.write_text('id,abbr,name,role\n1,A,A,GM\n2,B,B,BOTH\n',encoding='utf8');reopened=Project.open(self.p.root)
  self.assertTrue(v1_training_preflight(reopened,workers=1)['unresolved_review_warnings'])
 def test_normal_correction_allows_preflight_when_warning_disappears(self):
  self.fill_manual(self.ids[0],duplicate=True);self.p.save_landmark(self.ids[0],2,80,10,'corrected',provenance='corrected_by_human')
  self.assertFalse(v1_training_preflight(self.p,workers=1)['unresolved_review_warnings'])

if __name__=='__main__':unittest.main()