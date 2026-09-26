import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class WindowsBrandBuildTests(unittest.TestCase):
    def test_exe_and_installer_use_generated_morpholabel_icon(self):
        workflow=(ROOT/".github"/"workflows"/"windows-release.yml").read_text(encoding="utf-8")
        spec=(ROOT/"packaging"/"morpholabel.spec").read_text(encoding="utf-8")
        installer=(ROOT/"packaging"/"windows"/"MorphoLabel.iss").read_text(encoding="utf-8")
        self.assertIn("build_brand_assets.py build/brand",workflow)
        self.assertIn('build" / "brand" / "MorphoLabel.ico"',spec)
        self.assertIn("SetupIconFile=..\\..\\build\\brand\\MorphoLabel.ico",installer)
        self.assertIn("UninstallDisplayIcon={app}\\MorphoLabel.exe",installer)
if __name__=="__main__":
    unittest.main()
