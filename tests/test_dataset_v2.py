import unittest
from app.dataset_v2 import FINAL_STATES

class StrictDatasetTests(unittest.TestCase):
    def test_auto_points_are_not_final_training_states(self): self.assertNotIn("auto",FINAL_STATES)
    def test_missing_is_explicitly_allowed(self): self.assertIn("missing",FINAL_STATES)

if __name__ == "__main__": unittest.main()
