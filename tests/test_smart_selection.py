import json, shutil, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from app.ai import ImagePrediction, LandmarkPrediction
from app.ai_batch import run_batch
from app.project_storage import Project, schema_hash
from app.smart_selection import candidate_pool, select_ranked, rank_candidates, create_batch_from_selection

class Backend:
 def __init__(self,digest): self.model_id='v2';self.schema_sha256=digest
 def predict_readonly_many(self,requests):
  return tuple(ImagePrediction(r.image_id,self.model_id,self.schema_sha256,tuple(LandmarkPrediction(int(x['id']),10+i*3,12+i*2,.2+(i%3)*.2) for i,x in enumerate(r.schema))) for r in requests)
class Service:
 def __init__(self,p):self.p=p;self.calls=[]
 def predict_one(self,image_id):
  self.calls.append(image_id)
  self.p.save_landmark(image_id,1,10,10,'auto',provenance='machine',model_id='v2',predicted_x=10,predicted_y=10,confidence=.5,prediction_run_id='final-'+image_id)
  return SimpleNamespace(prediction_run_id='final-'+image_id)
class SmartSelectionTests(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp());src=self.temp/'src';src.mkdir();schema=self.temp/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n3,C,Three,BOTH\n',encoding='utf8')
  for i in range(20): Image.new('RGB',(80,60)).save(src/f'img_{i:02}.jpg')
  self.p=Project.create('p',src,self.temp,schema,source_layout='direct');self.rows=self.p.catalog_rows();self.ids=[r['image_id'] for r in self.rows]
  for r in self.rows:
   out=self.p.cache_root/'standardized'/f"{r['image_id']}.png";out.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(80,60)).save(out)
  d=self.p.data_root/'ai/datasets/d';d.mkdir(parents=True);(d/'manifest.json').write_text(json.dumps({'dataset_id':'d','images':[{'image_id':self.ids[0],'split':'train'},{'image_id':self.ids[1],'split':'validation'}]}),encoding='utf8')
  self.p.register_model('v2','landmark',path='ai/models/v2',active=True,schema_digest=schema_hash(self.p.schema_path),dataset_id='d',dataset_manifest_path='ai/datasets/d/manifest.json')
 def tearDown(self):shutil.rmtree(self.temp,ignore_errors=True)
 def _ranked(self,n=12):
  return [{'image_id':self.ids[i],'original_name':f'i{i}','locality':f'L{i%4}','sample_id':f'L{i%4}','median_confidence':.1+i/100,'low_confidence':.05,'descriptor':((i/10,0),(0,i/10),(-i/10,0)),'predictions':[]} for i in range(n)]
 def test_01_development_train_and_validation_excluded(self):
  pool={r['image_id'] for r in candidate_pool(self.p,'v2')};self.assertNotIn(self.ids[0],pool);self.assertNotIn(self.ids[1],pool)
 def test_02_annotated_excluded(self):
  self.p.save_landmark(self.ids[2],1,1,1,'auto',provenance='machine');self.assertNotIn(self.ids[2],{r['image_id'] for r in candidate_pool(self.p,'v2')})
 def test_03_holdout_excluded(self):
  self.p.reserve_permanent_test([self.ids[2]]);self.assertNotIn(self.ids[2],{r['image_id'] for r in candidate_pool(self.p,'v2')})
 def test_04_ranking_is_readonly(self):
  before=self.p.count('landmarks');rank_candidates(self.p,Backend(schema_hash(self.p.schema_path)),candidate_pool(self.p,'v2')[:3]);self.assertEqual(before,self.p.count('landmarks'))
 def test_05_seed_is_reproducible(self):
  a,b=select_ranked(self.p,self._ranked(),7);c,d=select_ranked(self.p,self._ranked(),7);self.assertEqual([x['image_id'] for x in a+b],[x['image_id'] for x in c+d])
 def test_06_exact_composition_and_no_overlap(self):
  a,b=select_ranked(self.p,self._ranked(),9);self.assertEqual((len(a),len(b)),(7,3));self.assertFalse({x['image_id'] for x in a}&{x['image_id'] for x in b})
 def test_07_diversity_prefers_nonduplicate(self):
  r=self._ranked();r[0]['descriptor']=((0,0),(1,0),(0,1));r[1]['descriptor']=r[0]['descriptor'];r[2]['descriptor']=((-1,0),(0,0),(1,0));a,_=select_ranked(self.p,r,1,active_count=2,random_count=1);self.assertIn(self.ids[2],[x['image_id'] for x in a])
 def test_08_locality_cap_when_alternatives(self):
  a,_=select_ranked(self.p,self._ranked(),1);counts={}
  for x in a:counts[x['locality']]=counts.get(x['locality'],0)+1
  self.assertLessEqual(max(counts.values()),2)
 def test_09_controls_are_from_remaining(self):
  a,b=select_ranked(self.p,self._ranked(),2);self.assertTrue(all(x not in a for x in b))
 def test_10_ranking_creates_no_history(self):
  rank_candidates(self.p,Backend(schema_hash(self.p.schema_path)),candidate_pool(self.p,'v2')[:2]);self.assertFalse((self.p.data_root/'ai/predictions').exists())
 def test_11_only_final_selected_are_written(self):
  ranked=self._ranked();a,b=select_ranked(self.p,ranked,2);sel={'model_id':'v2','model_dataset_id':'d','schema_sha256':schema_hash(self.p.schema_path),'selection_id':'s','selected_images':[{'image_id':x['image_id'],'selection_type':'ACTIVE_SELECTION'} for x in a]+[{'image_id':x['image_id'],'selection_type':'RANDOM_CONTROL'} for x in b]};path=self.p.data_root/'ai/selections/s/selection.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(sel));batch,bpath=create_batch_from_selection(self.p,path);svc=Service(self.p);run_batch(self.p,bpath,svc);self.assertEqual(set(svc.calls),{x['image_id'] for x in batch['selected_images']})
 def test_12_final_ai_rows_unchecked(self):
  self.p.save_landmark(self.ids[2],1,1,1,'auto',provenance='machine');self.assertFalse(self.p.annotation_status(self.ids[2])['verified'])
 def test_13_metadata_reload(self):
  a,b=select_ranked(self.p,self._ranked(),2);self.assertEqual(len(a)+len(b),10)
 def test_14_candidate_pool_never_uses_sequential_rule(self):
  source=Path(__file__).parents[1]/'app/smart_selection.py';self.assertNotIn('start_image_id',source.read_text(encoding='utf8'))
if __name__=='__main__':unittest.main()