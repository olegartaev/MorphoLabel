import unittest
from app.crop_model import CropModel
class CropModelTests(unittest.TestCase):
 def test_corner_edge_and_move_clamp(self):
  c=CropModel(100,80,20,20,70,60);c.set_edge("lt",5,7);self.assertEqual((c.left,c.top),(5,7));c.move(-100,-100);self.assertEqual((c.left,c.top),(0,0));self.assertGreater(c.right,c.left)
if __name__=="__main__":unittest.main()
