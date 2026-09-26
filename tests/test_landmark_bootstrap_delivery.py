import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import landmark_bootstrap


class _Response:
    def __init__(self, data):
        self._buffer=io.BytesIO(data)
        self.headers={"Content-Length":str(len(data))}
    def read(self, size=-1):
        return self._buffer.read(size)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class ManagedBootstrapDeliveryTests(unittest.TestCase):
    def _component(self, root, payload):
        component=Path(root)/"component"
        config=component/"vendor"/"mmpose"/"configs"/"animal_2d_keypoint"/"rtmpose"/"ap10k"/"rtmpose-m_8xb64-210e_ap10k-256x256.py"
        config.parent.mkdir(parents=True)
        config.write_text("model={}",encoding="utf-8")
        checkpoint=component/"assets"/"bootstrap.pth"
        manifest={
            "component_format":1,
            "component_version":"test",
            "platform":"windows-x64",
            "python_relative_path":"python.exe",
            "bootstrap_config":config.relative_to(component).as_posix(),
            "bootstrap_checkpoint":checkpoint.relative_to(component).as_posix(),
            "bootstrap_checkpoint_url":"https://download.openmmlab.com/test/bootstrap.pth",
            "bootstrap_checkpoint_sha256":hashlib.sha256(payload).hexdigest(),
            "mmpose_source":"vendor/mmpose",
        }
        (component/"component.json").write_text(json.dumps(manifest),encoding="utf-8")
        (component/"python.exe").write_bytes(b"python")
        return component,config,checkpoint

    def test_missing_checkpoint_downloads_from_openmmlab_and_verifies_sha(self):
        payload=b"official-checkpoint"
        with tempfile.TemporaryDirectory() as td:
            component,config,checkpoint=self._component(td,payload)
            with patch("app.landmark_bootstrap.ensure_ai_runtime",return_value=(component/"python.exe",Path("runner"))),                  patch("app.landmark_bootstrap.component_root_for_runtime",return_value=component),                  patch("urllib.request.urlopen",return_value=_Response(payload)):
                spec=landmark_bootstrap.resolve_landmark_bootstrap(None)
            self.assertEqual(config,spec.config_path)
            self.assertEqual(checkpoint,spec.checkpoint_path)
            self.assertEqual(payload,checkpoint.read_bytes())
            self.assertEqual(hashlib.sha256(payload).hexdigest(),spec.checksum)

    def test_corrupt_checkpoint_is_rejected_without_final_file(self):
        expected=b"expected"
        bad=b"tampered"
        with tempfile.TemporaryDirectory() as td:
            component,_,checkpoint=self._component(td,expected)
            with patch("app.landmark_bootstrap.ensure_ai_runtime",return_value=(component/"python.exe",Path("runner"))),                  patch("app.landmark_bootstrap.component_root_for_runtime",return_value=component),                  patch("urllib.request.urlopen",return_value=_Response(bad)):
                with self.assertRaises(RuntimeError):
                    landmark_bootstrap.resolve_landmark_bootstrap(None)
            self.assertFalse(checkpoint.exists())
            self.assertFalse(checkpoint.with_suffix(checkpoint.suffix+".part").exists())

    def test_untrusted_checkpoint_url_is_rejected_without_network(self):
        payload=b"expected"
        with tempfile.TemporaryDirectory() as td:
            component,_,checkpoint=self._component(td,payload)
            manifest=json.loads((component/"component.json").read_text(encoding="utf-8"))
            manifest["bootstrap_checkpoint_url"]="https://example.com/bootstrap.pth"
            (component/"component.json").write_text(json.dumps(manifest),encoding="utf-8")
            with patch("app.landmark_bootstrap.ensure_ai_runtime",return_value=(component/"python.exe",Path("runner"))),                  patch("app.landmark_bootstrap.component_root_for_runtime",return_value=component),                  patch("urllib.request.urlopen") as urlopen:
                with self.assertRaises(RuntimeError):
                    landmark_bootstrap.resolve_landmark_bootstrap(None)
            urlopen.assert_not_called()
            self.assertFalse(checkpoint.exists())


if __name__=="__main__":
    unittest.main()
