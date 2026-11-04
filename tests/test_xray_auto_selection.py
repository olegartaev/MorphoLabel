"""Focused, CPU-only checks for conservative X-ray model selection."""
import unittest

from app.xray_auto_selection import (
    MIN_COMMON_SPECIMENS, choose_better_model, common_validation_specimens,
)


class FakeProject:
    def __init__(self, ancestry=False, overlapping_train=False):
        self.models = [
            {"model_id": "old", "schema_digest": "schema", "parent_model_id": "root" if ancestry else None},
            {"model_id": "new", "schema_digest": "schema", "parent_model_id": "old"},
        ]
        if ancestry:
            self.models.append({"model_id": "root", "schema_digest": "schema", "parent_model_id": None})
        self.overlapping_train = overlapping_train

    def structure_models(self):
        return self.models

    def structure_model_membership(self, model_id):
        if model_id == "root":
            return [{"specimen_id": "spec-0", "split": "train"}]
        rows = [{"specimen_id": f"spec-{i}", "split": "val"} for i in range(12)]
        rows += [{"specimen_id": "spec-99", "split": "train"}]
        if model_id == "new" and self.overlapping_train:
            rows.append({"specimen_id": "spec-0", "split": "train"})
        return rows

    def specimen(self, specimen_id):
        index = int(specimen_id.split("-")[1])
        return {"image_id": f"plate-{index // 4}"}

    def annotation_run(self, specimen_id, *args):
        return {"status": "verified"}


def report(correct, trait_correct=None, marker_f1=0.9, marker_count=0.0, marker_p95=0.01):
    trait_correct = correct if trait_correct is None else trait_correct
    return {
        "summary": {
            "all_traits_evaluable_specimens": 30,
            "all_traits_correct_specimens": correct,
        },
        "traits": [{"trait_id": "a", "evaluated": 30, "correct": trait_correct}],
        "structures": [{
            "structure_id": "vertebra", "n": 30, "f1": marker_f1,
            "count_mae": marker_count, "localization_p95_diag": marker_p95,
            "localization_median_diag": .004, "role_accuracy": 0.9,
        }],
        "failures": [],
    }


class XRayAutomaticSelectionTests(unittest.TestCase):
    def test_common_holdout_requires_verified_plates(self):
        project = FakeProject()
        ids, reason = common_validation_specimens(project, project.models[0], project.models[1])
        self.assertEqual(MIN_COMMON_SPECIMENS, len(ids))
        self.assertFalse(reason)

    def test_training_plate_overlap_blocks_promotion(self):
        project = FakeProject(overlapping_train=True)
        ids, reason = common_validation_specimens(project, project.models[0], project.models[1])
        self.assertFalse(ids)
        self.assertIn("Not enough", reason)

    def test_ancestral_training_plate_overlap_blocks_promotion(self):
        project = FakeProject(ancestry=True)
        ids, _ = common_validation_specimens(project, project.models[0], project.models[1])
        self.assertFalse(ids)

    def test_only_complete_improvement_without_regressions_is_promoted(self):
        self.assertTrue(choose_better_model(report(10), report(13))[0])
        self.assertFalse(choose_better_model(report(10), report(10))[0])
        self.assertFalse(choose_better_model(report(10), report(11))[0])
        self.assertFalse(choose_better_model(report(10), report(13, trait_correct=9))[0])
        self.assertFalse(choose_better_model(report(10), report(13, marker_count=.2))[0])
        self.assertFalse(choose_better_model(report(10), report(13, marker_p95=.03))[0])

    def test_missing_and_incomplete_evidence_keeps_old_model(self):
        old = report(10)
        new = report(13)
        new["failures"] = [{"specimen_id": "spec-1", "reason": "inference failed"}]
        self.assertFalse(choose_better_model(old, new)[0])
        new = report(13)
        new["traits"] = []
        self.assertFalse(choose_better_model(old, new)[0])
        new = report(13)
        new["summary"]["all_traits_evaluable_specimens"] = 5
        self.assertFalse(choose_better_model(old, new)[0])


if __name__ == "__main__":
    unittest.main()
