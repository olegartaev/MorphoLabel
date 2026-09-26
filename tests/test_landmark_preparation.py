import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.landmark_dataset import create_dataset
from app.landmark_preparation import (
    prepare_inference_metadata,
    prepare_training_snapshot,
    standardized_metadata,
)
from app.ai_hardware import HardwareProfile
from app.project_storage import Project
from app.transforms import Transform


class LandmarkPreparationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"; source.mkdir()
        for number in range(2): Image.new("RGB", (40, 30), (number * 40, 1, 2)).save(source / f"fish{number}.jpg")
        schema = self.root / "schema.csv"; schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        self.project = Project.create("p", source, self.root / "project", schema, source_layout="direct")
        self.hardware = HardwareProfile("QA CPU", 2, 2, 8 * 1024**3, None, None, None, False, None, "CPU")
        self.ids = [row["image_id"] for row in self.project.catalog_rows()]
        for image_id in self.ids:
            developed = self.project.cache_root / "developed" / f"{image_id}.png"; developed.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", (40, 30), "white").save(developed)
            standard = self.project.cache_root / "standardized" / f"{image_id}.png"; standard.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", (40, 30), "white").save(standard)
            transform = Transform(40, 30, 0, 20, 15, 0, 0, 40, 30)
            self.project.save_crop(image_id, {"image_id": image_id, "developed_full_relpath": developed.relative_to(self.project.data_root).as_posix(), "standardized_relpath": standard.relative_to(self.project.data_root).as_posix(), "crop_bounds": [0, 0, 40, 30], "transform": transform.__dict__, "rotation_degrees": 0, "normalization_status": "final"}, provenance="manual")
            with self.project.transaction() as connection: connection.execute("UPDATE crops SET human_verified=1 WHERE image_id=?", (image_id,))
            for ident in (1, 2): self.project.save_landmark(image_id, ident, ident * 5, ident * 4, "manual", provenance="manual")
            self.project.mark_checked(image_id)

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)

    def test_unchanged_snapshot_reuses_hash_and_dataset_manifest_is_exact(self):
        first = prepare_training_snapshot(self.project, self.ids, hardware=self.hardware)
        second = prepare_training_snapshot(self.project, self.ids, hardware=self.hardware, reuse=first)
        self.assertEqual(first["entries"][self.ids[0]]["standardized_sha256"], second["entries"][self.ids[0]]["standardized_sha256"])
        manifest = create_dataset(self.project, dataset_id="prepared", splits={"train": self.ids}, eligibility_mode="v2_human_final", prepared_snapshot=second, hardware=self.hardware)
        entry = manifest["images"][0]; frame = self.project.data_root / entry["standardized_relpath"]
        self.assertEqual(hashlib.sha256(frame.read_bytes()).hexdigest(), entry["standardized_sha256"])

    def test_label_change_invalidates_only_changed_snapshot_entry(self):
        first = prepare_training_snapshot(self.project, self.ids, hardware=self.hardware)
        self.project.save_landmark(self.ids[0], 1, 17, 19, "corrected", provenance="corrected_by_human")
        self.project.mark_checked(self.ids[0])
        second = prepare_training_snapshot(self.project, self.ids, hardware=self.hardware, reuse=first)
        self.assertEqual(17, second["entries"][self.ids[0]]["labels"][0]["x"])
        self.assertEqual(first["entries"][self.ids[1]]["human_review_fingerprint"], second["entries"][self.ids[1]]["human_review_fingerprint"])

    def test_standardized_hash_cache_recomputes_after_signature_change(self):
        frame, first = standardized_metadata(self.project, self.ids[0])
        Image.new("RGB", (40, 30), "black").save(frame)
        _frame, second = standardized_metadata(self.project, self.ids[0])
        self.assertNotEqual(first["standardized_sha256"], second["standardized_sha256"])

    def test_parallel_inference_metadata_reuses_verified_hashes(self):
        first = prepare_inference_metadata(self.project, self.ids, hardware=self.hardware)
        second = prepare_inference_metadata(self.project, self.ids, hardware=self.hardware)
        self.assertEqual(self.ids, list(first))
        self.assertEqual(first[self.ids[0]]["standardized_sha256"], second[self.ids[0]]["standardized_sha256"])
        self.assertEqual((40, 30), (first[self.ids[0]]["standardized_width"], first[self.ids[0]]["standardized_height"]))

    def test_atomic_machine_prediction_preserves_human_points_and_values(self):
        image_id = self.ids[0]
        # Point 1 is deliberately made replaceable; point 2 remains a human
        # correction and must survive a complete machine-prediction write.
        self.project.delete_landmark(image_id, 1)
        original_human = dict(self.project.load_landmarks(image_id)[2])
        saved, skipped = self.project.save_machine_landmarks(
            image_id,
            [
                {"landmark_id": 1, "x": 12.25, "y": 8.5, "confidence": 0.875},
                {"landmark_id": 2, "x": 999.0, "y": 998.0, "confidence": 0.1},
            ],
            model_id="rtmpose_v001",
            prediction_run_id="qa-run",
        )
        rows = self.project.load_landmarks(image_id)
        self.assertEqual((1, 1), (saved, skipped))
        self.assertEqual((12.25, 8.5, 0.875, "machine"), (
            rows[1]["x_standardized"], rows[1]["y_standardized"], rows[1]["confidence"], rows[1]["provenance"],
        ))
        self.assertEqual(original_human["x_standardized"], rows[2]["x_standardized"])
        self.assertEqual(original_human["y_standardized"], rows[2]["y_standardized"])
        self.assertEqual("manual", rows[2]["provenance"])


if __name__ == "__main__":
    unittest.main()
