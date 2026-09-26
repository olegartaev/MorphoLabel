import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.build_ai_release_assets import build_release_assets


class AIReleaseAssetTests(unittest.TestCase):
    def test_split_parts_reconstruct_exact_archive_and_stay_under_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            archive=root/"component.zip"
            payload=b"abcdefghijklmnopqrstuvwxyz"
            archive.write_bytes(payload)
            (root/"AI_BUILD_INFO.json").write_text(json.dumps({
                "archive":archive.name,
                "archive_sha256":hashlib.sha256(payload).hexdigest(),
                "archive_bytes":len(payload),
                "installed_bytes":100,
                "component_manifest":{"component_version":"1.0-test","platform":"windows-x64"},
            }),encoding="utf-8")
            manifest,folder=build_release_assets(root,"0.5-test",max_part_bytes=10)
            self.assertEqual([10,10,6],[item["bytes"] for item in manifest["parts"]])
            rebuilt=b"".join((folder/item["name"]).read_bytes() for item in manifest["parts"])
            self.assertEqual(payload,rebuilt)
            self.assertEqual(hashlib.sha256(payload).hexdigest(),manifest["archive_sha256"])
            self.assertTrue(all(item["bytes"]<2*1024**3 for item in manifest["parts"]))


if __name__=="__main__":
    unittest.main()
