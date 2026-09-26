import shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from app.normalization_pipeline import prepare_crop_result, paths
from app.paths import ROOT, WORK
from app.png_atomic import verify_png

class ActiveCropPreparePipelineTests(unittest.TestCase):
 def test_missing_cache_active_prediction_creates_valid_standardized_png(self):
  folder=Path(tempfile.mkdtemp(prefix="_crop_active_test_",dir=ROOT));source=folder/"image.png";Image.new("RGB",(200,100),(20,30,40)).save(source)
  try:
   with patch("app.normalization_pipeline.active_project",return_value=None), patch("app.project_runtime.active_project",return_value=None), patch("app.normalization_pipeline.crop_predict",return_value=(np.array([.1,.1,.9,.9]),"crop_model_v001")):
    result=prepare_crop_result(source,force=True,materialize_learned=True)
    developed=paths(source)[2];standard=paths(source)[4]
   self.assertTrue(developed.exists());self.assertTrue(standard.exists());self.assertTrue(verify_png(developed)[0]);self.assertTrue(verify_png(standard)[0]);self.assertEqual(result["crop_model_version"],"crop_model_v001")
   with Image.open(standard) as image:image.load();self.assertEqual(image.size,(160,80))
  finally:
   shutil.rmtree(folder,ignore_errors=True);shutil.rmtree(WORK/folder.name,ignore_errors=True)
