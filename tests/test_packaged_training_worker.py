import tempfile
import unittest
from pathlib import Path
from tools.check_packaged_training_worker import REQUIRED, verify_distribution


class PackagedGpuWorkerTests(unittest.TestCase):
    def test_requires_real_files_at_installer_runtime_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/"MorphoLabel"/"_internal"
            for item in REQUIRED:
                path=target/item
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text("# minimal syntactically valid source\n",encoding="utf-8")
            self.assertEqual(verify_distribution(target.parent),(len({
                str(target/item) for item in REQUIRED if item.startswith("app/")
            }),len({str(target/item) for item in REQUIRED if item.startswith("ai_runtime/")})))
            (target/"tools/train_universal_multires.py").unlink()
            with self.assertRaisesRegex(FileNotFoundError,"train_universal_multires.py"):
                verify_distribution(target.parent)

    def test_fails_on_broken_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for item in REQUIRED:
                path=root/item
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text("pass\n",encoding="utf-8")
            (root/"app/xray_structure_ai.py").write_text("def invalid(:\n",encoding="utf-8")
            with self.assertRaises(SyntaxError):
                verify_distribution(root)


if __name__=="__main__":
    unittest.main()
