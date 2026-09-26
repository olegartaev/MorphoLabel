"""Regression checks for the public, generic source distribution."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublicRepositoryHygieneTests(unittest.TestCase):
    def test_taxon_specific_defaults_are_not_shipped_from_repository_root(self):
        self.assertFalse((ROOT / "landmark_schema.csv").exists())
        self.assertFalse((ROOT / "profiles" / "Phoxinus_lateral_v1.json").exists())
        fixture = ROOT / "tests" / "fixtures" / "phoxinus"
        self.assertTrue((fixture / "landmark_schema.csv").is_file())
        self.assertTrue((fixture / "Phoxinus_lateral_v1.json").is_file())

    def test_legacy_export_has_no_taxon_specific_root_default(self):
        source = (ROOT / "app" / "export_v2.py").read_text(encoding="utf-8")
        self.assertNotIn('ROOT/"landmark_schema.csv"', source)
        self.assertIn("schema_path", source)

    def test_canonical_launcher_uses_current_product_identity(self):
        launcher = (ROOT / "RUN_CANONICAL.cmd").read_text(encoding="utf-8")
        self.assertIn("MORPHOLABEL_ROOT", launcher)
        self.assertNotIn("SIMM_ROOT", launcher)

    def test_obsolete_technical_notes_are_not_published_as_current_docs(self):
        self.assertFalse((ROOT / "docs" / "TECHNICAL_NOTES.md").exists())


if __name__ == "__main__":
    unittest.main()
