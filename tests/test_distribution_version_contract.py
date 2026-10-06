import json
import unittest
from pathlib import Path

from app.version import __version__
from tests.documentation_contract import assert_public_readme_contract

ROOT=Path(__file__).resolve().parents[1]


class DistributionVersionContractTests(unittest.TestCase):
    def test_public_metadata_uses_application_version(self):
        assert_public_readme_contract(self,(ROOT/"README.md").read_text(encoding="utf-8"))
        self.assertIn(f'version: "{__version__}"',(ROOT/"CITATION.cff").read_text(encoding="utf-8"))
        self.assertIn('date-released: "2026-10-06"',(ROOT/"CITATION.cff").read_text(encoding="utf-8"))
        installer=(ROOT/"packaging"/"windows"/"MorphoLabel.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "1.0.0-rc.1"',installer)
        component=json.loads((ROOT/"ai_runtime"/"windows-cu121-component.json").read_text(encoding="utf-8"))
        self.assertEqual(__version__,component["component_version"])

    def test_readme_presents_both_production_modules_and_no_beta_limitations(self):
        readme=(ROOT/"README.md").read_text(encoding="utf-8")
        assert_public_readme_contract(self,readme)
        self.assertNotIn("Development beta",readme)
        self.assertNotIn("Current beta limitations",readme)

    def test_windows_distribution_reads_source_version_and_checks_release_tag(self):
        workflow=(ROOT/".github"/"workflows"/"windows-release.yml").read_text(encoding="utf-8")
        self.assertIn("from app.version import __version__",workflow)
        self.assertIn("does not match application version",workflow)
        self.assertNotIn('0.5.0-beta.2-dev-$($env:GITHUB_SHA.Substring(0,7))',workflow)


    def test_windows_distribution_uses_direct_inno_compiler_path(self):
        workflow=(ROOT/".github"/"workflows"/"windows-release.yml").read_text(encoding="utf-8")
        self.assertIn("--scope machine --source winget",workflow)
        self.assertIn('Join-Path $env:ProgramFiles "Inno Setup 7\\ISCC.exe"',workflow)
        self.assertIn("Test-Path -LiteralPath $iscc -PathType Leaf",workflow)
        self.assertNotIn('-Filter ISCC.exe -Recurse',workflow)



if __name__=="__main__":
    unittest.main()
