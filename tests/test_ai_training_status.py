import shutil
import tempfile
import unittest
from pathlib import Path

from app.ai_training_status import format_training_status, training_status
from app.project_storage import Project, schema_hash
from tests.current_fixtures import make_reviewed_crop


class AITrainingStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        source = self.temp / "source"
        source.mkdir()
        for name in ("manual.jpg", "reviewed_ai.jpg", "unreviewed_ai.jpg"):
            (source / name).write_bytes(name.encode())
        schema = self.temp / "schema.csv"
        schema.write_text("id,abbr,name\n1,A,Alpha\n2,B,Beta\n", encoding="utf-8")
        self.project = Project.create("p", source, self.temp, schema, source_layout="direct")
        self.rows = {row["original_name"]: row["image_id"] for row in self.project.catalog_rows()}
        for image_id in self.rows.values(): make_reviewed_crop(self.project, image_id, 80, 60)
        self.project.register_model("landmark_v1", "landmark", path="ai/models/v1", active=True)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _save(self, name, provenance, **extra):
        for landmark_id in (1, 2):
            self.project.save_landmark(self.rows[name], landmark_id, landmark_id * 10, landmark_id * 20, "auto" if provenance == "machine" else "manual", provenance, **extra)

    def test_status_counts_match_project_database(self):
        self._save("manual.jpg", "manual")
        self._save("reviewed_ai.jpg", "machine", model_id="landmark_v1", predicted_x=1, predicted_y=2, prediction_run_id="run1")
        self.project.mark_checked(self.rows["reviewed_ai.jpg"])
        self._save("unreviewed_ai.jpg", "machine", model_id="landmark_v1", predicted_x=1, predicted_y=2, prediction_run_id="run2")
        status = training_status(self.project)
        self.assertEqual(2, status["human_verified_landmark_images"])
        self.assertEqual(1, status["fully_manual_images"])
        self.assertEqual(1, status["ai_assisted_human_verified_images"])
        self.assertEqual(1, status["ai_predicted_not_reviewed_images"])
        self.assertEqual(2, status["training_eligible_landmark_images"])
        self.assertEqual("landmark_v1", status["active_landmark_model_id"])
        self.assertTrue(status["last_training_at"])
        self.assertEqual(schema_hash(self.project.schema_path), status["schema_sha256"])

    def test_status_format_is_compact_and_includes_control_set(self):
        status = training_status(self.project)
        text = format_training_status(status)
        self.assertIn("Control Set: 0 / 0", text)
        self.assertIn("Training-eligible landmark images", text)
        self.assertIn("AI predicted but not reviewed images", text)
        self.assertNotIn("Fully manual images", text)
        self.assertNotIn("AI-assisted but human-verified images", text)
    def test_status_is_read_only(self):
        self._save("manual.jpg", "manual")
        with self.project.transaction() as connection:
            before = tuple(connection.iterdump())
        training_status(self.project)
        with self.project.transaction() as connection:
            after = tuple(connection.iterdump())
        self.assertEqual(before, after)

    def test_ai_only_image_is_not_human_verified(self):
        self._save("unreviewed_ai.jpg", "machine", model_id="landmark_v1", predicted_x=1, predicted_y=2)
        status = training_status(self.project)
        self.assertEqual(0, status["human_verified_landmark_images"])
        self.assertEqual(1, status["ai_predicted_not_reviewed_images"])
        self.assertEqual(0, status["training_eligible_landmark_images"])

    def test_active_model_information_loads(self):
        status = training_status(self.project)
        self.assertEqual("landmark_v1", status["active_landmark_model_id"])
        self.assertTrue(status["last_training_at"])


if __name__ == "__main__":
    unittest.main()
