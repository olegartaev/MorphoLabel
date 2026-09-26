import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ai_hardware import HardwareProfile, machine_profile_path, persist_machine_profile
from app.ui import preferences


class UserStateMigrationTests(unittest.TestCase):
    def test_current_paths_use_morpholabel_localappdata(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}, clear=False):
            self.assertEqual(Path(root) / "MorphoLabel" / "ui_preferences.json", preferences.preference_path())
            self.assertEqual(Path(root) / "MorphoLabel" / "hardware_profile.json", machine_profile_path())

    def test_legacy_preference_is_read_but_new_write_uses_morpholabel(self):
        with tempfile.TemporaryDirectory() as root:
            local = Path(root) / "local"
            roaming = Path(root) / "roaming"
            project = Path(root) / "project"; project.mkdir()
            legacy = roaming / "SIMM" / "ui_preferences.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({"last_project": str(project)}), encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}, clear=False):
                self.assertEqual(project.resolve(), preferences.last_project())
                self.assertTrue(preferences.remember_project(project))
                current = local / "MorphoLabel" / "ui_preferences.json"
                self.assertTrue(current.is_file())
                self.assertEqual(str(project.resolve()), json.loads(current.read_text(encoding="utf-8"))["last_project"])
                self.assertTrue(legacy.is_file())

    def test_machine_profile_never_writes_legacy_simm_directory(self):
        profile=HardwareProfile("CPU",8,16,32*1024**3,None,None,None,False,None,"CPU")
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}, clear=False):
            persist_machine_profile(profile)
            self.assertTrue((Path(root)/"MorphoLabel"/"hardware_profile.json").is_file())
            self.assertFalse((Path(root)/"SIMM").exists())


if __name__ == "__main__":
    unittest.main()
