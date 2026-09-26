import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.__main__ import main

class AISelfTestCliContractTests(unittest.TestCase):
    def test_ai_self_test_routes_to_diagnostic_with_cuda_requirement(self):
        with patch("app.self_test.run_ai_self_test", return_value={"status":"PASS","device":"cuda:0"}) as diagnostic:
            self.assertEqual(0, main(["--ai-self-test", "--require-cuda"]))
        diagnostic.assert_called_once()
        self.assertTrue(diagnostic.call_args.kwargs["require_cuda"])

    def test_ai_self_test_writes_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/"report.json"
            with patch("app.self_test.run_ai_self_test", return_value={"status":"PASS","cuda_available":True}):
                self.assertEqual(0, main(["--ai-self-test","--diagnostic-report",str(target)]))
            self.assertEqual("PASS",json.loads(target.read_text(encoding="utf-8"))["status"])

    def test_ai_self_test_writes_failure_report_before_reraising(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/"report.json"
            with patch("app.self_test.run_ai_self_test", side_effect=RuntimeError("synthetic failure")):
                with self.assertRaisesRegex(RuntimeError,"synthetic failure"):
                    main(["--ai-self-test","--diagnostic-report",str(target)])
            data=json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual("FAIL",data["status"])
            self.assertEqual("RuntimeError",data["error_type"])

    def test_require_cuda_without_ai_self_test_is_rejected(self):
        with self.assertRaises(SystemExit):
            main(["--require-cuda"])

    def test_report_without_ai_self_test_is_rejected(self):
        with self.assertRaises(SystemExit):
            main(["--diagnostic-report","report.json"])

if __name__ == "__main__":
    unittest.main()
