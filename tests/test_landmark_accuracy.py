import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.human_baseline import _evaluate_pair, evaluate_model_against_repeatability


class LandmarkAccuracyTests(unittest.TestCase):
    def test_human_repeatability_has_gm_only_scope(self):
        project=SimpleNamespace(schema=[
            {"id":1,"abbr":"GM1","role":"BOTH"},
            {"id":2,"abbr":"GM2","role":"GM"},
            {"id":3,"abbr":"Tip","role":"CLASSICAL"},
        ])
        run={"image_ids":["image"]}
        first={
            1:{"state":"present","x":0.0,"y":0.0},
            2:{"state":"present","x":100.0,"y":0.0},
            3:{"state":"present","x":1000.0,"y":0.0},
        }
        second={
            1:{"state":"present","x":1.0,"y":0.0},
            2:{"state":"present","x":100.0,"y":0.0},
            3:{"state":"present","x":1300.0,"y":0.0},
        }
        with patch("app.human_baseline._repeat_points",side_effect=[first,second]):
            result=_evaluate_pair(project,run,("a",),("b",))
        self.assertEqual(3,result["aggregate"]["n_comparable_landmarks"])
        self.assertEqual(2,result["aggregate_by_scope"]["gm"]["n_comparable_landmarks"])
        self.assertAlmostEqual(1.0,result["per_landmark_by_scope"]["gm"]["1"]["p90_error_percent"],places=6)
        self.assertGreater(result["aggregate"]["p90_error_percent"],result["aggregate_by_scope"]["gm"]["p90_error_percent"])

    def test_symmetric_model_comparison_uses_both_blind_annotations(self):
        run={"format_version":2,"run_id":"r","image_ids":["i"]}
        expected={"ok":True}
        with (
            patch("app.human_baseline._run_by_id",return_value=({},run)),
            patch("app.human_baseline.pass_progress",return_value={"complete":True}),
            patch("app.human_baseline._evaluate_model_on_repeatability_passes",return_value=expected) as evaluate,
        ):
            result=evaluate_model_against_repeatability(object(),"r","m",backend="backend")
        self.assertIs(result,expected)
        self.assertEqual((1,2),evaluate.call_args.kwargs["reference_passes"])

    def test_accuracy_ui_explains_gm_filter_and_ratio_limit(self):
        from pathlib import Path
        source=(Path(__file__).parents[1]/"app"/"ui"/"model_accuracy.py").read_text(encoding="utf-8")
        self.assertIn("GM landmarks only",source)
        self.assertIn("ratio is context, not a formal accuracy score",source)
        self.assertIn("CLASSICAL-only landmarks are excluded",source)


if __name__=="__main__":
    unittest.main()
