import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ai_package import AIPackageError, export_ai_package, import_ai_package
from app.project_storage import Project


class AIPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.source = self.temp / "source"; self.source.mkdir(); (self.source / "fish.jpg").write_bytes(b"x")
        self.schema = self.temp / "schema.csv"; self.schema.write_text("id,abbr,name\n1,A,Alpha\n", encoding="utf-8")
        self.source_project = Project.create("origin_project", self.source, self.temp, self.schema, source_layout="direct")
        artifact = self.source_project.data_root / "ai" / "models" / "rtmpose_v001"; artifact.mkdir(parents=True)
        (artifact / "best_engineering_validation.pth").write_bytes(b"weights")
        (artifact / "model.json").write_text("{}", encoding="utf-8")
        self.source_project.register_model("rtmpose_v001", "landmark", path="ai/models/rtmpose_v001", metrics={"training_examples": 7}, active=True)
        self.package = self.temp / "model.zip"

    def tearDown(self): shutil.rmtree(self.temp, ignore_errors=True)

    def test_export_package_created(self):
        with patch("app.ai_package.active_info", return_value={"model_id": None}):
            export_ai_package(self.source_project, self.package)
        self.assertTrue(self.package.is_file())
        self.assertGreater(self.package.stat().st_size, 0)

    def test_import_restores_model_without_activation(self):
        with patch("app.ai_package.active_info", return_value={"model_id": None}): export_ai_package(self.source_project, self.package)
        target = Project.create("target", self.source, self.temp, self.schema, source_layout="direct")
        self.assertEqual(("rtmpose_v001",), import_ai_package(target, self.package))
        model = target.model_metadata("rtmpose_v001")
        self.assertIsNotNone(model)
        self.assertFalse(model["active"])
        self.assertTrue((target.data_root / model["path"] / "best_engineering_validation.pth").is_file())

    def test_incompatible_schema_is_rejected_without_project_changes(self):
        with patch("app.ai_package.active_info", return_value={"model_id": None}): export_ai_package(self.source_project, self.package)
        other_schema = self.temp / "other.csv"; other_schema.write_text("id,abbr,name\n1,A,Alpha\n2,B,Beta\n", encoding="utf-8")
        target = Project.create("target", self.source, self.temp, other_schema, source_layout="direct")
        with target.transaction() as connection: before = tuple(connection.iterdump())
        with self.assertRaises(AIPackageError): import_ai_package(target, self.package)
        with target.transaction() as connection: after = tuple(connection.iterdump())
        self.assertEqual(before, after)
        self.assertIsNone(target.model_metadata("rtmpose_v001"))

    def test_existing_models_are_not_overwritten(self):
        with patch("app.ai_package.active_info", return_value={"model_id": None}): export_ai_package(self.source_project, self.package)
        target = Project.create("target", self.source, self.temp, self.schema, source_layout="direct")
        target.register_model("rtmpose_v001", "landmark", path="other")
        with self.assertRaises(AIPackageError): import_ai_package(target, self.package)
        self.assertEqual("other", target.model_metadata("rtmpose_v001")["path"])


if __name__ == "__main__": unittest.main()
