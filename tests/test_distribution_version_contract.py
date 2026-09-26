import unittest
from pathlib import Path

from app.version import __version__

ROOT=Path(__file__).resolve().parents[1]


class DistributionVersionContractTests(unittest.TestCase):
    def test_public_metadata_uses_application_version(self):
        self.assertIn(f'Development beta · {__version__}',(ROOT/"README.md").read_text(encoding="utf-8"))
        self.assertIn(f'version: "{__version__}"',(ROOT/"CITATION.cff").read_text(encoding="utf-8"))

    def test_windows_distribution_reads_source_version_and_checks_release_tag(self):
        workflow=(ROOT/".github"/"workflows"/"windows-release.yml").read_text(encoding="utf-8")
        self.assertIn("from app.version import __version__",workflow)
        self.assertIn("does not match application version",workflow)
        self.assertNotIn('0.5.0-beta.2-dev-$($env:GITHUB_SHA.Substring(0,7))',workflow)


if __name__=="__main__":
    unittest.main()
