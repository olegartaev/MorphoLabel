import unittest
import numpy as np
from app.fish_crop import interior_component
class FishCropTests(unittest.TestCase):
 def test_rejects_edge_and_keeps_internal_blob(self):
  m=np.zeros((20,30),bool);m[:,0]=True;m[5:14,10:20]=True;p=interior_component(m);self.assertEqual(len(p),90);self.assertEqual(tuple(p.min(0)),(5.,10.))
if __name__=="__main__":unittest.main()
