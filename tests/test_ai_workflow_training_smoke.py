import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class AIWorkflowTrainingSmokeTests(unittest.TestCase):
    def test_ai_component_workflow_exercises_managed_training(self):
        text=(ROOT/".github"/"workflows"/"ai-component.yml").read_text(encoding="utf-8")
        self.assertIn("app/self_test.py",text)
        self.assertIn("--ai-self-test --include-training",text)
        self.assertIn("AI_SELF_TEST.json",text)
        self.assertIn("MANAGED_AI_INFERENCE_TRAINING_PASS",text)
        self.assertIn("training_smoke.status",text)
        self.assertIn("training_smoke.checkpoint_sha256",text)


if __name__=="__main__":
    unittest.main()
