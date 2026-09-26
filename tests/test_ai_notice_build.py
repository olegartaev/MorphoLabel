import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class AINoticeBuildTests(unittest.TestCase):
    def test_generator_uses_installed_distribution_metadata(self):
        text=(ROOT/"tools"/"build_ai_notices.py").read_text(encoding="utf-8")
        self.assertIn("metadata.distributions()",text)
        self.assertIn("License-Expression",text)
        self.assertIn("licenses/",text)
        self.assertIn("Python redistribution license was not found",text)


if __name__=="__main__":
    unittest.main()
