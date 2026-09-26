import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.ai_hardware import HardwareProfile
from app.landmark_dataset import create_dataset
from app.landmark_training_workflow import _next_model_id, prepare_landmark_training, run_landmark_training
from app.project_storage import Project, schema_hash


class Backend:
    class Spec:
        config_path = Path("base.py")
        checkpoint_path = Path("base.pth")
        input_size = (512, 256)
        device = "cpu"
    spec = Spec()


class TrainingRetryDatasetIdTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); source = self.root / "source"; source.mkdir()
        for number in range(2): Image.new("RGB", (30, 20)).save(source / f"fish_{number}.jpg")
        schema = self.root / "schema.csv"; schema.write_text("id,abbr,name\n1,A,Alpha\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_layout="direct")
        for row in self.project.catalog_rows():
            cache = self.project.cache_root / "standardized" / f"{row['image_id']}.png"; cache.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", (30, 20)).save(cache)
            self.project.save_landmark(row["image_id"], 1, 5, 6, "present", provenance="manual"); self.project.mark_checked(row["image_id"])
        self.parent = {"model_id": "rtmpose_v004", "schema_sha256": schema_hash(self.project.schema_path)}
        self.hardware = HardwareProfile("CPU", 4, 4, None, None, None, None, False, None, "CPU")

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)

    def _prepare(self):
        with patch("app.landmark_training_workflow.active_backend", return_value=(self.parent, Backend())), patch("app.landmark_training_workflow.get_hardware_profile", return_value=self.hardware):
            return prepare_landmark_training(self.project, seed=20260824)

    def test_orphan_artifact_advances_next_model_id(self):
        self.project.register_model("rtmpose_v004", "landmark")
        (self.project.data_root / "ai" / "models" / "rtmpose_v005").mkdir(parents=True)
        self.assertEqual("rtmpose_v006", _next_model_id(self.project))

    def test_next_model_id_is_sequential_without_orphan_artifact(self):
        self.project.register_model("rtmpose_v004", "landmark")
        self.assertEqual("rtmpose_v005", _next_model_id(self.project))
    def test_same_day_preparation_attempts_have_unique_dataset_ids(self):
        first = self._prepare(); second = self._prepare()
        self.assertEqual(first.model_id, second.model_id)
        self.assertNotEqual(first.dataset_id, second.dataset_id)

    def test_orphan_dataset_does_not_block_retry(self):
        failed = self._prepare()
        create_dataset(self.project, dataset_id=failed.dataset_id, splits=failed.splits, seed=failed.seed, eligibility_mode="v2_human_final")
        retry = self._prepare()
        def trained(_project, dataset_id, backend, **_kwargs): return {"model_id": backend.model_id, "dataset_id": dataset_id}
        with patch("app.landmark_training_workflow.active_backend", return_value=(self.parent, Backend())), patch("app.landmark_training_workflow.train_project", side_effect=trained):
            result = run_landmark_training(self.project, retry)
        self.assertEqual(retry.dataset_id, result["dataset_id"])


if __name__ == "__main__":
    unittest.main()