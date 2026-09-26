import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.landmark_review import (batch_vector_swap_warnings, consistency_warnings, robust_swap_suggestions, root_v1_eligible_image_ids, structural_warnings, scan_project, warning_landmark_ids, trusted_identity_warnings)

class LandmarkReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());src=self.tmp/'source';src.mkdir()
  for i in range(12):(src/f'i_{i}.jpg').write_bytes(b'x')
  schema=self.tmp/'schema.csv';schema.write_text('id,abbr,name,role\n7,L7,Seven,BOTH\n8,L8,Eight,CLASSICAL\n',encoding='utf8')
  self.p=Project.create('p',src,self.tmp,schema,source_layout='direct');self.ids=[r['image_id'] for r in self.p.catalog_rows()]
  self.l7=self.p.active_landmark_id_for_abbr('L7');self.l8=self.p.active_landmark_id_for_abbr('L8')
  for ident in self.ids:Image.new('RGB',(100,100)).save(self.p.cache_root/'standardized'/f'{ident}.png')
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def manual(self,ident,a=(20,20),b=(80,80),checked=True):
  self.p.save_landmark(ident,self.l7,*a,'manual',provenance='manual');self.p.save_landmark(ident,self.l8,*b,'manual',provenance='manual')
  if checked:self.p.mark_checked(ident)
 def test_swap_preserves_ai_history_and_undo_restores_final(self):
  ident=self.ids[0]
  self.p.save_landmark(ident,self.l7,20,20,'auto',provenance='machine',predicted_x=20,predicted_y=20,model_id='m',confidence=.8,prediction_run_id='run')
  self.p.save_landmark(ident,self.l8,80,80,'auto',provenance='machine',predicted_x=80,predicted_y=80,model_id='m',confidence=.7,prediction_run_id='run')
  before=self.p.swap_present_landmarks(ident,self.l7,self.l8);rows=self.p.load_landmarks(ident)
  self.assertEqual((rows[self.l7]['x_standardized'],rows[self.l7]['predicted_x'],rows[self.l7]['prediction_run_id']),(80,20,'run'))
  self.assertEqual((rows[self.l8]['x_standardized'],rows[self.l8]['predicted_x'],rows[self.l8]['prediction_run_id']),(20,80,'run'))
  self.assertEqual(rows[self.l7]['provenance'],'corrected_by_human');self.assertFalse(self.p.annotation_status(ident)['verified'])
  self.p.restore_landmark_finals(ident,before);self.assertEqual(self.p.load_landmarks(ident)[self.l7]['x_standardized'],20)
 def test_duplicate_warning_tracks_both_involved_landmarks(self):
  self.assertEqual((self.l7,self.l8),warning_landmark_ids({'kind':'duplicate','landmark_id':self.l7,'other_landmark_id':self.l8}))

 def test_structural_unresolved_duplicate_and_bounds(self):
  ident=self.ids[0];self.p.save_landmark(ident,self.l7,101,5,'manual',provenance='manual');self.p.save_landmark(ident,self.l8,101,5,'manual',provenance='manual')
  kinds={x['kind'] for x in structural_warnings(self.p,ident,100,100)}
  self.assertTrue({'bounds','duplicate'}<=kinds)
 def test_root_v1_requires_manual_and_checked(self):
  self.manual(self.ids[0],checked=False);self.assertIn(self.ids[0],root_v1_eligible_image_ids(self.p))
  self.p.save_landmark(self.ids[1],self.l7,20,20,'auto',provenance='machine');self.p.save_landmark(self.ids[1],self.l8,80,80,'auto',provenance='machine');self.p.mark_checked(self.ids[1]);self.assertNotIn(self.ids[1],root_v1_eligible_image_ids(self.p))
 def test_per_landmark_variability_controls_warnings_and_swap(self):
  # Nine checked manual references; LM7 stable, LM8 intentionally highly variable.
  for n,ident in enumerate(self.ids[1:10]):self.manual(ident,(20+n%2,20),(20+7*n,80))
  target=self.ids[0];self.manual(target,(50,20),(55,80))
  dims={ident:(100,100) for ident in self.ids};warnings=consistency_warnings(self.p,target,dims)
  self.assertIn(self.l7,{w['landmark_id'] for w in warnings});self.assertNotIn(self.l8,{w['landmark_id'] for w in warnings})
  self.p.save_landmark(target,self.l7,80,80,'corrected',provenance='corrected_by_human');self.p.save_landmark(target,self.l8,20,20,'corrected',provenance='corrected_by_human');self.p.mark_checked(target)
  suggestions=robust_swap_suggestions(self.p,target,dims);self.assertEqual(suggestions,[])
 def test_synthetic_stable_pair_swap_is_suggested(self):
  for n,ident in enumerate(self.ids[1:10]):self.manual(ident,(20+n%2,20),(80+n%2,80))
  target=self.ids[0];self.manual(target,(80,80),(20,20));dims={ident:(100,100) for ident in self.ids}
  suggestions=robust_swap_suggestions(self.p,target,dims)
  self.assertTrue(any(s['first_landmark_id']==self.l7 and s['second_landmark_id']==self.l8 for s in suggestions))
 def test_review_ui_strings_are_english(self):
  source=(Path(__file__).parents[1]/'app'/'editor_ready_v15.py').read_text(encoding='utf8')
  for label in ('Check Landmarks','Next Issue','Previous Issue','Swap 2 Landmarks','Undo Reassignment','Exit Review','Done'):
   self.assertIn(label,source)
  self.assertFalse(any('\u0400' <= character <= '\u052f' for character in source))
 def test_project_scan_is_deterministic_read_only_and_skips_excluded(self):
  self.p.save_landmark(self.ids[0],self.l7,10,10,'manual',provenance='manual');self.p.save_landmark(self.ids[1],self.l7,10,10,'manual',provenance='manual');self.p.exclude_image(self.ids[1],'Bad image')
  before=self.p.load_landmarks(self.ids[0]);first=scan_project(self.p);second=scan_project(self.p)
  self.assertEqual(first['queue'],second['queue']);self.assertEqual(first['scanned'],len(self.ids)-1);self.assertTrue(first['queue'])
  self.assertEqual(self.p.load_landmarks(self.ids[0]),before);self.assertFalse(self.p.annotation_status(self.ids[0])['verified']);self.assertNotIn(self.ids[1],{item['image_id'] for item in first['queue']})
 def test_project_scan_can_be_limited_to_one_completed_batch(self):
  target=self.ids[0];other=self.ids[1]
  self.p.save_landmark(target,self.l7,10,10,'manual',provenance='manual')
  self.p.save_landmark(other,self.l7,10,10,'manual',provenance='manual')
  result=scan_project(self.p,image_ids=(target,))
  self.assertEqual(1,result['scanned'])
  self.assertTrue(result['queue'])
  self.assertEqual({target},{item['image_id'] for item in result['queue']})

 def test_trusted_identity_candidate_scope_is_applied_before_group_scoring(self):
  for ident in self.ids[2:11]:self.manual(ident)
  first,second=self.ids[0],self.ids[1]
  for image_id in (first,second):
   self.p.save_landmark(image_id,self.l7,20,20,'auto',provenance='machine')
   self.p.save_landmark(image_id,self.l8,80,80,'auto',provenance='machine')
   self.p.clear_checked(image_id)
  refs=root_v1_eligible_image_ids(self.p)
  self.assertGreaterEqual(len(refs),8)
  with patch('app.landmark_review._group_score',return_value=None) as score:
   trusted_identity_warnings(self.p,image_ids=(first,))
  self.assertEqual(len(refs),score.call_count)

 def _vector_batch_project(self,swapped=True):
  root=Path(tempfile.mkdtemp());src=root/'source';src.mkdir()
  for i in range(5):(src/f'b_{i}.jpg').write_bytes(b'x')
  schema=root/'schema.csv';schema.write_text('id,abbr,name,role\n1,L1,One,BOTH\n2,L2,Two,BOTH\n3,L3,Three,BOTH\n4,L4,Four,BOTH\n5,L5,Five,BOTH\n',encoding='utf8')
  project=Project.create('batch',src,root,schema,source_layout='direct');ids=[r['image_id'] for r in project.catalog_rows()]
  base={1:(15.,15.),2:(55.,14.),3:(18.,55.),4:(78.,25.),5:(80.,67.)}
  for n,image_id in enumerate(ids):
   Image.new('RGB',(140,100)).save(project.cache_root/'standardized'/f'{image_id}.png')
   scale=1.0+.01*n;dx=2.0*n;dy=-1.5*n
   coords={i:(x*scale+dx,y*scale+dy) for i,(x,y) in base.items()}
   if swapped and n==0:coords[4],coords[5]=coords[5],coords[4]
   for ident,(x,y) in coords.items():project.save_landmark(image_id,ident,x,y,'manual',provenance='manual')
   project.mark_checked(image_id)
  self.addCleanup(lambda:shutil.rmtree(root,ignore_errors=True))
  return project,ids

 def test_batch_vector_reversal_finds_single_swapped_manual_fish(self):
  project,ids=self._vector_batch_project(swapped=True)
  warnings=batch_vector_swap_warnings(project,ids)
  target=ids[0]
  hits=[w for w in warnings if w['image_id']==target and set(w['landmark_ids'])=={4,5}]
  self.assertEqual(1,len(hits),warnings)
  self.assertGreaterEqual(hits[0]['vote_count'],2)
  self.assertFalse(any(w['image_id']!=target and set(w['landmark_ids'])=={4,5} for w in warnings),warnings)

 def test_batch_vector_reversal_has_no_false_swap_on_clean_manual_batch(self):
  project,ids=self._vector_batch_project(swapped=False)
  self.assertEqual((),batch_vector_swap_warnings(project,ids))

 def test_explicit_review_worker_count_skips_autotuning(self):
  project,ids=self._vector_batch_project(swapped=True)
  with patch('app.landmark_review.tune_workload',side_effect=AssertionError('explicit workers must skip autotune')):
   result=scan_project(project,image_ids=ids,workers=1)
  self.assertFalse(result['cancelled'])

 def test_finite_batch_scan_includes_vector_reversal_warning(self):
  project,ids=self._vector_batch_project(swapped=True)
  result=scan_project(project,image_ids=ids,workers=1)
  hits=[w for w in result['queue'] if w.get('kind')=='batch_vector_swap' and set(warning_landmark_ids(w))=={4,5}]
  self.assertEqual(1,len(hits),result['queue'])
  self.assertEqual(ids[0],hits[0]['image_id'])

 def test_less_than_eight_references_has_no_cross_image_warning(self):
  for ident in self.ids[1:8]:self.manual(ident)
  self.manual(self.ids[0],(90,90),(80,80));dims={ident:(100,100) for ident in self.ids};self.assertEqual(consistency_warnings(self.p,self.ids[0],dims),[])
if __name__=='__main__':unittest.main()