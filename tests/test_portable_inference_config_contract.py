import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import ai_runtime.rtmpose_runner as runner


class PortableInferenceConfigContractTests(unittest.TestCase):
    def test_runner_exposes_portable_config_operation(self):
        text=Path(runner.__file__).read_text(encoding="utf-8")
        self.assertIn("export_portable_inference_config",text)
        self.assertIn("export_inference_config",text)
        self.assertIn("test_dataloader",text)
        self.assertIn("backbone['init_cfg']=None",text)


if __name__=="__main__":
    unittest.main()
