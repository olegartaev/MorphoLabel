import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.ai import MockBackend
from app.landmark_ai_service import LandmarkAIService
from app.landmark_qc import evaluate_model, save_qc_report
from app.prospective_qc import evaluate_prospective_batch
from app.project_runtime import record, scoped_project, save
from app.project_storage import Project, schema_hash
from app.workflow import set_human_point


class ProspectiveQCTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        source = self.temp / "source"
        source.mkdir()
        for name in ("a.jpg", "b.jpg"):
            Image.new("RGB", (100, 80)).save(source / name)
        schema = self.temp / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n", encoding="utf-8")
        self.project = Project.create("p", source, self.temp, schema, source_layout="direct")
        self.rows = self.project.catalog_rows()
        self.ids = [row["image_id"] for row in self.rows]
        for image_id in self.ids:
            target = self.project.cache_root / "standardized" / f"{image_id}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (100, 80)).save(target)
        self.backend = MockBackend(schema_hash(self.project.schema_path), confidences={1: .2, 2: .8})
        self.service = LandmarkAIService(self.project, self.backend)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def _predict_and_correct(self, image_id, x, y):
        prediction = self.service.predict_one(image_id)
        with scoped_project(self.project):
            current = record(self.project, next(row for row in self.rows if row["image_id"] == image_id))
            set_human_point(current, 1, "A", x, y, corrected=True)
            save(self.project, current)
        self.project.mark_checked(image_id)
        return prediction.prediction_run_id

    def _batch(self, image_id, run_id):
        return {
            "batch_id": "batch-1", "model_id": "mock-landmark-v1",
            "selected_images": [{"image_id": image_id}],
            "prediction_runs": {image_id: run_id},
        }

    def test_evaluate_model_accepts_exact_image_and_run_filters(self):
        first = self._predict_and_correct(self.ids[0], 40, 50)
        self._predict_and_correct(self.ids[1], 41, 51)
        result = evaluate_model(self.project, "mock-landmark-v1", image_ids=[self.ids[0]], prediction_run_ids=[first])
        self.assertEqual(result["image_ids"], [self.ids[0]])
        self.assertEqual(result["prediction_run_ids"], [first])

    def test_prospective_report_uses_immutable_prediction_and_current_final(self):
        run_id = self._predict_and_correct(self.ids[0], 40, 50)
        original = json.loads((self.project.data_root / "ai" / "predictions" / run_id / "manifest.json").read_text(encoding="utf-8"))
        predicted = next(point for point in original["returned_predictions"] if point["landmark_id"] == 1)
        report = evaluate_prospective_batch(self.project, self._batch(self.ids[0], run_id))
        row = report["per_landmark"]["1"]
        self.assertEqual(report["aggregate"]["n_comparable_landmarks"], 2)
        self.assertAlmostEqual(row["median_dx"], 40 - predicted["x"])
        self.assertAlmostEqual(row["median_dy"], 50 - predicted["y"])
        self.assertEqual(report["human_final_snapshot"][0]["image_id"], self.ids[0])

    def test_saved_prospective_report_is_immutable_after_future_edit(self):
        run_id = self._predict_and_correct(self.ids[0], 40, 50)
        report = evaluate_prospective_batch(self.project, self._batch(self.ids[0], run_id))
        path = save_qc_report(self.project, report, "prospective")
        before = path.read_bytes()
        self.project.save_landmark(self.ids[0], 1, 45, 55, "corrected", provenance="corrected_by_human")
        self.assertEqual(path.read_bytes(), before)


    def test_changed_standardized_input_is_excluded_without_losing_history(self):
        run_id = self._predict_and_correct(self.ids[0], 40, 50)
        manifest_path = self.project.data_root / "ai" / "predictions" / run_id / "manifest.json"
        before = manifest_path.read_bytes()
        Image.new("RGB", (101, 80), color="white").save(self.project.cache_root / "standardized" / f"{self.ids[0]}.png")
        report = evaluate_prospective_batch(self.project, self._batch(self.ids[0], run_id))
        self.assertEqual(report["aggregate"]["n_images"], 0)
        self.assertEqual(report["input_changed_after_prediction"][0]["reason"], "standardized_png_sha256_changed")
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_changed_input_does_not_contaminate_aggregate_and_remains_v2_eligible(self):
        first = self._predict_and_correct(self.ids[0], 40, 50)
        second = self._predict_and_correct(self.ids[1], 41, 51)
        Image.new("RGB", (120, 80), color="white").save(self.project.cache_root / "standardized" / f"{self.ids[0]}.png")
        batch = {"batch_id":"b", "model_id":"mock-landmark-v1", "selected_images":[{"image_id":self.ids[0],"selection_type":"ACTIVE_SELECTION"},{"image_id":self.ids[1],"selection_type":"RANDOM_CONTROL"}], "prediction_runs":{self.ids[0]:first,self.ids[1]:second}}
        report = evaluate_prospective_batch(self.project,batch)
        self.assertEqual(report["aggregate"]["n_images"],1)
        self.assertEqual(report["image_ids"],[self.ids[1]])
        from app.landmark_dataset import v2_human_final_eligible_image_ids
        self.assertIn(self.ids[0],v2_human_final_eligible_image_ids(self.project))

    def test_subgroup_selection_types_can_be_evaluated_after_exclusion(self):
        first = self._predict_and_correct(self.ids[0], 40, 50)
        second = self._predict_and_correct(self.ids[1], 41, 51)
        Image.new("RGB", (120, 80)).save(self.project.cache_root / "standardized" / f"{self.ids[0]}.png")
        active = self._batch(self.ids[0], first); active["selected_images"][0]["selection_type"]="ACTIVE_SELECTION"
        control = self._batch(self.ids[1], second); control["selected_images"][0]["selection_type"]="RANDOM_CONTROL"
        self.assertEqual(evaluate_prospective_batch(self.project,active)["aggregate"]["n_images"],0)
        self.assertEqual(evaluate_prospective_batch(self.project,control)["aggregate"]["n_images"],1)
if __name__ == "__main__":
    unittest.main()
