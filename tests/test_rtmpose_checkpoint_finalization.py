import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.project_storage import Project, schema_hash
from app.rtmpose_backend import RTMPoseRuntimeError, RTMPoseModelSpec, train_project, _prune_completed_training_checkpoints


class _Backend:
 def __init__(self, root):
  self.model_id='rtmpose_finalization_test'; self.schema_sha256=schema_hash(root/'schema.csv')
  base=root/'base.pth'; base.write_bytes(b'base')
  self.spec=RTMPoseModelSpec(self.model_id,self.schema_sha256,root/'base.py',base,device='cpu')
  self.registered=[]
 def train(self, manifest, artifact, **kwargs):
  (artifact/'epoch_10.pth').write_bytes(b'epoch-10')
  return {'status':'trained'}
 def _invoke(self, operation, payload):
  if operation=='export_inference_config':
   Path(payload['output_path']).write_text("default_scope='mmpose'\n",encoding='utf-8')
   return {'status':'ok','config_path':payload['output_path']}
  return {'runtime':'test'}
 def model_info(self): return {'backend':'test'}


class CheckpointFinalizationTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp()); source=self.root/'source'; source.mkdir(); (source/'fish.jpg').write_bytes(b'x')
  schema=self.root/'schema.csv'; schema.write_text('id,abbr,name\n1,A,One\n',encoding='utf8')
  self.project=Project.create('p',source,self.root/'project',schema,source_layout='direct')
  self.backend=_Backend(self.root); self.manifest=self.project.data_root/'dataset.json'; self.manifest.write_text('{}',encoding='utf8')
  self.registered=[]
  self.project.register_model=lambda *args,**kwargs:self.registered.append((args,kwargs))
  self.common={'dataset_manifest_path':lambda *_:self.manifest,'verify_dataset':lambda *_:{'ok':True,'errors':[]},'generate_smoke_config':lambda *args,**kwargs:self.root/'config.py','export_coco':lambda *args,**kwargs:{}}
 def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)
 def run_train(self, selection, conversion):
  selection_patch={'side_effect':selection} if isinstance(selection,BaseException) else {'return_value':selection}
  conversion_patch={'side_effect':conversion} if isinstance(conversion,BaseException) else {'side_effect':conversion}
  with patch.multiple('app.rtmpose_backend',**self.common), patch('app.rtmpose_backend.select_best_epoch',**selection_patch), patch('app.rtmpose_backend.create_ema_inference_checkpoint',**conversion_patch):
   return train_project(self.project,'dataset',self.backend,settings={'device':'cpu'})
 def test_selected_epoch_becomes_best_engineering_validation_checkpoint(self):
  seen=[]
  def convert(_backend, source, output): seen.extend((source,output)); Path(output).write_bytes(b'ema'); return Path(output)
  self.run_train({'best_epoch':10,'best_metrics':{'median_error_percent':1,'p90_error_percent':2,'p95_error_percent':3},'validation_by_epoch':[]},convert)
  self.assertEqual(seen,[self.project.data_root/'ai/models/rtmpose_finalization_test/epoch_10.pth',self.project.data_root/'ai/models/rtmpose_finalization_test/best_engineering_validation.pth'])
 def test_result_checkpoint_path_points_to_finalized_ema_checkpoint(self):
  def convert(_backend, _source, output): Path(output).write_bytes(b'ema'); return Path(output)
  model=self.run_train({'best_epoch':10,'best_metrics':{'median_error_percent':1,'p90_error_percent':2,'p95_error_percent':3},'validation_by_epoch':[{'epoch':10}]},convert)
  result=model['result']; checkpoint=self.project.data_root/'ai/models/rtmpose_finalization_test/best_engineering_validation.pth'
  self.assertEqual(result['checkpoint_path'],str(checkpoint)); self.assertEqual(result['best_epoch'],10); self.assertEqual(result['engineering_validation']['p95_error_percent'],3); self.assertTrue(result['ema_used']); self.assertEqual(result['checkpoint_sha256'],hashlib.sha256(b'ema').hexdigest())
  portable=self.project.data_root/'ai/models/rtmpose_finalization_test/inference_config.py'
  self.assertTrue(portable.is_file()); self.assertEqual(result['inference_config'],'inference_config.py'); self.assertEqual(result['inference_config_sha256'],hashlib.sha256(portable.read_bytes()).hexdigest())
  epoch=self.project.data_root/'ai/models/rtmpose_finalization_test/epoch_10.pth'
  self.assertFalse(epoch.exists())
  state=json.loads((self.project.data_root/'ai/models/rtmpose_finalization_test/finalization.json').read_text(encoding='utf8'))
  self.assertEqual(['epoch_10.pth'],state['retention']['removed_files']);self.assertGreater(state['retention']['removed_bytes'],0)
  self.assertEqual('best_engineering_validation.pth',state['retention']['retained_checkpoint'])
  self.assertEqual([{'epoch':10}],state['result']['validation_by_epoch'])
 def test_completed_legacy_model_with_config_py_prunes_intermediate_epochs(self):
  artifact=self.project.data_root/'ai/models/legacy';artifact.mkdir(parents=True)
  final=artifact/'best_engineering_validation.pth';final.write_bytes(b'final')
  (artifact/'config.py').write_text("default_scope='mmpose'\n",encoding='utf8')
  (artifact/'model.json').write_text('{}',encoding='utf8')
  (artifact/'epoch_1.pth').write_bytes(b'epoch')
  (artifact/'last_checkpoint').write_text('epoch_1.pth',encoding='utf8')
  state={'stage':'COMPLETE','registered':True,'result':{'checkpoint_sha256':hashlib.sha256(b'final').hexdigest(),'validation_by_epoch':[{'epoch':1}]}}
  retention=_prune_completed_training_checkpoints(artifact,state)
  self.assertTrue(retention['pruned'])
  self.assertEqual('config.py',retention['retained_config'])
  self.assertFalse((artifact/'epoch_1.pth').exists())
  self.assertFalse((artifact/'last_checkpoint').exists())
  self.assertTrue(final.exists())

 def test_completed_model_without_any_usable_config_is_not_pruned(self):
  artifact=self.project.data_root/'ai/models/no-config';artifact.mkdir(parents=True)
  final=artifact/'best_engineering_validation.pth';final.write_bytes(b'final')
  (artifact/'model.json').write_text('{}',encoding='utf8')
  epoch=artifact/'epoch_1.pth';epoch.write_bytes(b'epoch')
  state={'stage':'COMPLETE','registered':True,'result':{'checkpoint_sha256':hashlib.sha256(b'final').hexdigest()}}
  retention=_prune_completed_training_checkpoints(artifact,state)
  self.assertFalse(retention['pruned'])
  self.assertEqual('portable_model_incomplete',retention['reason'])
  self.assertTrue(epoch.exists())

 def test_selection_or_conversion_failure_prevents_model_registration(self):
  with self.assertRaises(RTMPoseRuntimeError): self.run_train(RTMPoseRuntimeError('selection failed'),lambda *_:None)
  artifact=self.project.data_root/'ai/models/rtmpose_finalization_test'
  self.assertEqual(self.registered,[]);self.assertTrue((artifact/'epoch_10.pth').exists())
  shutil.rmtree(artifact)
  with self.assertRaises(RTMPoseRuntimeError): self.run_train({'best_epoch':10,'best_metrics':{},'validation_by_epoch':[]},RTMPoseRuntimeError('conversion failed'))
  self.assertEqual(self.registered,[]);self.assertTrue((artifact/'epoch_10.pth').exists())


if __name__=='__main__': unittest.main()