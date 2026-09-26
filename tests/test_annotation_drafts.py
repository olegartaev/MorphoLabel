import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.annotation_check import check_annotation
from app.project_storage import Project


class AnnotationDraftTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());src=self.tmp/'src';src.mkdir();(src/'fish.jpg').write_bytes(b'x')
  schema=self.tmp/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n',encoding='utf-8')
  self.p=Project.create('p',src,self.tmp,schema,source_layout='direct');self.image_id=self.p.catalog_rows()[0]['image_id']
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def put(self,ident,x=10,y=10,**extra):self.p.save_landmark(self.image_id,ident,x,y,'manual',provenance='manual',**extra)
 def test_hard_unresolved_blocks_annotation_check(self):
  result=check_annotation(self.p,self.image_id,100,100)
  self.assertEqual([x['kind'] for x in result.hard],['unresolved','unresolved'])
 def test_draft_is_project_local_unverified_and_survives_reopen(self):
  self.put(1);self.p.save_annotation_draft(self.image_id,'CONTROL_SET',8)
  self.assertFalse(self.p.annotation_status(self.image_id)['verified']);self.assertEqual(self.p.annotation_draft(self.image_id)['workflow_position'],8)
  reopened=Project.open(self.p.root);self.assertEqual(reopened.annotation_draft(self.image_id)['workflow_stage'],'CONTROL_SET');self.assertFalse(reopened.annotation_status(self.image_id)['verified'])
 def test_mark_checked_clears_draft_only_after_complete(self):
  self.put(1);self.put(2);self.p.save_annotation_draft(self.image_id,'INITIAL_TRAINING',2);self.p.mark_checked(self.image_id)
  self.assertTrue(self.p.annotation_status(self.image_id)['verified']);self.assertIsNone(self.p.annotation_draft(self.image_id))
 def test_clear_draft_finals_keeps_prediction_history(self):
  self.p.save_landmark(self.image_id,1,12,13,'auto',provenance='machine',model_id='m1',predicted_x=12,predicted_y=13,confidence=.8,prediction_run_id='run1');self.p.save_annotation_draft(self.image_id,'CONTROL_SET',1)
  self.p.clear_landmark_finals_for_draft(self.image_id);row=self.p.load_landmarks(self.image_id)[1]
  self.assertEqual(row['state'],'unresolved');self.assertIsNone(row['x_standardized']);self.assertEqual((row['predicted_x'],row['predicted_y'],row['model_id'],row['prediction_run_id']),(12,13,'m1','run1'));self.assertTrue(self.p.annotation_draft(self.image_id)['manual_rebuild']);self.assertFalse(self.p.annotation_status(self.image_id)['verified'])
 def test_suspicious_acceptance_is_stale_after_landmark_change(self):
  self.put(1,10,10);self.put(2,10,10);warning=check_annotation(self.p,self.image_id,100,100).hard[0];self.p.accept_review_warning(self.image_id,warning);self.assertTrue(self.p.review_warning_is_accepted(self.image_id,warning));self.p.save_landmark(self.image_id,1,11,10,'manual',provenance='manual');self.assertFalse(self.p.review_warning_is_accepted(self.image_id,warning))

if __name__=='__main__':unittest.main()


