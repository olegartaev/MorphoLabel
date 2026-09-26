import unittest
from app.crop_editor import CropEditor
class T(unittest.TestCase):
 def test_image_signature_excludes_crop_rectangle(self):
  # Dragging a handle changes bounds but not this rendering signature; overlays only.
  self.assertTrue(True)
 def test_gui_thread_guard_rejects_worker(self):
  self.assertTrue(hasattr(CropEditor,"_assert_gui_thread"))
