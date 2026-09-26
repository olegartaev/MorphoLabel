import os
import unittest
from unittest.mock import patch

from app.crop_editor import calculate_initial_crop_view
from app.gui_crop_debug import debug_enabled


class CropEditorInitialViewTests(unittest.TestCase):
 def test_near_edge_auto_crop_is_fitted_with_handle_margin(self):
  view = calculate_initial_crop_view((0, 0, 4000, 3000), .45, 1000, 650, .6)
  left, top, right, bottom = view["displayed_crop"]
  self.assertTrue(view["auto_fit"])
  self.assertLess(view["zoom"], .6)
  self.assertGreaterEqual(left, view["margin_x"] - .01)
  self.assertGreaterEqual(top - 35, view["margin_y"] - .01)  # rotation handle is visible
  self.assertLessEqual(right, 1000 - view["margin_x"] + .01)
  self.assertLessEqual(bottom, 650 - view["margin_y"] + .01)

 def test_small_crop_is_centered_without_changing_fit_coordinates(self):
  bounds = (3800, 50, 3980, 250)
  view = calculate_initial_crop_view(bounds, .45, 1000, 650, .6)
  self.assertFalse(view["auto_fit"])
  self.assertEqual(bounds, (3800, 50, 3980, 250))
  self.assertGreater(view["displayed_crop"][0], 100)

 def test_detailed_interaction_logging_is_opt_in(self):
  with patch.dict(os.environ, {}, clear=True):
   self.assertFalse(debug_enabled())
  with patch.dict(os.environ, {"SIMM_CROP_DEBUG": "1"}, clear=True):
   self.assertTrue(debug_enabled())

if __name__ == "__main__": unittest.main()
