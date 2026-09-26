import unittest
from PIL import Image,ImageDraw
from app.standardize_fish import propose
class FishStandardizationTests(unittest.TestCase):
 def test_centered_fish_proposal_has_tight_crop(self):
  i=Image.new("RGB",(1000,600),(220,220,220));ImageDraw.Draw(i).ellipse((250,260,750,360),fill=(20,30,40));a,c,r=propose(i);self.assertLess(c[0],250);self.assertGreater(c[2],750);self.assertLess(c[2]-c[0],1000);self.assertEqual(r,"adaptive_interior_component_v1")
if __name__=="__main__":unittest.main()
