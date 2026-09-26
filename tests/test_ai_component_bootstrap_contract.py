import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.ai_component import AIComponentError, _validate_tree


class AIComponentBootstrapContractTests(unittest.TestCase):
    def _tree(self, root, *, url=True):
        root=Path(root)
        (root/"vendor"/"mmpose"/"tools").mkdir(parents=True)
        (root/"vendor"/"mmpose"/"tools"/"train.py").write_text("",encoding="utf-8")
        (root/"vendor"/"mmpose"/"configs").mkdir(parents=True)
        (root/"vendor"/"mmpose"/"configs"/"bootstrap.py").write_text("",encoding="utf-8")
        (root/"python.exe").write_bytes(b"python")
        digest=hashlib.sha256(b"weights").hexdigest()
        return {
            "python_relative_path":"python.exe",
            "bootstrap_config":"vendor/mmpose/configs/bootstrap.py",
            "bootstrap_checkpoint":"assets/bootstrap.pth",
            "bootstrap_checkpoint_sha256":digest,
            "bootstrap_checkpoint_url":"https://download.openmmlab.com/test/bootstrap.pth" if url else "",
            "mmpose_source":"vendor/mmpose",
        }

    def test_checkpoint_may_be_absent_when_trusted_upstream_and_sha_are_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            manifest=self._tree(td)
            runtime=_validate_tree(Path(td),manifest,run_runtime_check=False)
            self.assertEqual(Path(td)/"python.exe",runtime)

    def test_missing_trusted_checkpoint_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            manifest=self._tree(td,url=False)
            with self.assertRaises(AIComponentError):
                _validate_tree(Path(td),manifest,run_runtime_check=False)

    def test_present_checkpoint_must_still_match_sha(self):
        with tempfile.TemporaryDirectory() as td:
            manifest=self._tree(td)
            checkpoint=Path(td)/"assets"/"bootstrap.pth"
            checkpoint.parent.mkdir()
            checkpoint.write_bytes(b"wrong")
            with self.assertRaises(AIComponentError):
                _validate_tree(Path(td),manifest,run_runtime_check=False)


if __name__=="__main__":
    unittest.main()
