import queue
import unittest
from pathlib import Path
from unittest.mock import patch

from app.editor_ready_v13 import ReadyEditorV13


class NavigationPrepareTests(unittest.TestCase):
 def test_not_ready_selected_image_is_prepared_in_worker_then_loaded(self):
  editor = ReadyEditorV13.__new__(ReadyEditorV13)
  editor._pending = queue.Queue()
  source = Path("orig_photos/ob-altay_Katun_Nizh-Ujmon_RU_25/img_008662.nef")
  row = {"source_relpath": str(source), "sample_id": source.parent.name}
  bad = {"ready": False, "png_exists": True, "source_hash_match": False, "settings_hash_match": True,
         "standardized_exists": True, "reason": "source_sha256_mismatch", "png_path": "x", "standardized_path": "y", "png_integrity":True, "standardized_integrity":True}
  good = dict(bad, ready=True, source_hash_match=True, reason="ready")
  with patch("app.editor_ready_v13.navigation_cache_status", side_effect=[bad, good]), \
       patch("app.editor_ready_v13.normalize") as normalize, \
       patch("app.editor_ready_v13.ensure") as ensure:
   editor._load_selected_v12(1, row, source, 0)
  normalize.assert_called_once_with(source, force=True)
  ensure.assert_called_once_with(source)
  item = editor._pending.get_nowait()
  self.assertEqual(item[0:2], (1, "ok"))


if __name__ == "__main__":
 unittest.main()
