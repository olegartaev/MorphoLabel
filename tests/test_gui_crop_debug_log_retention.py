import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.gui_crop_debug import _append, _rotate_log


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

    def test_small_log_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"app.log";path.write_text("small\n",encoding="utf-8")
            before=path.read_bytes()
            self.assertFalse(_rotate_log(path,max_bytes=64,backup_bytes=48))
            self.assertEqual(before,path.read_bytes())
            self.assertFalse(path.with_name("app.log.1").exists())

    def test_unwritable_primary_log_falls_back_without_raising(self):
        primary=Path("primary")/"app.log"
        fallback=Path("fallback")/"app.log"
        calls=[]
        def write(path,line):
            calls.append((Path(path),line))
            return Path(path)==fallback
        with patch("app.gui_crop_debug._log_paths",return_value=(primary,)), \
             patch("app.gui_crop_debug._fallback_log_path",return_value=fallback), \
             patch("app.gui_crop_debug._append_to_path",side_effect=write):
            self.assertTrue(_append("hello\n"))
        self.assertEqual([primary,fallback],[item[0] for item in calls])

    def test_logging_failure_is_non_fatal_even_if_fallback_is_unwritable(self):
        primary=Path("primary")/"app.log"
        fallback=Path("fallback")/"app.log"
        with patch("app.gui_crop_debug._log_paths",return_value=(primary,)), \
             patch("app.gui_crop_debug._fallback_log_path",return_value=fallback), \
             patch("app.gui_crop_debug._append_to_path",return_value=False):
            self.assertFalse(_append("hello\n"))

    def test_one_writable_target_prevents_unnecessary_fallback(self):
        first=Path("one")/"app.log";second=Path("two")/"app.log";fallback=Path("fallback")/"app.log"
        calls=[]
        def write(path,line):
            calls.append(Path(path));return Path(path)==second
        with patch("app.gui_crop_debug._log_paths",return_value=(first,second)), \
             patch("app.gui_crop_debug._fallback_log_path",return_value=fallback), \
             patch("app.gui_crop_debug._append_to_path",side_effect=write):
            self.assertTrue(_append("hello\n"))
        self.assertEqual([first,second],calls)

if __name__=="__main__":
    unittest.main()
