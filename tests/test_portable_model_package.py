import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.ai_package import export_model_package
from app.project_storage import Project


class PortableModelPackageTests(unittest.TestCase):
    def test_landmark_package_contains_only_portable_inference_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"source";source.mkdir();(source/"fish.jpg").write_bytes(b"x")
            schema=root/"schema.csv";schema.write_text("id,abbr,name\n1,A,Alpha\n",encoding="utf-8")
            project=Project.create("p",source,root,schema,source_layout="direct")
            artifact=project.data_root/"ai"/"models"/"rtmpose_v001";artifact.mkdir(parents=True)
            (artifact/"best_engineering_validation.pth").write_bytes(b"weights")
            (artifact/"inference_config.py").write_text("default_scope='mmpose'\n",encoding="utf-8")
            (artifact/"config.py").write_text("_base_=['C:/PRIVATE/bootstrap.py']\ndata_root='C:/PRIVATE/project'\n",encoding="utf-8")
            (artifact/"train.coco.json").write_text('{"private":"landmarks"}',encoding="utf-8")
            (artifact/"finalization.json").write_text('{"dataset_manifest":"C:/PRIVATE/dataset.json"}',encoding="utf-8")
            (artifact/"model.json").write_text(json.dumps({"backend":"rtmpose","schema_sha256":"x","input_size":[512,256],"dataset_manifest":"C:/PRIVATE/dataset.json"}),encoding="utf-8")
            project.register_model("rtmpose_v001","landmark",path=artifact.relative_to(project.data_root).as_posix(),metrics={"backend":"rtmpose"},active=True)
            target=root/"model.zip";export_model_package(project,"landmark",target)
            with zipfile.ZipFile(target) as z:
                names=set(z.namelist());payload=b"\n".join(z.read(name) for name in names if not name.endswith(".pth"))
            self.assertEqual({"artifacts/config.py","artifacts/best_engineering_validation.pth","artifacts/model.json","manifest.json"},names)
            self.assertNotIn(b"PRIVATE",payload)
            self.assertNotIn(b"train.coco",payload)
            self.assertNotIn(b"dataset_manifest",payload)

    def test_crop_package_redacts_training_membership(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/"source";source.mkdir();(source/"fish.jpg").write_bytes(b"x")
            schema=root/"schema.csv";schema.write_text("id,abbr,name\n1,A,Alpha\n",encoding="utf-8")
            project=Project.create("p",source,root,schema,source_layout="direct")
            artifact=project.models_root/"crop"/"crop_model_v001";artifact.mkdir(parents=True)
            (artifact/"model.npz").write_bytes(b"weights")
            (artifact/"model_manifest.json").write_text(json.dumps({"model_id":"crop_model_v001","backend":"numpy","training_image_ids":["secret-id"],"train_indices":[0],"validation_indices":[1],"metrics":{"validation_iou":0.9}}),encoding="utf-8")
            project.register_model("crop_model_v001","crop",path=artifact.relative_to(project.data_root).as_posix(),metrics={"backend":"numpy"},active=True)
            target=root/"crop.zip";export_model_package(project,"crop",target)
            with zipfile.ZipFile(target) as z:payload=z.read("artifacts/model_manifest.json")
            self.assertNotIn(b"secret-id",payload)
            self.assertNotIn(b"training_image_ids",payload)


if __name__=="__main__":
    unittest.main()
