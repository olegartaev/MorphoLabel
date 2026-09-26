import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.landmark_ai_workflow import create_stage, refresh_stage
from app.landmark_dataset import create_dataset, dataset_manifest_path
from app.project_storage import Project, schema_hash
from app.landmark_frames import restore_standardized_frame
from app.transforms import Transform


class LandmarkAIStageLineageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"
        source.mkdir()
        for number in range(40):
            (source / f"fish_{number:02d}.jpg").write_bytes(b"source")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_layout="direct")
        self.controls = tuple(create_stage(self.project, "CONTROL_SET", 25)["control_image_ids"])
        for image_id in self.controls:
            self._verify(image_id)
        self.initial = tuple(create_stage(self.project, "INITIAL_TRAINING", 10)["initial_image_ids"])
        for image_id in self.initial:
            cache = self.project.cache_root / "standardized" / f"{image_id}.png"
            cache.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (32, 24)).save(cache)
            developed = self.project.cache_root / "developed" / f"{image_id}.png"
            Image.new("RGB", (32, 24)).save(developed)
            transform = Transform(32, 24, 0.0, 16.0, 12.0, 0, 0, 32, 24)
            self.project.save_reviewed_crop(image_id, {"developed_full_relpath": f"cache/developed/{image_id}.png", "standardized_relpath": f"cache/standardized/{image_id}.png", "crop_bounds": [0, 0, 32, 24], "rotation_degrees": 0.0, "transform": transform.__dict__, "normalization_status": "PASS"})
            restore_standardized_frame(self.project, image_id)
            self._verify(image_id)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _verify(self, image_id):
        self.project.save_landmark(image_id, 1, 10, 11, "present", provenance="manual")
        self.project.mark_checked(image_id)

    def test_completed_initial_stage_stays_active_for_old_imported_model(self):
        artifact = self.project.models_root / "imported"
        artifact.mkdir(parents=True)
        self.project.register_model(
            "imported", "landmark", path=artifact.relative_to(self.project.data_root).as_posix(),
            active=True, schema_digest=schema_hash(self.project.schema_path),
        )
        self.assertEqual("INITIAL_TRAINING", refresh_stage(self.project, create_missing=False)["stage"])

    def test_train_and_validation_initial_ids_advance_to_ready(self):
        create_dataset(self.project, dataset_id="initial", splits={"train": self.initial[:8], "validation": self.initial[8:]})
        manifest = dataset_manifest_path(self.project, "initial").relative_to(self.project.data_root).as_posix()
        self.project.register_model(
            "trained", "landmark", active=True, schema_digest=schema_hash(self.project.schema_path),
            dataset_id="initial", dataset_manifest_path=manifest,
        )
        self.assertEqual("READY_FOR_FULL_PREDICTION", refresh_stage(self.project, create_missing=False)["stage"])

class LandmarkAIReadyControlsTests(unittest.TestCase):
    def test_ready_stage_shows_new_improvement_and_hides_training(self):
        from app.editor_ready_v15 import ReadyEditorV15

        class Widget:
            def __init__(self): self.grid_calls = 0; self.removed = 0
            def grid(self, **_kwargs): self.grid_calls += 1
            def grid_remove(self): self.removed += 1
            def config(self, **_kwargs): pass
        class Context:
            def winfo_manager(self): return False
            def pack(self, **_kwargs): pass
            def pack_forget(self): pass

        editor = ReadyEditorV15.__new__(ReadyEditorV15)
        editor._landmark_workflow_active = False
        editor.landmark_workflow_context = Context()
        editor.landmark_train_button = Widget()
        editor.landmark_improvement_button = Widget()
        editor._landmark_ai_info = {"stage": "READY_FOR_FULL_PREDICTION", "verified": 10, "total": 10, "active_model_id": "rtmpose_v004"}
        editor._set_landmark_workflow_controls()
        self.assertEqual(1, editor.landmark_train_button.grid_calls)
        self.assertEqual(0, editor.landmark_train_button.removed)
        self.assertEqual(1, editor.landmark_improvement_button.grid_calls)
        source = (Path(__file__).parents[1] / "app" / "editor_ready_v15.py").read_text(encoding="utf-8")
        self.assertIn('text="New Improvement Batch"', source)

if __name__ == "__main__":
    unittest.main()
