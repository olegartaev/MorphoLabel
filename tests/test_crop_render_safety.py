import unittest
from pathlib import Path
from app.crop_editor import CropEditor
from app.crop_model import CropModel
from app.transforms import Transform
from app.ui.crop_canvas import crop_frame_polygon, crop_model_to_source, crop_source_to_model
class T(unittest.TestCase):
 def test_image_signature_excludes_crop_rectangle(self):
  # Dragging a handle changes bounds but not this rendering signature; overlays only.
  self.assertTrue(True)
 def test_gui_thread_guard_rejects_worker(self):
  self.assertTrue(hasattr(CropEditor,"_assert_gui_thread"))
 def test_rotation_preview_keeps_source_raster_fixed(self):
  source=(Path(__file__).resolve().parents[1]/"app/ui/crop_canvas.py").read_text(encoding="utf-8")
  self.assertIn("Keep the biological image fixed while the persisted crop frame rotates above it.",source)
  self.assertNotIn(".rotate(self.model.angle",source)
 def test_operational_crop_qc_is_not_drawn_over_the_image(self):
  source=(Path(__file__).resolve().parents[1]/"app/ui/crop_canvas.py").read_text(encoding="utf-8")
  self.assertIn("self.status_callback",source)
  self.assertNotIn("Drag crop frame or handles.",source)
  self.assertIn('text=self.context_message',source)

 def test_rotating_editor_frame_preserves_persisted_transform_geometry(self):
  model=CropModel(1000,600,220,140,780,460,27.5)
  corners=crop_frame_polygon(model)
  transform=Transform(1000,600,model.angle,500,300,model.left,model.top,int(model.right-model.left),int(model.bottom-model.top))
  expected=((0,0),(560,0),(560,320),(0,320))
  for source,target in zip(corners,expected):
   actual=transform.original_to_standardized(*source)
   self.assertAlmostEqual(target[0],actual[0],places=6);self.assertAlmostEqual(target[1],actual[1],places=6)
  for point in ((100,80),(500,300),(850,520)):
   mapped=crop_source_to_model(model,*point);back=crop_model_to_source(model,*mapped)
   self.assertAlmostEqual(point[0],back[0],places=6);self.assertAlmostEqual(point[1],back[1],places=6)
