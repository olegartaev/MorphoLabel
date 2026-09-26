import ast
import unittest
from pathlib import Path




def _quality_formatter():
 source=Path("app/editor_ready_v15.py").read_text(encoding="utf-8")
 tree=ast.parse(source)
 node=next(item for item in tree.body if isinstance(item,ast.FunctionDef) and item.name=="format_landmark_quality_table")
 namespace={"_quality_rows":lambda profile: sorted((value for value in (profile or {}).get("per_landmark",{}).values() if value.get("p90_error_percent") is not None and value.get("median_error_percent") is not None),key=lambda value:(-value["p90_error_percent"],-value["median_error_percent"],value["landmark_id"]))}
 exec(compile(ast.Module(body=[node],type_ignores=[]),"editor_ready_v15.py","exec"),namespace)
 return namespace["format_landmark_quality_table"]


def _baseline_helpers():
 source=Path("app/human_baseline.py").read_text(encoding="utf-8")
 tree=ast.parse(source)
 names={"grade_ratio","build_comparison","comparison_for_model","landmark_model_rows"}
 nodes=[item for item in tree.body if isinstance(item,ast.FunctionDef) and item.name in names]
 namespace={}
 exec(compile(ast.Module(body=nodes,type_ignores=[]),"human_baseline.py","exec"),namespace)
 return namespace


format_landmark_quality_table=_quality_formatter()
landmark_model_rows=_baseline_helpers()["landmark_model_rows"]

HUMAN={"aggregate":{"median_error_percent":0.5,"p90_error_percent":1.0,"p95_error_percent":1.2},"per_landmark":{"1":{"landmark_id":1,"p90_error_percent":1.0},"2":{"landmark_id":2,"p90_error_percent":2.0}}}
REPORT={"run_id":"run","model_id":"old","image_ids":["one","two"],"human":HUMAN,"per_landmark":[{"landmark_id":1,"human_p90_error_percent":1.0,"model_p90_error_percent":1.2,"ratio":1.2,"status":"Very close to human"},{"landmark_id":2,"human_p90_error_percent":2.0,"model_p90_error_percent":3.0,"ratio":1.5,"status":"Close to human"}]}
PREVIOUS={"model_id":"old","control_image_ids":["one","two"],"aggregate":{"median_error_percent":0.6,"p90_error_percent":1.2,"p95_error_percent":1.4},"per_landmark":{"1":{"landmark_id":1,"p90_error_percent":1.2},"2":{"landmark_id":2,"p90_error_percent":3.0}}}
NEW={"model_id":"new","control_image_ids":["one","two"],"aggregate":{"median_error_percent":0.55,"p90_error_percent":1.1,"p95_error_percent":1.3},"per_landmark":{"1":{"landmark_id":1,"p90_error_percent":1.1},"2":{"landmark_id":2,"p90_error_percent":4.2}}}
PROFILE={"model_id":"old","weak_landmark_ids":[2],"per_landmark":{"1":{"landmark_id":1,"p90_error_percent":1.2,"median_error_percent":0.5},"2":{"landmark_id":2,"p90_error_percent":3.0,"median_error_percent":1.0}}}
SCHEMA=[{"id":1,"abbr":"SnT"},{"id":2,"abbr":"NarP"}]


class HumanBaselineReportingTests(unittest.TestCase):
 def test_rows_use_same_fixed_baseline_images_and_correct_ratios(self):
  rows=landmark_model_rows(REPORT,PREVIOUS,NEW)
  self.assertEqual([1,2],[row["landmark_id"] for row in rows])
  self.assertAlmostEqual(1.1,rows[0]["new_human_ratio"])
  self.assertAlmostEqual(2.1,rows[1]["new_human_ratio"])
  self.assertAlmostEqual(40.0,rows[1]["change_percent"])
  self.assertEqual("Clearly worse than human",rows[1]["status"])
 def test_landmark_quality_keeps_training_and_human_statuses(self):
  text=format_landmark_quality_table(PROFILE,SCHEMA,[2],REPORT,"old")
  self.assertIn("Training status | Human P90 | AI/Human | Human status",text.splitlines()[0])
  self.assertIn("Persistent weak",text)
  self.assertIn("Very close to human",text)
 def test_different_model_does_not_fake_a_cross_dataset_ratio(self):
  text=format_landmark_quality_table(PROFILE,SCHEMA,[2],REPORT,"new")
  self.assertIn("Unavailable (different model)",text)
 def test_no_baseline_keeps_legacy_quality_table_safe(self):
  text=format_landmark_quality_table(PROFILE,SCHEMA,[2])
  self.assertEqual("LM | Abbr | P90 | Median | Status",text.splitlines()[0])
  self.assertIn("Persistent weak",text)


if __name__ == "__main__":
 unittest.main()