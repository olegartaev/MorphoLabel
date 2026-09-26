import tempfile
import unittest
from pathlib import Path
from app.project_storage import Project

def crop(bounds): return {"crop_bounds":bounds,"original_width":100,"original_height":100,"normalization_status":"PASS"}
class CropAutoWorkflowTests(unittest.TestCase):
 def make(self):
  d=Path(tempfile.mkdtemp());src=d/'src';src.mkdir();(src/'a.jpg').write_bytes(b'x');schema=d/'schema.csv';schema.write_text("id,abbr,name,role\n1,A,A,BOTH\n");p=Project.create('p',src,d,schema,source_types=['jpg']);return p,p.catalog_rows()[0]['image_id']
 def test_ai_history_and_review_semantics(self):
  p,i=self.make();p.save_crop(i,crop([10,10,90,90]),'automatic','old');p.record_ai_crop_prediction(i,crop([10,10,90,90]),'m1');self.assertEqual(p.crop_record(i)['provenance'],'ai_unreviewed');p.save_reviewed_crop(i,crop([10,10,90,90]));self.assertEqual(p.crop_record(i)['provenance'],'ai_accepted');self.assertEqual(len(p.crop_prediction_history(i)),1)
 def test_human_protected_and_training_eligible(self):
  p,i=self.make();p.save_reviewed_crop(i,crop([10,10,90,90]));self.assertEqual(p.crop_auto_candidates()[0],());self.assertIn(i,p.crop_training_eligible_ids())
 def test_automatic_crop_never_overwrites_images_with_landmarks(self):
  p,i=self.make()
  p.save_landmark(i,1,12,13,'manual','manual')
  selected,protected=p.crop_auto_candidates()
  self.assertEqual((),selected);self.assertEqual(1,protected)
  p.save_crop(i,crop([10,10,90,90]),'automatic','old');p.record_ai_crop_prediction(i,crop([10,10,90,90]),'m1')
  selected,protected=p.crop_auto_candidates(rerun=True)
  self.assertEqual((),selected);self.assertEqual(1,protected)

 def test_rerun_candidate_only_unreviewed(self):
  p,i=self.make();p.save_crop(i,crop([10,10,90,90]),'automatic','old');p.record_ai_crop_prediction(i,crop([10,10,90,90]),'m1');self.assertEqual(p.crop_auto_candidates(rerun=True)[0],(i,))
  p.save_reviewed_crop(i,crop([10,10,90,90]));self.assertEqual(p.crop_record(i)['provenance'],'ai_accepted');self.assertEqual(p.crop_auto_candidates(rerun=True)[0],())
 def test_crop_counts_are_crop_only_and_exclude_inactive_images(self):
  p,i=self.make();p.save_reviewed_crop(i,crop([10,10,90,90]));counts=p.crop_counts()
  self.assertEqual({'Total':1,'Reviewed':1,'AI pending':0,'Train ready':1,'Uncropped':0},counts)
  p.save_crop(i,crop([10,10,90,90]),'automatic','m1');p.record_ai_crop_prediction(i,crop([10,10,90,90]),'m1')
  counts=p.crop_counts();self.assertEqual(1,counts['AI pending']);self.assertEqual(0,counts['Reviewed']);self.assertEqual(0,counts['Uncropped'])
 def test_unprovable_landmark_frame_is_archived_and_not_trainable(self):
  p,i=self.make();p.save_landmark(i,1,12,13,'manual','manual');p.mark_checked(i)
  result=p.save_reviewed_crop(i,crop([10,10,90,90]))
  self.assertTrue(result['legacy_landmarks_invalidated'])
  row=p.load_landmarks(i)[1];self.assertEqual('unresolved',row['state']);self.assertIsNone(row['x_standardized'])
  self.assertTrue(p.landmark_crop_review_required(i))
  with p.transaction() as c: audit=c.execute("SELECT previous_json FROM corrections WHERE image_id=? AND kind='landmark_frame_unknown_before_crop_change'",(i,)).fetchone()
  self.assertIsNotNone(audit);self.assertIn('previous_landmark_frame_unknown_before_crop_change',audit[0])
 def test_review_worst_includes_all_pending_ai_levels(self):
  p,i=self.make(); ids=[i]
  for name in ('b.jpg','c.jpg'):
   (p.source_root/name).write_bytes(b'x')
  p.scan_originals();ids=[row['image_id'] for row in p.catalog_rows()]
  for ident,level,score in zip(ids,('OK','REVIEW','BAD'),(90,40,5)):
   p.save_crop(ident,crop([10,10,90,90]),'automatic','m');p.record_ai_crop_prediction(ident,crop([10,10,90,90]),'m')
   with p.transaction() as c:c.execute('UPDATE crops SET qc_level=?,qc_score=? WHERE image_id=?',(level,score,ident))
  self.assertEqual((ids[2],ids[1],ids[0]),p.crop_review_candidates())
