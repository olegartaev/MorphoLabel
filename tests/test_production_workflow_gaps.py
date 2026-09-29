import shutil,tempfile,unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.transforms import Transform
from app.human_baseline import start_or_continue_run,ensure_pass,pass_progress,complete_pass,complete_run,record_repeatability_pass_qc,evaluate_model_on_repeatability_run,pass_session_ids,pending_pass_session_ids,redo_repeatability_image,repeatability_report_state,repeatability_reference_frame_issue
from app.operator_qc import set_repeat_landmark,complete_repeat_session,_load,operator_eligible_image_ids
from app.ai import MockBackend
from app.project_storage import schema_hash
from app.landmark_ai_workflow import STATE_KEY,load_state
from app.ui.landmarks_section import LandmarksSection,_format_percent,_landmark_toolbar_state,_remaining_prediction_ids,_reapply_unverified_prediction_ids,_confirm_complex_qc_image
from app.ui.context import UIContext, _training_ready_image_ids, _training_seen_image_ids
from app.ui.batch_status import position_and_remaining
from app.ui.shell import ProductionShell
from unittest.mock import patch,Mock
from types import SimpleNamespace
import queue,threading

class ProductionWorkflowGapTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());src=self.root/'source'/'L';src.mkdir(parents=True)
  for n in range(4):Image.new('RGB',(40,30),(255,255,255)).save(src/f'f{n}.jpg')
  schema=self.root/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n',encoding='utf8')
  self.p=Project.create('p',src.parent,self.root,schema,source_layout='direct');self.ids=[r['image_id'] for r in self.p.catalog_rows()]
  for image_id in self.ids:
   (self.p.cache_root/'standardized').mkdir(parents=True,exist_ok=True);Image.new('RGB',(40,30)).save(self.p.cache_root/'standardized'/f'{image_id}.png')
   for ident in (1,2):self.p.save_landmark(image_id,ident,10*ident,10,'manual','manual')
   self.p.mark_checked(image_id)
  self.p.set_ui_state(STATE_KEY,{'control_image_ids':self.ids[:2]})
 def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
 def _final_crop(self,image_id):
  transform=Transform(40,30,0.0,20.0,15.0,0.0,0.0,40,30)
  crop={'crop_bounds':[0,0,40,30],'transform':transform.__dict__,'rotation_degrees':0.0,'standardized_relpath':f'cache/standardized/{image_id}.png','normalization_status':'PASS'}
  self.p.save_reviewed_crop(image_id,crop,previous_frame_proven=True)
  return crop
 def _finish(self,sids,offset=0):
  for sid in sids:
   for ident in (1,2):set_repeat_landmark(self.p,sid,ident,10*ident+offset,10)
   complete_repeat_session(self.p,sid)
 def _batch_section(self,context,complete=True):
  section=LandmarksSection.__new__(LandmarksSection);section.context=context
  section.canvas=type('Canvas',(),{'state':type('State',(),{'complete':complete})(),'refresh_authoritative':lambda *_a,**_k:None})()
  panel=type('Panel',(),{'sync_current':lambda *_a,**_k:None,'refresh':lambda *_a,**_k:None})()
  section.shell=type('Shell',(),{'photo_panel':panel,'_selected_image':lambda *_a,**_k:None,'_update_status':lambda *_a,**_k:None})()
  return section
 def test_two_passes_are_independent_and_resume(self):
  run,new=start_or_continue_run(self.p,count=2);self.assertTrue(new);one=ensure_pass(self.p,run['run_id'],1)[1];self.assertEqual(2,len(one));self.assertEqual(0,pass_progress(self.p,run,2)['completed'])
  self._finish(one);complete_pass(self.p,run['run_id'],1);record_repeatability_pass_qc(self.p,run['run_id'],1,());_,two=ensure_pass(self.p,run['run_id'],2);self.assertEqual(2,len(two));self.assertNotEqual(set(one),set(two));self.assertEqual([], _load(self.p,two[0])['repeat'])
  self._finish(two,1);complete_pass(self.p,run['run_id'],2);record_repeatability_pass_qc(self.p,run['run_id'],2,());report=complete_run(self.p,run['run_id']);self.assertEqual(2,report['format_version']);self.assertEqual(self.ids[:2],report['image_ids']);self.assertEqual('completed',next(r for r in __import__('app.human_baseline',fromlist=['previous_runs']).previous_runs(self.p) if r['run_id']==run['run_id'])['status'])
 def test_three_image_passes_finish_only_on_final_session(self):
  self.p.set_ui_state(STATE_KEY,{'control_image_ids':self.ids[:3]})
  run,new=start_or_continue_run(self.p,count=3);self.assertTrue(new)
  _,first=ensure_pass(self.p,run['run_id'],1);self.assertEqual(3,len(first))
  for index,sid in enumerate(first):
   self._finish([sid]);progress=pass_progress(self.p,run,1);self.assertEqual(index+1,progress['completed'])
   if index<2:
    self.assertFalse(progress['complete'])
    with self.assertRaises(ValueError):complete_pass(self.p,run['run_id'],1)
  self.assertTrue(pass_progress(self.p,run,1)['complete']);complete_pass(self.p,run['run_id'],1);record_repeatability_pass_qc(self.p,run['run_id'],1,())
  _,second=ensure_pass(self.p,run['run_id'],2);self.assertEqual(3,len(second));self.assertEqual([], _load(self.p,second[0])['repeat'])
 def test_stale_active_landmark_schema_does_not_break_header_counts(self):
  project=SimpleNamespace(active_model_readonly=Mock(side_effect=ValueError('active landmark model schema hash does not match project schema')))
  self.assertEqual(set(),_training_seen_image_ids(project))

 def test_landmarks_source_handles_incompatible_active_model_without_blank_workspace(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertIn("except ValueError:",source)
  self.assertIn("No compatible active model",source)
  self.assertIn("prediction_state='normal' if active else 'disabled'",source)

 def test_train_ready_means_current_state_not_yet_in_active_lineage(self):
  project=SimpleNamespace()
  with patch('app.ui.context.training_ready_image_ids',return_value=('c',)):
   self.assertEqual({'c'},_training_ready_image_ids(project))
  with patch('app.ui.context.training_ready_image_ids',return_value=('a','b')):
   self.assertEqual({'a','b'},_training_ready_image_ids(project))

 def test_crop_marker_means_final_crop_exists_independently_of_landmark_review(self):
  image_id=self.ids[0]
  self.p.delete_landmark(image_id,1);self.p.delete_landmark(image_id,2);self.p.clear_checked(image_id)
  self.assertFalse(self.p.landmark_crop_ready(image_id))
  self._final_crop(image_id)
  row=self.p.catalog_row(image_id)
  self.assertTrue(row['has_crop'])
  from app.landmark_frames import landmark_frame_ready
  self.assertTrue(landmark_frame_ready(self.p,image_id))
  with self.p.transaction() as db:
   db.execute("UPDATE crops SET provenance='ai_unreviewed',human_verified=0 WHERE image_id=?",(image_id,))
  self.assertFalse(self.p.catalog_row(image_id)['has_crop'])
  self.assertFalse(landmark_frame_ready(self.p,image_id))

 def test_legacy_project_data_prefixed_frame_paths_restore_existing_cache(self):
  from app.landmark_frames import crop_frame_record,restore_standardized_frame
  image_id=self.ids[0];self._final_crop(image_id)
  expected=self.p.cache_root/'standardized'/f'{image_id}.png'
  # This fixture represents a valid legacy standardized frame produced after
  # the persisted Crop.  Make that ordering explicit instead of depending on
  # machine speed between setUp() and save_reviewed_crop().
  Image.new('RGB',(40,30)).save(expected)
  import os,time
  future=time.time()+2.0;os.utime(expected,(future,future))
  developed=self.p.cache_root/'developed'/f'{image_id}.png';developed.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(40,30)).save(developed)
  with self.p.transaction() as db:
   db.execute("UPDATE crops SET standardized_relpath=?,developed_relpath=? WHERE image_id=?",(f'project_data/cache/standardized/{image_id}.png',f'project_data/cache/developed/{image_id}.png',image_id))
   db.execute("DELETE FROM crop_holdout WHERE image_id=?",(image_id,))
  manifest=expected.with_name(expected.name+'.frame.json')
  if manifest.exists():manifest.unlink()
  self.assertEqual(expected,self.p.resolve_data_path(f'project_data/cache/standardized/{image_id}.png'))
  self.assertIsNotNone(crop_frame_record(self.p,image_id))
  path,rebuilt=restore_standardized_frame(self.p,image_id)
  self.assertEqual(expected,path);self.assertFalse(rebuilt)
  self.assertTrue(manifest.is_file())
  self.assertIn(image_id,{row['image_id'] for row in self.p.crop_training_rows()})

 def test_complex_qc_confirmation_clears_pending_crop_review_on_final_crop(self):
  image_id=self.ids[0];self._final_crop(image_id)
  self.assertTrue(self.p.landmark_crop_review_required(image_id))
  state=_confirm_complex_qc_image(self.p,image_id)
  self.assertFalse(self.p.landmark_crop_review_required(image_id))
  self.assertTrue(state['verified'])
  self.assertTrue(self.p.catalog_row(image_id)['human_verified'])

 def test_random_manual_completion_updates_train_ready_delta_immediately(self):
  image_id=self.ids[0]
  self.p.delete_landmark(image_id,1);self.p.delete_landmark(image_id,2);self.p.clear_checked(image_id)
  self._final_crop(image_id)
  context=UIContext(self.p,'landmarks');context.refresh(force=True)
  self.assertEqual(0,context.landmark_counts()['New/changed'])
  self.p.save_landmark(image_id,1,10,10,'manual','manual')
  context.refresh_landmark_state(image_id);context.update_landmark_counts(image_id)
  self.assertEqual(0,context.landmark_counts()['New/changed'])
  self.p.save_landmark(image_id,2,20,10,'manual','manual')
  context.refresh_landmark_state(image_id);counts=context.update_landmark_counts(image_id)
  self.assertEqual(1,counts['New/changed'])

 def test_correction_to_image_already_seen_by_model_becomes_train_ready(self):
  import json
  from app.landmark_dataset import _crop_identity,current_training_state_fingerprint,model_training_state_fingerprints
  from app.landmark_frames import landmark_frame_ready
  image_id=self.ids[0];self._final_crop(image_id)
  # Creating/changing Crop after landmarks deliberately requires downstream
  # landmark review. Explicitly confirm that frame before representing it in a model.
  self.assertTrue(self.p.landmark_crop_review_required(image_id));self.p.mark_checked(image_id)
  self.assertTrue(landmark_frame_ready(self.p,image_id))
  dataset=self.p.data_root/'ai'/'datasets'/'seen';dataset.mkdir(parents=True,exist_ok=True)
  manifest={
   'format_version':1,'dataset_id':'seen',
   'schema_landmarks':[{'landmark_id':1,'abbr':'A'},{'landmark_id':2,'abbr':'B'}],
   'images':[{'image_id':image_id,'split':'train','crop_transform_sha256':_crop_identity(self.p,image_id),
              'landmarks':[{'landmark_id':1,'state':'present','x':10.0,'y':10.0},{'landmark_id':2,'state':'present','x':20.0,'y':10.0}]}],
  }
  (dataset/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
  digest=__import__('app.project_storage',fromlist=['schema_hash']).schema_hash(self.p.schema_path)
  self.p.register_model('seen-model','landmark',active=True,schema_digest=digest,dataset_id='seen',dataset_manifest_path='ai/datasets/seen/manifest.json')
  context=UIContext(self.p,'landmarks');context.refresh(force=True)
  represented=model_training_state_fingerprints(self.p,'seen-model')
  self.assertEqual(represented[str(image_id)],current_training_state_fingerprint(self.p,image_id))
  self.assertEqual(0,context.landmark_counts()['New/changed']);self.assertEqual(0,self.p.landmark_counts()['New/changed'])

  self.p.save_landmark(image_id,1,11,10,'corrected','corrected_by_human')
  self.assertEqual(11,self.p.load_landmarks(image_id)[1]['x_standardized'])
  self.assertNotEqual(represented[str(image_id)],current_training_state_fingerprint(self.p,image_id))
  context.refresh_landmark_state(image_id);counts=context.update_landmark_counts(image_id)
  self.assertEqual(1,counts['New/changed']);self.assertEqual(1,self.p.landmark_counts()['New/changed'])

  learned=self.p.data_root/'ai'/'datasets'/'learned';learned.mkdir(parents=True,exist_ok=True)
  learned_manifest={
   'format_version':1,'dataset_id':'learned',
   'schema_landmarks':[{'landmark_id':1,'abbr':'A'},{'landmark_id':2,'abbr':'B'}],
   'images':[{'image_id':image_id,'split':'train','crop_transform_sha256':_crop_identity(self.p,image_id),
              'landmarks':[{'landmark_id':1,'state':'present','x':11.0,'y':10.0},{'landmark_id':2,'state':'present','x':20.0,'y':10.0}]}],
  }
  (learned/'manifest.json').write_text(json.dumps(learned_manifest),encoding='utf8')
  self.p.register_model('learned-model','landmark',active=True,schema_digest=digest,dataset_id='learned',parent_model_id='seen-model',dataset_manifest_path='ai/datasets/learned/manifest.json')
  context.invalidate_counts()
  self.assertEqual(0,context.landmark_counts()['New/changed']);self.assertEqual(0,self.p.landmark_counts()['New/changed'])

  self.p.save_landmark(image_id,1,11,10,'corrected','corrected_by_human')
  context.refresh_landmark_state(image_id);counts=context.update_landmark_counts(image_id)
  self.assertEqual(0,counts['New/changed']);self.assertEqual(0,self.p.landmark_counts()['New/changed'])

  changed=Transform(40,30,1.0,20.0,15.0,0.0,0.0,40,30)
  crop={'crop_bounds':[0,0,40,30],'transform':changed.__dict__,'rotation_degrees':1.0,'standardized_relpath':f'cache/standardized/{image_id}.png','normalization_status':'PASS'}
  self.p.save_reviewed_crop(image_id,crop,previous_frame_proven=True)
  context.refresh_landmark_state(image_id);counts=context.update_landmark_counts(image_id)
  self.assertTrue(self.p.landmark_crop_review_required(image_id));self.assertEqual(0,counts['New/changed'])
  self.p.mark_checked(image_id)
  context.refresh_landmark_state(image_id);counts=context.update_landmark_counts(image_id)
  self.assertEqual(1,counts['New/changed']);self.assertEqual(1,self.p.landmark_counts()['New/changed'])

 def test_crop_review_pending_keeps_crop_marker_but_not_verified_state(self):
  image_id=self.ids[0];self._final_crop(image_id)
  self.assertTrue(self.p.landmark_crop_review_required(image_id))
  self.assertFalse(self.p.annotation_status(image_id)['verified'])
  from app.landmark_frames import landmark_frame_ready
  row=self.p.catalog_row(image_id);self.assertFalse(row['human_verified']);self.assertTrue(row['has_crop']);self.assertEqual('yellow',row['status_color'])
  self.assertFalse(landmark_frame_ready(self.p,image_id))
  bulk=next(item for item in self.p.catalog_rows() if item['image_id']==image_id)
  self.assertFalse(bulk['human_verified']);self.assertTrue(bulk['has_crop']);self.assertEqual('yellow',bulk['status_color'])
  context=UIContext(self.p,'landmarks');context.refresh(force=True)
  self.assertEqual(3,context.landmark_counts()['Human verified']);self.assertEqual(3,self.p.landmark_counts()['Human verified'])
  self.p.save_landmark(image_id,1,11,10,'corrected','corrected_by_human')
  self.assertFalse(self.p.annotation_status(image_id)['verified']);self.assertTrue(self.p.landmark_crop_review_required(image_id))
  self.p.mark_checked(image_id);context.refresh_landmark_state(image_id);counts=context.update_landmark_counts(image_id)
  row=self.p.catalog_row(image_id);self.assertTrue(row['human_verified']);self.assertTrue(row['has_crop']);self.assertEqual('green',row['status_color'])
  self.assertTrue(landmark_frame_ready(self.p,image_id))
  self.assertEqual(4,counts['Human verified']);self.assertEqual(4,self.p.landmark_counts()['Human verified'])

 def test_reapplying_identical_crop_does_not_create_landmark_review(self):
  image_id=self.ids[0]
  self.p.delete_landmark(image_id,1);self.p.delete_landmark(image_id,2);self.p.clear_checked(image_id)
  crop=self._final_crop(image_id)
  for ident in (1,2):self.p.save_landmark(image_id,ident,10*ident,10,'manual','manual')
  self.p.mark_checked(image_id)
  transform=dict(reversed(list(crop['transform'].items())))
  same={'crop_bounds':[float(value) for value in crop['crop_bounds']],'transform':transform,'rotation_degrees':0,'standardized_relpath':crop['standardized_relpath'],'normalization_status':'PASS'}
  self.p.save_reviewed_crop(image_id,same,previous_frame_proven=True)
  self.assertFalse(self.p.landmark_crop_review_required(image_id))
  self.assertTrue(self.p.annotation_status(image_id)['verified'])
  self.assertTrue(self.p.catalog_row(image_id)['has_crop'])

 def test_accept_all_ai_crops_confirms_only_active_pending_proposals(self):
  first,second,excluded=self.ids[:3]
  for image_id,level in ((first,'REVIEW'),(second,'OK'),(excluded,'BAD')):
   self._final_crop(image_id)
   with self.p.transaction() as db:
    db.execute("UPDATE crops SET provenance='ai_unreviewed',human_verified=0,human_changed=0,reviewed_at=NULL,ai_proposal_json=crop_json,qc_level=? WHERE image_id=?",(level,image_id))
  self.p.exclude_image(excluded,'test')
  before={image_id:self.p.load_landmarks(image_id) for image_id in (first,second,excluded)}
  summary=self.p.pending_ai_crop_summary()
  self.assertEqual(2,summary['total']);self.assertEqual({'REVIEW':1,'OK':1},summary['by_qc'])
  result=self.p.accept_all_ai_crops()
  self.assertEqual(2,result['accepted']);self.assertEqual(0,result['skipped'])
  for image_id in (first,second):
   crop=self.p.crop_record(image_id)
   self.assertEqual('ai_accepted',crop['provenance']);self.assertEqual(1,crop['human_verified']);self.assertEqual(0,crop['human_changed']);self.assertIsNotNone(crop['reviewed_at'])
   self.assertTrue(self.p.landmark_crop_ready(image_id));self.assertEqual(before[image_id],self.p.load_landmarks(image_id))
  untouched=self.p.crop_record(excluded)
  self.assertEqual('ai_unreviewed',untouched['provenance']);self.assertEqual(0,untouched['human_verified']);self.assertEqual(before[excluded],self.p.load_landmarks(excluded))

 def test_reopen_repairs_only_legacy_manual_crop_verification_gap(self):
  legacy,current=self.ids[:2]
  self._final_crop(legacy);self._final_crop(current)
  with self.p.transaction() as db:
   db.execute("UPDATE crops SET provenance='manual',human_verified=0,reviewed_at=NULL WHERE image_id=?",(legacy,))
   db.execute("UPDATE crops SET provenance='manual',human_verified=0,reviewed_at='2026-01-01T00:00:00+00:00' WHERE image_id=?",(current,))
  reopened=Project.open(self.p.root)
  self.assertTrue(reopened.landmark_crop_ready(legacy))
  self.assertFalse(reopened.landmark_crop_ready(current))
  with reopened.transaction() as db:
   legacy_row=db.execute("SELECT human_verified,reviewed_at FROM crops WHERE image_id=?",(legacy,)).fetchone()
   current_row=db.execute("SELECT human_verified,reviewed_at FROM crops WHERE image_id=?",(current,)).fetchone()
  self.assertEqual(1,legacy_row['human_verified']);self.assertIsNotNone(legacy_row['reviewed_at'])
  self.assertEqual(0,current_row['human_verified']);self.assertEqual('2026-01-01T00:00:00+00:00',current_row['reviewed_at'])

 def test_reopen_preserves_raw_human_history_while_crop_review_is_effectively_pending(self):
  image_id=self.ids[0];self._final_crop(image_id)
  with self.p.transaction() as db:db.execute("UPDATE image_review SET human_verified=1 WHERE image_id=?",(image_id,))
  reopened=Project.open(self.p.root)
  self.assertTrue(reopened.landmark_crop_review_required(image_id));self.assertFalse(reopened.annotation_status(image_id)['verified'])
  self.assertFalse(reopened.catalog_row(image_id)['human_verified'])
  with reopened.transaction() as db:raw=db.execute("SELECT human_verified FROM image_review WHERE image_id=?",(image_id,)).fetchone()[0]
  self.assertEqual(1,raw)

 def test_reopen_does_not_erase_raw_human_history_for_pending_machine_state(self):
  image_id=self.ids[3]
  for ident in (1,2):self.p.delete_landmark(image_id,ident)
  self.p.clear_checked(image_id);self._final_crop(image_id)
  self.p.save_machine_landmarks(image_id,[{'landmark_id':1,'x':10,'y':10},{'landmark_id':2,'x':20,'y':10}],model_id='ai-model',prediction_run_id='pending-run')
  with self.p.transaction() as db:db.execute("UPDATE image_review SET human_verified=1 WHERE image_id=?",(image_id,))
  reopened=Project.open(self.p.root)
  self.assertFalse(reopened.annotation_status(image_id)['verified'])
  with reopened.transaction() as db:raw=db.execute("SELECT human_verified FROM image_review WHERE image_id=?",(image_id,)).fetchone()[0]
  self.assertEqual(1,raw)

 def test_complex_qc_checked_next_confirms_current_ai_state(self):
  image_id=self.ids[2]
  for ident in (1,2):self.p.delete_landmark(image_id,ident)
  self.p.clear_checked(image_id);self._final_crop(image_id)
  self.p.save_machine_landmarks(image_id,[{'landmark_id':1,'x':10,'y':10},{'landmark_id':2,'x':20,'y':10}],model_id='ai-model',prediction_run_id='qc-run')
  self.assertFalse(self.p.annotation_status(image_id)['verified'])
  self.assertIn(image_id,self.p.pending_ai_landmark_image_ids())
  state=_confirm_complex_qc_image(self.p,image_id)
  self.assertTrue(state['verified'])
  self.assertNotIn(image_id,self.p.pending_ai_landmark_image_ids())
  self.assertTrue(self.p.catalog_row(image_id)['human_verified'])
  self.assertTrue(all(bool(row.get('reviewed')) for row in self.p.load_landmarks(image_id).values()))

 def test_verify_ai_landmarks_can_finish_pending_crop_review(self):
  image_id=self.ids[1]
  for ident in (1,2):self.p.delete_landmark(image_id,ident)
  self.p.clear_checked(image_id);self._final_crop(image_id)
  self.p.save_machine_landmarks(image_id,[{'landmark_id':1,'x':10,'y':10},{'landmark_id':2,'x':20,'y':10}],model_id='ai-model',prediction_run_id='run-1')
  self.p.set_attribute(image_id,'landmark_crop_review_required','true')
  self.assertFalse(self.p.annotation_status(image_id)['verified']);self.assertEqual('yellow',self.p.catalog_row(image_id)['status_color'])
  self.p.mark_checked(image_id)
  self.assertFalse(self.p.landmark_crop_review_required(image_id));self.assertTrue(self.p.annotation_status(image_id)['verified'])
  self.assertTrue(self.p.landmark_ai_review_ready(image_id));self.assertTrue(self.p.catalog_row(image_id)['has_crop'])
  self.p.schema_path.write_text('id,abbr,name,role\n1,A,Alpha renamed,BOTH\n2,B,Beta renamed,BOTH\n',encoding='utf8')
  self.assertTrue(self.p.landmark_ai_review_ready(image_id))

 def test_human_corrected_ai_ancestry_is_not_still_pending(self):
  image_id=self.ids[0]
  self._final_crop(image_id);self.p.mark_checked(image_id)
  for ident in (1,2):self.p.delete_landmark(image_id,ident)
  self.p.clear_checked(image_id)
  self.p.save_machine_landmarks(image_id,[{'landmark_id':1,'x':10,'y':10},{'landmark_id':2,'x':20,'y':10}],model_id='ai-model',prediction_run_id='run-1')
  self.assertFalse(self.p.annotation_status(image_id)['verified'])
  self.p.save_landmark(image_id,1,11,10,'corrected','corrected_by_human')
  self.assertFalse(self.p.annotation_status(image_id)['verified'])
  self.p.save_landmark(image_id,2,21,10,'corrected','corrected_by_human')
  points=self.p.load_landmarks(image_id)
  self.assertTrue(all(point.get('model_id')=='ai-model' and point.get('prediction_run_id')=='run-1' for point in points.values()))
  self.assertTrue(all(not bool(point.get('reviewed')) for point in points.values()))
  self.assertTrue(self.p.annotation_status(image_id)['verified'])
  self.assertTrue(self.p.catalog_row(image_id)['human_verified'])
  bulk=next(row for row in self.p.catalog_rows() if row['image_id']==image_id)
  self.assertTrue(bulk['human_verified']);self.assertEqual('green',bulk['status_color'])
  self.assertTrue(self.p.landmark_ai_review_ready(image_id))
  self.assertNotIn(image_id,self.p.pending_ai_landmark_image_ids())
  self.assertIn(image_id,operator_eligible_image_ids(self.p))
  self.p._sync_auto_verified_images()
  self.assertTrue(self.p.annotation_status(image_id)['verified'])
  reopened=Project.open(self.p.root)
  self.assertTrue(reopened.annotation_status(image_id)['verified'])
  reopened_bulk=next(row for row in reopened.catalog_rows() if row['image_id']==image_id)
  self.assertTrue(reopened_bulk['human_verified']);self.assertEqual('green',reopened_bulk['status_color'])

 def test_remaining_machine_landmark_still_requires_ai_review(self):
  image_id=self.ids[1]
  self._final_crop(image_id);self.p.mark_checked(image_id)
  for ident in (1,2):self.p.delete_landmark(image_id,ident)
  self.p.clear_checked(image_id)
  self.p.save_machine_landmarks(image_id,[{'landmark_id':1,'x':10,'y':10},{'landmark_id':2,'x':20,'y':10}],model_id='ai-model',prediction_run_id='run-2')
  self.p.save_landmark(image_id,1,11,10,'corrected','corrected_by_human')
  self.assertFalse(self.p.annotation_status(image_id)['verified'])
  self.assertFalse(self.p.landmark_ai_review_ready(image_id))
  self.assertIn(image_id,self.p.pending_ai_landmark_image_ids())

 def _completed_repeatability_run(self,image_id):
  with patch('app.human_baseline.available_control_image_ids',return_value=(image_id,)):
   run,_=start_or_continue_run(self.p,count=1)
  first=ensure_pass(self.p,run['run_id'],1)[1];self._finish(first);complete_pass(self.p,run['run_id'],1);record_repeatability_pass_qc(self.p,run['run_id'],1,())
  _,second=ensure_pass(self.p,run['run_id'],2);self._finish(second,1);complete_pass(self.p,run['run_id'],2);record_repeatability_pass_qc(self.p,run['run_id'],2,())
  complete_run(self.p,run['run_id'],include_model=False)
  return run

 def test_repeatability_preflight_detects_legacy_changed_reference_before_inference(self):
  image_id=self.ids[0];run=self._completed_repeatability_run(image_id)
  first_sid=pass_session_ids(run,1)[0];session=_load(self.p,first_sid)
  from app.operator_qc import _save
  session['standardized_snapshot']=False
  session['standardized_relpath']=(self.p.cache_root/'standardized'/f'{image_id}.png').relative_to(self.p.data_root).as_posix()
  session['standardized_sha256']='0'*64
  _save(self.p,first_sid,session)
  issue=repeatability_reference_frame_issue(self.p,run['run_id'],1)
  self.assertEqual('legacy_changed',issue['kind']);self.assertEqual(1,issue['position']);self.assertEqual(1,issue['total'])
  self.assertEqual(image_id,issue['image_id']);self.assertEqual(1,issue['annotation'])

 def test_targeted_redo_clears_reference_frame_preflight_with_frozen_sessions(self):
  image_id=self.ids[0];run=self._completed_repeatability_run(image_id)
  first_sid=pass_session_ids(run,1)[0];session=_load(self.p,first_sid)
  from app.operator_qc import _save
  session['standardized_snapshot']=False
  session['standardized_relpath']=(self.p.cache_root/'standardized'/f'{image_id}.png').relative_to(self.p.data_root).as_posix()
  session['standardized_sha256']='0'*64
  _save(self.p,first_sid,session)
  self.assertIsNotNone(repeatability_reference_frame_issue(self.p,run['run_id'],1))
  live,result=redo_repeatability_image(self.p,run['run_id'],1)
  self.assertEqual(1,result['position'])
  self.assertIsNone(repeatability_reference_frame_issue(self.p,run['run_id'],1))
  self.assertIsNone(repeatability_reference_frame_issue(self.p,run['run_id'],2))
  for number in (1,2):
   repaired=_load(self.p,pass_session_ids(live,number)[0])
   self.assertTrue(repaired['standardized_snapshot'])
   self.assertTrue((self.p.data_root/repaired['standardized_relpath']).is_file())

 def test_redo_one_repeatability_image_preserves_every_other_session(self):
  image_ids=self.ids[:2]
  with patch('app.human_baseline.available_control_image_ids',return_value=tuple(image_ids)):
   run,_=start_or_continue_run(self.p,count=2)
  first=ensure_pass(self.p,run['run_id'],1)[1];self._finish(first);complete_pass(self.p,run['run_id'],1);record_repeatability_pass_qc(self.p,run['run_id'],1,())
  _,second=ensure_pass(self.p,run['run_id'],2);self._finish(second,1);complete_pass(self.p,run['run_id'],2);record_repeatability_pass_qc(self.p,run['run_id'],2,())
  complete_run(self.p,run['run_id'],include_model=False)
  old_first=tuple(first);old_second=tuple(second)
  live,result=redo_repeatability_image(self.p,run['run_id'],2)
  new_first=pass_session_ids(live,1);new_second=pass_session_ids(live,2)
  self.assertEqual(old_first[0],new_first[0]);self.assertEqual(old_second[0],new_second[0])
  self.assertNotEqual(old_first[1],new_first[1]);self.assertNotEqual(old_second[1],new_second[1])
  self.assertEqual(image_ids[1],result['image_id']);self.assertEqual(2,result['position']);self.assertEqual(2,result['total'])
  self.assertEqual((new_first[1],),pending_pass_session_ids(self.p,live,1));self.assertEqual((new_second[1],),pending_pass_session_ids(self.p,live,2))
  self.assertEqual(1,pass_progress(self.p,live,1)['completed']);self.assertEqual(1,pass_progress(self.p,live,2)['completed'])
  first_session=_load(self.p,new_first[1]);second_session=_load(self.p,new_second[1])
  self.assertEqual(first_session['standardized_sha256'],second_session['standardized_sha256'])
  self.assertEqual('in_progress',live['status']);self.assertTrue(live['report_stale'])

 def test_models_never_fall_back_to_old_report_while_targeted_repair_is_unfinished(self):
  image_id=self.ids[0];run=self._completed_repeatability_run(image_id)
  live,_=redo_repeatability_image(self.p,run['run_id'],1)
  state=repeatability_report_state(self.p)
  self.assertFalse(state['ready']);self.assertIsNone(state['report']);self.assertEqual(live['run_id'],state['run']['run_id'])
  self.assertIn('newest Human repeatability update is not finished',state['message'])
  self.assertIn('Annotation 1: 0/1 images',state['message']);self.assertIn('Annotation 2: 0/1 images',state['message'])

 def test_models_refresh_current_repaired_report_after_only_pending_sessions_are_finished(self):
  image_id=self.ids[0];run=self._completed_repeatability_run(image_id)
  live,_=redo_repeatability_image(self.p,run['run_id'],1)
  first=pending_pass_session_ids(self.p,live,1);second=pending_pass_session_ids(self.p,live,2)
  self.assertEqual(1,len(first));self.assertEqual(1,len(second))
  self._finish(first);complete_pass(self.p,run['run_id'],1);record_repeatability_pass_qc(self.p,run['run_id'],1,())
  self._finish(second,1);complete_pass(self.p,run['run_id'],2);record_repeatability_pass_qc(self.p,run['run_id'],2,())
  state=repeatability_report_state(self.p)
  self.assertTrue(state['ready']);self.assertEqual(run['run_id'],state['report']['run_id'])
  self.assertEqual('completed',state['run']['status']);self.assertFalse(state['run'].get('report_stale'))
  self.assertEqual(1,state['report']['human']['aggregate']['n_images'])

 def test_legacy_changed_frame_error_names_position_id_and_annotation(self):
  image_ids=self.ids[:2]
  with patch('app.human_baseline.available_control_image_ids',return_value=tuple(image_ids)):
   run,_=start_or_continue_run(self.p,count=2)
  first=ensure_pass(self.p,run['run_id'],1)[1];self._finish(first);complete_pass(self.p,run['run_id'],1);record_repeatability_pass_qc(self.p,run['run_id'],1,())
  _,second=ensure_pass(self.p,run['run_id'],2);self._finish(second,1);complete_pass(self.p,run['run_id'],2);record_repeatability_pass_qc(self.p,run['run_id'],2,())
  complete_run(self.p,run['run_id'],include_model=False)
  target_sid=first[1];session=_load(self.p,target_sid)
  canonical=self.p.cache_root/'standardized'/f"{image_ids[1]}.png"
  session['standardized_relpath']=canonical.relative_to(self.p.data_root).as_posix();session['standardized_snapshot']=False
  from app.operator_qc import _save
  _save(self.p,target_sid,session)
  Image.new('RGB',(40,30),(23,24,25)).save(canonical)
  digest=schema_hash(self.p.schema_path);self.p.register_model('legacy-message-model','landmark',schema_digest=digest)
  backend=MockBackend(digest,model_id='legacy-message-model',coordinate_overrides={1:(10,10),2:(20,10)})
  with self.assertRaises(ValueError) as caught:
   evaluate_model_on_repeatability_run(self.p,run['run_id'],'legacy-message-model',backend=backend)
  message=str(caught.exception)
  self.assertIn('Image: 2/2',message);self.assertIn(f'ID: {image_ids[1]}',message);self.assertIn('Batch: Annotation 1',message);self.assertIn('Only this image must be repeated in Annotation 1 and Annotation 2.',message)

 def test_compare_manual_uses_frozen_repeatability_annotation_not_current_verified_state(self):
  image_id=self.ids[0];run=self._completed_repeatability_run(image_id)
  digest=schema_hash(self.p.schema_path);self.p.register_model('frozen-model','landmark',schema_digest=digest)
  backend=MockBackend(digest,model_id='frozen-model',coordinate_overrides={1:(10,10),2:(20,10)})
  self.p.clear_checked(image_id)
  self.assertFalse(self.p.annotation_status(image_id)['verified'])
  result=evaluate_model_on_repeatability_run(self.p,run['run_id'],'frozen-model',backend=backend)
  self.assertEqual((image_id,),tuple(result['control_image_ids']));self.assertEqual(1,result['aggregate']['n_images']);self.assertEqual(0.0,result['aggregate']['p90_error_percent'])
  self.assertEqual('human_repeatability_annotation_1',result['reference_source'])

 def test_annotation_two_reuses_annotation_one_frozen_frame_after_cache_rewrite(self):
  image_id=self.ids[0]
  with patch('app.human_baseline.available_control_image_ids',return_value=(image_id,)):
   run,_=start_or_continue_run(self.p,count=1)
  first=ensure_pass(self.p,run['run_id'],1)[1];self._finish(first);complete_pass(self.p,run['run_id'],1);record_repeatability_pass_qc(self.p,run['run_id'],1,())
  first_session=_load(self.p,first[0]);first_path=self.p.data_root/first_session['standardized_relpath'];first_bytes=first_path.read_bytes()
  Image.new('RGB',(40,30),(7,8,9)).save(self.p.cache_root/'standardized'/f'{image_id}.png')
  _,second=ensure_pass(self.p,run['run_id'],2)
  second_session=_load(self.p,second[0]);second_path=self.p.data_root/second_session['standardized_relpath']
  self.assertTrue(first_session['standardized_snapshot']);self.assertTrue(second_session['standardized_snapshot'])
  self.assertNotEqual(first_path,second_path);self.assertEqual(first_bytes,second_path.read_bytes())
  self.assertEqual(first_session['standardized_sha256'],second_session['standardized_sha256'])

 def test_compare_manual_uses_frozen_repeatability_image_after_canonical_cache_rewrite(self):
  image_id=self.ids[0];run=self._completed_repeatability_run(image_id)
  digest=schema_hash(self.p.schema_path);self.p.register_model('frozen-model','landmark',schema_digest=digest)
  backend=MockBackend(digest,model_id='frozen-model',coordinate_overrides={1:(10,10),2:(20,10)})
  Image.new('RGB',(40,30),(1,2,3)).save(self.p.cache_root/'standardized'/f'{image_id}.png')
  result=evaluate_model_on_repeatability_run(self.p,run['run_id'],'frozen-model',backend=backend)
  self.assertEqual((image_id,),tuple(result['control_image_ids']));self.assertEqual(0.0,result['aggregate']['p90_error_percent'])

 def test_compare_manual_rejects_tampered_frozen_repeatability_image(self):
  image_id=self.ids[0];run=self._completed_repeatability_run(image_id)
  digest=schema_hash(self.p.schema_path);self.p.register_model('frozen-model','landmark',schema_digest=digest)
  backend=MockBackend(digest,model_id='frozen-model',coordinate_overrides={1:(10,10),2:(20,10)})
  first_sid=pass_session_ids(run,1)[0];session=_load(self.p,first_sid)
  frozen=self.p.data_root/session['standardized_relpath']
  Image.new('RGB',(40,30),(4,5,6)).save(frozen)
  with self.assertRaisesRegex(ValueError,image_id):
   evaluate_model_on_repeatability_run(self.p,run['run_id'],'frozen-model',backend=backend)

 def test_landmark_counter_delta_never_scans_catalog_or_trainer(self):
  context=UIContext(self.p,'landmarks');context.refresh(force=True);self.assertEqual(0,context.landmark_counts()['New/changed'])
  image_id=self.ids[0];self.p.delete_landmark(image_id,1)
  with patch.object(self.p,'catalog_rows',side_effect=AssertionError('whole catalog scan')),patch('app.landmark_dataset.v2_human_final_eligible_image_ids',side_effect=AssertionError('whole trainer scan')):
   self.assertTrue(context.refresh_landmark_state(image_id));counts=context.update_landmark_counts(image_id)
  self.assertEqual(1,counts['Incomplete']);self.assertEqual(0,counts['New/changed'])
 def test_landmark_batch_counter_uses_cached_rows_without_status_scan(self):
  ids=self.ids[:3];self.p.set_ui_state(STATE_KEY,{'stage':'INITIAL_TRAINING','initial_image_ids':ids,'improvement_image_ids':[],'current_image_id':ids[0],'current_position':0})
  context=UIContext(self.p,'landmarks');context.refresh(force=True);shell=ProductionShell.__new__(ProductionShell);shell.context=context
  with patch.object(self.p,'annotation_status',side_effect=AssertionError('batch-wide status scan')):
   summary=shell._active_batch_summary()
  self.assertEqual('landmark',summary['kind']);self.assertIn('1 / 3',summary['text'])
 def test_shared_batch_position_is_exact_and_final_is_explicit(self):
  ids=['a','b','c'];self.assertEqual({'position':2,'total':3,'remaining':2,'final':False},position_and_remaining(ids,'b',{'a'}));self.assertEqual({'position':3,'total':3,'remaining':1,'final':True},position_and_remaining(ids,'c',{'a','b'}))
 def test_forward_next_accepts_complete_initial_and_improvement_batches(self):
  ids=self.ids[:4]
  for stage,key in (('INITIAL_TRAINING','initial_image_ids'),('MODEL_IMPROVEMENT','improvement_image_ids')):
   for image_id in ids:self.p.clear_checked(image_id)
   state={'stage':stage,'initial_image_ids':ids if key=='initial_image_ids' else [],'improvement_image_ids':ids if key=='improvement_image_ids' else [],'current_image_id':ids[0],'current_position':0}
   self.p.set_ui_state(STATE_KEY,state);context=UIContext(self.p,'landmarks');context.refresh(force=True);context.landmark_counts();section=self._batch_section(context)
   with patch('app.ui.landmarks_section.messagebox.showinfo'),patch.object(self.p,'catalog_rows',side_effect=AssertionError('global catalog scan')),patch('app.landmark_dataset.v2_human_final_eligible_image_ids',side_effect=AssertionError('global trainer scan')):
    self.assertTrue(section.navigate_training_batch(1))
   self.assertTrue(self.p.annotation_status(ids[0])['verified']);self.assertFalse(self.p.annotation_status(ids[1])['verified']);self.assertEqual(ids[1],context.current()['image_id']);self.assertEqual('green',next(row for row in context.rows if row['image_id']==ids[0])['status_color']);self.assertEqual(0,context.landmark_counts()['New/changed'])
   self.assertTrue(section.navigate_training_batch(-1));self.assertFalse(self.p.annotation_status(ids[1])['verified']);self.assertEqual(ids[0],context.current()['image_id'])
 def test_final_batch_next_accepts_final_member_and_persists_position(self):
  ids=self.ids[:4]
  for image_id in ids:self.p.clear_checked(image_id)
  self.p.set_ui_state(STATE_KEY,{'stage':'INITIAL_TRAINING','initial_image_ids':ids,'improvement_image_ids':[],'current_image_id':ids[0],'current_position':0})
  context=UIContext(self.p,'landmarks');context.refresh(force=True);section=self._batch_section(context)
  with patch('app.ui.landmarks_section.messagebox.showinfo'),patch('app.ui.landmarks_section.messagebox.askyesno',return_value=False):
   for expected in ids[1:]:
    self.assertTrue(section.navigate_training_batch(1));self.assertEqual(expected,context.current()['image_id'])
   self.assertTrue(section.navigate_training_batch(1))
  self.assertTrue(all(self.p.annotation_status(image_id)['verified'] for image_id in ids));self.assertEqual(ids[-1],load_state(self.p)['current_image_id']);self.assertEqual(len(ids)-1,load_state(self.p)['current_position'])
 def test_incomplete_batch_next_neither_verifies_nor_advances(self):
  ids=self.ids[:4]
  for stage,key in (('INITIAL_TRAINING','initial_image_ids'),('MODEL_IMPROVEMENT','improvement_image_ids')):
   self.p.delete_landmark(ids[0],1);self.p.clear_checked(ids[0])
   self.p.set_ui_state(STATE_KEY,{'stage':stage,'initial_image_ids':ids if key=='initial_image_ids' else [],'improvement_image_ids':ids if key=='improvement_image_ids' else [],'current_image_id':ids[0],'current_position':0})
   context=UIContext(self.p,'landmarks');context.refresh(force=True);section=self._batch_section(context,complete=False)
   self.assertTrue(section.navigate_training_batch(1))
   self.assertFalse(self.p.annotation_status(ids[0])['verified']);self.assertEqual(ids[0],context.current()['image_id'])
   self.p.save_landmark(ids[0],1,10,10,'manual','manual');self.p.mark_checked(ids[0])
 def test_ordinary_catalog_navigation_is_never_auto_verified(self):
  image_id=self.ids[0];self.p.clear_checked(image_id);self.p.set_ui_state(STATE_KEY,{'stage':'IDLE','initial_image_ids':[],'improvement_image_ids':[]})
  context=UIContext(self.p,'landmarks');context.refresh(force=True);section=self._batch_section(context)
  self.assertFalse(section.navigate_training_batch(1));self.assertFalse(self.p.annotation_status(image_id)['verified'])
 def test_human_window_is_native_and_launcher_is_direct(self):
  ui=(Path(__file__).parents[1]/'app'/'human_baseline_ui.py').read_text(encoding='utf8');section=(Path(__file__).parents[1]/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertNotIn('self.transient(parent)',ui);self.assertIn("'Confirm & Finish' if final",ui);self.assertIn("'Edit repeat annotations...',self.open_repeat",section)
 def test_section_specific_counts_are_authoritative(self):
  self.assertEqual(0,self.p.landmark_counts()['New/changed'])
  self.assertEqual(0,self.p.crop_section_counts()['Train ready'])
  first=self.ids[0];self.p.save_crop(first,{'crop_bounds':[0,0,10,10]},'manual');self.p.save_reviewed_crop(first,{'crop_bounds':[0,0,10,10]})
  self.assertEqual(1,self.p.crop_section_counts()['Train ready']);self.assertEqual({'Reviewed':1,'Remaining':1,'Train ready':1,'Total':2},self.p.crop_batch_counts(self.ids[:2]))
 def test_excluded_member_does_not_count_in_crop_batch(self):
  self.p.exclude_image(self.ids[0],'Bad image');self.assertEqual({'Reviewed':0,'Remaining':1,'Train ready':0,'Total':1},self.p.crop_batch_counts(self.ids[:2]))
 def test_persisted_landmark_batch_navigation_never_falls_to_catalog(self):
  a,b,c=self.ids[:3];state={'stage':'INITIAL_TRAINING','initial_image_ids':[a,b],'improvement_image_ids':[],'current_image_id':a,'current_position':0}
  self.p.set_ui_state(STATE_KEY,state)
  context=UIContext(self.p,'landmarks');context.refresh(force=True);section=self._batch_section(context)
  with patch('app.ui.landmarks_section.messagebox.showwarning'):
   self.assertTrue(section.navigate_training_batch(1));self.assertEqual(b,context.current()['image_id'])
  section.canvas.state=type('State',(),{'complete':False})()
  self.assertTrue(section.navigate_training_batch(1))
 def test_clear_all_resets_only_current_image_through_existing_rebuild_path(self):
  from app.ui.landmark_canvas import LandmarkCanvasController
  image_id=self.ids[0];before=self.p.load_landmarks(image_id);other_before=self.p.load_landmarks(self.ids[1])
  canvas=LandmarkCanvasController.__new__(LandmarkCanvasController);canvas.image_id=image_id;canvas._points=before;canvas.parent=object();canvas.context=SimpleNamespace(project=self.p);canvas.changed=Mock();canvas.refresh_authoritative=Mock();canvas._draw_overlays=Mock();canvas._sync_selection=Mock();canvas.operator_state=Mock();canvas.choice=Mock()
  with patch('app.ui.landmark_canvas.messagebox.askyesno',return_value=True):LandmarkCanvasController.clear_all(canvas)
  self.assertFalse(self.p.annotation_status(image_id)['verified']);self.assertEqual({1,2},set(self.p.annotation_status(image_id)['unresolved_ids']));canvas.changed.assert_called_once()
  canvas.operator_state.select.assert_called_once_with(1);canvas.choice.set.assert_called_once_with(1)
  self.assertEqual(other_before,self.p.load_landmarks(self.ids[1]))
 def test_clear_repeat_session_never_changes_canonical_landmarks(self):
  from app.operator_qc import create_repeat_session,clear_repeat_landmarks
  image_id=self.ids[0];before=self.p.load_landmarks(image_id);session=create_repeat_session(self.p,image_id,eligibility_prevalidated=True);sid=session['repeat_session_id']
  set_repeat_landmark(self.p,sid,1,3,4);set_repeat_landmark(self.p,sid,2,5,6);clear_repeat_landmarks(self.p,sid)
  self.assertEqual([], _load(self.p,sid)['repeat']);self.assertEqual(before,self.p.load_landmarks(image_id))
 def test_landmark_load_defers_crop_lookup_until_background_worker(self):
  from app.ui.landmark_canvas import LandmarkCanvasController
  class Canvas:
   def delete(self,*_a):pass
   def create_text(self,*_a,**_k):pass
   def itemconfigure(self,*_a,**_k):pass
   def after(self,*_a):return 'after-id'
  project=Mock();project.crop_record.side_effect=AssertionError('crop lookup must not run on Tk thread')
  controller=LandmarkCanvasController.__new__(LandmarkCanvasController);controller.context=SimpleNamespace(current=lambda:{'image_id':'one'},project=project);controller.canvas=Canvas();controller._token=0;controller._events=queue.Queue();controller._destroyed=False;controller._poll_ids=set();controller._poll=None;controller._prefetch_lock=threading.Lock();controller._prefetched={};controller._prefetching=set();controller._workers=set();controller._closing=threading.Event()
  with patch('app.ui.landmark_canvas.threading.Thread') as thread:LandmarkCanvasController.load_current(controller)
  project.crop_record.assert_not_called();thread.assert_called_once();thread.return_value.start.assert_called_once()
 def test_current_batch_warms_exactly_one_next_image(self):
  from app.ui.landmark_canvas import LandmarkCanvasController
  ids=self.ids[:3];self.p.set_ui_state(STATE_KEY,{'stage':'INITIAL_TRAINING','initial_image_ids':ids,'improvement_image_ids':[]})
  controller=LandmarkCanvasController.__new__(LandmarkCanvasController);controller.context=SimpleNamespace(project=self.p);controller.prefetch=Mock()
  LandmarkCanvasController._prefetch_next_batch_image(controller,ids[0]);controller.prefetch.assert_called_once_with(ids[1])
 def test_all_finite_manual_landmark_batch_paths_share_common_error_review(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertIn("self._offer_batch_error_review(session['image_ids'],'Prediction review complete',summary)",source)
  self.assertIn("self._offer_batch_error_review(ids,title,message)",source)
  self.assertIn("scan_project(self.context.project,image_ids=ids",source)

 def test_unmark_missing_restores_previous_production_point(self):
  image_id=self.ids[0];before=self.p.load_landmarks(image_id)[1]
  self.p.save_landmark(image_id,1,None,None,'missing','missing')
  self.assertEqual('missing',self.p.load_landmarks(image_id)[1]['state'])
  self.assertTrue(self.p.restore_landmark_before_missing(image_id,1))
  restored=self.p.load_landmarks(image_id)[1]
  self.assertEqual(before['x_standardized'],restored['x_standardized']);self.assertEqual(before['y_standardized'],restored['y_standardized'])

 def test_reapply_unverified_includes_partial_and_complete_unverified_but_not_empty_or_verified(self):
  partial,complete_unverified,verified,empty=self.ids
  self.p.delete_landmark(partial,2);self.p.clear_checked(partial)
  self.p.clear_checked(complete_unverified)
  for ident in (1,2):self.p.delete_landmark(empty,ident)
  self.p.clear_checked(empty)
  rows=self.p.catalog_rows()
  with patch('app.ui.landmarks_section.landmark_frame_ready',return_value=True):
   ids=_reapply_unverified_prediction_ids(self.p,rows)
  self.assertIn(partial,ids);self.assertIn(complete_unverified,ids)
  self.assertNotIn(verified,ids);self.assertNotIn(empty,ids)

 def test_repeatability_percent_is_human_readable_but_precise_value_can_stay_stored(self):
  self.assertEqual('0.50%',_format_percent(0.49731822679167603))
  self.assertEqual('not available',_format_percent(None))

 def test_landmark_toolbar_labels_missing_and_verified_states_explicitly(self):
  missing=SimpleNamespace(points_by_id={2:{'state':'missing'}},human_verified=False)
  self.assertEqual({'missing_text':'Unmark missing','verify_text':'Verify image','verify_enabled':True},_landmark_toolbar_state(missing,2))
  verified=SimpleNamespace(points_by_id={2:{'state':'present'}},human_verified=True)
  self.assertEqual('Mark missing',_landmark_toolbar_state(verified,2)['missing_text'])
  self.assertEqual('Verified ✓',_landmark_toolbar_state(verified,2)['verify_text'])
  self.assertFalse(_landmark_toolbar_state(verified,2)['verify_enabled'])

 def test_apply_reapply_remaining_targets_unannotated_and_unverified_ai_only(self):
  project=Mock();project.pending_ai_landmark_image_ids.return_value=('ai-pending',)
  project.annotation_status.return_value={'verified':False}
  project.load_landmarks.side_effect=lambda image_id:{} if image_id=='empty' else {1:{'state':'present'}}
  rows=[{'image_id':'empty'},{'image_id':'ai-pending'},{'image_id':'human-partial'},{'image_id':'excluded','excluded':True}]
  with patch('app.ui.landmarks_section.landmark_frame_ready',return_value=True):
   self.assertEqual(('empty','ai-pending'),_remaining_prediction_ids(project,rows))

 def test_landmarks_ui_has_single_apply_reapply_remaining_action(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertIn("'All remaining'",source)
  self.assertIn("'Reapply'",source)
  self.assertNotIn("self.button(predict_actions,'Reapply AI pending'",source)
  self.assertIn("self.missing_button",source);self.assertIn("'Verify image'",source)

 def test_landmark_models_window_is_plain_language_and_opens_accuracy_details(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'shell.py').read_text(encoding='utf8')
  self.assertIn('text="Landmark models"',source)
  self.assertIn('"Training images"',source)
  self.assertIn('"Validation P90"',source)
  self.assertIn('"Accuracy details…"',source)
  self.assertIn('open_landmark_accuracy',source)
  self.assertIn("same-image human comparison",source)

 def test_landmark_header_uses_non_overlapping_meaningful_labels(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'context.py').read_text(encoding='utf8')
  self.assertIn('("Human verified", "Training set", "New/changed", "Incomplete")',source)
  shell=(Path(__file__).parents[1]/'app'/'ui'/'shell.py').read_text(encoding='utf8')
  self.assertIn('"Training set":"Verified, complete images currently eligible for model training.',shell)
  self.assertIn('"New/changed":"Training-set images whose current Crop or landmarks are not yet represented',shell)

 def test_active_section_has_theme_independent_visual_marker(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'shell.py').read_text(encoding='utf8')
  self.assertIn('("● "+spec.label) if active else spec.label',source)
  self.assertIn('relief="sunken"',source)

 def test_existing_standardized_crop_is_usable_without_source_or_developed_cache(self):
  from app.landmark_frames import crop_frame_record,restore_standardized_frame
  image_id='cached-only';standardized=self.root/'cache'/'standardized'/f'{image_id}.png';standardized.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(20,10)).save(standardized)
  transform={'original_width':20,'original_height':10,'rotation_degrees':0.0,'center_x':10.0,'center_y':5.0,'crop_left':0.0,'crop_top':0.0,'output_width':20,'output_height':10}
  project=SimpleNamespace(
   data_root=self.root,cache_root=self.root/'cache',
   crop_record=lambda _id:{'crop_json':[0,0,20,10],'transform_json':transform,'developed_relpath':'cache/developed/missing.png','standardized_relpath':f'cache/standardized/{image_id}.png'},
   image_path=lambda _id:None,
  )
  self.assertIsNotNone(crop_frame_record(project,image_id))
  path,rebuilt=restore_standardized_frame(project,image_id)
  self.assertEqual(standardized,path);self.assertFalse(rebuilt)

 def test_random_lm1_is_traced_not_silently_deleted(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'landmark_canvas.py').read_text(encoding='utf8')
  self.assertIn('production_landmark_lm1_loaded',source)
  self.assertIn('production_landmark_place',source)
  self.assertNotIn('delete_landmark(self.image_id, 1)',source)

 def test_main_drag_release_defers_expensive_refresh(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'landmark_canvas.py').read_text(encoding='utf8')
  release=source[source.index('    def release(self, _event):'):source.index('    def current_is_missing',source.index('    def release(self, _event):'))]
  normal_tail=release[release.index('log(self.image_id, "production_landmark_drag_release"'):]
  self.assertNotIn('refresh_authoritative',normal_tail)
  self.assertIn('self.canvas.after_idle(self.changed)',normal_tail)

 def test_review_worst_v2_is_background_bounded_and_explainable(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertIn("lambda:self.review_worst(prediction.get())",source)
  self.assertIn("self.shell._run_background_task('Unverified AI review'",source)
  self.assertIn("'review_worst_v2'",source)
  self.assertIn("self.canvas.clear_review_landmarks()",source)
  self.assertIn("display_reason='Inspect all landmarks' if reason.startswith('Correction history:') else reason",source)
  self.assertIn("self._inline_status('Unverified AI review: '+display_reason)",source)

 def test_landmark_loading_reports_preparation_stages(self):
  source=(Path(__file__).parents[1]/'app'/'ui'/'landmark_canvas.py').read_text(encoding='utf8')
  self.assertIn('progress("Checking saved crop frame")',source)
  self.assertIn('progress("Preparing saved crop frame")',source)
  self.assertIn('progress("Opening crop image" if not rebuilt else "Opening rebuilt crop image")',source)
  self.assertIn('if status=="progress":',source)
  self.assertIn('self._loading_text = str(text)',source)
  self.assertIn('text=self._loading_text+dots',source)
  self.assertIn('self._loading_text=str(error)',source)
  self.assertIn('"production_landmark_load_stage"',source)

 def test_ai_hardware_is_warmed_on_launch_and_prediction_tuning_is_visible(self):
  shell=(Path(__file__).parents[1]/'app'/'ui'/'shell.py').read_text(encoding='utf8')
  landmarks=(Path(__file__).parents[1]/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  service=(Path(__file__).parents[1]/'app'/'landmark_ai_service.py').read_text(encoding='utf8')
  self.assertIn('threading.Thread(target=self._warm_ai_hardware',shell)
  self.assertIn('persist_machine_profile(profile)',shell)
  self.assertIn("kind=='status'",landmarks)
  self.assertIn('Calibrating inference — first run only…',service)
  self.assertIn('Running AI: batch',service)

 def test_human_baseline_clear_all_control_is_present(self):
  ui=(Path(__file__).parents[1]/'app'/'human_baseline_ui.py').read_text(encoding='utf8')
  self.assertIn("text='Clear image…'",ui);self.assertIn('self.surface.clear_all()',ui)
if __name__=='__main__':unittest.main()

