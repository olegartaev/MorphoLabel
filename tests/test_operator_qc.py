import json, math, shutil, tempfile, unittest
from pathlib import Path
from PIL import Image
from app.ai import MockBackend
from app.landmark_ai_service import LandmarkAIService
from app.landmark_qc import evaluate_model, save_qc_report
from app.operator_qc import (blind_session_input, cancel_repeat_session, complete_repeat_session,
    create_repeat_session, evaluate_operator_sessions, operator_eligible_image_ids,
    remove_repeat_landmark, save_operator_report, select_repeat_candidates, set_repeat_landmark)
from app.project_storage import Project, schema_hash
from app.transforms import Transform

class OperatorQCTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp()); self.src=self.tmp/'source'; self.src.mkdir()
  for n in range(3): (self.src/f'image_{n}.jpg').write_bytes(b'x')
  self.schema=self.tmp/'schema.csv'; self.schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf-8')
  self.p=Project.create('operator-qc',self.src,self.tmp,self.schema,source_layout='direct')
  self.ids=[row['image_id'] for row in self.p.catalog_rows()]
  for image_id in self.ids:
   path=self.p.cache_root/'standardized'/f'{image_id}.png'; path.parent.mkdir(parents=True,exist_ok=True); Image.new('RGB',(100,80)).save(path)
   transform=Transform(100,80,0.0,50.0,40.0,0.0,0.0,100,80)
   self.p.save_reviewed_crop(image_id, {"developed_full_relpath": f"cache/standardized/{image_id}.png", "standardized_relpath": f"cache/standardized/{image_id}.png", "crop_bounds": [0,0,100,80], "rotation_degrees": 0.0, "transform": transform.__dict__, "normalization_status": "final"})
   self._manual(image_id)
 def tearDown(self): shutil.rmtree(self.tmp,ignore_errors=True)
 def _manual(self,image_id,missing=()):
  self.p.save_landmark(image_id,1,None if 1 in missing else 10,None if 1 in missing else 10,'missing' if 1 in missing else 'manual',provenance='manual')
  self.p.save_landmark(image_id,2,None if 2 in missing else 20,None if 2 in missing else 20,'missing' if 2 in missing else 'manual',provenance='manual')
 def _new(self,image_id=None): return create_repeat_session(self.p,image_id or self.ids[0])['repeat_session_id']
 def _complete(self,sid,one=(10,10),two=(20,20),missing=()):
  set_repeat_landmark(self.p,sid,1,*one,state='missing' if 1 in missing else 'present')
  set_repeat_landmark(self.p,sid,2,*two,state='missing' if 2 in missing else 'present')
  return complete_repeat_session(self.p,sid)
 def _session_json(self,sid): return json.loads((self.p.data_root/'ai'/'operator_sessions'/sid/'session.json').read_text(encoding='utf-8'))
 def test_01_repeat_does_not_change_canonical_landmarks(self):
  before=self.p.load_landmarks(self.ids[0]); sid=self._new(); set_repeat_landmark(self.p,sid,1,13,14); self.assertEqual(self.p.load_landmarks(self.ids[0]),before)
 def test_02_baseline_snapshot_is_immutable_after_canonical_edit(self):
  sid=self._new(); baseline=self._session_json(sid)['baseline']; self.p.save_landmark(self.ids[0],1,90,91,'corrected',provenance='corrected_by_human'); self.assertEqual(self._session_json(sid)['baseline'],baseline)
 def test_03_fully_manual_image_is_default_eligible(self): self.assertIn(self.ids[0],operator_eligible_image_ids(self.p))
 def test_03b_eligibility_is_bulk_and_does_not_requery_each_image(self):
  original_status=self.p.annotation_status;original_load=self.p.load_landmarks
  self.p.annotation_status=lambda _image_id: (_ for _ in ()).throw(AssertionError('per-image annotation_status call'))
  self.p.load_landmarks=lambda _image_id: (_ for _ in ()).throw(AssertionError('per-image load_landmarks call'))
  try:eligible=operator_eligible_image_ids(self.p)
  finally:self.p.annotation_status=original_status;self.p.load_landmarks=original_load
  self.assertEqual(set(self.ids),set(eligible))
 def test_04_ai_only_checked_image_is_not_default_eligible(self):
  image=self.ids[2]; self.p.replace_landmarks(image,{})
  LandmarkAIService(self.p,MockBackend(schema_hash(self.p.schema_path))).predict_one(image); self.p.mark_checked(image)
  self.assertNotIn(image,operator_eligible_image_ids(self.p))
 def test_05_repeat_coordinates_persist_and_reload(self):
  sid=self._new(); set_repeat_landmark(self.p,sid,1,13,14); self.assertEqual(self._session_json(sid)['repeat'][0]['x'],13); self.assertEqual(blind_session_input(self.p,sid)['image_id'],self.ids[0])
 def test_06_repeat_manual_missing_does_not_change_canonical(self):
  before=self.p.load_landmarks(self.ids[0])[1]; sid=self._new(); set_repeat_landmark(self.p,sid,1,0,0,state='missing'); self.assertEqual(self.p.load_landmarks(self.ids[0])[1],before)
 def test_07_incomplete_repeat_cannot_complete(self):
  sid=self._new(); set_repeat_landmark(self.p,sid,1,10,10)
  with self.assertRaises(ValueError): complete_repeat_session(self.p,sid)
 def test_08_completed_session_cannot_be_edited(self):
  sid=self._new(); self._complete(sid)
  with self.assertRaises(ValueError): set_repeat_landmark(self.p,sid,1,1,1)
 def test_09_cancelled_session_is_not_in_qc(self):
  sid=self._new(); cancel_repeat_session(self.p,sid); result=evaluate_operator_sessions(self.p,[sid]); self.assertEqual(result['aggregate']['n_sessions'],0)
 def test_10_candidate_selection_is_deterministic_for_seed(self): self.assertEqual(select_repeat_candidates(self.p,2,123),select_repeat_candidates(self.p,2,123))
 def test_11_completed_image_is_avoided_while_new_candidates_exist(self):
  sid=self._new(self.ids[0]); self._complete(sid); self.assertNotIn(self.ids[0],select_repeat_candidates(self.p,2,7)['image_ids'])
 def test_12_known_geometry_has_exactly_five_pixel_error(self):
  sid=self._new(); self._complete(sid,one=(13,14)); self.assertEqual(evaluate_operator_sessions(self.p,[sid])['per_image'][0]['max_error_px'],5)
 def test_13_normalized_diagonal_metric_is_correct(self):
  sid=self._new(); self._complete(sid,one=(13,14)); r=evaluate_operator_sessions(self.p,[sid]); self.assertAlmostEqual(r['per_image'][0]['max_error_normalized'],5/math.hypot(100,80))
 def test_14_calibration_gives_correct_error_mm(self):
  image=self.p.catalog_rows()[0]; self.p.set_locality_calibration(image['locality'] or image['sample_id'],self.ids[0],2,'mm',{})
  sid=self._new(); self._complete(sid,one=(13,14)); self.assertAlmostEqual(evaluate_operator_sessions(self.p,[sid])['per_image'][0]['max_error_mm'],2.5)
 def test_15_baseline_present_repeat_missing_is_separate(self):
  sid=self._new(); self._complete(sid,missing={1}); r=evaluate_operator_sessions(self.p,[sid]); self.assertEqual(r['aggregate']['baseline_present_repeat_missing'],1); self.assertEqual(r['aggregate']['baseline_missing_repeat_present'],0)
 def test_16_baseline_missing_repeat_present_is_separate(self):
  self._manual(self.ids[0],missing={1}); sid=self._new(); self._complete(sid); r=evaluate_operator_sessions(self.p,[sid]); self.assertEqual(r['aggregate']['baseline_missing_repeat_present'],1); self.assertEqual(r['aggregate']['baseline_present_repeat_missing'],0)
 def test_17_per_landmark_metrics_identify_larger_error(self):
  sid=self._new(); self._complete(sid,one=(11,10),two=(26,28)); r=evaluate_operator_sessions(self.p,[sid]); self.assertGreater(r['per_landmark']['2']['max_error_px'],r['per_landmark']['1']['max_error_px'])
 def test_18_per_image_metrics_identify_worst_image(self):
  a=self._new(self.ids[0]); self._complete(a,one=(11,10)); b=self._new(self.ids[1]); self._complete(b,one=(20,20)); r=evaluate_operator_sessions(self.p,[a,b]); by={x['image_id']:x for x in r['per_image']}; self.assertGreater(by[self.ids[1]]['max_error_px'],by[self.ids[0]]['max_error_px'])
 def test_19_operator_report_is_immutable_after_future_project_edit(self):
  sid=self._new(); self._complete(sid); path=save_operator_report(self.p,evaluate_operator_sessions(self.p,[sid]),'immutable'); before=path.read_bytes(); self.p.save_landmark(self.ids[0],1,99,99,'corrected',provenance='corrected_by_human'); self.assertEqual(path.read_bytes(),before)
 def test_20_ai_qc_report_keeps_historical_human_final_snapshot(self):
  image=self.ids[0]; self.p.replace_landmarks(image,{})
  run=LandmarkAIService(self.p,MockBackend(schema_hash(self.p.schema_path))).predict_one(image)
  self.p.save_landmark(image,1,40,50,'corrected',provenance='corrected_by_human',model_id='mock-landmark-v1',predicted_x=37,predicted_y=53,confidence=.9,prediction_run_id=run.prediction_run_id); self.p.mark_checked(image)
  report=save_qc_report(self.p,evaluate_model(self.p,'mock-landmark-v1'),'historical'); snapshot=json.loads(report.read_text(encoding='utf-8'))['per_image'][0]['human_final_snapshot']; self.p.save_landmark(image,1,70,80,'corrected',provenance='corrected_by_human',model_id='mock-landmark-v1',predicted_x=37,predicted_y=53,confidence=.9,prediction_run_id=run.prediction_run_id); self.assertEqual(json.loads(report.read_text(encoding='utf-8'))['per_image'][0]['human_final_snapshot'],snapshot)

if __name__=='__main__': unittest.main()
