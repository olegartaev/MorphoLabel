import unittest
from unittest.mock import patch

import app.process_utils as process_utils


class ProcessUtilsTests(unittest.TestCase):
    def test_non_windows_needs_no_special_process_flags(self):
        with patch.object(process_utils.sys, "platform", "linux"):
            self.assertEqual({}, process_utils.hidden_window_kwargs())

    def test_windows_requests_hidden_child_process(self):
        class StartupInfo:
            def __init__(self):
                self.dwFlags = 0
                self.wShowWindow = None

        with (
            patch.object(process_utils.sys, "platform", "win32"),
            patch.object(process_utils.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
            patch.object(process_utils.subprocess, "STARTUPINFO", StartupInfo, create=True),
            patch.object(process_utils.subprocess, "STARTF_USESHOWWINDOW", 1, create=True),
            patch.object(process_utils.subprocess, "SW_HIDE", 0, create=True),
        ):
            kwargs = process_utils.hidden_window_kwargs()
        self.assertEqual(0x08000000, kwargs["creationflags"])
        self.assertEqual(1, kwargs["startupinfo"].dwFlags)
        self.assertEqual(0, kwargs["startupinfo"].wShowWindow)


if __name__ == "__main__":
    unittest.main()
