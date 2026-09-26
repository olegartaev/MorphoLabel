import unittest
from pathlib import Path


class CoverageMatrixContractTests(unittest.TestCase):
    def test_matrix_names_current_critical_coverage(self):
        root = Path(__file__).parents[1]
        matrix = (root / "tests" / "TEST_MATRIX.md").read_text(encoding="utf-8")
        required = (
            "Project/storage", "Crop", "Landmark state", "Checked/Train ready",
            "Exclude/Restore", "Schema compatibility", "Dataset/model lineage",
            "AI prediction history", "QC", "Human repeatability",
            "Measurements/calibration", "Export", "Production UI",
            "Launcher/provenance",
        )
        for area in required:
            self.assertIn(area, matrix)
        self.assertIn("test_restored_regressions.py", matrix)
        self.assertTrue((root / "tests" / "test_restored_regressions.py").is_file())


if __name__ == "__main__":
    unittest.main()
