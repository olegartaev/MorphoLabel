import unittest

from autopilot.scripts.morpholabel_autopilot import MorphoLabelAutopilot, sha256_text


class AutopilotCoreTests(unittest.TestCase):
    def test_extract_task(self):
        text = "pre AUTOPILOT_TASK_BEGIN_T1\nTask body\nAUTOPILOT_TASK_END_T1 post"
        self.assertEqual(MorphoLabelAutopilot.extract_task(text, "T1"), "Task body")

    def test_extract_no_task(self):
        self.assertIsNone(MorphoLabelAutopilot.extract_task("NO_TASK_T2", "T2"))

    def test_sha256(self):
        self.assertEqual(
            sha256_text("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )


if __name__ == "__main__":
    unittest.main()
