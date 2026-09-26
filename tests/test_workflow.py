import tempfile
import unittest
from pathlib import Path
from app.workflow import assert_no_split_leakage, correction_report, set_human_point

class WorkflowTests(unittest.TestCase):
    def test_split_leakage_rejected(self):
        with self.assertRaises(ValueError):
            assert_no_split_leakage({"train":["a"],"validation":["a"],"permanent_test":[]})
    def test_human_correction_retains_prediction(self):
        record = {"points":{"1":{"state":"auto","predicted_x":1,"predicted_y":2,"confidence":.4,"model_id":"v001"}}}
        set_human_point(record, 1, "SnT", 3, 4, corrected=True)
        point = record["points"]["1"]
        self.assertEqual(point["state"], "corrected")
        self.assertEqual((point["predicted_x"], point["final_y"]), (1, 4))
    def test_missing_is_not_coordinate(self):
        record = {"points":{}}
        set_human_point(record, 2, "NarP", None, None)
        self.assertEqual(record["points"]["2"]["state"], "missing")
        self.assertIsNone(record["points"]["2"]["x_standardized"])

if __name__ == "__main__": unittest.main()
