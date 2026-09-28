import unittest
from pathlib import Path
from unittest.mock import patch

from tools import source_launcher


class SourceLauncherTests(unittest.TestCase):
    def test_poisoned_host_falls_back_to_repo_local_environment(self):
        fallback=Path("fallback-python")
        with patch.object(source_launcher,"_core_available",return_value=False), \
             patch.object(source_launcher,"_ensure_local_venv",return_value=fallback) as ensure:
            self.assertEqual(fallback,source_launcher.resolve_source_python())
        ensure.assert_called_once_with()

    def test_healthy_host_does_not_touch_local_environment(self):
        host=Path(source_launcher.sys.executable)
        with patch.object(source_launcher,"_core_available",return_value=True), \
             patch.object(source_launcher,"_ensure_local_venv") as ensure:
            self.assertEqual(host,source_launcher.resolve_source_python())
        ensure.assert_not_called()

    def test_clean_environment_preserves_profile_paths_but_removes_python_overrides(self):
        env=source_launcher._clean_environment({
            "APPDATA":"X:/real-profile",
            "LOCALAPPDATA":"X:/local-profile",
            "PYTHONPATH":"bad",
            "PYTHONHOME":"bad",
        })
        self.assertEqual("X:/real-profile",env["APPDATA"])
        self.assertEqual("X:/local-profile",env["LOCALAPPDATA"])
        self.assertNotIn("PYTHONPATH",env)
        self.assertNotIn("PYTHONHOME",env)

    def test_runner_delegates_to_canonical_with_resolved_python(self):
        python=Path("repo-python")
        with patch.object(source_launcher,"resolve_source_python",return_value=python), \
             patch.object(source_launcher.subprocess,"call",return_value=0) as call:
            self.assertEqual(0,source_launcher.main(["provenance"]))
        command=call.call_args.args[0]
        self.assertEqual(str(python),command[0])
        self.assertIn(str(source_launcher.CANONICAL),command)
        self.assertEqual("provenance",command[-1])


if __name__=="__main__":
    unittest.main()
