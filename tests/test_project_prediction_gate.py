import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app import project_runtime
from app.project_runtime import open_project, record as project_record
from app.project_storage import Project
from app.workflow import save_record, set_human_point
from tests.current_fixtures import make_reviewed_crop


class ProjectPredictionGateTests(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp());self.source=self.temp/"source";self.source.mkdir()
  (self.source/"image.jpg").write_bytes(b"image")
  self.schema=self.temp/"schema.csv";self.schema.write_text("id,abbr,name,role\n1,P1,Point 1,BOTH\n",encoding="utf-8")
  self.project=Project.create("project",self.source,self.temp,self.schema,source_layout="direct")
  self.image=self.project.catalog_rows()[0];self.image_id=self.image["image_id"];make_reviewed_crop(self.project,self.image_id,80,60)
  open_project(self.project)

 def tearDown(self):
  if project_runtime.active_project() is self.project: project_runtime._active=None
  shutil.rmtree(self.temp,ignore_errors=True)

 def _write_prediction(self, reviewed=False):
  self.project.save_landmark(self.image_id,1,10.0,20.0,"auto",provenance="machine",model_id="landmark_v001",predicted_x=10.0,predicted_y=20.0,confidence=.75,reviewed=reviewed)

 def _record(self): return project_record(self.project,self.image)
 def _row(self): return Project.open(self.project.root).load_landmarks(self.image_id)[1]

 def test_prediction_survives_project_runtime_human_correction_and_checked_reset(self):
  self._write_prediction();self.project.mark_checked(self.image_id)
  record=self._record();set_human_point(record,1,"P1",12.0,22.0,corrected=True);save_record(record)
  row=self._row()
  self.assertEqual((row["x_standardized"],row["y_standardized"]),(12.0,22.0))
  self.assertEqual((row["predicted_x"],row["predicted_y"]),(10.0,20.0))
  self.assertEqual(row["model_id"],"landmark_v001");self.assertEqual(row["confidence"],.75)
  self.assertEqual(row["provenance"],"corrected_by_human");self.assertEqual(row["state"],"corrected")
  self.assertTrue(Project.open(self.project.root).annotation_status(self.image_id)["verified"])

 def test_prediction_survives_three_project_runtime_corrections(self):
  self._write_prediction()
  for x,y in ((12.0,22.0),(14.0,24.0),(16.0,26.0)):
   record=self._record();set_human_point(record,1,"P1",x,y,corrected=True);save_record(record)
   row=self._row()
   self.assertEqual((row["x_standardized"],row["y_standardized"]),(x,y))
   self.assertEqual((row["predicted_x"],row["predicted_y"]),(10.0,20.0))
   self.assertEqual(row["model_id"],"landmark_v001");self.assertEqual(row["confidence"],.75)

 def test_prediction_survives_project_runtime_manual_missing(self):
  self._write_prediction();record=self._record();set_human_point(record,1,"P1",None,None);save_record(record)
  row=self._row()
  self.assertEqual(row["state"],"missing");self.assertEqual(row["provenance"],"manual")
  self.assertIsNone(row["x_standardized"]);self.assertIsNone(row["y_standardized"])
  self.assertEqual((row["predicted_x"],row["predicted_y"]),(10.0,20.0))
  self.assertEqual(row["model_id"],"landmark_v001");self.assertEqual(row["confidence"],.75)

 def test_checked_auto_prediction_keeps_machine_reference(self):
  self._write_prediction();self.project.mark_checked(self.image_id)
  row=self._row();status=Project.open(self.project.root).annotation_status(self.image_id)
  self.assertTrue(status["verified"]);self.assertEqual(row["provenance"],"machine")
  self.assertEqual((row["x_standardized"],row["y_standardized"]),(10.0,20.0))
  self.assertEqual((row["predicted_x"],row["predicted_y"]),(10.0,20.0));self.assertEqual(row["model_id"],"landmark_v001")

 def test_replace_landmarks_preserves_complete_prediction_metadata(self):
  self._write_prediction(reviewed=False);record=self._record();self.assertFalse(record["points"]["1"]["reviewed"])
  save_record(record);row=self._row()
  self.assertFalse(row["reviewed"]);self.assertEqual(row["state"],"auto");self.assertEqual(row["provenance"],"machine")
  self.assertEqual((row["predicted_x"],row["predicted_y"]),(10.0,20.0));self.assertEqual(row["model_id"],"landmark_v001");self.assertEqual(row["confidence"],.75)

 def test_schema_hashes_match_for_new_project_and_sync_on_open(self):
  actual=hashlib.sha256(self.project.schema_path.read_bytes()).hexdigest()
  self.assertEqual(json.loads(self.project.config_path.read_text(encoding="utf-8"))["schema_sha256"],actual)
  with self.project.transaction() as c:self.assertEqual(c.execute("SELECT value FROM project WHERE key='schema_sha256'").fetchone()[0],actual)
  self.project.schema_path.write_text("id,abbr,name,role\n1,P1renamed,Point 1,BOTH\n",encoding="utf-8")
  reopened=Project.open(self.project.root);changed=hashlib.sha256(reopened.schema_path.read_bytes()).hexdigest()
  self.assertEqual(json.loads(reopened.config_path.read_text(encoding="utf-8"))["schema_sha256"],changed)
  with reopened.transaction() as c:self.assertEqual(c.execute("SELECT value FROM project WHERE key='schema_sha256'").fetchone()[0],changed)

 def test_open_uses_changed_csv_as_startup_schema_source_of_truth(self):
  schema_b="id,abbr,name,role\n1,P1B,Point 1 renamed,GM\n2,P2,Point 2,BOTH\n"
  self.project.schema_path.write_text(schema_b,encoding="utf-8")
  reopened=Project.open(self.project.root);digest=hashlib.sha256(reopened.schema_path.read_bytes()).hexdigest()
  self.assertEqual(reopened.schema,[
   {"id":1,"abbr":"P1B","name":"Point 1 renamed","role":"GM","category":""},
   {"id":2,"abbr":"P2","name":"Point 2","role":"BOTH","category":""},
  ])
  self.assertEqual(json.loads(reopened.config_path.read_text(encoding="utf-8"))["schema_sha256"],digest)
  with reopened.transaction() as c:self.assertEqual(c.execute("SELECT value FROM project WHERE key='schema_sha256'").fetchone()[0],digest)

 def test_open_replaces_stale_yaml_and_sqlite_hashes_from_csv(self):
  schema_b="id,abbr,name,role\n1,P1B,Point 1 renamed,GM\n"
  self.project.schema_path.write_text(schema_b,encoding="utf-8")
  config=json.loads(self.project.config_path.read_text(encoding="utf-8"));config["schema_sha256"]="stale-yaml";self.project.config_path.write_text(json.dumps(config),encoding="utf-8")
  with self.project.transaction() as c:c.execute("UPDATE project SET value=? WHERE key='schema_sha256'",("stale-sqlite",))
  reopened=Project.open(self.project.root);digest=hashlib.sha256(reopened.schema_path.read_bytes()).hexdigest()
  self.assertEqual(reopened.schema[0]["abbr"],"P1B")
  self.assertEqual(json.loads(reopened.config_path.read_text(encoding="utf-8"))["schema_sha256"],digest)
  with reopened.transaction() as c:self.assertEqual(c.execute("SELECT value FROM project WHERE key='schema_sha256'").fetchone()[0],digest)

 def test_open_rejects_invalid_csv_instead_of_using_stale_metadata(self):
  old_digest=hashlib.sha256(self.project.schema_path.read_bytes()).hexdigest()
  self.project.schema_path.write_text("id,abbr,name,role\n1,P1,Point 1,NOT_A_ROLE\n",encoding="utf-8")
  reopened=Project.open(self.project.root)
  self.assertEqual(reopened.schema,[])
  self.assertNotEqual(json.loads(self.project.config_path.read_text(encoding="utf-8"))["schema_sha256"],old_digest)
 def test_active_landmark_model_with_old_schema_hash_is_rejected_after_sync(self):
  old=hashlib.sha256(self.project.schema_path.read_bytes()).hexdigest()
  self.project.register_model("landmark_v001","landmark",active=True,schema_digest=old)
  self.project.schema_path.write_text("id,abbr,name,role\n1,P1changed,Point 1,BOTH\n",encoding="utf-8")
  reopened=Project.open(self.project.root)
  with self.assertRaises(ValueError):reopened.active_model("landmark")


if __name__=="__main__": unittest.main()
