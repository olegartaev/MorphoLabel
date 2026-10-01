import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.ui.photo_list_panel import PhotoListPanel
from app.ui.shell import ProductionShell
from app.ui.landmarks_section import LandmarksSection
from app.ui.crop_section import CropSection


class AttentionNavigationFastPathTests(unittest.TestCase):
 def test_photo_list_can_reveal_current_at_top_without_full_refresh(self):
  panel=object.__new__(PhotoListPanel)
  panel.context=SimpleNamespace(selected=5)
  panel.visible_indices=[3,5,7]
  panel.refresh=Mock()
  panel.canvas=SimpleNamespace(selection_set=Mock(),see=Mock())
  panel.sync_current(reveal=True,align_top=True,refresh_rows=False)
  panel.refresh.assert_not_called()
  panel.canvas.selection_set.assert_called_once_with(1)
  panel.canvas.see.assert_called_once_with(1,align_top=True)

 def test_attention_transition_within_landmarks_does_not_rebuild_workspace(self):
  selected=[]
  context=SimpleNamespace(
   project=object(),
   section="landmarks",
   select_image=lambda image_id:(selected.append(image_id) or True),
  )
  view=SimpleNamespace(refresh_attention_banner=Mock(),_inline_status=Mock())
  shell=SimpleNamespace(
   context=context,current_view=view,photo_panel=object(),
   _sync_photo_panel_current=Mock(),_selected_image=Mock(),render=Mock(),
   _update_status=Mock(),after_idle=lambda fn:fn(),
  )
  self.assertTrue(ProductionShell.open_landmark_attention(shell,{"image_id":"b","stage":"landmarks","reason":"Review"}))
  self.assertEqual(["b"],selected)
  shell.render.assert_not_called()
  shell._sync_photo_panel_current.assert_called_once_with(align_top=True,refresh_rows=False)
  shell._selected_image.assert_called_once_with(False)
  view.refresh_attention_banner.assert_called_once()

 def test_attention_stage_change_rebuilds_once_and_aligns_selected_row_top(self):
  context=SimpleNamespace(
   project=object(),section="crop",
   select_image=lambda _image_id:True,
  )
  shell=SimpleNamespace(
   context=context,current_view=object(),photo_panel=object(),
   _sync_photo_panel_current=Mock(),_selected_image=Mock(),render=Mock(),
   _update_status=Mock(),after_idle=lambda fn:fn(),
  )
  self.assertTrue(ProductionShell.open_landmark_attention(shell,{"image_id":"b","stage":"landmarks","reason":"Review"}))
  self.assertTrue(shell._align_selected_top_once)
  shell.render.assert_called_once()
  shell._selected_image.assert_not_called()

 def test_attention_verify_uses_delta_counter_update_not_global_invalidation(self):
  landmark_source=inspect.getsource(LandmarksSection.navigate_attention_queue)
  crop_source=inspect.getsource(CropSection.navigate_attention_queue)
  self.assertIn("update_landmark_counts(current)",landmark_source)
  self.assertIn("update_landmark_counts(current)",crop_source)
  self.assertNotIn("invalidate_counts()",landmark_source)
  self.assertNotIn("invalidate_counts()",crop_source)


if __name__=="__main__":
 unittest.main()
