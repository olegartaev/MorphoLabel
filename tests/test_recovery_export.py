import tempfile
import unittest
from pathlib import Path
from app.recovery import snapshot, restore_latest
from app.transforms import Transform

class RecoveryTests(unittest.TestCase):
    def test_transform_retains_original_coordinate_precision(self):
        transform=Transform(100,80,0,50,40,10,5,80,70)
        self.assertEqual(transform.standardized_to_original(1.25,2.5),(11.25,7.5))
    def test_history_module_is_available(self):
        self.assertTrue(callable(snapshot)); self.assertTrue(callable(restore_latest))

if __name__ == "__main__": unittest.main()
