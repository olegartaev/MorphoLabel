import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import app.crop_training as ct
from app.editor_ready_v13 import ReadyEditorV13


class CropTrainingTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.old=(ct.DATA,ct.CSV,ct.MODELS,ct.ACTIVE,ct.require_relative);ct.require_relative=lambda p:str(p)
  ct.DATA=self.root/"data";ct.CSV=ct.DATA/"crop_corrections.csv";ct.MODELS=self.root/"models";ct.ACTIVE=ct.MODELS/"crop_model_active.json"
  self.image=self.root/"full.png";Image.new("RGB",(100,50),(50,60,70)).save(self.image)
 def tearDown(self):
  ct.DATA,ct.CSV,ct.MODELS,ct.ACTIVE,ct.require_relative=self.old;self.temp.cleanup()
 def test_no_record_without_actual_correction(self):
  self.assertFalse(ct.save_correction("i",self.image,self.image,100,50,(1,2,90,40),(1,2,90,40),"rule-based"));self.assertFalse(ct.CSV.exists())
 def test_saved_correction_is_normalized_and_append_only(self):
  self.assertTrue(ct.save_correction("i",self.image,self.image,100,50,(1,2,90,40),(10,5,80,45),"rule-based"));row=ct.latest_corrections()[0]
  self.assertEqual([float(row[k]) for k in ("x1","y1","x2","y2")],[.1,.1,.8,.9])
  ct.save_correction("i",self.image,self.image,100,50,(10,5,80,45),(12,5,80,45),"rule-based")
  self.assertEqual(len(ct.CSV.read_text().splitlines()),3);self.assertEqual(float(ct.latest_corrections()[0]["x1"]),.12)
 def test_version_is_immutable_and_worse_model_is_not_activated(self):
  rows=[{"image_id":str(i),"developed_full_relpath":"unused","x1":".1","y1":".1","x2":".8","y2":".9"} for i in range(5)]
  d=ct.MODELS/"crop_model_v001";d.mkdir(parents=True);np.savez_compressed(d/"model.npz",weights=np.zeros((3,4)));ct.ACTIVE.parent.mkdir(parents=True,exist_ok=True);ct.atomic_json_write(ct.ACTIVE,{"model_id":"crop_model_v001"})
  metrics=[{"validation_iou":.1,"boundary_mae_percent":[1,1,1,1]},{"validation_iou":.9,"boundary_mae_percent":[1,1,1,1]}]
  with patch.object(ct,"latest_corrections",return_value=rows),patch.object(ct,"_feature",return_value=np.array([.2,.3])),patch.object(ct,"_metrics",side_effect=metrics): result=ct.train()
  self.assertEqual(result["model_id"],"crop_model_v002");self.assertFalse(result["new_model_activated"]);self.assertEqual(ct.active_info()["model_id"],"crop_model_v001")
 def test_navigation_class_does_not_train(self):
  self.assertNotIn("train",ReadyEditorV13._load_selected_v12.__code__.co_names)

if __name__=="__main__":unittest.main()
