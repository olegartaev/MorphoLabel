import tempfile
import unittest
from pathlib import Path

from app.xray_project import _db_connection


class XRaySQLiteLifecycleTests(unittest.TestCase):
    def test_transaction_context_releases_database_file_handle(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"lifecycle.sqlite3"
            with _db_connection(db) as connection:
                connection.execute("CREATE TABLE sample(value INTEGER)")
                connection.execute("INSERT INTO sample(value) VALUES(1)")
            # This is the regression condition that fails on Windows when a
            # sqlite handle survives the context manager.
            db.unlink()
            self.assertFalse(db.exists())

    def test_xray_project_uses_explicit_closing_helper_for_all_connections(self):
        source=(Path(__file__).resolve().parents[1]/"app/xray_project.py").read_text(encoding="utf-8")
        self.assertNotIn("with sqlite3.connect(",source)
        self.assertEqual(1,source.count("sqlite3.connect("))
        self.assertIn("finally:\n        connection.close()",source)


if __name__=="__main__":
    unittest.main()
