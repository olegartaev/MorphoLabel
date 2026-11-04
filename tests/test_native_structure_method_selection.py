"""Focused schema-driven multi-method training calibration regression tests."""
import unittest

from app.native_structure_bootstrap import choose_family_detail_policy
from app.xray_schema import bundled_scheme


class NativeDetailStandardCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scheme=bundled_scheme("phoxinus_vertebral_counts")

    @staticmethod
    def points(ptery=2,vertebra=3):
        rows=[{"structure_id":"vertebra","x":.1+.1*i,"y":.5,"sort_order":i}
              for i in range(vertebra)]
        rows += [{"structure_id":"first_caudal","x":.3,"y":.5,"sort_order":0},
                 {"structure_id":"last_predorsal","x":.2,"y":.5,"sort_order":0}]
        rows += [{"structure_id":"preanal_pterygiophore","x":.4+.1*i,"y":.7,"sort_order":i}
                 for i in range(ptery)]
        return rows

    def make_cases(self,standard_best=False):
        cases=[]
        for i in range(24):
            native=self.points(ptery=3 if i<5 else 2)
            detail=self.points(ptery=2 if not standard_best else 3,vertebra=2)
            standard=self.points(ptery=2 if standard_best else (3 if i<5 else 2))
            cases.append({"specimen_id":f"fish-{i}","image_id":f"plate-{i//4}",
                          "human":self.points(),"visibility":{},"crop_size":(900,300),
                          "native":native,"detail":detail,"standard":standard})
        return cases

    def test_detail_used_only_for_independent_marker_family(self):
        chosen,evidence=choose_family_detail_policy(self.scheme,self.make_cases())
        self.assertIn("preanal_pterygiophore",chosen["detail"])
        self.assertNotIn("vertebra",chosen["detail"])
        self.assertNotIn("first_caudal",chosen["detail"])
        self.assertNotIn("last_predorsal",chosen["detail"])
        self.assertEqual(24,evidence["selected_all_correct"])
        self.assertEqual("development_calibration_not_independent",evidence["status"])

    def test_standard_can_win_without_training_third_network(self):
        chosen,evidence=choose_family_detail_policy(self.scheme,self.make_cases(True))
        self.assertIn("preanal_pterygiophore",chosen["standard"])
        self.assertFalse(set(chosen["standard"]) & set(chosen["detail"]))
        self.assertEqual(24,evidence["selected_all_correct"])

    def test_insufficient_examples_keeps_native_instead_of_unproven_selection(self):
        chosen,evidence=choose_family_detail_policy(self.scheme,self.make_cases()[:8])
        self.assertEqual({"standard":[],"detail":[]},chosen)
        self.assertEqual("insufficient_development_validation",evidence["status"])


if __name__=="__main__":
    unittest.main()
