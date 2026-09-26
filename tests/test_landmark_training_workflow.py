import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.landmark_training_workflow import activate_landmark_model, prepare_landmark_training, run_landmark_training
from app.project_storage import Project, schema_hash
from app.landmark_frames import restore_standardized_frame
from app.transforms import Transform


class _Backend:
    class _Spec:
        config_path = Path("base.py")
        checkpoint_path = Path("base.pth")
        input_size = (512, 256)
        device = "cuda:0"
    spec = _Spec()


class LandmarkTrainingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        source = self.temp / "source"; source.mkdir()
        for index in range(4): Image.new("RGB", (30, 20)).save(source / f"fish{index}.jpg")
        schema = self.temp / "schema.csv"; schema.write_text("id,abbr,name\n1,A,Alpha\n", encoding="utf-8")
        self.project = Project.create("p", source, self.temp, schema, source_layout="direct")
        self.parent = {"model_id": "rtmpose_v001", "schema_sha256": schema_hash(self.project.schema_path)}
        for row in self.project.catalog_rows():
            image_id = row["image_id"]
            developed = self.project.cache_root / "developed" / f"{image_id}.png"
            Image.new("RGB", (30, 20)).save(developed)
            transform = Transform(30, 20, 0.0, 15.0, 10.0, 0, 0, 30, 20)
            self.project.save_reviewed_crop(image_id, {"developed_full_relpath": f"cache/developed/{image_id}.png", "standardized_relpath": f"cache/standardized/{image_id}.png", "crop_bounds": [0, 0, 30, 20], "rotation_degrees": 0.0, "transform": transform.__dict__, "normalization_status": "PASS"})
            restore_standardized_frame(self.project, image_id)
            self.project.save_landmark(row["image_id"], 1, 5, 6, "manual", provenance="manual")
        self.project.register_model("rtmpose_v001", "landmark", path="ai/models/rtmpose_v001", active=True)

    def tearDown(self): shutil.rmtree(self.temp, ignore_errors=True)

    def test_preflight_uses_only_human_verified_eligible_images_and_cancel_is_read_only(self):
        before = tuple(self.project.connect().iterdump())
        with patch("app.landmark_training_workflow.active_backend", return_value=(self.parent, _Backend())):
            plan = prepare_landmark_training(self.project, seed=44)
        after = tuple(self.project.connect().iterdump())
        self.assertEqual(before, after)
        self.assertEqual(4, len(plan.image_ids))
        self.assertEqual(set(plan.image_ids), set(self.project.catalog_rows()[i]["image_id"] for i in range(4)))

    def test_preflight_accepts_parent_after_name_only_schema_edit(self):
        dataset=self.project.data_root/"ai"/"datasets"/"parent";dataset.mkdir(parents=True,exist_ok=True)
        manifest=dataset/"manifest.json"
        manifest.write_text(json.dumps({
            "format_version":1,
            "dataset_id":"parent",
            "schema_landmarks":[{"landmark_id":1,"abbr":"A"}],
            "images":[],
        }),encoding="utf-8")
        with self.project.transaction() as connection:
            connection.execute("UPDATE models SET dataset_id=?,dataset_manifest_path=? WHERE model_id=?",("parent","ai/datasets/parent/manifest.json","rtmpose_v001"))
        parent=self.project.model_metadata("rtmpose_v001")
        self.project.schema_path.write_text("id,abbr,name\n1,A,Renamed alpha\n",encoding="utf-8")
        with patch("app.landmark_training_workflow.active_backend", return_value=(parent, _Backend())):
            plan=prepare_landmark_training(self.project, seed=46, batch_size=4)
        self.assertEqual("rtmpose_v001",plan.parent_model_id)

    def test_training_plan_accepts_selected_overrides(self):
        with patch("app.landmark_training_workflow.active_backend", return_value=(self.parent, _Backend())):
            plan=prepare_landmark_training(self.project, seed=45, batch_size=4, epochs=150, experimental_photometric_augmentation=True)
        self.assertEqual(4,plan.training_settings["batch_size"]);self.assertEqual(150,plan.training_settings["max_epochs"]);self.assertTrue(plan.training_settings["photometric_augmentation"])
    def test_start_calls_existing_pipeline_and_registers_new_model(self):
        with patch("app.landmark_training_workflow.active_backend", return_value=(self.parent, _Backend())):
            plan = prepare_landmark_training(self.project, seed=45)
        def trained(project, dataset_id, backend, *, parent_model_id, settings):
            project.register_model(backend.model_id, "landmark", path=f"ai/models/{backend.model_id}", dataset_id=dataset_id, parent_model_id=parent_model_id)
            return {"model_id": backend.model_id, "result": {"status": "trained"}}
        with patch("app.landmark_training_workflow.active_backend", return_value=(self.parent, _Backend())), patch("app.landmark_training_workflow.train_project", side_effect=trained) as training:
            result = run_landmark_training(self.project, plan)
        training.assert_called_once()
        self.assertEqual(plan.model_id, result["model_id"])
        self.assertIsNotNone(self.project.model_metadata(plan.model_id))
        self.assertIsNotNone(self.project.model_metadata("rtmpose_v001"))

    def test_selected_parent_is_independent_of_active_prediction_model(self):
        self.project.register_model("rtmpose_v002", "landmark", path="ai/models/rtmpose_v002", active=False)
        selected={"model_id":"rtmpose_v002","schema_sha256":schema_hash(self.project.schema_path)}
        with patch("app.landmark_training_workflow.backend_for_model", return_value=(selected, _Backend())) as resolver:
            plan=prepare_landmark_training(self.project,parent_model_id="rtmpose_v002",seed=47,batch_size=4)
        self.assertEqual("rtmpose_v002",plan.parent_model_id)
        self.assertEqual("rtmpose_v001",self.project.active_model("landmark")["model_id"])
        self.assertEqual((self.project,"rtmpose_v002"),resolver.call_args.args[:2])
    def test_activation_switches_only_active_model(self):
        self.project.register_model("rtmpose_v002", "landmark", path="ai/models/rtmpose_v002")
        activate_landmark_model(self.project, "rtmpose_v002")
        self.assertEqual("rtmpose_v002", self.project.active_model("landmark")["model_id"])
        self.assertIsNotNone(self.project.model_metadata("rtmpose_v001"))
        self.assertIsNotNone(self.project.model_metadata("rtmpose_v002"))


if __name__ == "__main__": unittest.main()
