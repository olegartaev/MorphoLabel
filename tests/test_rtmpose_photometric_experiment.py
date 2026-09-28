import json
import tempfile
import unittest
from pathlib import Path
from app.rtmpose_dataset import generate_smoke_config
class PhotometricExperimentConfigTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());self.manifest=self.root/'dataset.json';self.manifest.write_text(json.dumps({'format_version':1,'dataset_id':'d','schema_sha256':'h','schema_landmarks':[{'landmark_id':1,'abbr':'P'}],'images':[]}))
 def config(self,enabled,input_size=(512,256)):
  return generate_smoke_config(self.manifest,data_root=self.root,train_coco=self.root/'train.json',val_coco=self.root/'val.json',output_path=self.root/f'{enabled}.py',base_config=self.root/'base.py',base_checkpoint=self.root/'base.pth',photometric_augmentation=enabled,input_size=input_size).read_text()
 def test_opt_in_only_adds_conservative_generic_stage(self):
  text=self.config(True);compile(text,'enabled.py','exec');self.assertIn("mmdet.PhotoMetricDistortion",text);self.assertIn("brightness_delta=12",text);self.assertIn("contrast_range=(0.9, 1.1)",text);self.assertNotIn('RandomFlip',text);self.assertNotIn('CLAHE',text);self.assertNotIn("rtmpose_augmentations",text)
 def test_default_pipeline_is_unchanged(self):
  text=self.config(False);compile(text,'disabled.py','exec');self.assertNotIn('PhotoMetricDistortion',text);self.assertNotIn("rtmpose_augmentations",text);self.assertIn("custom_imports = None",text)
 def test_simcc_sigma_scales_with_proportional_input_resolution(self):
  for size,expected in (((512,256),5.66),((640,320),6.33),((768,384),6.93)):
   text=self.config(False,size); match=__import__('re').search(r"sigma=\(([^,]+),",text); self.assertIsNotNone(match); self.assertAlmostEqual(float(match.group(1)),expected,places=2)
if __name__=='__main__':unittest.main()
