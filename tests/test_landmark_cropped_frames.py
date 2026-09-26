import hashlib
import shutil
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image

from app.landmark_dataset import create_dataset, v2_human_final_eligible_image_ids
from app.landmark_frames import crop_frame_record, restore_standardized_frame
from app.project_storage import Project
from app.transforms import Transform


class LandmarkCroppedFramesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"; source.mkdir()
        for number in range(3):
            Image.new("RGB", (80, 50), (number * 30, 40, 90)).save(source / f"fish_{number}.png")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_types=["png"], source_layout="direct")
        self.ids = [row["image_id"] for row in self.project.catalog_rows()]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _crop_and_check(self, image_id):
        source = self.project.image_path(image_id)
        developed = self.project.cache_root / "developed" / f"{image_id}.png"
        developed.parent.mkdir(parents=True, exist_ok=True)
        Image.open(source).convert("RGB").save(developed)
        transform = Transform(80, 50, 0.0, 40.0, 25.0, 5, 4, 60, 36)
        self.project.save_reviewed_crop(image_id, {
            "developed_full_relpath": f"cache/developed/{image_id}.png",
            "standardized_relpath": f"cache/standardized/{image_id}.png",
            "crop_bounds": [5, 4, 65, 40], "rotation_degrees": 0.0,
            "transform": transform.__dict__, "normalization_status": "PASS",
        })
        restore_standardized_frame(self.project, image_id)
        self.project.save_landmark(image_id, 1, 10, 10, "manual", "manual")
        self.project.save_landmark(image_id, 2, 20, 20, "manual", "manual")
        self.project.mark_checked(image_id)

    def test_verified_cropped_frame_is_train_ready_and_missing_cache_is_restored(self):
        image_id = self.ids[0]; self._crop_and_check(image_id)
        standard = self.project.cache_root / "standardized" / f"{image_id}.png"
        before = hashlib.sha256(standard.read_bytes()).hexdigest()
        points_before = self.project.load_landmarks(image_id)
        self.assertIn(image_id, v2_human_final_eligible_image_ids(self.project))
        standard.unlink()
        restored, created = restore_standardized_frame(self.project, image_id)
        self.assertTrue(created)
        self.assertEqual(before, hashlib.sha256(restored.read_bytes()).hexdigest())
        self.assertEqual(points_before, self.project.load_landmarks(image_id))
        self.assertIn(image_id, v2_human_final_eligible_image_ids(self.project))

    def test_legacy_standardized_without_developed_does_not_redecode_raw(self):
        image_id = self.ids[0]
        transform = Transform(80, 50, 0.0, 40.0, 25.0, 5, 4, 60, 36)
        self.project.save_reviewed_crop(image_id, {
            "developed_full_relpath": f"cache/developed/{image_id}.png",
            "standardized_relpath": f"cache/standardized/{image_id}.png",
            "crop_bounds": [5, 4, 65, 40], "rotation_degrees": 0.0,
            "transform": transform.__dict__, "normalization_status": "PASS",
        })
        developed = self.project.cache_root / "developed" / f"{image_id}.png"
        developed.unlink(missing_ok=True)
        standard = self.project.cache_root / "standardized" / f"{image_id}.png"
        standard.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (60, 36), (12, 34, 56)).save(standard)

        with patch("app.landmark_frames.develop_full", side_effect=AssertionError("legacy cache must not re-decode RAW")):
            restored, rebuilt = restore_standardized_frame(self.project, image_id)
        self.assertEqual(standard, restored)
        self.assertFalse(rebuilt)
        self.assertTrue(standard.with_name(standard.name + ".frame.json").is_file())

    def test_legacy_standardized_newer_than_crop_is_adopted_without_rebuild(self):
        image_id = self.ids[0]
        transform = Transform(80, 50, 0.0, 40.0, 25.0, 5, 4, 60, 36)
        self.project.save_reviewed_crop(image_id, {
            "developed_full_relpath": f"cache/developed/{image_id}.png",
            "standardized_relpath": f"cache/standardized/{image_id}.png",
            "crop_bounds": [5, 4, 65, 40], "rotation_degrees": 0.0,
            "transform": transform.__dict__, "normalization_status": "PASS",
        })
        standard = self.project.cache_root / "standardized" / f"{image_id}.png"
        standard.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (60, 36), (12, 34, 56)).save(standard)
        manifest = standard.with_name(standard.name + ".frame.json")
        manifest.unlink(missing_ok=True)

        with patch("app.landmark_frames.atomic_save_png", side_effect=AssertionError("current legacy cache must not rebuild")):
            restored, rebuilt = restore_standardized_frame(self.project, image_id)
        self.assertEqual(standard, restored)
        self.assertFalse(rebuilt)
        self.assertTrue(manifest.is_file())

    def test_stale_standardized_cache_is_rebuilt_from_current_crop_geometry(self):
        image_id = self.ids[0]
        source = self.project.image_path(image_id)
        # Non-uniform pixels make a shifted stale crop detectable.
        gradient = Image.new("RGB", (80, 50))
        for y in range(50):
            for x in range(80):
                gradient.putpixel((x, y), (x, y, (x + y) % 256))
        gradient.save(source)
        developed = self.project.cache_root / "developed" / f"{image_id}.png"
        developed.parent.mkdir(parents=True, exist_ok=True)
        gradient.save(developed)

        transform = Transform(80, 50, 0.0, 40.0, 25.0, 5, 4, 60, 36)
        self.project.save_reviewed_crop(image_id, {
            "developed_full_relpath": f"cache/developed/{image_id}.png",
            "standardized_relpath": f"cache/standardized/{image_id}.png",
            "crop_bounds": [5, 4, 65, 40], "rotation_degrees": 0.0,
            "transform": transform.__dict__, "normalization_status": "PASS",
        })

        standard = self.project.cache_root / "standardized" / f"{image_id}.png"
        standard.parent.mkdir(parents=True, exist_ok=True)
        # Same output size, but deliberately wrong/old crop shifted right by 5 px.
        gradient.crop((10, 4, 70, 40)).save(standard)
        os.utime(standard, (1, 1))

        restored, rebuilt = restore_standardized_frame(self.project, image_id)
        self.assertTrue(rebuilt)
        with Image.open(restored) as image:
            self.assertEqual((5, 4, 9), image.getpixel((0, 0)))
            self.assertNotEqual((10, 4, 14), image.getpixel((0, 0)))
        restored2, rebuilt2 = restore_standardized_frame(self.project, image_id)
        self.assertEqual(restored, restored2)
        self.assertFalse(rebuilt2)

    def test_complete_human_landmarks_without_crop_are_not_train_ready(self):
        image_id = self.ids[1]
        self.project.save_landmark(image_id, 1, 10, 10, "manual", "manual")
        self.project.save_landmark(image_id, 2, 20, 20, "manual", "manual")
        self.project.mark_checked(image_id)
        before = self.project.load_landmarks(image_id)
        self.assertNotIn(image_id, v2_human_final_eligible_image_ids(self.project))
        self.assertEqual(before, self.project.load_landmarks(image_id))
        self.assertIsNone(crop_frame_record(self.project, image_id))

    def test_landmark_canvas_never_falls_back_to_developed_without_crop(self):
        from app.ui.landmark_canvas import LandmarkCanvasController
        image_id = self.ids[2]
        developed = self.project.cache_root / "developed" / f"{image_id}.png"
        developed.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (80, 50)).save(developed)
        row = self.project.catalog_row(image_id)
        with self.assertRaisesRegex(Exception, "Crop required before landmarking"):
            LandmarkCanvasController._load_prepared_image(object(), row, self.project)
    def test_dataset_rebuilds_missing_canonical_cache_and_crop_change_requires_review(self):
        first, second = self.ids[:2]
        self._crop_and_check(first); self._crop_and_check(second)
        standard = self.project.cache_root / "standardized" / f"{first}.png"; standard.unlink()
        manifest = create_dataset(self.project, dataset_id="cropped", splits={"train": [first], "validation": [second]}, eligibility_mode="v2_human_final")
        self.assertEqual({first, second}, {entry["image_id"] for entry in manifest["images"]})
        points = self.project.load_landmarks(first)
        crop = self.project.crop_record(first); changed = dict(crop)
        changed.update({"crop_bounds": [6, 4, 66, 40], "transform": Transform(80, 50, 0.0, 40.0, 25.0, 6, 4, 60, 36).__dict__, "normalization_status": "PASS"})
        self.project.save_reviewed_crop(first, changed)
        self.assertTrue(self.project.landmark_crop_review_required(first))
        self.assertNotIn(first, v2_human_final_eligible_image_ids(self.project))
        # A crop change without a provable preceding frame preserves the old
        # points in corrections but makes their active coordinates unresolved.
        current = self.project.load_landmarks(first)
        self.assertTrue(all(row["state"] == "unresolved" for row in current.values()))
        self.assertTrue(self.project.landmark_crop_review_required(first))


if __name__ == "__main__":
    unittest.main()
