import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
import numpy as np
from PIL import Image
from pathlib import Path

from app.ai_package import AIPackageError, export_model_package, import_model_package
from app.project_storage import Project


class SeparateModelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.source = self.temp / "source"; self.source.mkdir(); (self.source / "fish.jpg").write_bytes(b"x")
        self.schema = self.temp / "schema.csv"; self.schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n", encoding="utf-8")
        self.project = Project.create("origin", self.source, self.temp, self.schema, source_layout="direct")
        self.crop = self.project.models_root / "crop_model_v001"; self.crop.mkdir(parents=True)
        np.savez_compressed(self.crop / "model.npz", weights=np.zeros((769, 4)))
        (self.crop / "model_manifest.json").write_text(json.dumps({"backend":"numpy_ridge_image_regression","metrics":{"validation_iou":0.8}}), encoding="utf-8")
        self.project.register_model("crop_model_v001", "crop", path=self.crop.relative_to(self.project.data_root).as_posix(), metrics={"backend":"numpy_ridge_image_regression", "training_examples":9}, active=True)
        self.landmark = self.project.models_root / "rtmpose_v001"; self.landmark.mkdir()
        (self.landmark / "checkpoint.pth").write_bytes(b"checkpoint")
        (self.landmark / "model.json").write_text("{}", encoding="utf-8")
        self.project.register_model("rtmpose_v001", "landmark", path=self.landmark.relative_to(self.project.data_root).as_posix(), metrics={"backend":"rtmpose", "training_examples":9}, active=True)

    def tearDown(self): shutil.rmtree(self.temp, ignore_errors=True)

    def target(self, schema=None):
        return Project.create("target", self.source, self.temp, schema or self.schema, source_layout="direct")

    def test_crop_package_is_separate_and_has_no_project_data(self):
        package = self.temp / "crop.zip"; export_model_package(self.project, "crop", package)
        with zipfile.ZipFile(package) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual("crop", manifest["model_type"])
            self.assertIn("numpy_ridge_image_regression", manifest["backend"])
            self.assertFalse(any("sqlite" in name or "fish.jpg" in name for name in archive.namelist()))
        target = self.target(); local = import_model_package(target, package, "crop")
        self.assertEqual("crop_model_v001", local)
        self.assertTrue((target.data_root / target.model_metadata(local)["path"] / "model.npz").is_file())
        target.set_active_model("crop", local)
        prediction, used = __import__("app.crop_training", fromlist=["predict"]).predict(Image.new("RGB", (64, 48)), image_id="test", project=target)
        self.assertEqual(local, used)
        self.assertEqual(4, len(prediction))

    def test_landmark_package_imports_as_local_parent_candidate(self):
        package = self.temp / "landmark.zip"; export_model_package(self.project, "landmark", package)
        target = self.target(); local = import_model_package(target, package, "landmark")
        self.assertEqual("rtmpose_v001", local)
        self.assertFalse(target.model_metadata(local)["active"])
        target.register_model("rtmpose_v002", "landmark", parent_model_id=local)
        self.assertEqual(local, target.model_metadata("rtmpose_v002")["parent_model_id"])

    def test_collision_gets_unique_local_id_without_overwrite(self):
        package = self.temp / "crop.zip"; export_model_package(self.project, "crop", package)
        target = self.target(); existing = target.models_root / "existing"; existing.mkdir(parents=True)
        target.register_model("crop_model_v001", "crop", path=existing.relative_to(target.data_root).as_posix())
        local = import_model_package(target, package, "crop")
        self.assertEqual("imported_crop_model_v001_2", local)
        self.assertEqual(existing.relative_to(target.data_root).as_posix(), target.model_metadata("crop_model_v001")["path"])

    def test_landmark_schema_mismatch_rejected_without_registration(self):
        package = self.temp / "landmark.zip"; export_model_package(self.project, "landmark", package)
        other = self.temp / "other.csv"; other.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,GM\n", encoding="utf-8")
        target = self.target(other)
        with self.assertRaises(AIPackageError): import_model_package(target, package, "landmark")
        self.assertIsNone(target.model_metadata("rtmpose_v001"))

    def test_bad_checksum_leaves_target_unmodified(self):
        package = self.temp / "crop.zip"; export_model_package(self.project, "crop", package)
        corrupt = self.temp / "corrupt.zip"
        with zipfile.ZipFile(package) as src, zipfile.ZipFile(corrupt, "w") as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename.endswith("model.npz"): data += b"corrupt"
                dst.writestr(item, data)
        target = self.target()
        with self.assertRaises(AIPackageError): import_model_package(target, corrupt, "crop")
        self.assertIsNone(target.model_metadata("crop_model_v001"))
        self.assertFalse((target.models_root / "crop" / "crop_model_v001").exists())

    def test_wrong_type_is_rejected(self):
        package = self.temp / "crop.zip"; export_model_package(self.project, "crop", package)
        with self.assertRaises(AIPackageError): import_model_package(self.target(), package, "landmark")

if __name__ == "__main__": unittest.main()