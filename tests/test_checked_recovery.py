import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.checked_recovery import CheckedRecoveryError, apply_checked_recovery, validate_recovery_plan
from app.project_storage import Project
from app.transforms import Transform


class CheckedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp())
        source=self.root/"source";source.mkdir()
        Image.new("RGB",(40,30),"white").save(source/"fish.jpg")
        schema=self.root/"schema.csv"
        schema.write_text("id,abbr,name\n1,A,One\n2,B,Two\n",encoding="utf8")
        self.project=Project.create("p",source,self.root,schema,source_layout="direct")
        self.image_id=self.project.catalog_rows()[0]["image_id"]
        transform=Transform(40,30,0.0,20.0,15.0,0.0,0.0,40,30)
        with self.project.transaction() as db:
            db.execute(
                """INSERT INTO crops(image_id,crop_json,transform_json,rotation_degrees,status,provenance,human_verified,reviewed_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (self.image_id,json.dumps([0,0,40,30]),json.dumps(transform.__dict__),0.0,"PASS","manual",1,"2026-01-01T00:00:00+00:00","2026-01-01T00:00:00+00:00"),
            )
        self.project.save_machine_landmarks(
            self.image_id,
            [{"landmark_id":1,"x":10,"y":10,"confidence":.9},{"landmark_id":2,"x":20,"y":10,"confidence":.8}],
            model_id="m1",prediction_run_id="r1",
        )
        self.project.mark_checked(self.image_id)
        self.reference=self.root/"reference.sqlite"
        source_db=sqlite3.connect(self.project.path);target=sqlite3.connect(self.reference)
        try:source_db.backup(target)
        finally:target.close();source_db.close()

    def tearDown(self):
        shutil.rmtree(self.root,ignore_errors=True)

    def _simulate_mass_reset(self):
        with self.project.transaction() as db:
            db.execute("UPDATE landmarks SET reviewed=0 WHERE image_id=?",(self.image_id,))
            db.execute("UPDATE image_review SET human_verified=0 WHERE image_id=?",(self.image_id,))

    def test_exact_state_recovery_restores_effective_checked_with_audit_and_backup(self):
        self._simulate_mass_reset()
        plan=validate_recovery_plan(self.project,self.reference,[self.image_id])
        self.assertEqual(1,len(plan["restore"]))
        result=apply_checked_recovery(self.project,self.reference,[self.image_id],plan_sha256="plan")
        self.assertEqual(1,result["restored"])
        self.assertTrue(Path(result["backup_path"]).is_file())
        self.assertTrue(self.project.annotation_status(self.image_id)["verified"])
        self.assertNotIn(self.image_id,self.project.pending_ai_landmark_image_ids())
        self.assertTrue(all(bool(row.get("reviewed")) for row in self.project.load_landmarks(self.image_id).values()))
        with self.project.transaction() as db:
            audit=db.execute("SELECT payload_json FROM qc WHERE image_id=? AND kind='checked_history_recovery'",(self.image_id,)).fetchone()
        self.assertIsNotNone(audit)
        payload=json.loads(audit["payload_json"]);self.assertEqual("plan",payload["plan_sha256"]);self.assertTrue(payload["state_sha256"])

    def test_legacy_backup_without_landmark_abbr_is_resolved_through_landmark_schema(self):
        legacy=self.root/"legacy_reference.sqlite"
        shutil.copy2(self.reference,legacy)
        db=sqlite3.connect(legacy)
        try:
            db.execute("ALTER TABLE landmarks RENAME TO landmarks_modern")
            db.execute("""CREATE TABLE landmarks AS
                          SELECT image_id,landmark_id,x_standardized,y_standardized,state,provenance,
                                 model_id,predicted_x,predicted_y,confidence,prediction_run_id,reviewed,updated_at
                          FROM landmarks_modern""")
            db.execute("DROP TABLE landmarks_modern")
            db.commit()
        finally:
            db.close()
        self._simulate_mass_reset()
        plan=validate_recovery_plan(self.project,legacy,[self.image_id])
        self.assertEqual(1,len(plan["restore"]))
        self.assertEqual(0,len(plan["already_checked"]))

    def test_raw_checked_with_pending_machine_is_still_recovered_to_effective_checked(self):
        self._simulate_mass_reset()
        with self.project.transaction() as db:
            db.execute("UPDATE image_review SET human_verified=1 WHERE image_id=?",(self.image_id,))
        self.assertFalse(self.project.annotation_status(self.image_id)["verified"])
        plan=validate_recovery_plan(self.project,self.reference,[self.image_id])
        self.assertEqual(1,len(plan["restore"]));self.assertEqual(0,len(plan["already_checked"]))
        result=apply_checked_recovery(self.project,self.reference,[self.image_id])
        self.assertEqual(1,result["restored"])
        self.assertTrue(self.project.annotation_status(self.image_id)["verified"])

    def test_recovery_aborts_before_write_when_scientific_state_changed(self):
        self._simulate_mass_reset()
        with self.project.transaction() as db:
            db.execute("UPDATE landmarks SET x_standardized=x_standardized+1 WHERE image_id=? AND landmark_abbr='A'",(self.image_id,))
        before=list((self.project.root/"backups").glob("checked_recovery_*")) if (self.project.root/"backups").exists() else []
        with self.assertRaises(CheckedRecoveryError):
            apply_checked_recovery(self.project,self.reference,[self.image_id])
        after=list((self.project.root/"backups").glob("checked_recovery_*")) if (self.project.root/"backups").exists() else []
        self.assertEqual(before,after)
        self.assertFalse(self.project.annotation_status(self.image_id)["verified"])

    def test_identical_observation_preserves_checked_new_run_and_coordinates_invalidate(self):
        self.assertTrue(self.project.annotation_status(self.image_id)["verified"])
        points=[{"landmark_id":1,"x":10,"y":10,"confidence":.7},{"landmark_id":2,"x":20,"y":10,"confidence":.7}]
        self.project.save_machine_landmarks(self.image_id,points,model_id="m1",prediction_run_id="r1")
        self.assertTrue(self.project.annotation_status(self.image_id)["verified"])
        self.project.save_machine_landmarks(self.image_id,points,model_id="m2",prediction_run_id="r2")
        self.assertFalse(self.project.annotation_status(self.image_id)["verified"])
        self.assertTrue(all(not bool(row.get("reviewed")) for row in self.project.load_landmarks(self.image_id).values()))
        self.project.mark_checked(self.image_id)
        self.project.save_machine_landmarks(self.image_id,[{**points[0],"x":11},points[1]],model_id="m2",prediction_run_id="r2")
        self.assertFalse(self.project.annotation_status(self.image_id)["verified"])
        self.assertIn(self.image_id,self.project.pending_ai_landmark_image_ids())


if __name__=="__main__":
    unittest.main()
