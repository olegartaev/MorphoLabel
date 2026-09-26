import unittest
from PIL import Image,ImageDraw
from app.standardize_v2 import propose_normalization

class StandardizeV2Tests(unittest.TestCase):
    def test_crop_is_tight_and_no_mirror_decision_exists(self):
        image=Image.new("RGB",(800,400),(245,245,245)); ImageDraw.Draw(image).ellipse((200,150,620,250),fill=(30,30,30))
        angle,crop,reason=propose_normalization(image)
        self.assertLess(crop[0],200); self.assertGreater(crop[2],620); self.assertLess(crop[2]-crop[0],800)
        self.assertEqual(reason,"foreground_pca_proposal")

if __name__ == "__main__": unittest.main()
