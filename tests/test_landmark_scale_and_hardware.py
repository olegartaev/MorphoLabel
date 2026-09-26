import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.ai import MockBackend
from app.ai_hardware import HardwareProfile
from app.landmark_qc import compare_control_models, evaluate_control_set
from app.landmark_training_workflow import prepare_landmark_training
from app.project_storage import Project, schema_hash
from app.rtmpose_dataset import generate_smoke_config


class LandmarkScaleAndHardwareTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.localappdata_patch = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)})
        self.localappdata_patch.start()

    def tearDown(self):
        self.localappdata_patch.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _project_with_control(self, size, points):
        source = self.root / f"source_{size}"; source.mkdir()
        (source / "fish.jpg").write_bytes(b"source")
        schema = self.root / f"schema_{size}.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        project = Project.create(f"p_{size}", source, self.root, schema, source_layout="direct")
        image_id = project.catalog_rows()[0]["image_id"]
        cache = project.cache_root / "standardized" / f"{image_id}.png"; cache.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (size, size)).save(cache)
        for landmark_id, (x, y) in points.items(): project.save_landmark(image_id, landmark_id, x, y, "present", provenance="manual")
        project.mark_checked(image_id); project.set_ui_state("landmark_ai_workflow", {"control_image_ids": [image_id]})
        return project

    def test_same_geometric_error_at_different_resolutions_has_same_span_percent(self):
        small = self._project_with_control(100, {1: (10, 10), 2: (90, 10)})
        large = self._project_with_control(200, {1: (20, 20), 2: (180, 20)})
        small_backend = MockBackend(schema_hash(small.schema_path), model_id="small", coordinate_overrides={1: (14, 10), 2: (86, 10)})
        large_backend = MockBackend(schema_hash(large.schema_path), model_id="large", coordinate_overrides={1: (28, 20), 2: (172, 20)})
        self.assertEqual(5.0, evaluate_control_set(small, "small", backend=small_backend)["aggregate"]["median_error_percent"])
        self.assertEqual(5.0, evaluate_control_set(large, "large", backend=large_backend)["aggregate"]["median_error_percent"])

    def test_model_comparison_uses_normalized_percent_not_raw_pixels(self):
        old = {"aggregate": {"median_error_px": 1, "p90_error_px": 1, "p95_error_px": 1, "median_error_percent": 10, "p90_error_percent": 10, "p95_error_percent": 10}}
        new = {"aggregate": {"median_error_px": 100, "p90_error_px": 100, "p95_error_px": 100, "median_error_percent": 5, "p90_error_percent": 5, "p95_error_percent": 5}}
        with patch("app.landmark_qc.evaluate_control_set", side_effect=(old, new)):
            comparison = compare_control_models(object(), "old", "new", backends={"old": object(), "new": object()})
        self.assertEqual("Improved", comparison["result"])

    def test_cuda_auto_settings_reach_generated_config(self):
        profile = HardwareProfile("CPU", 8, 8, 32 * 1024**3, "Mock CUDA", 12_288, "driver", True, "12.0", "CUDA")
        parent = {"model_id": "rtmpose_v001", "schema_sha256": "digest"}
        backend = SimpleNamespace(spec=SimpleNamespace(input_size=(512,256), config_path=self.root/"base.py", checkpoint_path=self.root/"base.pth", device="cuda:0"))
        project=SimpleNamespace(schema_path=Path("schema.csv"),schema=({"id":1},{"id":2}),data_root=self.root,active_model_readonly=lambda _kind:parent)
        probe_assets={"root":self.root,"manifest":self.root/"manifest.json","train_coco":self.root/"train.json","val_coco":self.root/"val.json"}
        with patch("app.landmark_training_workflow.active_backend", return_value=(parent, backend)), patch("app.landmark_training_workflow.v2_human_final_eligible_image_ids", return_value=("a", "b")), patch("app.landmark_training_workflow.deterministic_splits", return_value={"train": ("a",), "validation": ("b",), "test": ()}), patch("app.landmark_training_workflow.schema_hash", return_value="digest"), patch("app.landmark_training_workflow._next_model_id", return_value="rtmpose_v002"), patch("app.landmark_training_workflow.get_hardware_profile", return_value=profile), patch("app.landmark_training_workflow.restore_standardized_frame", return_value=(self.root/"frame.png",{})), patch("app.landmark_training_workflow.prepare_training_snapshot", return_value={"workers":1}), patch("app.landmark_training_workflow._prepare_training_probe_assets", return_value=probe_assets):
            plan = prepare_landmark_training(project, seed=1)
        self.assertEqual(("cuda:0", 8, 4, True), (plan.training_settings["device"], plan.training_settings["batch_size"], plan.training_settings["workers"], plan.training_settings["mixed_precision"]))
        manifest = self.root / "manifest.json"; manifest.write_text('{"format_version":1,"dataset_id":"d","schema_sha256":"test","schema_landmarks":[{"landmark_id":1,"abbr":"A"}],"images":[]}', encoding="utf-8")
        config = generate_smoke_config(manifest, data_root=self.root, train_coco=self.root / "train.json", val_coco=self.root / "val.json", output_path=self.root / "config.py", base_config=self.root / "base.py", base_checkpoint=self.root / "base.pth", batch_size=plan.training_settings["batch_size"], workers=plan.training_settings["workers"], mixed_precision=plan.training_settings["mixed_precision"], device=plan.training_settings["device"], pin_memory=plan.training_settings["pin_memory"], persistent_workers=plan.training_settings["persistent_workers"])
        text = config.read_text(encoding="utf-8")
        self.assertIn("num_workers=4", text); self.assertIn("persistent_workers=True", text); self.assertIn("pin_memory=True", text); self.assertIn("AmpOptimWrapper", text); self.assertIn("env_cfg = dict(cudnn_benchmark=True)", text)


if __name__ == "__main__":
    unittest.main()
