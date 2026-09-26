import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from app.ai import MockBackend
from app.landmark_ai_service import LandmarkAIService
from app.landmark_dataset import (DatasetError, ModelLineageError, create_dataset, dataset_manifest_path, deterministic_splits, eligible_image_ids, is_image_unseen_by_model, model_seen_image_ids, verify_dataset)
from app.project_storage import Project, schema_hash

class LandmarkDatasetGateTwoTests(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp());self.source=self.temp/'source';self.source.mkdir()
  for n in range(6):(self.source/f'image_{n}.jpg').write_bytes(b'source')
  self.schema=self.temp/'schema.csv';self.schema.write_text('id,abbr,name,role\n1,P1,One,BOTH\n2,P2,Two,GM\n',encoding='utf-8')
  self.project=Project.create('project',self.source,self.temp,self.schema,source_layout='direct');self.images=self.project.catalog_rows();self.ids=[row['image_id'] for row in self.images]
  for n,image_id in enumerate(self.ids):
   path=self.project.cache_root/'standardized'/f'{image_id}.png';path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(80,60),(n,2,3)).save(path)
   with self.project.transaction() as c:c.execute('UPDATE images SET locality=?,sample_id=? WHERE image_id=?',(chr(65+n//2),chr(65+n//2),image_id))
 def tearDown(self): shutil.rmtree(self.temp,ignore_errors=True)
 def manual(self,image_id,missing=False):
  self.project.save_landmark(image_id,1,10,11,'manual',provenance='manual')
  if missing:self.project.save_landmark(image_id,2,None,None,'missing',provenance='manual')
  else:self.project.save_landmark(image_id,2,20,21,'manual',provenance='manual')
 def dataset(self, dataset_id='ds', splits=None):
  return create_dataset(self.project,dataset_id=dataset_id,splits=splits or {'train':[self.ids[0]]})
 def rel(self,dataset_id): return dataset_manifest_path(self.project,dataset_id).relative_to(self.project.data_root).as_posix()

 def test_human_final_labels_are_immutable_snapshot(self):
  image_id=self.ids[0];self.manual(image_id);manifest=self.dataset('immutable')
  before=json.loads(dataset_manifest_path(self.project,'immutable').read_text(encoding='utf-8'))
  self.project.save_landmark(image_id,1,44,45,'corrected',provenance='corrected_by_human')
  self.assertEqual(self.project.load_landmarks(image_id)[1]['x_standardized'],44)
  self.assertEqual(before['images'][0]['landmarks'][0]['x'],10)
  self.assertEqual(json.loads(dataset_manifest_path(self.project,'immutable').read_text(encoding='utf-8')),manifest)

 def test_unchecked_ai_is_not_eligible_but_checked_ai_is(self):
  image_id=self.ids[0];LandmarkAIService(self.project,MockBackend(schema_hash(self.project.schema_path))).predict_one(image_id)
  self.assertNotIn(image_id,eligible_image_ids(self.project,include_permanent=True))
  self.project.mark_checked(image_id);self.assertIn(image_id,eligible_image_ids(self.project,include_permanent=True))
  manifest=self.dataset('checked-ai');self.assertEqual(manifest['images'][0]['image_id'],image_id)

 def test_manual_and_manual_missing_are_eligible_and_snapshotted(self):
  image_id=self.ids[0];self.manual(image_id,missing=True);manifest=self.dataset('missing')
  labels=manifest['images'][0]['landmarks'];self.assertEqual(labels[1],{'landmark_id':2,'state':'missing','x':None,'y':None,'provenance':'manual'})
  self.assertEqual(self.project.annotation_status(image_id)['color'],'green')

 def test_unresolved_and_excluded_images_are_rejected(self):
  with self.assertRaises(DatasetError): self.dataset('unresolved')
  self.manual(self.ids[0]);self.project.exclude_image(self.ids[0],'Bad image')
  with self.assertRaises(DatasetError): self.dataset('excluded')

 def test_permanent_holdout_is_not_training_but_remains_project_eligible(self):
  image_id=self.ids[0];self.manual(image_id);self.project.reserve_permanent_test([image_id])
  self.assertNotIn(image_id,eligible_image_ids(self.project));self.assertIn(image_id,eligible_image_ids(self.project,include_permanent=True))
  with self.assertRaises(DatasetError): self.dataset('holdout',{'train':[image_id]})
  manifest=self.dataset('holdout-test',{'test':[image_id]});self.assertEqual(manifest['images'][0]['split'],'test')

 def test_split_overlap_and_group_split_do_not_leak(self):
  for image_id in self.ids:self.manual(image_id)
  with self.assertRaises(DatasetError): create_dataset(self.project,dataset_id='overlap',splits={'train':[self.ids[0]],'validation':[self.ids[0]]})
  splits=deterministic_splits(self.project,split_fractions={'train':.5,'validation':.25,'test':.25},seed=8,group_by='locality')
  lookup={row['image_id']:row['locality'] for row in self.project.catalog_rows()};groups={key:{lookup[item] for item in value} for key,value in splits.items()}
  self.assertFalse(groups['train']&groups['validation']);self.assertFalse(groups['train']&groups['test']);self.assertFalse(groups['validation']&groups['test'])
  with self.project.transaction() as c:c.execute("UPDATE images SET locality='only'")
  with self.assertRaises(DatasetError): deterministic_splits(self.project,split_counts={'train':1,'validation':1,'test':4},seed=1,group_by='locality')

 def test_schema_and_standardized_or_crop_change_make_dataset_stale(self):
  image_id=self.ids[0];self.manual(image_id);self.dataset('integrity');path=dataset_manifest_path(self.project,'integrity');original=path.read_bytes()
  self.schema_in_project=self.project.schema_path;self.schema_in_project.write_text('id,abbr,name,role\n1,P1x,One,BOTH\n2,P2,Two,GM\n',encoding='utf-8')
  self.assertIn('schema_identity_mismatch',verify_dataset(self.project,'integrity')['errors']);self.assertEqual(path.read_bytes(),original)
  self.schema_in_project.write_text('id,abbr,name,role\n1,P1,One,BOTH\n2,P2,Two,GM\n',encoding='utf-8')
  Image.new('RGB',(80,60),(99,2,3)).save(self.project.cache_root/'standardized'/f'{image_id}.png')
  result=verify_dataset(self.project,'integrity');self.assertIn(f'standardized_sha256_mismatch:{image_id}',result['errors']);self.assertEqual(path.read_bytes(),original)
  self.project.save_crop(image_id,{'crop_bounds':[1,2,3,4],'transform':{'full_width':1},'rotation_degrees':0,'standardized_relpath':'cache/standardized/x.png'})
  self.assertIn(f'crop_transform_mismatch:{image_id}',verify_dataset(self.project,'integrity')['errors'])

 def test_dataset_id_is_atomic_and_never_overwritten(self):
  self.manual(self.ids[0]);self.dataset('fixed');path=dataset_manifest_path(self.project,'fixed');before=path.read_bytes()
  with self.assertRaises(FileExistsError): self.dataset('fixed')
  self.assertEqual(path.read_bytes(),before)

 def test_lineage_seen_and_unseen_use_only_train_across_ancestors(self):
  for image_id in self.ids:self.manual(image_id)
  self.dataset('d1',{'train':[self.ids[0]],'validation':[self.ids[1]]});self.dataset('d2',{'train':[self.ids[2]]});self.dataset('d3',{'train':[self.ids[3]]})
  digest=schema_hash(self.project.schema_path)
  self.project.register_model('v1','landmark',schema_digest=digest,dataset_id='d1',dataset_manifest_path=self.rel('d1'))
  self.project.register_model('v2','landmark',schema_digest=digest,dataset_id='d2',parent_model_id='v1',dataset_manifest_path=self.rel('d2'))
  self.project.register_model('v3','landmark',schema_digest=digest,dataset_id='d3',parent_model_id='v2',dataset_manifest_path=self.rel('d3'))
  self.assertEqual(model_seen_image_ids(self.project,'v3'),frozenset((self.ids[0],self.ids[2],self.ids[3])))
  self.assertTrue(is_image_unseen_by_model(self.project,'v3',self.ids[1]));self.assertFalse(is_image_unseen_by_model(self.project,'v3',self.ids[0]));self.assertTrue(is_image_unseen_by_model(self.project,'v3',self.ids[4]))

 def test_broken_or_cyclic_lineage_is_controlled_error(self):
  self.manual(self.ids[0]);self.dataset('d1');digest=schema_hash(self.project.schema_path)
  self.project.register_model('v1','landmark',schema_digest=digest,dataset_id='d1',dataset_manifest_path=self.rel('d1'))
  with self.project.transaction() as c:c.execute("UPDATE models SET parent_model_id='missing' WHERE model_id='v1'")
  with self.assertRaises(ModelLineageError): model_seen_image_ids(self.project,'v1')
  with self.project.transaction() as c:c.execute("UPDATE models SET parent_model_id='v1' WHERE model_id='v1'")
  with self.assertRaises(ModelLineageError): model_seen_image_ids(self.project,'v1')

if __name__=='__main__': unittest.main()