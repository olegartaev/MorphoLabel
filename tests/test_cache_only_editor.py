import queue
import unittest
from pathlib import Path
from unittest.mock import patch

from app.crop_editor_async_v2 import AsyncCropEditorV2
from app.editor_ready_v10 import ReadyEditorV10


class CacheOnlyEditorTests(unittest.TestCase):
 def test_annotation_entry_has_no_raw_decoder_dependency(self):
  # The interactive annotation path must be PNG-only; RAW development belongs
  # to the cache worker used by the crop editor.
  self.assertNotIn("decode(", ReadyEditorV10.open_image.__code__.co_names)

 def test_crop_loader_uses_png_worker_contract(self):
  editor = AsyncCropEditorV2.__new__(AsyncCropEditorV2)
  editor.source = Path("any.nef")
  editor.queue = queue.Queue()
  sentinel = ({"source_sha256": "x"}, object(), object())
  with patch("app.crop_editor_async_v2.load_png", return_value=sentinel) as loader:
   editor._load()
  kind, value = editor.queue.get_nowait()
  self.assertEqual(kind, "ok")
  self.assertIs(value, sentinel)
  loader.assert_called_once_with(editor.source)


if __name__ == "__main__":
 unittest.main()
