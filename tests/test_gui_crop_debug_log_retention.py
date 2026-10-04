import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.gui_crop_debug import _append, _rotate_log, dump_threads, log


class DiagnosticLogRetentionTests(unittest.TestCase):
    def test_oversized_log_is_compacted_to_bounded_tail(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"app.log"
            path.write_bytes((b"line-0123456789\n"*20))
            original=path.stat().st_size
            self.assertTrue(_rotate_log(path,max_bytes=64,backup_bytes=48))
            self.assertFalse(path.exists())
            backup=path.with_name("app.log.1")
            self.assertTrue(backup.is_file())
            self.assertLessEqual(backup.stat().st_size,48)
            self.assertLess(backup.stat().st_size,original)

    def test_permission_denied_log_sink_never_breaks_caller(self):
        denied=MagicMock()
        denied.parent=MagicMock()
        denied.open.side_effect=PermissionError(13,"denied")
        with patch("app.gui_crop_debug._log_paths",return_value=(denied,)), \
             patch("app.gui_crop_debug._rotate_log",return_value=False):
            self.assertFalse(_append("diagnostic\n"))
            log("TEST","permission","PASS")

    def test_thread_dump_permission_denied_is_non_fatal(self):
        denied=MagicMock()
        denied.parent=MagicMock()
        denied.open.side_effect=PermissionError(13,"denied")
        with patch("app.gui_crop_debug._log_paths",return_value=(denied,)), \
             patch("app.gui_crop_debug._rotate_log",return_value=False):
            dump_threads("TEST","permission")

    def test_unwritable_primary_sink_falls_through_to_secondary_sink(self):
        primary=MagicMock();secondary=MagicMock()
        primary.parent=MagicMock();secondary.parent=MagicMock()
        primary.open.side_effect=PermissionError(13,"denied")
        handle=MagicMock()
        secondary.open.return_value.__enter__.return_value=handle
        with patch("app.gui_crop_debug._log_paths",return_value=(primary,secondary)), \
             patch("app.gui_crop_debug._rotate_log",return_value=False):
            self.assertTrue(_append("secondary survives\n"))
        handle.write.assert_called_once_with("secondary survives\n")

    def test_small_log_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"app.log";path.write_text("small\n",encoding="utf-8")
            before=path.read_bytes()
            self.assertFalse(_rotate_log(path,max_bytes=64,backup_bytes=48))
            self.assertEqual(before,path.read_bytes())
            self.assertFalse(path.with_name("app.log.1").exists())


if __name__=="__main__":
    unittest.main()
