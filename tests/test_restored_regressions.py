"""Current-only regression coverage salvaged from the pre-cleanup suite.

These tests deliberately exercise Project/services directly.  They must not
import any removed legacy editor or launcher.
"""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.ai import MockBackend
from app.ai_batch import reviewed_count
from app.landmark_ai_service import LandmarkAIService
from app.landmark_dataset import create_dataset, dataset_manifest_path, eligible_image_ids, model_seen_image_ids
from app.landmark_qc import evaluate_model, save_qc_report
from app.project_storage import Project, landmark_model_schema_compatible, schema_hash
from app.transforms import Transform


class RestoredRegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="morpholabel_restored_regressions_"))
        source = self.root / "source"
        source.mkdir()
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            Image.new("RGB", (80, 60), "white").save(source / name)
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n3,C,Three,BOTH\n", encoding="utf-8")
        self.project = Project.create("regression", source, self.root, schema, source_layout="direct")
        self.rows = self.project.catalog_rows()
        self.ids = [row["image_id"] for row in self.rows]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _prepare_frame(self, image_id):
        target = self.project.cache_root / "standardized" / f"{image_id}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (80, 60), "white").save(target)
        transform = Transform(80, 60, 0.0, 40.0, 30.0, 0.0, 0.0, 80, 60)
        self.project.save_reviewed_crop(image_id, {
            "developed_full_relpath": f"cache/standardized/{image_id}.png",
            "standardized_relpath": f"cache/standardized/{image_id}.png",
            "crop_bounds": [0, 0, 80, 60],
            "rotation_degrees": 0.0,
            "transform": transform.__dict__,
            "normalization_status": "PASS",
        })

    def _manual(self, image_id, checked=True):
        self.project.save_landmark(image_id, 1, 10, 20, "manual", provenance="manual")
        self.project.save_landmark(image_id, 2, 30, 40, "manual", provenance="manual")
        self.project.save_landmark(image_id, 3, None, None, "missing", provenance="missing")
        if checked:
            self.project.mark_checked(image_id)

    def test_checked_semantics_keep_ai_unverified_and_preserve_prediction_history(self):
        image_id = self.ids[0]
        self._prepare_frame(image_id)
        result = LandmarkAIService(self.project, MockBackend(schema_hash(self.project.schema_path))).predict_one(image_id)
        batch = {"selected_images": [{"image_id": image_id}]}
        self.assertEqual(0, reviewed_count(self.project, batch))
        self.assertFalse(self.project.annotation_status(image_id)["verified"])
        self.project.mark_checked(image_id)
        self.assertTrue(self.project.annotation_status(image_id)["verified"])
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result.prediction_run_id, manifest["prediction_run_id"])
        self.project.clear_checked(image_id)
        self.assertEqual(result.prediction_run_id, self.project.load_landmarks(image_id)[1]["prediction_run_id"])

    def test_exclude_restore_preserves_landmarks_and_results_membership(self):
        image_id, other = self.ids[:2]
        self._manual(image_id)
        self._manual(other)
        before = self.project.load_landmarks(image_id)
        self.project.exclude_image(image_id, "Bent specimen")
        excluded = next(row for row in self.project.catalog_rows() if row["image_id"] == image_id)
        self.assertEqual("excluded", excluded["status_color"])
        self.assertEqual(before, self.project.load_landmarks(image_id))
        self.assertNotIn(image_id, [row["image_id"] for row in self.project.catalog_rows() if not row["excluded"]])
        self.project.restore_image(image_id)
        self.assertFalse(self.project.image_exclusion(image_id)["excluded"])
        self.assertEqual(before, self.project.load_landmarks(image_id))

    def test_schema_identity_uses_ordered_landmark_abbreviations(self):
        dataset = self.project.data_root / "ai" / "datasets" / "d"
        dataset.mkdir(parents=True)
        manifest = dataset / "manifest.json"
        digest = schema_hash(self.project.schema_path)
        manifest.write_text(json.dumps({
            "format_version": 1, "dataset_id": "d", "schema_sha256": digest,
            "schema_landmarks": [{"landmark_id": 1, "abbr": "A", "role": "BOTH"},
                                  {"landmark_id": 2, "abbr": "B", "role": "BOTH"},
                                  {"landmark_id": 3, "abbr": "C", "role": "BOTH"}],
            "images": [],
        }), encoding="utf-8")
        self.project.register_model("m", "landmark", active=True, schema_digest=digest,
                                    dataset_id="d", dataset_manifest_path="ai/datasets/d/manifest.json")
        self.project.schema_path.write_text("id,abbr,name,role\n1,A,Renamed,GM\n2,B,Two,GM\n3,C,Three,CLASSICAL\n", encoding="utf-8")
        reopened = Project.open(self.project.root)
        self.assertTrue(landmark_model_schema_compatible(reopened, reopened.active_model("landmark")))
        reopened.schema_path.write_text("id,abbr,name,role\n1,B,Two,BOTH\n2,A,Renamed,BOTH\n3,C,Three,BOTH\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identities/order"):
            Project.open(reopened.root).active_model("landmark")

    def test_dataset_snapshot_and_model_lineage_are_immutable_and_split_scoped(self):
        for image_id in self.ids:
            self._prepare_frame(image_id)
            self._manual(image_id)
        first = create_dataset(self.project, dataset_id="d1", splits={"train": [self.ids[0]], "validation": [self.ids[1]]})
        second = create_dataset(self.project, dataset_id="d2", splits={"train": [self.ids[2]]})
        self.project.register_model("m1", "landmark", schema_digest=schema_hash(self.project.schema_path), dataset_id="d1", dataset_manifest_path="ai/datasets/d1/manifest.json")
        self.project.register_model("m2", "landmark", schema_digest=schema_hash(self.project.schema_path), dataset_id="d2", parent_model_id="m1", dataset_manifest_path="ai/datasets/d2/manifest.json")
        self.assertEqual(frozenset((self.ids[0], self.ids[1], self.ids[2])), model_seen_image_ids(self.project, "m2"))
        manifest_path = dataset_manifest_path(self.project, "d1")
        before = manifest_path.read_bytes()
        self.project.save_landmark(self.ids[0], 1, 44, 45, "corrected", provenance="corrected_by_human")
        self.assertEqual(before, manifest_path.read_bytes())
        self.assertIn(self.ids[1], eligible_image_ids(self.project, include_permanent=True))
        self.assertIsNotNone(second)

    def test_prediction_qc_report_is_snapshot_and_not_rewritten_by_future_edits(self):
        image_id = self.ids[0]
        self._prepare_frame(image_id)
        service = LandmarkAIService(self.project, MockBackend(schema_hash(self.project.schema_path)))
        service.predict_one(image_id)
        self.project.mark_checked(image_id)
        qc = evaluate_model(self.project, "mock-landmark-v1")
        report = save_qc_report(self.project, qc, "restored-regression")
        before = report.read_bytes()
        self.project.save_landmark(image_id, 1, 50, 53, "corrected", provenance="corrected_by_human")
        self.assertEqual(before, report.read_bytes())
        self.assertGreaterEqual(qc["aggregate"]["n_comparable_landmarks"], 1)

    def test_export_and_calibration_remain_current_backend_contracts(self):
        from app.measurements import export_measurements
        image_id = self.ids[0]
        self._manual(image_id)
        self.project.set_locality_calibration(self.rows[0]["locality"] or self.rows[0]["sample_id"], image_id, 2, "mm", {})
        result = self.project.sync_results()
        self.assertTrue(result["specimens"].is_file())
        self.assertTrue(result["tps"].is_file())
        self.assertGreaterEqual(export_measurements(self.project)["rows"], 0)


if __name__ == "__main__":
    unittest.main()
