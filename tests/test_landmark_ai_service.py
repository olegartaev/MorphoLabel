import math
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.ai import LandmarkPrediction, MockBackend
from app.landmark_ai_service import LandmarkAIService, PredictionValidationError, SchemaMismatchError
from app.project_runtime import record as project_record, scoped_project
from app.project_storage import Project, schema_hash
from app.workflow import save_record, set_human_point
from app.transforms import Transform

class LandmarkAIGateOneTests(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp());self.source=self.temp/"source";self.source.mkdir()
  for index in range(5):(self.source/f"image_{index}.jpg").write_bytes(b"source")
  self.schema=self.temp/"schema.csv";self.schema.write_text("id,abbr,name,role\n1,P1,Point 1,BOTH\n2,P2,Point 2,BOTH\n3,P3,Point 3,GM\n4,P4,Point 4,CLASSICAL\n5,P5,Point 5,BOTH\n",encoding="utf-8")
  self.project=Project.create("project",self.source,self.temp,self.schema,source_layout="direct")
  self.images=self.project.catalog_rows();self.ids=[row["image_id"] for row in self.images]
  for image_id in self.ids:
   path=self.project.cache_root/"standardized"/f"{image_id}.png";path.parent.mkdir(parents=True,exist_ok=True);Image.new("RGB",(100,80),(10,20,30)).save(path)
   crop={"crop_bounds":[0,0,100,80],"transform":Transform(100,80,0,50,40,0,0,100,80).__dict__,"standardized_relpath":path.relative_to(self.project.data_root).as_posix()}
   self.project.save_reviewed_crop(image_id,crop)
 def tearDown(self): shutil.rmtree(self.temp,ignore_errors=True)
 def backend(self,**kwargs): return MockBackend(schema_hash(self.project.schema_path),**kwargs)
 def service(self,**kwargs): return LandmarkAIService(self.project,self.backend(**kwargs))
 def points(self,image_id=None): return self.project.load_landmarks(image_id or self.ids[0])

 def test_full_prediction_writes_standardized_machine_rows_and_clears_checked(self):
  image_id=self.ids[0];self.project.mark_checked if False else None
  result=self.service(confidences={1:.1,2:.2,3:.3,4:.4,5:.5}).predict_one(image_id)
  rows=Project.open(self.project.root).load_landmarks(image_id)
  self.assertEqual(result.saved_landmarks,5);self.assertEqual(set(rows),{1,2,3,4,5})
  for landmark_id,row in rows.items():
   self.assertEqual(row["state"],"auto");self.assertEqual(row["provenance"],"machine");self.assertEqual(row["model_id"],"mock-landmark-v1")
   self.assertEqual((row["x_standardized"],row["y_standardized"]),(row["predicted_x"],row["predicted_y"]));self.assertAlmostEqual(row["confidence"],landmark_id/10)
  self.assertFalse(self.project.annotation_status(image_id)["verified"])
  with self.project.transaction() as c:
   model=c.execute("SELECT kind,schema_sha256 FROM models WHERE model_id=?",("mock-landmark-v1",)).fetchone()
  self.assertEqual((model["kind"],model["schema_sha256"]),("landmark",schema_hash(self.project.schema_path)))

 def test_manual_landmark_is_never_overwritten(self):
  image_id=self.ids[0];self.project.save_landmark(image_id,1,7,8,"manual",provenance="manual")
  result=self.service().predict_one(image_id);rows=self.points(image_id)
  self.assertEqual((rows[1]["x_standardized"],rows[1]["y_standardized"],rows[1]["provenance"]),(7,8,"manual"))
  self.assertIsNone(rows[1]["predicted_x"]);self.assertEqual(result.saved_landmarks,4);self.assertEqual(result.skipped_human_landmarks,1)
  self.assertTrue(all(rows[i]["provenance"]=="machine" for i in (2,3,4,5)))

 def test_partial_prediction_keeps_absent_schema_id_unresolved(self):
  image_id=self.ids[0];self.service(missing_ids={3}).predict_one(image_id)
  self.assertEqual(set(self.points(image_id)),{1,2,4,5})
  status=self.project.annotation_status(image_id)
  self.assertEqual(status["missing_ids"],[3]);self.assertEqual(status["color"],"red")

 def test_registered_model_survives_nonstructural_schema_label_change(self):
  image_id=self.ids[0]
  dataset=self.project.data_root/"ai"/"datasets"/"compat";dataset.mkdir(parents=True,exist_ok=True)
  manifest=dataset/"manifest.json"
  manifest.write_text(__import__("json").dumps({
   "format_version":1,"dataset_id":"compat","schema_sha256":schema_hash(self.project.schema_path),
   "schema_landmarks":[{"landmark_id":i,"abbr":f"P{i}"} for i in range(1,6)],"images":[]
  }),encoding="utf-8")
  old_digest=schema_hash(self.project.schema_path)
  self.project.register_model("compat-model","landmark",schema_digest=old_digest,dataset_id="compat",dataset_manifest_path="ai/datasets/compat/manifest.json")
  self.project.schema_path.write_text("id,abbr,name,role\n1,P1,Renamed point 1,GM\n2,P2,Point 2,BOTH\n3,P3,Point 3,GM\n4,P4,Point 4,CLASSICAL\n5,P5,Point 5,BOTH\n",encoding="utf-8")
  backend=MockBackend(schema_hash(self.project.schema_path),model_id="compat-model")
  result=LandmarkAIService(self.project,backend).predict_one(image_id)
  self.assertEqual(5,result.saved_landmarks)
  self.assertEqual("compat-model",self.project.load_landmarks(image_id)[1]["model_id"])

 def test_registered_model_rejects_landmark_identity_reorder(self):
  image_id=self.ids[0]
  dataset=self.project.data_root/"ai"/"datasets"/"compat";dataset.mkdir(parents=True,exist_ok=True)
  manifest=dataset/"manifest.json"
  manifest.write_text(__import__("json").dumps({
   "format_version":1,"dataset_id":"compat","schema_sha256":schema_hash(self.project.schema_path),
   "schema_landmarks":[{"landmark_id":i,"abbr":f"P{i}"} for i in range(1,6)],"images":[]
  }),encoding="utf-8")
  self.project.register_model("compat-model","landmark",schema_digest=schema_hash(self.project.schema_path),dataset_id="compat",dataset_manifest_path="ai/datasets/compat/manifest.json")
  self.project.schema_path.write_text("id,abbr,name,role\n1,P2,Point 2,BOTH\n2,P1,Point 1,BOTH\n3,P3,Point 3,GM\n4,P4,Point 4,CLASSICAL\n5,P5,Point 5,BOTH\n",encoding="utf-8")
  backend=MockBackend(schema_hash(self.project.schema_path),model_id="compat-model")
  with self.assertRaises(SchemaMismatchError):LandmarkAIService(self.project,backend).predict_one(image_id)
  self.assertEqual({},self.project.load_landmarks(image_id))

 def test_schema_mismatch_writes_nothing(self):
  image_id=self.ids[0];backend=MockBackend("not-current-schema")
  with self.assertRaises(SchemaMismatchError): LandmarkAIService(self.project,backend).predict_one(image_id)
  self.assertEqual(self.points(image_id),{})

 def test_invalid_landmark_id_writes_nothing(self):
  image_id=self.ids[0];bad=LandmarkPrediction(99,1,1,.5)
  with self.assertRaises(PredictionValidationError): self.service(extra_predictions=(bad,)).predict_one(image_id)
  self.assertEqual(self.points(image_id),{})

 def test_invalid_coordinates_write_nothing(self):
  image_id=self.ids[0]
  for coords in ((math.nan,1),(1,math.inf),(-1,1),(101,1)):
   with self.subTest(coords=coords):
    with self.assertRaises(PredictionValidationError): self.service(coordinate_overrides={1:coords}).predict_one(image_id)
    self.assertEqual(self.points(image_id),{})

 def test_subpixel_edge_prediction_is_clipped_and_audited(self):
  image_id=self.ids[0];result=self.service(coordinate_overrides={1:(100.0,40.0),2:(20.0,-0.25)}).predict_one(image_id)
  rows=self.points(image_id)
  self.assertGreaterEqual(rows[1]["x_standardized"],0);self.assertLess(rows[1]["x_standardized"],100)
  self.assertEqual(rows[1]["y_standardized"],40.0)
  self.assertEqual(rows[2]["x_standardized"],20.0);self.assertEqual(rows[2]["y_standardized"],0.0)
  manifest=__import__("json").loads(result.manifest_path.read_text(encoding="utf8"))
  self.assertEqual(2,len(manifest["coordinate_adjustments"]))
  raw={row["landmark_id"]:row for row in manifest["returned_predictions"]}
  self.assertEqual(100.0,raw[1]["x"]);self.assertEqual(-0.25,raw[2]["y"])

 def test_mock_prediction_survives_human_correction_through_runtime_path(self):
  image_id=self.ids[0];self.service().predict_one(image_id)
  with scoped_project(self.project):
   record=project_record(self.project,self.images[0]);initial=self.points(image_id)[1]
   set_human_point(record,1,"P1",44,55,corrected=True);save_record(record)
  row=Project.open(self.project.root).load_landmarks(image_id)[1]
  self.assertEqual((row["x_standardized"],row["y_standardized"]),(44,55))
  self.assertEqual((row["predicted_x"],row["predicted_y"]),(initial["predicted_x"],initial["predicted_y"]))
  self.assertEqual((row["model_id"],row["confidence"]),("mock-landmark-v1",initial["confidence"]))
  self.assertEqual(row["provenance"],"corrected_by_human")

 def test_mock_prediction_can_be_checked_without_coordinate_change(self):
  image_id=self.ids[0];self.service().predict_one(image_id);before=self.points(image_id)
  self.project.mark_checked(image_id);after=Project.open(self.project.root).load_landmarks(image_id)
  self.assertTrue(self.project.annotation_status(image_id)["verified"])
  for landmark_id in before:self.assertEqual((after[landmark_id]["x_standardized"],after[landmark_id]["predicted_x"],after[landmark_id]["model_id"]),(before[landmark_id]["x_standardized"],before[landmark_id]["predicted_x"],"mock-landmark-v1"))

 def test_batch_isolates_one_failed_image(self):
  failed=self.ids[2];summary=self.service(fail_image_ids={failed}).predict_many(self.ids)
  self.assertEqual((summary.attempted,summary.succeeded,summary.failed,summary.skipped,summary.written_landmarks),(5,4,1,0,20))
  self.assertIn(failed,summary.errors);self.assertEqual(self.points(failed),{})
  self.assertTrue(all(len(self.points(image_id))==5 for image_id in self.ids if image_id!=failed))

 def test_missing_standardized_cache_is_restored_only_from_persisted_crop(self):
  image_id=self.ids[0];developed=self.project.cache_root/'developed'/f'{image_id}.png';developed.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(100,80),(10,20,30)).save(developed)
  cached=self.project.cache_root/'standardized'/f'{image_id}.png';cached.unlink()
  path=self.service()._standardized_image(image_id)
  self.assertTrue(path.is_file());self.assertEqual(path,cached)

 def test_uncropped_image_never_normalizes_for_prediction(self):
  image_id=self.ids[0]
  with self.project.transaction() as c:c.execute('DELETE FROM crops WHERE image_id=?',(image_id,))
  with self.assertRaises(Exception) as error:self.service()._standardized_image(image_id)
  self.assertIn('Crop required',str(error.exception))
if __name__=="__main__": unittest.main()

