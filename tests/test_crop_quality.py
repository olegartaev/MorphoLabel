import unittest
from unittest.mock import patch
from app.crop_quality import assess_crop
class CropQualityTests(unittest.TestCase):
 def test_valid_crop_classified(self):self.assertEqual(assess_crop((10,10,90,70),100,80).level,'green')
 def test_border_flagged(self):self.assertEqual(assess_crop((0,10,90,70),100,80).level,'red')
 def test_extreme_size_flagged(self):self.assertEqual(assess_crop((45,35,47,37),100,80).level,'red')
 def test_invalid_is_red(self):self.assertEqual(assess_crop((1,1,float('nan'),3),100,80).level,'red')
 def test_accepted_reference_can_flag_aspect(self):
  with patch('app.crop_quality.latest_corrections',return_value=[{'x1':'0.1','y1':'0.1','x2':'0.8','y2':'0.5'}]):self.assertNotEqual(assess_crop((10,10,30,75),100,100).level,'green')
if __name__=='__main__':unittest.main()
