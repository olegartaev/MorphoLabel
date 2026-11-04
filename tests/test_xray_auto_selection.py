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
        "specimen_outcomes": [{"specimen_id": f"spec-{i}", "evaluable": True, "correct": i < correct} for i in range(30)],
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

    def test_missing_training_membership_blocks_promotion(self):
        project = FakeProject()
        original = project.structure_model_membership
        project.structure_model_membership = lambda model_id: [x for x in original(model_id) if x["split"] != "train"]
        ids, reason = common_validation_specimens(project, project.models[0], project.models[1])
        self.assertFalse(ids)
        self.assertIn("history", reason)

    def test_paired_evidence_rejects_hidden_regression_and_changed_cohort(self):
        old, new = report(10), report(13)
        new["specimen_outcomes"][0]["correct"] = False
        new["specimen_outcomes"][13]["correct"] = True
        self.assertFalse(choose_better_model(old, new)[0])
        new = report(13)
        new["specimen_outcomes"][0]["specimen_id"] = "different"
        self.assertFalse(choose_better_model(old, new)[0])
        new = report(13)
        del new["specimen_outcomes"]
        self.assertFalse(choose_better_model(old, new)[0])

    def test_missing_continuous_prediction_is_incorrect_not_unevaluable(self):
        from unittest.mock import patch
        from app.xray_structure_ai import summarize_structure_ai_human_comparison
        scheme = {"structures": [], "traits": [{"id": "length", "method": "distance", "tolerance": .1}]}
        with patch("app.xray_structure_ai.calculate_trait_values", side_effect=[{"length": 1.0}, {"length": None}]):
            result = summarize_structure_ai_human_comparison(scheme, [{"specimen_id": "one"}])
        self.assertEqual(1, result["summary"]["all_traits_evaluable_specimens"])
        self.assertEqual(0, result["summary"]["all_traits_correct_specimens"])
        self.assertEqual(1, result["traits"][0]["evaluated"])
        self.assertEqual({"specimen_id": "one", "evaluable": True, "correct": False}, result["specimen_outcomes"][0])

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


    def test_auto_activation_only_after_paired_success(self):
        from unittest.mock import patch
        from app.xray_structure_ai import _auto_select_trained_structure_model
        project = FakeProject()
        project.scheme = {}
        with (
            patch("app.xray_structure_ai._scheme_matches_model", return_value=True),
            patch("app.xray_structure_ai.compare_structure_model_to_human",
                  side_effect=[report(10), report(13)]) as compare,
            patch.object(project, "activate_structure_model", create=True) as activate,
        ):
            outcome = _auto_select_trained_structure_model(project, project.models[0], "new")
        self.assertEqual("selected", outcome["decision"])
        self.assertEqual(2, compare.call_count)
        self.assertEqual("new", activate.call_args.args[0])

    def test_failed_comparison_preserves_active_model(self):
        from unittest.mock import patch
        from app.xray_structure_ai import _auto_select_trained_structure_model
        project = FakeProject()
        project.scheme = {}
        incomplete = report(13)
        incomplete["failures"] = [{"specimen_id": "spec-1", "reason": "error"}]
        with (
            patch("app.xray_structure_ai._scheme_matches_model", return_value=True),
            patch("app.xray_structure_ai.compare_structure_model_to_human",
                  side_effect=[report(10), incomplete]),
            patch.object(project, "activate_structure_model", create=True) as activate,
        ):
            outcome = _auto_select_trained_structure_model(project, project.models[0], "new")
        self.assertEqual("kept", outcome["decision"])
        activate.assert_not_called()

    def test_no_eligible_holdout_skips_inference(self):
        from unittest.mock import patch
        from app.xray_structure_ai import _auto_select_trained_structure_model
        project = FakeProject(overlapping_train=True)
        project.scheme = {}
        with (
            patch("app.xray_structure_ai._scheme_matches_model", return_value=True),
            patch("app.xray_structure_ai.compare_structure_model_to_human") as compare,
            patch.object(project, "activate_structure_model", create=True) as activate,
        ):
            outcome = _auto_select_trained_structure_model(project, project.models[0], "new")
        self.assertEqual("kept", outcome["decision"])
        compare.assert_not_called()
        activate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
