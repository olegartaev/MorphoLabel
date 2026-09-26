import json
import tempfile
import unittest
from pathlib import Path

from app.rtmpose_backend import _resolve_parent_checkpoint


class ParentModelCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.parent = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_best_engineering_validation_checkpoint_is_preferred(self):
        primary = self.parent / "best_engineering_validation.pth"
        primary.write_bytes(b"primary-weights")
        fallback = self.parent / "fallback.pth"; fallback.write_bytes(b"fallback-weights")
        (self.parent / "model.json").write_text(json.dumps({"result": {"checkpoint_path": str(fallback)}}), encoding="utf-8")
        self.assertEqual(primary, _resolve_parent_checkpoint(self.parent))

    def test_model_json_result_checkpoint_fallback_is_accepted(self):
        fallback = self.parent / "epoch_210.pth"; fallback.write_bytes(b"fallback-weights")
        (self.parent / "model.json").write_text(json.dumps({"result": {"checkpoint_path": str(fallback)}}), encoding="utf-8")
        self.assertEqual(fallback, _resolve_parent_checkpoint(self.parent))


if __name__ == "__main__":
    unittest.main()