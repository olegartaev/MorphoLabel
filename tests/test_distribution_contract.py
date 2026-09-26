import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.ai_runtime_resolver import installed_component_runtimes, resolve_ai_runtime
from app.runtime_paths import app_state_dir, resource_path
class DistributionContractTests(unittest.TestCase):
    def test_app_state_uses_morpholabel_localappdata(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}, clear=False):
            self.assertEqual(Path(root) / "MorphoLabel", app_state_dir())
    def test_installed_ai_component_precedes_developer_fallback(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}, clear=False):
            runtime = Path(root) / "MorphoLabel" / "components" / "ai" / "1.0.0" / "Scripts" / "python.exe"
            runtime.parent.mkdir(parents=True)
            runtime.write_bytes(b"")
            self.assertEqual([runtime], installed_component_runtimes())
            resolved, runner = resolve_ai_runtime()
            self.assertEqual(runtime, resolved)
            self.assertEqual(resource_path("ai_runtime", "rtmpose_runner.py"), runner)
    def test_legacy_simm_runtime_is_fallback_only(self):
        with tempfile.TemporaryDirectory() as root:
            current = Path(root) / "current.exe"; current.write_bytes(b"")
            legacy = Path(root) / "legacy.exe"; legacy.write_bytes(b"")
            with patch.dict(os.environ, {"MORPHOLABEL_AI_RUNTIME": str(current), "SIMM_AI_RUNTIME": str(legacy)}, clear=False):
                resolved, _ = resolve_ai_runtime()
            self.assertEqual(current, resolved)
if __name__ == "__main__":
    unittest.main()
