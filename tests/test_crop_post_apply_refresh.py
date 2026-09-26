import unittest
from pathlib import Path
class T(unittest.TestCase):
 def test_callback_is_named_async_refresh(self):
  self.assertIn('post_crop_apply_refresh',Path('app/editor_ready_v9.py').read_text())
 def test_watchdog_exists(self):
  self.assertIn('navigation_stall_detected',Path('app/editor_ready_v15.py').read_text())
