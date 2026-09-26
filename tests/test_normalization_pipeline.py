import unittest
from PIL import Image,ImageDraw
from app.normalization_pipeline import localize_fish

class PipelineTests(unittest.TestCase):
 def test_localization_prefers_internal_horizontal_object(self):
  im=Image.new("RGB",(1200,700),(220,220,220));d=ImageDraw.Draw(im);d.ellipse((300,280,900,400),fill=(20,40,50));d.rectangle((20,650,1180,670),fill=(5,5,5));box,mask,scale,qc=localize_fish(im);self.assertIsNotNone(box);self.assertLess(box[1],300*scale);self.assertLess(box[3],650*scale)
if __name__=="__main__":unittest.main()
