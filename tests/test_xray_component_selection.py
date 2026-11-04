"""CPU-only regression checks for schema-defined, per-family X-ray model selection."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.xray_component_selection import (
    choose_routed_components, combine_marker_rows, structure_families, validated_routes,
)
from app.xray_auto_selection import choose_better_model
from app.xray_schema import bundled_scheme
from app.xray_structure_ai import predict_structures, summarize_structure_ai_human_comparison


class ComponentRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scheme = bundled_scheme("phoxinus_vertebral_counts")

    @staticmethod
    def sample_points(ptery=2, vertebra=3):
        rows = [
            {"structure_id": "vertebra", "x": .1 + .1*i, "y": .5, "sort_order": i}
            for i in range(vertebra)
        ]
        rows.extend([
            {"structure_id": "first_caudal", "x": .3, "y": .5, "sort_order": 0},
            {"structure_id": "last_predorsal", "x": .2, "y": .5, "sort_order": 0},
        ])
        rows.extend([
            {"structure_id": "preanal_pterygiophore", "x": .4 + .1*i, "y": .7, "sort_order": i}
            for i in range(ptery)
        ])
        return rows

    def test_reference_roles_stay_with_their_ordered_series(self):
        groups = [set(group) for group in structure_families(self.scheme)]
        self.assertIn({"vertebra", "first_caudal", "last_predorsal"}, groups)
        self.assertIn({"preanal_pterygiophore"}, groups)
        with self.assertRaisesRegex(ValueError, "same model"):
            validated_routes(
                self.scheme, "old",
                {"vertebra": "new", "first_caudal": "old"}, {"old", "new"},
            )

    def test_component_combiner_never_fabricates_points(self):
        scheme = self.scheme
        assigned = validated_routes(
            scheme, "old",
            {"preanal_pterygiophore": "new"}, {"old", "new"},
        )
        selected = combine_marker_rows(scheme, {
            "old": self.sample_points(ptery=4),
            "new": self.sample_points(ptery=2, vertebra=1),
        }, assigned)
        self.assertEqual(3, sum(x["structure_id"] == "vertebra" for x in selected))
        self.assertEqual(2, sum(x["structure_id"] == "preanal_pterygiophore" for x in selected))
        with self.assertRaises(ValueError):
            combine_marker_rows(scheme, {"old": []}, assigned)

    def test_automatic_search_selects_ptery_source_without_harming_vertebrae(self):
        cases = []
        predictions = {"old": {}, "new": {}}
        for i in range(24):
            sid = f"synthetic-{i}"
            truth = self.sample_points(ptery=2)
            old = self.sample_points(ptery=3 if i < 5 else 2)
            new = self.sample_points(ptery=2, vertebra=2)
            cases.append({"specimen_id": sid, "human": truth,
                          "visibility": {}, "crop_size": (900, 300)})
            predictions["old"][sid] = old
            predictions["new"][sid] = new
        selection = choose_routed_components(
            self.scheme, "old", "new", cases, predictions,
            summarize_structure_ai_human_comparison,
            check=choose_better_model,
        )
        self.assertTrue(selection["accepted"], selection["reason"])
        self.assertEqual("new", selection["routes"]["preanal_pterygiophore"])
        for name in ("vertebra", "first_caudal", "last_predorsal"):
            self.assertEqual("old", selection["routes"][name])
        self.assertEqual(24, selection["report"]["summary"]["all_traits_correct_specimens"])

    def test_no_evidence_keeps_previous_routes(self):
        cases = [{"specimen_id": "synthetic-0", "human": self.sample_points(),
                  "visibility": {}, "crop_size": (900, 300)}]
        predictions = {"old": {"synthetic-0": self.sample_points()},
                       "new": {"synthetic-0": self.sample_points()}}
        selected = choose_routed_components(
            self.scheme, "old", "new", cases, predictions,
            summarize_structure_ai_human_comparison,
            check=choose_better_model,
        )
        self.assertFalse(selected["accepted"])
        self.assertEqual({"old"}, set(selected["routes"].values()))

    def test_routed_predict_saves_one_combined_model_id(self):
        scheme = self.scheme
        class Project:
            def __init__(self):
                self.scheme = scheme
                self.saved = []
                self.model = {
                    "model_id": "combined", "metrics": {
                        "component_routes": {
                            "vertebra": "old", "first_caudal": "old",
                            "last_predorsal": "old", "preanal_pterygiophore": "new",
                        }
                    },
                }
            def active_structure_model(self):
                return self.model
            def structure_models(self):
                return [self.model, {"model_id": "old"}, {"model_id": "new"}]
            def structure_prediction_candidate_ids(self, *args):
                return ["fish"]
            def structure_specimens(self, *args):
                return [{"specimen_id": "fish"}]
            def seed_structure_predictions(self, specimen_id, points, model_id, **kwargs):
                self.saved.append((specimen_id, points, model_id))
                return {"protected": False}
        project = Project()
        prepared = {
            "old": {"fish": self.sample_points(ptery=4)},
            "new": {"fish": self.sample_points(ptery=2, vertebra=1)},
        }
        with (
            patch("app.xray_structure_ai._scheme_matches_model", return_value=True),
            patch("app.xray_structure_ai._prediction_image", return_value="image.png"),
            patch("app.xray_structure_ai.structure_performance_settings",
                  return_value={"inference": {"device": "cpu", "batch_size": 1}}),
            patch("app.xray_structure_ai._predict_prepared_sources", return_value=(prepared, [], 1))
                  as runner,
        ):
            outcome = predict_structures(project, ["fish"], allow_verified=True)
        self.assertEqual([], outcome["failures"])
        self.assertEqual(1, len(project.saved))
        self.assertEqual("combined", project.saved[0][2])
        self.assertEqual(2, sum(row["structure_id"] == "preanal_pterygiophore"
                                for row in project.saved[0][1]))
        self.assertEqual({"old", "new"}, set(runner.call_args.args[1]))


if __name__ == "__main__":
    unittest.main()
