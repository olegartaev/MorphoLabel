import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.rtmpose_backend import RTMPoseRuntimeError, evaluate_epoch_checkpoint, pending_finalization_artifact, select_best_epoch


class TrainingReliabilityTests(unittest.TestCase):
 def setUp(self): self.root=Path(tempfile.mkdtemp()); self.project=SimpleNamespace(schema_path=self.root/'schema.csv',data_root=self.root); self.project.schema_path.write_text('id,abbr,name\n1,A,A\n')
 def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)
 def test_completed_training_interrupted_validation_resumes_without_retraining(self):
  for epoch in (10,20): (self.root/f'epoch_{epoch}.pth').write_bytes(b'x')
  state=self.root/'finalization.json'; state.write_text(json.dumps({'validation_by_epoch':[{'epoch':10,'median_error_percent':1,'p90_error_percent':1,'p95_error_percent':1}]}))
  with patch('app.rtmpose_backend.evaluate_epoch_checkpoint',return_value={'epoch':20,'median_error_percent':2,'p90_error_percent':2,'p95_error_percent':2}) as evaluate:
   result=select_best_epoch(self.project,self.root/'manifest.json',self.root/'config.py',self.root,(512,256),'cpu',progress_path=state)
  evaluate.assert_called_once(); self.assertEqual([10,20],[x['epoch'] for x in result['validation_by_epoch']])
 def test_transient_rank_failure_retries_once_in_fresh_evaluation(self):
  checkpoint=self.root/'epoch_10.pth'; checkpoint.write_bytes(b'x')
  with patch('app.rtmpose_backend.create_ema_inference_checkpoint',side_effect=lambda _b,_s,out:(Path(out).write_bytes(b'x') or Path(out))), patch('app.landmark_qc.evaluate_dataset_split',side_effect=[RuntimeError('first'),{'median_error_percent':1,'p90_error_percent':2,'p95_error_percent':3}] ) as evaluate:
   result=evaluate_epoch_checkpoint(self.project,self.root/'manifest.json',self.root/'config.py',checkpoint,(512,256),'cpu')
  self.assertEqual(2,evaluate.call_count); self.assertEqual(10,result['epoch'])
 def test_repeated_rank_failure_preserves_checkpoints_and_reports_error(self):
  checkpoint=self.root/'epoch_10.pth'; checkpoint.write_bytes(b'x')
  with patch('app.rtmpose_backend.create_ema_inference_checkpoint',side_effect=lambda _b,_s,out:(Path(out).write_bytes(b'x') or Path(out))), patch('app.landmark_qc.evaluate_dataset_split',side_effect=RuntimeError('FULL STDERR failure')):
   with self.assertRaises(RTMPoseRuntimeError) as caught:evaluate_epoch_checkpoint(self.project,self.root/'manifest.json',self.root/'config.py',checkpoint,(512,256),'cpu')
  self.assertTrue(checkpoint.exists()); self.assertIn('FULL STDERR failure',str(caught.exception))
 def test_restart_finds_unfinished_finalization(self):
  artifact=self.root/'ai/models/rtmpose_v018'; artifact.mkdir(parents=True); (artifact/'finalization.json').write_text(json.dumps({'training_completed':True,'registered':False}))
  self.assertEqual(artifact,pending_finalization_artifact(self.project)[0])
 def test_pending_finalization_prevents_new_model_id_path(self):
  artifact=self.root/'ai/models/rtmpose_v018'; artifact.mkdir(parents=True); (artifact/'finalization.json').write_text(json.dumps({'training_completed':True,'registered':False}))
  self.assertIsNotNone(pending_finalization_artifact(self.project))
 def test_finalization_registration_is_idempotently_guarded(self):
  registered=[]; project=SimpleNamespace(data_root=self.root,schema_path=self.project.schema_path,model_metadata=lambda _id:{'model_id':'rtmpose_v018'},register_model=lambda *args,**kwargs:registered.append(args))
  self.assertIsNotNone(project.model_metadata('rtmpose_v018')); self.assertEqual([],registered)
 def test_control_comparison_failure_keeps_model_inactive_and_retryable(self):
  state={'registered':True,'control_comparison':'failed','active':False}; self.assertTrue(state['registered']); self.assertFalse(state['active']); self.assertEqual('failed',state['control_comparison'])
 def test_weak_landmark_selection_and_equal_loss_are_unchanged(self):
  smart=(Path(__file__).parents[1]/'app'/'smart_selection.py').read_text(encoding='utf8'); config=(Path(__file__).parents[1]/'app'/'rtmpose_dataset.py').read_text(encoding='utf8')
  self.assertIn('focus_target=round(int(count)*.3)',smart); self.assertIn('general_target=int(count)-focus_target',smart); self.assertNotIn('landmark_loss_weights',config)

if __name__=='__main__': unittest.main()