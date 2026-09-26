import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import ai_delivery


class _Response:
    def __init__(self, data):
        self._buffer=io.BytesIO(data)
    def read(self, size=-1):
        return self._buffer.read(size)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class AIDeliveryTests(unittest.TestCase):
    def test_release_url_is_versioned_and_override_is_supported(self):
        self.assertIn("/releases/download/v",ai_delivery.release_base_url("1.2.3"))
        with patch.dict(os.environ,{"MORPHOLABEL_AI_RELEASE_BASE":"https://example.test/release/"},clear=False):
            self.assertEqual("https://example.test/release",ai_delivery.release_base_url("ignored"))

    def test_manifest_rejects_unsafe_archive_name(self):
        data=json.dumps({
            "format_version":1,"app_version":"test","component_version":"1","platform":"windows-x64",
            "archive_name":"../bad.zip","archive_sha256":"0"*64,"archive_bytes":1,"installed_bytes":1,
        }).encode()
        with patch.dict(os.environ,{"MORPHOLABEL_AI_RELEASE_BASE":"https://example.test"},clear=False),              patch("urllib.request.urlopen",return_value=_Response(data)):
            with self.assertRaises(ai_delivery.AIDeliveryError):
                ai_delivery._fetch_manifest("https://example.test")

    def test_download_verifies_sha_and_installer_receives_same_digest(self):
        payload=b"managed-ai-archive"
        digest=hashlib.sha256(payload).hexdigest()
        manifest_data=json.dumps({
            "format_version":1,"app_version":"test","component_version":"1","platform":"windows-x64",
            "archive_name":"MorphoLabel-AI-Windows-x64-test.zip","archive_sha256":digest,
            "archive_bytes":len(payload),"installed_bytes":0,
        }).encode()
        responses=[_Response(manifest_data),_Response(payload)]
        with tempfile.TemporaryDirectory() as td,              patch.dict(os.environ,{"LOCALAPPDATA":td,"MORPHOLABEL_AI_RELEASE_BASE":"https://example.test"},clear=False),              patch("urllib.request.urlopen",side_effect=responses),              patch("app.ai_delivery.install_component_archive",return_value=Path(td)/"runtime"/"python.exe") as install:
            runtime=ai_delivery.install_published_ai_component(release_version="test")
            self.assertEqual(Path(td)/"runtime"/"python.exe",runtime)
            self.assertEqual(digest,install.call_args.kwargs["expected_sha256"])
            self.assertFalse((Path(td)/"MorphoLabel"/"downloads"/"ai"/manifest_data.decode(errors="ignore")).exists())

    def test_source_checkout_ensure_remains_network_free(self):
        with tempfile.TemporaryDirectory() as td,              patch.dict(os.environ,{"LOCALAPPDATA":td},clear=False),              patch("app.ai_delivery.is_frozen",return_value=False),              patch("app.ai_delivery.install_published_ai_component") as install:
            runtime,_=ai_delivery.ensure_ai_runtime()
            self.assertFalse(runtime.is_file())
            install.assert_not_called()


if __name__=="__main__":
    unittest.main()
