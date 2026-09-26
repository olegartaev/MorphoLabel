import json, shutil, tempfile, unittest
from pathlib import Path
from PIL import Image
from app.ai import MockBackend
from app.landmark_ai_service import LandmarkAIService
from app.landmark_qc import evaluate_model, save_qc_report
from app.project_runtime import scoped_project, record
from app.project_storage import Project, schema_hash
from app.workflow import save_record,set_human_point

class PredictionHistoryQCTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());src=self.tmp/'src';src.mkdir();(src/'a.jpg').write_bytes(b'x');self.schema=self.tmp/'s.csv';self.schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n3,C,Three,BOTH\n',encoding='utf-8');self.p=Project.create('p',src,self.tmp,self.schema,source_layout='direct');self.image=self.p.catalog_rows()[0];self.id=self.image['image_id'];path=self.p.cache_root/'standardized'/f'{self.id}.png';path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(100,80)).save(path)
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def service(self,**kw):return LandmarkAIService(self.p,MockBackend(schema_hash(self.p.schema_path),**kw))
 def test_manifest_records_returned_omitted_and_run_survives_edits(self):
  result=self.service(missing_ids={3}).predict_one(self.id);manifest=json.loads(result.manifest_path.read_text())
  self.assertEqual(manifest['omitted_landmark_ids'],[3]);self.assertEqual(manifest['written_landmark_ids'],[1,2]);self.assertEqual(self.p.load_landmarks(self.id)[1]['prediction_run_id'],result.prediction_run_id)
  with scoped_project(self.p):
   r=record(self.p,self.image);set_human_point(r,1,'A',40,50,corrected=True);save_record(r);r=record(self.p,self.image);set_human_point(r,1,'A',41,51,corrected=True);save_record(r)
  self.assertEqual(self.p.load_landmarks(self.id)[1]['prediction_run_id'],result.prediction_run_id)
 def test_qc_omission_missing_error_calibration_and_accepted(self):
  result=self.service(missing_ids={3}).predict_one(self.id)
  with scoped_project(self.p):
   r=record(self.p,self.image);set_human_point(r,1,'A',40,53,corrected=True);set_human_point(r,3,'C',30,30);save_record(r)
  self.p.set_locality_calibration(self.image['locality'] or self.image['sample_id'],self.id,2,'mm',{})
  self.p.mark_checked(self.id);qc=evaluate_model(self.p,'mock-landmark-v1')
  self.assertEqual(qc['aggregate']['omitted_but_human_present'],1);self.assertEqual(qc['aggregate']['n_comparable_landmarks'],2);self.assertAlmostEqual(qc['aggregate']['median_error_mm'],0.0);self.assertEqual(qc['aggregate']['accepted_without_correction_fraction'],.5)
  report=save_qc_report(self.p,qc,'r1');before=report.read_bytes();self.p.save_landmark(self.id,1,50,53,'corrected',provenance='corrected_by_human',prediction_run_id=result.prediction_run_id,predicted_x=37,predicted_y=53,model_id='mock-landmark-v1');self.assertEqual(report.read_bytes(),before)
 def test_human_protected_return_is_in_manifest_but_not_written(self):
  self.p.save_landmark(self.id,1,1,2,'manual',provenance='manual');result=self.service().predict_one(self.id);m=json.loads(result.manifest_path.read_text());self.assertIn(1,m['skipped_existing_human_ids']);self.assertIn(1,[x['landmark_id'] for x in m['returned_predictions']]);self.assertEqual(self.p.load_landmarks(self.id)[1]['provenance'],'manual')
if __name__=='__main__':unittest.main()