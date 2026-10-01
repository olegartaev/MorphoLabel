import json, shutil, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from app.ai_batch import BatchError, create_batch, create_batch_for_ids, load_batch, prospective_candidates, reviewed_count, run_batch
from app.project_storage import Project, schema_hash
from app.project_runtime import record, save
from app.workflow import set_human_point
from app.transforms import Transform

class FakeService:
 def __init__(self,project,fail=()):self.project=project;self.calls=[];self.fail=set(fail)
 def predict_one(self,image_id):
  self.calls.append(image_id)
  if image_id in self.fail:raise RuntimeError('simulated prediction failure')
  for landmark_id in (1,2):self.project.save_landmark(image_id,landmark_id,10+landmark_id,20+landmark_id,'auto',provenance='machine',model_id='v1',predicted_x=10+landmark_id,predicted_y=20+landmark_id,confidence=.5,prediction_run_id='run-'+image_id,reviewed=False)
  return SimpleNamespace(prediction_run_id='run-'+image_id)

class AIBatchTests(unittest.TestCase):
 def setUp(self):
  self.t=Path(tempfile.mkdtemp());src=self.t/'src';src.mkdir();schema=self.t/'schema.csv';schema.write_text('id,abbr,name\n1,A,One\n2,B,Two\n',encoding='utf8')
  for n in range(15):Image.new('RGB',(40,30)).save(src/f'img_{n:02}.jpg')
  self.p=Project.create("p",src,self.t,schema,source_layout='direct');self.rows=self.p.catalog_rows();self.ids=[row['image_id'] for row in self.rows]
  for image_id in self.ids:
   standard=self.p.cache_root/'standardized'/f'{image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(40,30)).save(standard)
   crop={"crop_bounds":[0,0,40,30],"transform":Transform(40,30,0,20,15,0,0,40,30).__dict__,"standardized_relpath":standard.relative_to(self.p.data_root).as_posix()};self.p.save_reviewed_crop(image_id,crop)
  data=self.p.data_root/'ai/datasets/d';data.mkdir(parents=True);(data/'manifest.json').write_text(json.dumps({'format_version':1,'dataset_id':'d','schema_landmarks':[{'landmark_id':1,'abbr':'A'},{'landmark_id':2,'abbr':'B'}],'images':[{'image_id':self.ids[1],'split':'train'},{'image_id':self.ids[2],'split':'validation'}]}),encoding='utf8')
  self.p.register_model('v1','landmark',path='ai/models/v1',active=True,schema_digest=schema_hash(self.p.schema_path),dataset_id='d',dataset_manifest_path='ai/datasets/d/manifest.json')
 def tearDown(self):shutil.rmtree(self.t,ignore_errors=True)
 def test_01_candidates_exclude_train_and_validation(self):
  ids,_=prospective_candidates(self.p,'v1',self.ids[0],3);self.assertNotIn(self.ids[1],ids);self.assertNotIn(self.ids[2],ids)
 def test_02_candidates_exclude_existing_manual_or_ai_rows(self):
  self.p.save_landmark(self.ids[3],1,1,1,'manual');self.p.save_landmark(self.ids[4],1,1,1,'auto',provenance='machine');ids,_=prospective_candidates(self.p,'v1',self.ids[0],3);self.assertNotIn(self.ids[3],ids);self.assertNotIn(self.ids[4],ids)
 def test_03_candidates_exclude_excluded_and_holdout(self):
  self.p.exclude_image(self.ids[3],'Bad image');self.p.reserve_permanent_test([self.ids[4]]);ids,_=prospective_candidates(self.p,'v1',self.ids[0],3);self.assertNotIn(self.ids[3],ids);self.assertNotIn(self.ids[4],ids)
 def test_04_selection_is_deterministic_next_catalog_order(self):
  one,_=prospective_candidates(self.p,'v1',self.ids[0],4);two,_=prospective_candidates(self.p,'v1',self.ids[0],4);self.assertEqual(one,two);self.assertEqual(one,tuple(self.ids[3:7]))
 def test_05_manifest_records_exact_selection(self):
  data,path=create_batch(self.p,'v1',self.ids[0],10);loaded,_=load_batch(self.p,path);self.assertEqual([x['image_id'] for x in data['selected_images']],[x['image_id'] for x in loaded['selected_images']]);self.assertEqual(len(data['selected_images']),10);self.assertTrue(all(x['outside_development_dataset'] for x in data['selected_images']))
 def test_06_run_uses_service_and_records_runs(self):
  data,path=create_batch(self.p,'v1',self.ids[0],3);service=FakeService(self.p);done,_=run_batch(self.p,path,service);self.assertEqual(service.calls,[x['image_id'] for x in data['selected_images']]);self.assertEqual(set(done['prediction_runs']),set(service.calls))
 def test_07_predicted_images_are_not_checked(self):
  data,path=create_batch(self.p,'v1',self.ids[0],2);done,_=run_batch(self.p,path,FakeService(self.p));self.assertEqual(reviewed_count(self.p,done),0);self.assertTrue(all(not self.p.annotation_status(x['image_id'])['verified'] for x in done['selected_images']))
 def test_08_human_correction_preserves_prediction_metadata(self):
  data,path=create_batch(self.p,'v1',self.ids[0],1);done,_=run_batch(self.p,path,FakeService(self.p));image_id=done['selected_images'][0]['image_id'];before=self.p.load_landmarks(image_id)[1];rec=record(self.p,next(x for x in self.rows if x['image_id']==image_id));set_human_point(rec,1,'A',31,32,corrected=True);save(self.p,rec);after=self.p.load_landmarks(image_id)[1];self.assertEqual((after['predicted_x'],after['predicted_y'],after['prediction_run_id']),(before['predicted_x'],before['predicted_y'],before['prediction_run_id']))
 def test_09_failure_does_not_substitute_candidate(self):
  data,path=create_batch(self.p,'v1',self.ids[0],3);failed=data['selected_images'][1]['image_id'];done,_=run_batch(self.p,path,FakeService(self.p,{failed}));self.assertEqual(len(done['selected_images']),3);self.assertIn(failed,done['failures']);self.assertEqual(len(done['prediction_runs']),2)
 def test_10_reviewed_counter_tracks_current_human_verified(self):
  data,path=create_batch(self.p,'v1',self.ids[0],1);done,_=run_batch(self.p,path,FakeService(self.p));image_id=done['selected_images'][0]['image_id'];self.p.mark_checked(image_id);self.assertEqual(reviewed_count(self.p,done),1)
 def test_11_no_training_api_is_called_by_batch_module(self):
  data,path=create_batch(self.p,'v1',self.ids[0],1);run_batch(self.p,path,FakeService(self.p));self.assertFalse((self.p.data_root/'ai/models/v2').exists())
 def test_14_insufficient_candidates_is_controlled(self):
  for image_id in self.ids[3:]:self.p.save_landmark(image_id,1,1,1,'manual')
  with self.assertRaises(BatchError):prospective_candidates(self.p,'v1',self.ids[0],10)
 def test_15_crop_readiness_excludes_candidates_and_explicit_batches(self):
  uncropped=self.ids[3]
  with self.p.transaction() as c:c.execute('DELETE FROM crops WHERE image_id=?',(uncropped,))
  ids,_=prospective_candidates(self.p,'v1',self.ids[0],3);self.assertNotIn(uncropped,ids)
  with self.assertRaisesRegex(BatchError,'crop-ready'):create_batch_for_ids(self.p,'v1',[uncropped])
 def test_16_interactive_batch_uses_smaller_remaining_pool(self):
  self.p.save_landmark(self.ids[0],1,1,1,'manual')
  for image_id in self.ids[4:]:self.p.save_landmark(image_id,1,1,1,'manual')
  data,_=create_batch(self.p,'v1',self.ids[0],10)
  self.assertEqual([self.ids[3]],[item['image_id'] for item in data['selected_images']])
  self.assertEqual(10,data['requested_count']);self.assertEqual(1,data['selected_count'])
  self.assertEqual('new_unannotated',data['selection_mode'])
 def test_17_explicit_batch_records_honest_selection_mode(self):
  data,_=create_batch_for_ids(self.p,'v1',[self.ids[3]],selection_mode='all_prediction_targets')
  self.assertEqual('all_prediction_targets',data['selection_mode'])
  self.assertEqual(1,data['selected_count'])

 def test_20_prediction_batch_rejects_only_current_human_confirmation(self):
  image_id=self.ids[3]
  self.p.save_machine_landmarks(image_id,[{'landmark_id':1,'x':5,'y':6},{'landmark_id':2,'x':7,'y':8}],model_id='v1',prediction_run_id='old-ai')
  self.p.mark_checked(image_id)
  self.assertTrue(self.p.landmark_prediction_locked(image_id))
  with self.assertRaisesRegex(BatchError,'human-confirmed'):
   create_batch_for_ids(self.p,'v1',[image_id],selection_mode='all_prediction_targets')

  with self.p.transaction() as c:c.execute("UPDATE image_review SET human_verified=0 WHERE image_id=?",(image_id,))
  self.assertFalse(self.p.landmark_prediction_locked(image_id))
  data,_=create_batch_for_ids(self.p,'v1',[image_id],selection_mode='all_prediction_targets')
  self.assertEqual([image_id],[item['image_id'] for item in data['selected_images']])

 def test_22_saved_batch_survives_name_only_schema_edit(self):
  _data,path=create_batch(self.p,'v1',self.ids[0],1)
  self.p.schema_path.write_text('id,abbr,name\n1,A,Renamed one\n2,B,Renamed two\n',encoding='utf8')
  done,_=run_batch(self.p,path,FakeService(self.p))
  self.assertEqual(1,len(done['prediction_runs']))

 def test_23_saved_batch_rejects_landmark_identity_reorder(self):
  _data,path=create_batch(self.p,'v1',self.ids[0],1)
  self.p.schema_path.write_text('id,abbr,name\n1,B,Two\n2,A,One\n',encoding='utf8')
  with self.assertRaisesRegex(BatchError,'identities/order'):run_batch(self.p,path,FakeService(self.p))

 def test_21_unconfirmed_ai_refresh_preserves_human_correction(self):
  data,path=create_batch(self.p,'v1',self.ids[0],1);done,_=run_batch(self.p,path,FakeService(self.p));image_id=done['selected_images'][0]['image_id']
  rec=record(self.p,next(x for x in self.rows if x['image_id']==image_id));set_human_point(rec,1,'A',31,32,corrected=True);save(self.p,rec)
  before=self.p.load_landmarks(image_id)[1]
  saved,skipped=self.p.save_machine_landmarks(image_id,[{'landmark_id':1,'x':11,'y':21,'confidence':.5},{'landmark_id':2,'x':12,'y':22,'confidence':.5}],model_id='v1',prediction_run_id='rerun')
  after=self.p.load_landmarks(image_id)[1]
  self.assertEqual((31,32),(after['x_standardized'],after['y_standardized']))
  self.assertEqual(before['provenance'],after['provenance'])
  self.assertEqual(1,skipped)

 def test_24_gui_retry_once_recovers_transient_failed_image(self):
  data,path=create_batch(self.p,'v1',self.ids[0],1);image_id=data['selected_images'][0]['image_id']
  class Flaky(FakeService):
   def __init__(self,project):super().__init__(project);self.attempts=0
   def predict_many(self,ids,progress=None,status=None):
    self.attempts+=1
    for ident in ids:progress(ident,None,RuntimeError('transient failure'))
   def predict_one(self,ident):
    self.attempts+=1
    return super().predict_one(ident)
  service=Flaky(self.p);done,_=run_batch(self.p,path,service,retry_failures=True)
  self.assertIn(image_id,done['prediction_runs']);self.assertNotIn(image_id,done['failures']);self.assertEqual(2,service.attempts)

if __name__=='__main__':unittest.main()

