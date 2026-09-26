import tempfile,unittest
from pathlib import Path
import app.crop_training as ct
class T(unittest.TestCase):
 def test_candidate_is_not_active_until_explicit_activation(self):
  d=Path(tempfile.mkdtemp());old_models,old_active=ct.MODELS,ct.ACTIVE
  try:
   ct.MODELS=d/'models';ct.MODELS.mkdir();ct.ACTIVE=d/'active.json';(ct.MODELS/'crop_model_v001').mkdir();(ct.MODELS/'crop_model_v001'/'model_manifest.json').write_text('{"metrics":{"validation_iou":0.8}}');self.assertEqual(ct.activate('crop_model_v001'),'crop_model_v001');self.assertEqual(ct.current_label(),'crop_model_v001')
  finally:ct.MODELS,ct.ACTIVE=old_models,old_active
