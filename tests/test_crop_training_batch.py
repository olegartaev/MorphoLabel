import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.crop_editor_async_v2 import load_project_developed
from app.crop_training_batch import crop_editor_input_ready, create_crop_training_batch, prepare_crop_training_images, select_crop_training_images
from app.project_storage import Project


class CropTrainingBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.source = self.temp / "source"
        for locality in ("A", "B", "C", "D"):
            for index in range(3):
                folder = self.source / locality
                folder.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (12, 8), (index, 1, 2)).save(folder / f"fish_{index}.jpg")
        schema = self.temp / "schema.csv"
        schema.write_text("id,abbr,name\n1,A,Alpha\n", encoding="utf-8")
        self.project = Project.create("p", self.source, self.temp, schema, source_layout="direct")
        self.rows = self.project.catalog_rows()
        for row in self.rows:
            Image.new("RGB", (32, 20), (1, 2, 3)).save(
                self.project.cache_root / "developed" / f"{row['image_id']}.png"
            )

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_requested_count_and_seed_are_reproducible(self):
        first = select_crop_training_images(self.project, 6, 741)
        second = select_crop_training_images(self.project, 6, 741)
        self.assertEqual(6, len(first))
        self.assertEqual([row["image_id"] for row in first], [row["image_id"] for row in second])
        payload, path = create_crop_training_batch(self.project, 6, seed=741)
        self.assertTrue(path.is_file())
        self.assertEqual(741, payload["seed"])
        self.assertEqual(6, len(payload["selected_images"]))

    def test_non_editable_images_are_not_selected(self):
        missing = self.rows[0]["image_id"]
        (self.project.cache_root / "developed" / f"{missing}.png").unlink()
        with self.project.transaction() as connection:
            connection.execute("UPDATE images SET source_available=0 WHERE image_id=?", (missing,))
        selected = select_crop_training_images(self.project, 6, 88)
        self.assertNotIn(missing, {row["image_id"] for row in selected})

    def test_excluded_and_verified_crop_examples_are_avoided(self):
        excluded = self.rows[0]["image_id"]
        used = self.rows[1]["image_id"]
        self.project.exclude_image(excluded, "Bad image")
        self.project.save_crop(used, {"crop_bounds": [1, 2, 30, 40], "rotation_degrees": 0}, provenance="manual")
        with self.project.transaction() as connection: connection.execute("UPDATE crops SET human_verified=1 WHERE image_id=?", (used,))
        selected = select_crop_training_images(self.project, 8, 99)
        selected_ids = {row["image_id"] for row in selected}
        self.assertNotIn(excluded, selected_ids)
        self.assertNotIn(used, selected_ids)

    def test_requested_count_is_capped_by_editable_images(self):
        keep = {self.rows[0]["image_id"], self.rows[1]["image_id"]}
        for row in self.rows:
            if row["image_id"] not in keep:
                (self.project.cache_root / "developed" / f"{row['image_id']}.png").unlink()
                with self.project.transaction() as connection:
                    connection.execute("UPDATE images SET source_available=0 WHERE image_id=?", (row["image_id"],))
        payload, _ = create_crop_training_batch(self.project, 7, seed=123)
        self.assertEqual(2, len(payload["selected_images"]))

    def test_preparation_builds_caches_before_editor_load(self):
        image_id = self.rows[0]["image_id"]
        (self.project.cache_root / "developed" / f"{image_id}.png").unlink()
        calls = []

        def prepare(source):
            calls.append(source.name)
            Image.new("RGB", (32, 20), (4, 5, 6)).save(self.project.cache_root / "developed" / f"{image_id}.png")

        result = prepare_crop_training_images(self.project, [self.rows[0]], ensure_developed=prepare, prepare_proposal=lambda _source: None)
        self.assertEqual((image_id,), result["prepared_ids"])
        self.assertEqual(1, len(calls))
        full, _ = load_project_developed(self.project, image_id)
        self.assertEqual((32, 20), full.size)

    def test_preparation_skips_failure_and_continues(self):
        first, second = self.rows[:2]
        for row in (first, second):
            (self.project.cache_root / "developed" / f"{row['image_id']}.png").unlink()

        def prepare(source):
            if source.name == first["original_name"]:
                raise OSError("unreadable source")
            Image.new("RGB", (32, 20), (7, 8, 9)).save(self.project.cache_root / "developed" / f"{second['image_id']}.png")

        result = prepare_crop_training_images(self.project, [first, second], ensure_developed=prepare)
        self.assertEqual((second["image_id"],), result["prepared_ids"])
        self.assertEqual(first["image_id"], result["skipped"][0]["image_id"])
        self.assertTrue(crop_editor_input_ready(self.project, second["image_id"]))

    def test_preparation_triggers_existing_crop_proposal_and_persists_it(self):
        row = self.rows[0]
        calls = []

        def proposal(source):
            calls.append(source)
            result = {"crop_bounds": [2, 3, 28, 18], "rotation_degrees": 0, "normalization_status": "REVIEW"}
            self.project.save_crop(row["image_id"], result, provenance="automatic", model_id="crop_model_test")
            return result

        result = prepare_crop_training_images(self.project, [row], prepare_proposal=proposal)
        self.assertEqual((row["image_id"],), result["prepared_ids"])
        self.assertEqual([2, 3, 28, 18], result["proposals"][row["image_id"]])
        self.assertEqual([self.source / row["relative_path"]], calls)
        with self.project.transaction() as connection:
            saved = connection.execute("SELECT crop_json,provenance,model_id FROM crops WHERE image_id=?", (row["image_id"],)).fetchone()
        self.assertEqual("[2, 3, 28, 18]", saved["crop_json"])
        self.assertEqual("automatic", saved["provenance"])
        self.assertEqual("crop_model_test", saved["model_id"])

    def test_proposal_failure_keeps_developed_image_editable_for_safe_fallback(self):
        row = self.rows[0]
        result = prepare_crop_training_images(self.project, [row], prepare_proposal=lambda _source: (_ for _ in ()).throw(RuntimeError("model unavailable")))
        self.assertEqual((row["image_id"],), result["prepared_ids"])
        self.assertEqual(row["image_id"], result["proposal_failures"][0]["image_id"])
        full, _ = load_project_developed(self.project, row["image_id"])
        self.assertEqual((32, 20), full.size)

    def test_existing_crop_editor_load_path_still_works(self):
        image_id = self.rows[0]["image_id"]
        full, proxy = load_project_developed(self.project, image_id)
        self.assertEqual((32, 20), full.size)
        self.assertEqual("RGB", proxy.mode)


if __name__ == "__main__":
    unittest.main()
