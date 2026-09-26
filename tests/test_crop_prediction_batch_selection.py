import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.crop_auto import candidates
from app.crop_training_batch import create_crop_prediction_batch, select_crop_prediction_images
from app.project_storage import Project


class CropPredictionBatchSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.source = self.temp / "source"
        for locality in ("A", "B", "C", "D"):
            for number in range(5):
                folder = self.source / locality
                folder.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (32, 20), (number, 4, 2)).save(folder / f"fish_{number}.jpg")
        schema = self.temp / "schema.csv"
        schema.write_text("id,abbr,name\n1,A,Alpha\n", encoding="utf-8")
        self.project = Project.create("p", self.source, self.temp, schema, source_layout="direct")
        self.rows = self.project.catalog_rows()
        self.ids = [row["image_id"] for row in self.rows]
        for row in self.rows:
            Image.new("RGB", (32, 20), (1, 2, 3)).save(self.project.cache_root / "developed" / f"{row['image_id']}.png")

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    @staticmethod
    def _ids(rows):
        return tuple(row["image_id"] for row in rows)

    def test_seeded_round_robin_is_reproducible_and_diverse(self):
        first = select_crop_prediction_images(self.project, 8, 741)
        again = select_crop_prediction_images(self.project, 8, 741)
        changed = select_crop_prediction_images(self.project, 8, 742)
        self.assertEqual(self._ids(first), self._ids(again))
        self.assertNotEqual(self._ids(first), self._ids(changed))
        self.assertEqual(4, len({row["locality"] for row in first[:4]}))
        eligible, _ = candidates(self.project)
        self.assertNotEqual(self._ids(first), tuple(eligible[:8]))

    def test_finite_selection_persists_seed_and_excludes_crop_holdout_and_crops(self):
        cropped = self.ids[0]
        self.project.save_crop(cropped, {"crop_bounds": [1, 1, 20, 18]}, provenance="manual")
        holdout_id, holdout_ids = self.project.create_crop_holdout(1, seed=9)
        self.assertTrue(holdout_id)
        data, path = create_crop_prediction_batch(self.project, 8, seed=741)
        self.assertTrue(path.is_file())
        stored = json.loads(path.read_text(encoding="utf-8"))
        selected = tuple(item["image_id"] for item in stored["selected_images"])
        self.assertEqual(741, stored["seed"])
        self.assertEqual(selected, tuple(item["image_id"] for item in data["selected_images"]))
        self.assertNotIn(cropped, selected)
        self.assertTrue(set(selected).isdisjoint(holdout_ids))

    def test_apply_remaining_keeps_every_currently_eligible_image(self):
        self.project.save_crop(self.ids[0], {"crop_bounds": [1, 1, 20, 18]}, provenance="manual")
        self.project.create_crop_holdout(1, seed=7)
        all_eligible, _ = candidates(self.project)
        self.assertEqual(tuple(all_eligible), self.project.crop_auto_candidates()[0])
        self.assertGreater(len(all_eligible), 1)

    def test_reviewed_ai_prediction_is_one_canonical_training_row(self):
        image_id = self.ids[3]
        crop = {"crop_bounds": [1, 1, 20, 18], "developed_full_relpath": f"cache/developed/{image_id}.png"}
        self.project.save_crop(image_id, crop, provenance="automatic", model_id="crop-v1")
        self.project.record_ai_crop_prediction(image_id, crop, "crop-v1")
        self.project.save_reviewed_crop(image_id, crop)
        training = [row["image_id"] for row in self.project.crop_training_rows()]
        self.assertEqual([image_id], training)
        self.assertEqual((image_id,), self.project.crop_training_eligible_ids())


if __name__ == "__main__":
    unittest.main()