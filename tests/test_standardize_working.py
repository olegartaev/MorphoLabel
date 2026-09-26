import unittest
from PIL import Image,ImageDraw
from app.standardize_working import propose_normalization

class WorkingNormalizationTests(unittest.TestCase):
 def test_crop_is_tight(self):
  i=Image.new("RGB",(800,400),(245,245,245));ImageDraw.Draw(i).ellipse((200,150,620,250),fill=(30,30,30));a,c,r=propose_normalization(i);self.assertLess(c[0],200);self.assertGreater(c[2],620);self.assertLess(c[2]-c[0],800);self.assertEqual(r,"foreground_pca_proposal")
if __name__=="__main__":unittest.main()
