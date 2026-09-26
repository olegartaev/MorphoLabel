import subprocess
import sys
import tempfile
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

    def test_brand_asset_script_runs_directly_from_repository_root(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/"brand"
            result=subprocess.run(
                [sys.executable,str(ROOT/"tools"/"build_brand_assets.py"),str(output)],
                cwd=ROOT,text=True,capture_output=True,check=False,
            )
            self.assertEqual(0,result.returncode,result.stderr)
            icon=output/"MorphoLabel.ico"
            self.assertTrue(icon.is_file())
            self.assertGreater(icon.stat().st_size,0)


if __name__=="__main__":
    unittest.main()
