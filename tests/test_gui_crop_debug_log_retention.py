import tempfile
import unittest
from pathlib import Path

from app.gui_crop_debug import _rotate_log


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


if __name__=="__main__":
    unittest.main()
