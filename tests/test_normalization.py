import unittest
from PIL import Image, ImageDraw
from app.normalization import propose_crop

class NormalizationTests(unittest.TestCase):
    def test_contrast_crop_keeps_margin(self):
        image=Image.new("RGB",(200,100),(240,240,240)); ImageDraw.Draw(image).ellipse((50,25,150,75),fill=(30,30,30))
        left,top,right,bottom=propose_crop(image,margin_ratio=.02)
        self.assertLess(left,50); self.assertLess(top,25); self.assertGreater(right,150); self.assertGreater(bottom,75)
    def test_blank_image_falls_back_to_full_frame(self):
        self.assertEqual(propose_crop(Image.new("RGB",(20,10),(1,1,1))), (0,0,20,10))

if __name__ == "__main__": unittest.main()
