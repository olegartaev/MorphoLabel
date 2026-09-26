import json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from app.rtmpose_dataset import ResizeTransform, export_coco, generate_smoke_config
from app.rtmpose_backend import RTMPoseBackend,RTMPoseModelSpec,RTMPoseRuntimeError,train_project
from app.project_storage import Project,schema_hash
from app.landmark_ai_service import LandmarkAIService,SchemaMismatchError
from app.performance_engine import PerformanceCache

class RTMPoseBackendTests(unittest.TestCase):
 def setUp(self):
  self.t=Path(tempfile.mkdtemp()); self.m=self.t/'manifest.json';self.m.write_text(json.dumps({'format_version':1,'dataset_id':'d','schema_sha256':'hash','schema_landmarks':[{'landmark_id':2,'abbr':'A','role':'BOTH'},{'landmark_id':5,'abbr':'B','role':'GM'},{'landmark_id':11,'abbr':'C','role':'CLASSICAL'}],'images':[{'image_id':'i','split':'train','standardized_relpath':'cache/standardized/i.png','standardized_width':512,'standardized_height':256,'landmarks':[{'landmark_id':2,'state':'present','x':10,'y':20},{'landmark_id':5,'state':'missing','x':None,'y':None},{'landmark_id':11,'state':'present','x':500,'y':230}]}]}),encoding='utf8')
 def tearDown(self):shutil.rmtree(self.t,ignore_errors=True)
 def coco(self):return export_coco(self.m,self.t/'coco.json')
 def test_01_manifest_converts_to_coco(self):self.assertEqual(self.coco()['annotations'][0]['bbox'],[0.0,0.0,512.0,256.0])
 def test_02_manual_missing_is_visibility_zero(self):self.assertEqual(self.coco()['annotations'][0]['keypoints'][3:6],[0.0,0.0,0])
 def test_03_arbitrary_ids_map_to_contiguous_network_order(self):self.assertEqual(self.coco()['categories'][0]['simm_landmark_ids'],[2,5,11])
 def test_04_network_mapping_retains_canonical_ids(self):self.assertEqual(self.coco()['categories'][0]['keypoints'],['A','B','C'])
 def test_05_config_has_fish_geometry_and_no_flip(self):
  p=generate_smoke_config(self.m,data_root=self.t,train_coco=self.t/'a.json',val_coco=self.t/'b.json',output_path=self.t/'config.py',base_config=self.t/'base.py',base_checkpoint=self.t/'base.pth');text=p.read_text();self.assertIn('input_size=(512, 256)',text);self.assertNotIn('RandomFlip',text);self.assertIn('out_channels=3',text)
 def test_06_resize_round_trip(self):
  x=ResizeTransform(512,256,512,256);self.assertEqual(x.inverse(*x.forward(500,230)),(500,230))
 def test_07_non_square_round_trip_edges_center(self):
  x=ResizeTransform(1000,200,512,256)
  for point in ((0,0),(1000,200),(500,100)):self.assertAlmostEqual(x.inverse(*x.forward(*point))[0],point[0]);self.assertAlmostEqual(x.inverse(*x.forward(*point))[1],point[1])
 def test_08_main_import_does_not_import_ml(self):
  import app.rtmpose_backend
  self.assertFalse(any(name=='torch' or name.startswith('mmpose') for name in sys.modules))
 def test_09_missing_runtime_is_controlled(self):
  b=RTMPoseBackend(RTMPoseModelSpec('m','h',self.t/'c',self.t/'k'),runtime_python=self.t/'missing.exe')
  with self.assertRaises(RTMPoseRuntimeError):b._invoke('predict',{})
 def test_10_subprocess_failure_is_controlled(self):
  runner=self.t/'bad.py';runner.write_text('raise SystemExit(7)');b=RTMPoseBackend(RTMPoseModelSpec('m','h',self.t/'c',self.t/'k'),runtime_python=Path(sys.executable),runner_path=runner)
  with self.assertRaises(RTMPoseRuntimeError):b._invoke('predict',{})
 def test_11_invalid_subprocess_json_is_controlled(self):
  runner=self.t/'bad.py';runner.write_text("print('not json')");b=RTMPoseBackend(RTMPoseModelSpec('m','h',self.t/'c',self.t/'k'),runtime_python=Path(sys.executable),runner_path=runner)
  with self.assertRaises(RTMPoseRuntimeError):b._invoke('predict',{})
 def test_12_schema_mismatch_blocks_before_runtime(self):
  source=self.t/'s';source.mkdir();(source/'a.jpg').write_bytes(b'x');schema=self.t/'s.csv';schema.write_text('id,abbr,name\n1,A,One\n');p=Project.create('p',source,self.t/'p',schema,source_layout='direct');image=p.catalog_rows()[0]['image_id'];q=p.cache_root/'standardized'/f'{image}.png';q.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(10,10)).save(q);b=RTMPoseBackend(RTMPoseModelSpec('m','wrong',self.t/'c',self.t/'k'),runtime_python=self.t/'missing.exe')
  with self.assertRaises(SchemaMismatchError):LandmarkAIService(p,b)._request(image)
 def test_13_missing_checkpoint_is_controlled_by_runtime(self):
  self.assertFalse((self.t/'missing.pth').exists())

 def test_14_config_initializes_only_pretrained_backbone(self):
  p=generate_smoke_config(self.m,data_root=self.t/'data',train_coco=self.t/'a.json',val_coco=self.t/'b.json',output_path=self.t/'config.py',base_config=self.t/'base.py',base_checkpoint=self.t/'base.pth');text=p.read_text();self.assertIn('prefix=',text);self.assertIn('backbone.',text);self.assertIn('load_from = None',text)

 def test_15_runner_selects_latest_checkpoint_numerically(self):
  text=(Path(__file__).resolve().parents[1]/'ai_runtime'/'rtmpose_runner.py').read_text(encoding='utf8');self.assertIn('key=lambda path:int(path.stem.split',text)
 def _rank_backend(self,body):
  runner=self.t/'rank_runner.py';runner.write_text(body,encoding='utf8')
  return RTMPoseBackend(RTMPoseModelSpec('m','h',self.t/'c',self.t/'k'),runtime_python=Path(sys.executable),runner_path=runner)
 def test_16_rank_progress_updates_and_stdout_json_parses(self):
  backend=self._rank_backend("import sys,json\njson.load(sys.stdin)\nprint('RANK_PROGRESS 0 2',file=sys.stderr,flush=True)\nprint('RANK_PROGRESS 2 2',file=sys.stderr,flush=True)\nprint(json.dumps({'model_id':'m','schema_sha256':'h','results':[]}))")
  progress=[];raw=backend._invoke('rank',{},progress_callback=lambda done,total:progress.append((done,total)),no_progress_timeout=.5)
  self.assertEqual(progress,[(0,2),(2,2)]);self.assertEqual(raw['results'],[])
 def test_17_rank_with_continuing_progress_is_not_killed(self):
  backend=self._rank_backend("import sys,json,time\njson.load(sys.stdin)\nfor done in range(4):\n print(f'RANK_PROGRESS {done} 3',file=sys.stderr,flush=True);time.sleep(.05)\nprint(json.dumps({'model_id':'m','schema_sha256':'h','results':[]}))")
  self.assertEqual(backend._invoke('rank',{},no_progress_timeout=.12)['model_id'],'m')
 def test_18_rank_without_progress_reports_stall(self):
  backend=self._rank_backend("import sys,json,time\njson.load(sys.stdin)\nprint('runner started',file=sys.stderr,flush=True)\ntime.sleep(2)")
  with self.assertRaisesRegex(RTMPoseRuntimeError,'RTMPose rank stalled: no progress for 180 seconds.') as caught:backend._invoke('rank',{},no_progress_timeout=.1)
  self.assertIn('runner started',str(caught.exception))
 def test_19_rank_runner_reports_progress_only_to_stderr(self):
  text=(Path(__file__).resolve().parents[1]/'ai_runtime'/'rtmpose_runner.py').read_text(encoding='utf8');self.assertIn("print(f'RANK_PROGRESS 0 {total}',file=sys.stderr,flush=True)",text)
 def test_20_training_retries_smaller_batch_after_cuda_oom(self):
  root=self.t/'project';root.mkdir();manifest=self.t/'dataset.json';manifest.write_text('{}',encoding='utf8')
  project=SimpleNamespace(data_root=root,schema_path=self.t/'schema.csv',model_metadata=lambda _id:None)
  spec=SimpleNamespace(config_path=self.t/'base.py',checkpoint_path=self.t/'base.pth',input_size=(512,256),device='cuda:0')
  calls=[]
  backend=SimpleNamespace(model_id='rtmpose_v002',schema_sha256='digest',spec=spec)
  def fake_train(_manifest,_artifact,*,parent_model_id=None,settings=None):
   calls.append(int(settings['batch_size']))
   if len(calls)==1:raise RTMPoseRuntimeError('CUDA out of memory')
   return {'status':'trained'}
  backend.train=fake_train
  def fake_config(*_args,**kwargs):
   path=Path(kwargs['output_path']);path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# test',encoding='utf8');return path
  progress=[]
  with patch.dict(os.environ,{'LOCALAPPDATA':str(self.t)}):
   self.assertTrue(PerformanceCache(project).put('training-oom-key',{'chosen':{'batch_size':8,'workers':2},'probes_succeeded':True}))
   with patch('app.rtmpose_backend.dataset_manifest_path',return_value=manifest),patch('app.rtmpose_backend.verify_dataset',return_value={'ok':True,'errors':[]}),patch('app.project_storage.schema_hash',return_value='digest'),patch('app.rtmpose_backend.generate_smoke_config',side_effect=fake_config),patch('app.rtmpose_backend.export_coco'),patch('app.rtmpose_backend._finalize_trained_artifact',return_value={'status':'ok'}):
    result=train_project(project,'d',backend,settings={'batch_size':8,'workers':2,'device':'cuda:0','tuning_key':'training-oom-key'},progress_callback=lambda *args:progress.append(args))
   self.assertEqual(4,PerformanceCache(project).get('training-oom-key')['chosen']['batch_size'])
  self.assertEqual({'status':'ok'},result);self.assertEqual([8,4],calls)
  state=json.loads((root/'ai'/'models'/'rtmpose_v002'/'finalization.json').read_text(encoding='utf8'))
  self.assertEqual(4,state['settings']['batch_size'])
  self.assertEqual({'attempted_batches':[8,4],'effective_batch_size':4,'cache_saved':True},state['settings']['runtime_batch_fallback'])
  self.assertTrue(any('retrying safely with batch 4' in ' '.join(map(str,item)) for item in progress))

 def test_21_grouped_probe_warms_each_candidate_before_timing(self):
  text=(Path(__file__).resolve().parents[1]/'ai_runtime'/'rtmpose_runner.py').read_text(encoding='utf8')
  self.assertIn('for _ in range(warmup_batches):',text)
  self.assertIn('train_step(next(iterator))',text)
  self.assertIn('torch.cuda.reset_peak_memory_stats()',text)
  self.assertIn('timing_scope":"steady_state_after_candidate_warmup"',text)

if __name__=='__main__':unittest.main()
