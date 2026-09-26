import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.developed_cache_v2 import navigation_cache_status


class NavigationCacheFastPathTests(unittest.TestCase):
 def test_normal_navigation_does_not_hash_original(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);developed=root/"developed.png";standardized=root/"standardized.png";metadata=root/"developed.json"
   developed.write_bytes(b"published");standardized.write_bytes(b"published")
   metadata.write_text(json.dumps({"source_sha256":"imported-hash","parameters_sha256":"params"}),encoding="utf-8")
   with patch("app.developed_cache_v2.paths",return_value=(None,None,developed,metadata,standardized,None,None)), patch("app.developed_cache_v2.base._params_hash",return_value="params"), patch("app.developed_cache_v2.base.sha256",side_effect=AssertionError("RAW must not be read")):
    status=navigation_cache_status(root/"offline.nef")
   self.assertTrue(status["ready"])
   self.assertTrue(status["source_hash_match"])
   self.assertEqual(status["png_integrity_error"],"deferred")

 def test_explicit_repair_validation_can_hash_original(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);developed=root/"developed.png";standardized=root/"standardized.png";metadata=root/"developed.json"
   developed.write_bytes(b"published");standardized.write_bytes(b"published")
   metadata.write_text(json.dumps({"source_sha256":"digest","parameters_sha256":"params"}),encoding="utf-8")
   with patch("app.developed_cache_v2.paths",return_value=(None,None,developed,metadata,standardized,None,None)), patch("app.developed_cache_v2.base._params_hash",return_value="params"), patch("app.developed_cache_v2.base.sha256",return_value="digest") as sha:
    status=navigation_cache_status(root/"original.nef",validate_source=True)
   self.assertTrue(status["ready"])
   sha.assert_called_once()


if __name__ == "__main__":
 unittest.main()
