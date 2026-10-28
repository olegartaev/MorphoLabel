"""Training-counter contract: count human-verified unregistered specimens, not drafts or pseudo-labels."""
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase,main,mock
from app.xray_project import XRayProject


class NewVerifiedCountTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/"xray_project.sqlite3"
        with sqlite3.connect(self.db) as c:
            c.executescript("""
                CREATE TABLE source_images(image_id TEXT,crop_reviewed INTEGER,excluded INTEGER);
                CREATE TABLE specimens(specimen_id TEXT,image_id TEXT,crop_status TEXT,excluded INTEGER);
                CREATE TABLE annotation_runs(run_id TEXT,specimen_id TEXT,pass_no INTEGER,
                    source TEXT,schema_version_id TEXT,status TEXT);
                CREATE TABLE annotations(annotation_id INTEGER,run_id TEXT);
                CREATE TABLE xray_structure_models(model_id TEXT,training_specimen_count INTEGER,
                    validation_specimen_count INTEGER);
                CREATE TABLE xray_structure_training_membership(model_id TEXT,specimen_id TEXT,split TEXT);
                INSERT INTO source_images VALUES('plate',1,0);
                INSERT INTO specimens VALUES('old','plate','confirmed',0);
                INSERT INTO specimens VALUES('new','plate','confirmed',0);
                INSERT INTO specimens VALUES('draft','plate','confirmed',0);
                INSERT INTO annotation_runs VALUES('one','old',1,'human','active','verified');
                INSERT INTO annotation_runs VALUES('two','new',1,'human','active','verified');
                INSERT INTO annotation_runs VALUES('three','draft',1,'human','active','draft');
                INSERT INTO annotations VALUES(1,'one');
                INSERT INTO annotations VALUES(2,'one');
                INSERT INTO annotations VALUES(3,'two');
                INSERT INTO annotations VALUES(4,'two');
                INSERT INTO annotations VALUES(5,'two');
                INSERT INTO annotations VALUES(6,'three');
                INSERT INTO xray_structure_models VALUES('known',1,0);
                INSERT INTO xray_structure_models VALUES('imported',1,0);
                INSERT INTO xray_structure_training_membership VALUES('known','old','train');
            """)
        self.project=XRayProject.__new__(XRayProject)
        self.project.db_path=self.db
        patch=mock.patch.object(XRayProject,"active_scheme_record",
                                return_value={"scientific_version_id":"active"})
        patch.start();self.addCleanup(patch.stop)

    def test_new_markers_and_specimens(self):
        self.assertEqual(self.project.new_verified_training_markers("known"),
                         {"known":True,"specimens":1,"markers":3})
        self.assertEqual(self.project.new_verified_training_markers(),
                         {"known":True,"specimens":2,"markers":5})

    def test_unknown_imported_training_history(self):
        self.assertEqual(self.project.new_verified_training_markers("imported")["known"],False)

    def test_invalid_parent(self):
        with self.assertRaises(KeyError):
            self.project.new_verified_training_markers("missing")


if __name__=="__main__":
    main()
