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
    def __init__(self, data, status=200):
        self._buffer=io.BytesIO(data)
        self.status=status
    def read(self, size=-1):
        return self._buffer.read(size)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class _InterruptingResponse(_Response):
    def __init__(self,data,error):
        super().__init__(data)
        self._sent=False
        self._error=error
    def read(self,size=-1):
        if not self._sent:
            self._sent=True
            return self._buffer.read(size)
        raise self._error



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

    def test_multipart_download_reassembles_and_verifies_full_archive(self):
        first=b"managed-ai-"
        second=b"archive"
        payload=first+second
        manifest={
            "format_version":1,"app_version":"test","component_version":"1","platform":"windows-x64",
            "archive_name":"MorphoLabel-AI-Windows-x64-test.zip",
            "archive_sha256":hashlib.sha256(payload).hexdigest(),
            "archive_bytes":len(payload),"installed_bytes":0,
            "parts":[
                {"name":"component.part01","bytes":len(first),"sha256":hashlib.sha256(first).hexdigest()},
                {"name":"component.part02","bytes":len(second),"sha256":hashlib.sha256(second).hexdigest()},
            ],
        }
        responses=[_Response(json.dumps(manifest).encode()),_Response(first),_Response(second)]
        with tempfile.TemporaryDirectory() as td,              patch.dict(os.environ,{"LOCALAPPDATA":td,"MORPHOLABEL_AI_RELEASE_BASE":"https://example.test"},clear=False),              patch("urllib.request.urlopen",side_effect=responses),              patch("app.ai_delivery.install_component_archive",return_value=Path(td)/"runtime"/"python.exe") as install:
            runtime=ai_delivery.install_published_ai_component(release_version="test")
            self.assertEqual(Path(td)/"runtime"/"python.exe",runtime)
            self.assertEqual(manifest["archive_sha256"],install.call_args.kwargs["expected_sha256"])
            cache=Path(td)/"MorphoLabel"/"downloads"/"ai"
            self.assertFalse(any(cache.glob("*.part")))

    def test_interrupted_download_retries_with_http_range_and_keeps_progress(self):
        payload=b"abcdef"
        manifest={
            "archive_name":"component.zip",
            "archive_sha256":hashlib.sha256(payload).hexdigest(),
            "archive_bytes":len(payload),"installed_bytes":0,
            "parts":[{"name":"component.part01","bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}],
        }
        requests=[]
        def open_side_effect(request,timeout=0):
            requests.append(request)
            if len(requests)==1:
                return _InterruptingResponse(b"abc",TimeoutError("simulated timeout"))
            self.assertEqual("bytes=3-",request.get_header("Range"))
            return _Response(b"def",status=206)
        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ,{"LOCALAPPDATA":td},clear=False), \
             patch("urllib.request.urlopen",side_effect=open_side_effect), \
             patch("app.ai_delivery.time.sleep"):
            target=ai_delivery._download_archive(manifest,"https://example.test")
            self.assertEqual(payload,target.read_bytes())
            self.assertFalse(target.with_suffix(target.suffix+".part").exists())

    def test_failed_attempt_keeps_partial_file_for_next_invocation(self):
        payload=b"abcdef"
        manifest={
            "archive_name":"component.zip",
            "archive_sha256":hashlib.sha256(payload).hexdigest(),
            "archive_bytes":len(payload),"installed_bytes":0,
            "parts":[{"name":"component.part01","bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}],
        }
        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ,{"LOCALAPPDATA":td},clear=False), \
             patch("urllib.request.urlopen",side_effect=lambda *_a,**_k:_InterruptingResponse(b"abc",TimeoutError("offline"))), \
             patch("app.ai_delivery.time.sleep"):
            with self.assertRaises(ai_delivery.AIDeliveryError):
                ai_delivery._download_archive(manifest,"https://example.test")
            partial=Path(td)/"MorphoLabel"/"downloads"/"ai"/"component.zip.part"
            self.assertTrue(partial.is_file())
            self.assertEqual(b"abc",partial.read_bytes())

        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"MorphoLabel"/"downloads"/"ai";cache.mkdir(parents=True)
            (cache/"component.zip.part").write_bytes(b"abc")
            seen=[]
            def resume(request,timeout=0):
                seen.append(request.get_header("Range"))
                return _Response(b"def",status=206)
            with patch.dict(os.environ,{"LOCALAPPDATA":td},clear=False), \
                 patch("urllib.request.urlopen",side_effect=resume):
                target=ai_delivery._download_archive(manifest,"https://example.test")
            self.assertEqual(["bytes=3-"],seen)
            self.assertEqual(payload,target.read_bytes())

    def test_multipart_download_rejects_corrupt_part_before_install(self):
        first=b"good"
        bad=b"tampered"
        manifest={
            "format_version":1,"app_version":"test","component_version":"1","platform":"windows-x64",
            "archive_name":"component.zip",
            "archive_sha256":hashlib.sha256(first+b"expected").hexdigest(),
            "archive_bytes":len(first)+len(bad),"installed_bytes":0,
            "parts":[
                {"name":"component.part01","bytes":len(first),"sha256":hashlib.sha256(first).hexdigest()},
                {"name":"component.part02","bytes":len(bad),"sha256":hashlib.sha256(b"expected").hexdigest()},
            ],
        }
        responses=[_Response(json.dumps(manifest).encode()),_Response(first),_Response(bad)]
        with tempfile.TemporaryDirectory() as td,              patch.dict(os.environ,{"LOCALAPPDATA":td,"MORPHOLABEL_AI_RELEASE_BASE":"https://example.test"},clear=False),              patch("urllib.request.urlopen",side_effect=responses),              patch("app.ai_delivery.install_component_archive") as install:
            with self.assertRaises(ai_delivery.AIDeliveryError):
                ai_delivery.install_published_ai_component(release_version="test")
            install.assert_not_called()

    def test_source_checkout_ensure_remains_network_free(self):
        with tempfile.TemporaryDirectory() as td,              patch.dict(os.environ,{"LOCALAPPDATA":td},clear=False),              patch("app.ai_delivery.is_frozen",return_value=False),              patch("app.ai_delivery.install_published_ai_component") as install:
            runtime,_=ai_delivery.ensure_ai_runtime()
            self.assertFalse(runtime.is_file())
            install.assert_not_called()


if __name__=="__main__":
    unittest.main()
