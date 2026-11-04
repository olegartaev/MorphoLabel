"""Biological, not geometric, score presentation contracts."""
import unittest
from app.xray_evaluation_summary import format_fraction,scientific_comparison_summary


class ScientificSummaryTests(unittest.TestCase):
    def test_exact_scientific_measurements(self):
        txt=scientific_comparison_summary({
            "all_traits_correct_specimens":3,"all_traits_evaluable_specimens":10,
            "exact_traits":32,"exact_traits_total":40,
            "repeated_count_mae":0.5})
        self.assertIn("3 of 10 (30.0%)",txt)
        self.assertIn("32 of 40 (80.0%)",txt)
        self.assertIn("0.50",txt)
        self.assertNotIn("F1",txt)
        self.assertNotIn("independent",txt)
    def test_no_evaluable_human_truth(self):
        txt=scientific_comparison_summary({})
        self.assertEqual(txt.count("not evaluated"),2)
        self.assertEqual(format_fraction(0,0),"not evaluated")

if __name__=="__main__":
    unittest.main()
