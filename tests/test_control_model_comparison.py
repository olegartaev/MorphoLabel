import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.ai import MockBackend
from app.landmark_qc import compare_control_models, evaluate_control_set
from app.project_storage import Project, schema_hash


class ControlModelComparisonTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"; source.mkdir()
        for number in range(2):
            (source / f"fish_{number}.jpg").write_bytes(b"source")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_layout="direct")
        self.ids = tuple(row["image_id"] for row in self.project.catalog_rows())
        for image_id in self.ids:
            path = self.project.cache_root / "standardized" / f"{image_id}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (100, 80)).save(path)
            self.project.save_landmark(image_id, 1, 10, 10, "present", provenance="manual")
            self.project.save_landmark(image_id, 2, 30, 30, "present", provenance="manual")
            self.project.mark_checked(image_id)
        self.project.set_ui_state("landmark_ai_workflow", {"control_image_ids": list(self.ids)})
        self.digest = schema_hash(self.project.schema_path)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_control_evaluation_does_not_alter_canonical_landmarks(self):
        before = {image_id: self.project.load_landmarks(image_id) for image_id in self.ids}
        backend = MockBackend(self.digest, model_id="candidate", coordinate_overrides={1: (10, 10), 2: (30, 30)})
        result = evaluate_control_set(self.project, "candidate", backend=backend)
        self.assertEqual(0.0, result["aggregate"]["median_error_px"])
        self.assertEqual(before, {image_id: self.project.load_landmarks(image_id) for image_id in self.ids})

    def test_rank_crash_retries_with_smaller_chunks(self):
        base=MockBackend(self.digest, model_id="candidate", coordinate_overrides={1:(10,10),2:(30,30)})
        class CrashOnce:
            model_id=base.model_id; schema_sha256=base.schema_sha256
            def __init__(self): self.calls=[]
            def predict_readonly_many(self, requests):
                self.calls.append(len(requests))
                if len(requests)==4: raise RuntimeError("RTMPose rank failed (return code 3221226505)")
                return tuple(base.predict(r) for r in requests)
        backend=CrashOnce(); ids=self.ids*2
        with patch("app.landmark_qc.auto_performance_config", return_value={"batch_size":4}), patch("app.landmark_ai_workflow.control_set_summary", return_value={"current_ids":self.ids*2}):
            result=evaluate_control_set(self.project,"candidate",backend=backend,image_ids=ids)
        self.assertEqual(backend.calls[:3],[4,2,2]); self.assertEqual(result["aggregate"]["n_images"],4)

    def test_rank_crash_at_single_image_reports_image_id(self):
        class Crash:
            model_id="candidate"; schema_sha256=self.digest
            def predict_readonly_many(self, requests): raise RuntimeError("RTMPose rank failed (return code 3221226505)")
        with patch("app.landmark_qc.auto_performance_config", return_value={"batch_size":1}):
            with self.assertRaisesRegex(RuntimeError, self.ids[0]): evaluate_control_set(self.project,"candidate",backend=Crash(),image_ids=(self.ids[0],))
    def test_known_better_predictions_are_classified_improved(self):
        previous = MockBackend(self.digest, model_id="previous", coordinate_overrides={1: (20, 20), 2: (40, 40)})
        new = MockBackend(self.digest, model_id="new", coordinate_overrides={1: (10, 10), 2: (30, 30)})
        comparison = compare_control_models(self.project, "previous", "new", backends={"previous": previous, "new": new})
        self.assertEqual("Improved", comparison["result"])


if __name__ == "__main__":
    unittest.main()