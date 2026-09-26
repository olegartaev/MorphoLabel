import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.landmark_training_workflow import prepare_landmark_training
from app.project_storage import Project
from app.landmark_frames import restore_standardized_frame
from app.transforms import Transform


REPO = Path(__file__).resolve().parents[1]


class CanonicalExecutionTests(unittest.TestCase):
    def test_poisoned_cwd_and_pythonpath_still_import_canonical_app(self):
        environment = dict(os.environ, PYTHONPATH=r"D:\Morphology_Pipeline")
        with tempfile.TemporaryDirectory() as temporary:
            for cwd in (Path(r"D:\Morphology_Pipeline"), Path(temporary)):
                result = subprocess.run([str(REPO / "RUN_CANONICAL.cmd"), "provenance"], cwd=cwd, env=environment, text=True, capture_output=True, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                sources = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
                self.assertTrue(Path(sources["APP_SOURCE"]).resolve().is_relative_to(REPO.resolve()))
                self.assertFalse(Path(sources["APP_SOURCE"]).resolve().is_relative_to(Path(r"D:\Morphology_Pipeline").resolve()))

    def test_zero_model_preflight_resolves_real_bootstrap_without_active_backend(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        source = root / "source"; source.mkdir()
        schema = root / "schema.csv"; schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        for number in range(4):
            Image.new("RGB", (64, 40), (number * 20, 40, 60)).save(source / f"fish_{number}.png")
        project = Project.create("zero", source, root, schema, source_types=["png"], source_layout="direct")
        for row in project.catalog_rows():
            image_id = row["image_id"]
            developed = project.cache_root / "developed" / f"{image_id}.png"
            Image.new("RGB", (64, 40), (20, 40, 60)).save(developed)
            transform = Transform(64, 40, 0.0, 32.0, 20.0, 0, 0, 64, 40)
            project.save_reviewed_crop(image_id, {"developed_full_relpath": f"cache/developed/{image_id}.png", "standardized_relpath": f"cache/standardized/{image_id}.png", "crop_bounds": [0, 0, 64, 40], "rotation_degrees": 0.0, "transform": transform.__dict__, "normalization_status": "PASS"})
            restore_standardized_frame(project, image_id)
            project.save_landmark(image_id, 1, 10, 10, "manual", provenance="manual")
            project.save_landmark(image_id, 2, 50, 30, "manual", provenance="manual")
            project.mark_checked(image_id)
        self.assertIsNone(project.active_model_readonly("landmark"))
        with patch("app.landmark_training_workflow.auto_performance_config", return_value={"batch_size": 1, "workers": 0, "device": "cpu"}):
            plan = prepare_landmark_training(project, seed=17)
        bootstrap = plan.training_settings["bootstrap"]
        self.assertEqual("rtmpose_v001", plan.model_id)
        self.assertIsNone(plan.parent_model_id)
        self.assertTrue(Path(bootstrap["config_path"]).is_file())
        self.assertTrue(Path(bootstrap["checkpoint_path"]).is_file())
        self.assertTrue(bootstrap["checksum"])


if __name__ == "__main__":
    unittest.main()
