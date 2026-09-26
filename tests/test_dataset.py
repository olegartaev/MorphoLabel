import tempfile
import unittest
from pathlib import Path
from app.dataset import export_training_dataset

class DatasetTests(unittest.TestCase):
    def test_module_imports_without_training_stack(self):
        # The portable runtime does not need RTMPose/HRNet/ViTPose packages.
        self.assertTrue(callable(export_training_dataset))

if __name__ == "__main__": unittest.main()
