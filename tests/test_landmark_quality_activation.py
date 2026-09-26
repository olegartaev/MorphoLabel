import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.landmark_qc import persist_control_landmark_quality_profile, stable_weak_landmark_profile, stored_control_landmark_quality_profile


def evaluation(model_id, weak_first=23):
    values = {}
    for landmark_id in range(1, 26):
        p90 = 10.0 if landmark_id == weak_first else 1.0
        values[str(landmark_id)] = {"landmark_id": landmark_id, "p90_error_percent": p90, "median_error_percent": p90 / 2}
    return {"model_id": model_id, "control_image_ids": ["c1"], "per_landmark": values}


class LandmarkQualityActivationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.project = type("Project", (), {"data_root": self.root})()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_computed_comparison_persists_without_inference_and_is_immediately_readable(self):
        result = evaluation("v1")
        with patch("app.landmark_qc.evaluate_control_set", side_effect=AssertionError("inference must not run")):
            profile = persist_control_landmark_quality_profile(self.project, result, activated=True)
        self.assertEqual("v1", profile["model_id"])
        self.assertEqual(profile, stored_control_landmark_quality_profile(self.project, "v1"))
        self.assertIn(23, profile["weak_landmark_ids"])

    def test_activated_model_is_recorded_once(self):
        result = evaluation("v1")
        persist_control_landmark_quality_profile(self.project, result, activated=True)
        persist_control_landmark_quality_profile(self.project, result, activated=True)
        history = json.loads((self.root / "ai" / "qc" / "control" / "activated_models.json").read_text(encoding="utf8"))
        self.assertEqual(["v1"], history["model_ids"])

    def test_two_consecutive_activated_profiles_produce_persistent_weak_landmark(self):
        persist_control_landmark_quality_profile(self.project, evaluation("v1", 23), activated=True)
        persist_control_landmark_quality_profile(self.project, evaluation("v2", 23), activated=True)
        persistent = stable_weak_landmark_profile(self.project, "v2")
        self.assertIsNotNone(persistent)
        self.assertIn(23, persistent["weak_landmark_ids"])


if __name__ == "__main__":
    unittest.main()