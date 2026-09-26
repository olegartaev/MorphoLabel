import unittest
from app.review_report import summarize_review

class ReviewReportTests(unittest.TestCase):
    def test_metrics_are_plain_language_and_deterministic(self):
        records=[{"points":{"1":{"point_code":"SnT","predicted_x":1,"predicted_y":2,"final_x":1,"final_y":2}}},{"points":{"1":{"point_code":"SnT","predicted_x":0,"predicted_y":0,"final_x":3,"final_y":4}}}]
        result=summarize_review(records)
        self.assertEqual(result["fish_accepted_zero_corrections"],1)
        self.assertEqual(result["median_correction_px"],2.5)
        self.assertEqual(result["maximum_correction_px"],5)

if __name__ == "__main__": unittest.main()
