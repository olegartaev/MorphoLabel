import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.editor_ready_v15 import parse_training_progress_line


def load_runner():
    path = Path(__file__).resolve().parents[1] / "ai_runtime" / "rtmpose_runner.py"
    spec = importlib.util.spec_from_file_location("rtmpose_runner_progress_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LandmarkTrainingProgressTests(unittest.TestCase):
    def test_streamed_training_log_grows_before_process_finishes(self):
        runner = load_runner()
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "training.log"
            result = {}
            command = [sys.executable, "-u", "-c", "import time; print('Epoch(train) [1][2/10]'); time.sleep(0.6)"]
            worker = threading.Thread(target=lambda: result.update(zip(("returncode", "tail"), runner.stream_training_process(command, log_path, cwd=temporary))))
            worker.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (not log_path.exists() or "Epoch(train)" not in log_path.read_text(encoding="utf-8")):
                time.sleep(0.02)
            self.assertTrue(log_path.exists())
            self.assertIn("Epoch(train) [1][2/10]", log_path.read_text(encoding="utf-8"))
            self.assertTrue(worker.is_alive(), "log output must be available before training exits")
            worker.join(3)
            self.assertEqual(0, result["returncode"])

    def test_gui_progress_parser_extracts_mmengine_epoch_and_batch(self):
        parsed = parse_training_progress_line("08/24 12:00:00 - mmengine - INFO - Epoch(train) [17][ 42/210]  lr: 1.0e-04")
        self.assertEqual({"epoch": 17, "batch": 42, "batches": 210}, parsed)


if __name__ == "__main__":
    unittest.main()