import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.ai_hardware import detect_hardware
from app.ai_runtime_resolver import resolve_ai_runtime
from app.rtmpose_backend import RTMPoseBackend, RTMPoseModelSpec


class AIRuntimeResolverTests(unittest.TestCase):
    def test_backend_and_hardware_share_explicit_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "python.exe"
            runner = root / "runner.py"
            runtime.write_text("", encoding="utf-8")
            runner.write_text("", encoding="utf-8")
            resolved, resolved_runner = resolve_ai_runtime(explicit=runtime, runner_path=runner)
            spec = RTMPoseModelSpec("m", "schema", root / "config.py", root / "model.pth")
            backend = RTMPoseBackend(spec, runtime_python=runtime, runner_path=runner)
            calls = []
            def command_runner(command, **kwargs):
                calls.append(command)
                return Mock(returncode=1, stdout="", stderr="")
            detect_hardware(command_runner=command_runner, runtime_python=runtime, runner_path=runner)
            self.assertEqual((Path(runtime), Path(runner)), (resolved, resolved_runner))
            self.assertEqual(Path(runtime), backend.runtime_python)
            self.assertTrue(any(str(runtime) == str(part) for command in calls for part in command))


if __name__ == "__main__":
    unittest.main()
