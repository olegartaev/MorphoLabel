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

    def test_packaged_xray_ai_includes_every_required_runner(self):
        spec=(ROOT/"packaging"/"morpholabel.spec").read_text(encoding="utf-8")
        for runner in (
            "xray_detector_runner.py",
            "xray_orientation_runner.py",
            "xray_structure_runner.py",
        ):
            self.assertIn(f'"{runner}"',spec)

    def test_uninstaller_removes_only_app_owned_install_and_state_directories(self):
        installer=(ROOT/"packaging"/"windows"/"MorphoLabel.iss").read_text(encoding="utf-8")
        self.assertIn("[UninstallDelete]",installer)
        self.assertIn('Type: filesandordirs; Name: "{localappdata}\\MorphoLabel"',installer)
        self.assertIn('Type: filesandordirs; Name: "{app}"',installer)
        self.assertNotIn("{userdocs}",installer)
        self.assertNotIn("{commondocs}",installer)
        self.assertIn('Type: files; Name: "{localappdata}\\SIMM\\performance_engine_tuning.json"',installer)
        self.assertIn('Type: files; Name: "{localappdata}\\SIMM\\performance_engine_tuning.json.lock"',installer)
        self.assertNotIn('Type: filesandordirs; Name: "{localappdata}\\SIMM"',installer)

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
