import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class AISelfTestTrainingContractTests(unittest.TestCase):
    def test_training_smoke_uses_real_generated_config_and_managed_runner(self):
        text=(ROOT/"app"/"self_test.py").read_text(encoding="utf-8")
        self.assertIn("generate_smoke_config",text)
        self.assertIn('"max_epochs": 1' if False else "max_epochs=1",text)
        self.assertIn('"train"',text)
        self.assertIn('"checkpoint_sha256"',text)
        self.assertIn("photometric_augmentation=False",text)
        self.assertIn("timeout=600",text)


if __name__=="__main__":
    unittest.main()
