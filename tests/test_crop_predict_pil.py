import tempfile, unittest
from pathlib import Path
import numpy as np
from PIL import Image
import app.crop_training as ct

class CropPredictPILTests(unittest.TestCase):
 def test_active_model_predict_accepts_pil_image(self):
  with tempfile.TemporaryDirectory() as temp:
   old=(ct.MODELS,ct.ACTIVE);ct.MODELS=Path(temp)/"models";ct.ACTIVE=ct.MODELS/"crop_model_active.json"
   try:
    directory=ct.MODELS/"crop_model_v001";directory.mkdir(parents=True);np.savez_compressed(directory/"model.npz",weights=np.zeros((769,4)));ct.atomic_json_write(ct.ACTIVE,{"model_id":"crop_model_v001"})
    prediction,version=ct.predict(Image.new("RGB",(80,40),(1,2,3)))
    self.assertEqual(version,"crop_model_v001");self.assertEqual(prediction.tolist(),[0.,0.,0.,0.])
   finally:ct.MODELS,ct.ACTIVE=old
