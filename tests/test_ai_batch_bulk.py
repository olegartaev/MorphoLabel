import json,tempfile,unittest
from pathlib import Path
from app.ai_batch import run_batch
class P:
 def __init__(self,d):self.data_root=Path(d);self.schema_path=self.data_root/'schema.csv';self.schema_path.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n',encoding='utf8')
class S:
 def __init__(self):self.calls=[]
 def predict_many(self,ids,progress=None):
  self.calls.append(tuple(ids))
  for i in ids: progress(i,type('R',(),{'prediction_run_id':'run-'+i})(),None)
class T(unittest.TestCase):
 def test_bulk_persists_and_resume_skips(self):
  with tempfile.TemporaryDirectory() as d:
   p=P(d);path=p.data_root/'batch.json';ids=[str(i) for i in range(8)];path.write_text(json.dumps({'schema_sha256':__import__('app.project_storage',fromlist=['schema_hash']).schema_hash(p.schema_path),'selected_images':[{'image_id':i,'display_name':i} for i in ids],'prediction_runs':{},'failures':{}}));s=S();events=[];data,_=run_batch(p,path,s,progress=lambda *x:events.append(x));self.assertEqual([tuple(ids)],s.calls);self.assertEqual(8,len(data['prediction_runs']));self.assertEqual(list(range(1,9)),[x[0] for x in events]);self.assertEqual(ids,[x[3] for x in events]);run_batch(p,path,s);self.assertEqual(1,len(s.calls))
if __name__=='__main__':unittest.main()
