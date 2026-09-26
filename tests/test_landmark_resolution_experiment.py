import unittest
from app.landmark_resolution_experiment import RESOLUTIONS,recommend_resolution
class ResolutionExperimentTests(unittest.TestCase):
 def rows(self,p90,p95):
  return [{'model_id':f'm{i}','input_size':size,'median_error_percent':1.,'p90_error_percent':a,'p95_error_percent':b} for i,(size,a,b) in enumerate(zip(RESOLUTIONS,p90,p95))]
 def test_negligible_gain_keeps_baseline(self):
  self.assertEqual((512,256),recommend_resolution(self.rows([10,9.6,9.4],[20,19.2,19.1]))['input_size'])
 def test_meaningful_gain_selects_larger(self):
  self.assertEqual((768,384),recommend_resolution(self.rows([10,9,8],[20,18,16]))['input_size'])
 def test_all_candidates_are_fixed(self):self.assertEqual(((512,256),(640,320),(768,384)),RESOLUTIONS)
if __name__=='__main__':unittest.main()