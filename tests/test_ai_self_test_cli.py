import unittest
from unittest.mock import patch

from app.__main__ import main


class AISelfTestCliContractTests(unittest.TestCase):
    def test_ai_self_test_routes_to_diagnostic_with_cuda_requirement(self):
        with patch("app.self_test.print_ai_self_test") as diagnostic:
            self.assertEqual(0, main(["--ai-self-test", "--require-cuda"]))
        diagnostic.assert_called_once()
        self.assertTrue(diagnostic.call_args.kwargs["require_cuda"])

    def test_require_cuda_without_ai_self_test_is_rejected(self):
        with self.assertRaises(SystemExit):
            main(["--require-cuda"])


if __name__ == "__main__":
    unittest.main()
