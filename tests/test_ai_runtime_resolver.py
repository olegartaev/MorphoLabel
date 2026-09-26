import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.ai_hardware import detect_hardware
from app.ai_runtime_resolver import AI_RUNTIME_INFO_TIMEOUT, resolve_ai_runtime, validate_ai_runtime
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


    def test_runtime_validation_allows_bounded_cold_start_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "python.exe"
            runner = root / "runner.py"
            runtime.touch()
            runner.touch()
            completed = Mock(returncode=0, stdout='{"cuda_available": true}\n', stderr="")
            with patch("app.ai_runtime_resolver.subprocess.run", return_value=completed) as command:
                info = validate_ai_runtime(runtime, runner)
            self.assertTrue(info["cuda_available"])
            self.assertEqual(60, AI_RUNTIME_INFO_TIMEOUT)
            self.assertEqual(AI_RUNTIME_INFO_TIMEOUT, command.call_args.kwargs["timeout"])


if __name__ == "__main__":
    unittest.main()
