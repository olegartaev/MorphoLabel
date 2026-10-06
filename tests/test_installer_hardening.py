import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from unittest.mock import MagicMock
from types import SimpleNamespace, ModuleType

from app import ai_starters, first_run_setup, landmark_bootstrap
from app.setup_progress import COMPONENTS, SetupProgress
from app.verified_download import byte_detail, download_verified, sha256_file


class Response:
    def __init__(self, data, status=200, start=0, total=None, interrupt=False):
        self.stream = io.BytesIO(data)
        self.status = status
        self.headers = {"Content-Length": str(total if status == 200 and total else len(data))}
        if status == 206:
            self.headers["Content-Range"] = f"bytes {start}-{start+len(data)-1}/{total}"
        self.interrupt = interrupt
        self.sent = False

    def read(self, size):
        if self.interrupt and self.sent:
            raise TimeoutError("offline")
        self.sent = True
        return self.stream.read(size)

    def __enter__(self): return self
    def __exit__(self, *args): return False


def ready_fixture(root):
    """Complete tiny managed component, with real hashes and persisted contract."""
    root = Path(root)
    component = root / "component"
    (component / "vendor/tools").mkdir(parents=True)
    (component / "vendor/tools/train.py").write_text("", encoding="utf-8")
    (component / "config.py").write_text("model={}", encoding="utf-8")
    runtime = component / "python.exe"
    runtime.write_bytes(b"runtime")
    bootstrap = component / "landmark.pth"
    bootstrap.write_bytes(b"landmark")
    manifest = dict(python_relative_path="python.exe", bootstrap_config="config.py",
                    bootstrap_checkpoint="landmark.pth", bootstrap_checkpoint_sha256=sha256_file(bootstrap),
                    bootstrap_checkpoint_url="https://download.openmmlab.com/landmark.pth", mmpose_source="vendor")
    (component / "component.json").write_text(json.dumps(manifest), encoding="utf-8")
    specs = tuple(replace(spec, size=len(b"starter"), sha256=hashlib.sha256(b"starter").hexdigest()) for spec in ai_starters.STARTERS)
    for spec in specs:
        spec.path.parent.mkdir(parents=True, exist_ok=True)
        spec.path.write_bytes(b"starter")
    state = dict(setup_contract_version=first_run_setup.SETUP_CONTRACT_VERSION, status="PASS",
                 runtime_python=str(runtime), runtime_sha256=sha256_file(runtime),
                 runtime_manifest_sha256=sha256_file(component / "component.json"),
                 bootstrap_checkpoint=str(bootstrap), starters={spec.role: spec.record() for spec in specs},
                 hardware={"cpu_model": "test", "cuda_available": False},
                 ai_self_test={"status": "PASS", "landmarks": 17, "bootstrap_sha256": sha256_file(bootstrap),
                               "training_smoke": {"status": "trained"}})
    return state, specs


class InstallerHardeningTests(unittest.TestCase):
    def test_detector_local_checkpoint_disables_upstream_backbone_download(self):
        from ai_runtime.xray_detector_runner import _configure_initial_checkpoint
        cfg=SimpleNamespace(model=SimpleNamespace(backbone=SimpleNamespace(init_cfg={"type":"Pretrained","checkpoint":"https://upstream.test/imagenet.pth"})))
        _configure_initial_checkpoint(cfg,"local-rtmdet.pth")
        self.assertEqual("local-rtmdet.pth",cfg.load_from)
        self.assertIsNone(cfg.model.backbone.init_cfg)
        self.assertIsNone(cfg.model.init_cfg)

    def test_three_frozen_first_training_payloads_use_verified_local_files_without_http(self):
        from app import xray_detector, xray_orientation, xray_structure_ai
        class Captured(Exception): pass
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"LOCALAPPDATA": td}):
            state, specs = ready_fixture(td)
            settings = {"device": "cpu", "batch_size": 1, "workers": 0}
            project = MagicMock()
            project.root = Path(td); project.models_root = Path(td) / "models"
            project.active_crop_model.return_value = None
            project.next_crop_model_id.return_value = "crop_001"
            project.active_structure_model.return_value = None
            project.next_structure_model_id.return_value = "structure_001"
            project.scheme = {"structures": []}
            dataset = {"root": Path(td), "train_json": Path(td)/"train.json", "val_json": Path(td)/"val.json"}
            with patch("app.ai_starters.STARTERS", specs), patch("app.ai_starters.is_frozen", return_value=True), patch("urllib.request.urlopen") as network:
                with patch.object(xray_detector, "ensure_ai_runtime", return_value=(Path(td)/"python.exe", None)), patch.object(xray_detector, "detector_performance_settings", return_value={"hardware": {}, "training": settings}), patch.object(xray_detector, "prepare_training_dataset", return_value=dataset), patch.object(xray_detector, "_run", side_effect=Captured) as run:
                    with self.assertRaises(Captured): xray_detector.train_detector(project)
                    self.assertEqual(str(specs[0].path), run.call_args.args[2]["initial_checkpoint"])
                with patch.object(xray_orientation, "prepare_orientation_dataset", return_value={"enabled": True, "manifest": Path(td)/"orientation.json"}), patch.object(xray_orientation, "_run", side_effect=Captured) as run:
                    with self.assertRaises(Captured): xray_orientation.train_orientation_model(project, "crop_001", project.models_root/"crop_001", Path(td)/"python.exe", settings)
                    self.assertEqual(str(specs[1].path), run.call_args.args[2]["pretrained_checkpoint"])
                backend = MagicMock(); backend.train.side_effect = Captured
                with patch.object(xray_structure_ai, "_structure_provider_spec"), patch.object(xray_structure_ai, "_structure_backend", return_value=backend), patch.object(xray_structure_ai, "structure_schema_digest", return_value="test"), patch.object(xray_structure_ai, "structure_performance_settings", return_value={"training": settings}), patch.object(xray_structure_ai, "prepare_structure_training_dataset", return_value={"manifest": Path(td)/"structure.json"}):
                    with self.assertRaises(Captured): xray_structure_ai.train_structure_model(project)
                    self.assertEqual(str(specs[2].path), backend.train.call_args.args[0]["pretrained_checkpoint"])
                    self.assertEqual("", backend.train.call_args.args[0]["initial_checkpoint"])
                network.assert_not_called()

    def test_runners_load_local_official_state_before_replacing_heads_without_weight_download(self):
        from ai_runtime import xray_orientation_runner, xray_structure_runner
        nn = ModuleType("torch.nn")
        class Module:
            def __init__(self): pass
        nn.Module = Module
        for name in ("Sequential", "Conv2d", "BatchNorm2d", "ReLU", "Linear"):
            setattr(nn, name, MagicMock())
        torch = ModuleType("torch"); torch.nn = nn; torch.load = MagicMock(return_value={"official": "state"})
        models = ModuleType("torchvision.models")
        models.MobileNet_V3_Small_Weights = SimpleNamespace(DEFAULT="network-mobilenet")
        models.ResNet18_Weights = SimpleNamespace(DEFAULT="network-resnet")
        mobile = MagicMock(); mobile.features = [MagicMock(), MagicMock()]
        mobile.classifier = [SimpleNamespace(in_features=1024)]
        # Feature iteration and parameters are both part of the real model API.
        class Features(list):
            def parameters(self): return []
        mobile.features = Features(mobile.features)
        mobile.load_state_dict.side_effect = lambda state: self.assertFalse(nn.Linear.called)
        encoder = MagicMock()
        encoder.load_state_dict.side_effect = lambda state: self.assertFalse(nn.Sequential.called)
        models.mobilenet_v3_small = MagicMock(return_value=mobile)
        models.resnet18 = MagicMock(return_value=encoder)
        modules = {"torch": torch, "torch.nn": nn, "torch.nn.functional": ModuleType("torch.nn.functional"), "torchvision": ModuleType("torchvision"), "torchvision.models": models}
        with patch.dict("sys.modules", modules):
            xray_orientation_runner._model(pretrained=True, pretrained_checkpoint="local-mobile.pth")
            models.mobilenet_v3_small.assert_called_once_with(weights=None)
            mobile.load_state_dict.assert_called_once_with({"official": "state"})
            torch.load.assert_called_with("local-mobile.pth", map_location="cpu", weights_only=True)
            nn.Sequential.reset_mock()
            xray_structure_runner._model(3, pretrained=True, pretrained_checkpoint="local-resnet.pth")
            models.resnet18.assert_called_once_with(weights=None)
            encoder.load_state_dict.assert_called_once_with({"official": "state"})
            torch.load.assert_called_with("local-resnet.pth", map_location="cpu", weights_only=True)

    def test_plan_initial_state_and_retry_preserve_ready_rows(self):
        self.assertEqual(8, len(COMPONENTS))
        self.assertEqual({"CORE", "AI ENGINE", "PRETRAINED MODEL", "XRAY CROP", "XRAY ORIENTATION", "XRAY STRUCTURE", "HARDWARE", "AI TEST"}, {c.stage for c in COMPONENTS})
        state = SetupProgress()
        self.assertEqual("✓ Ready", state.status["CORE"])
        self.assertTrue(all(v == "○ Waiting" for k, v in state.status.items() if k != "CORE"))
        last = state.overall
        for component in COMPONENTS[1:]:
            for detail in ("Checking…", "Downloading… 37%", "Downloading… 10%", "Installing…", "✓ Ready"):
                state.update(component.stage, detail)
                self.assertGreaterEqual(state.overall, last)
                last = state.overall
        self.assertEqual(100, last)
        self.assertEqual(8, state.ready_count)
        state = SetupProgress()
        state.update("AI ENGINE", "✓ Ready")
        state.update("PRETRAINED MODEL", "Downloading… 37%")
        state.fail(); state.retry()
        self.assertEqual("✓ Ready", state.status["AI ENGINE"])
        self.assertEqual("○ Waiting", state.status["PRETRAINED MODEL"])

    def test_each_starter_and_landmark_interruption_resumes_real_bytes(self):
        payload = b"abcdefghij"
        digest = hashlib.sha256(payload).hexdigest()
        for spec in (*ai_starters.STARTERS, None):
            with self.subTest(role=spec.role if spec else "landmark"), tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"LOCALAPPDATA": td}):
                target = Path(td) / "landmark.pth" if spec is None else spec.path
                url = "https://download.openmmlab.com/landmark.pth" if spec is None else spec.url
                events = []
                def perform():
                    if spec is None:
                        return landmark_bootstrap._download_verified_checkpoint(url, target, digest, lambda stage, detail: events.append(detail))
                    small = replace(spec, sha256=digest, size=len(payload))
                    return ai_starters.install_starter(small, lambda stage, detail: events.append(detail))
                with patch("urllib.request.urlopen", return_value=Response(payload[:4], total=len(payload), interrupt=True)):
                    with self.assertRaisesRegex(RuntimeError, "partial file was kept"):
                        perform()
                self.assertEqual(payload[:4], target.with_suffix(".pth.part").read_bytes())
                def resume(request, timeout):
                    self.assertEqual("bytes=4-", request.get_header("Range"))
                    return Response(payload[4:], 206, start=4, total=len(payload))
                with patch("urllib.request.urlopen", side_effect=resume):
                    perform()
                self.assertEqual(payload, target.read_bytes())
                self.assertIn("40%", " ".join(events))
                self.assertIn("100%", " ".join(events))

    def test_ignored_range_restarts_only_current_asset_and_wrong_hash_never_activates(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "model.pth"
            target.with_suffix(".pth.part").write_bytes(b"abc")
            payload = b"abcdef"
            with patch("urllib.request.urlopen", return_value=Response(payload)):
                download_verified("https://upstream.test/model", target, hashlib.sha256(payload).hexdigest())
            self.assertEqual(payload, target.read_bytes())
            with patch("urllib.request.urlopen", return_value=Response(b"bad")):
                with self.assertRaisesRegex(RuntimeError, "SHA256"):
                    download_verified("https://upstream.test/model", target, "0"*64)
            # A wrong replacement is never activated over an earlier valid file.
            self.assertEqual(payload, target.read_bytes())
            self.assertFalse(target.with_suffix(".pth.part").exists())

    def test_invalid_range_is_rejected_and_partial_is_kept(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "model.pth"
            target.with_suffix(".pth.part").write_bytes(b"abc")
            with patch("urllib.request.urlopen", return_value=Response(b"def", 206, start=1, total=6)):
                with self.assertRaisesRegex(RuntimeError, "invalid resume range"):
                    download_verified("https://upstream.test/model", target, "0"*64)
            self.assertEqual(b"abc", target.with_suffix(".pth.part").read_bytes())

    def test_progress_uses_actual_bytes_and_unknown_total_stays_unknown(self):
        self.assertEqual("23.10 MB / 44.70 MB · 51%", byte_detail(23_100_000, 44_700_000))
        self.assertEqual("23.10 MB received", byte_detail(23_100_000, None))

    def test_ready_state_requires_all_assets_runtime_hardware_qualification_and_contract(self):
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"LOCALAPPDATA": td}):
            state, specs = ready_fixture(td)
            with patch("app.ai_starters.STARTERS", specs), patch("app.first_run_setup.read_setup_state", return_value=state), patch("app.ai_runtime_resolver.validate_ai_runtime") as validate:
                self.assertTrue(first_run_setup.ai_setup_complete())
                for spec in specs:
                    spec.path.write_bytes(b"corrupt")
                    self.assertFalse(first_run_setup.ai_setup_complete())
                    spec.path.write_bytes(b"starter")
                    spec.path.unlink()
                    self.assertFalse(first_run_setup.ai_setup_complete())
                    spec.path.write_bytes(b"starter")
                for key, value in (("setup_contract_version", 2), ("hardware", {}), ("ai_self_test", {}), ("runtime_sha256", "0"*64)):
                    previous = state[key]; state[key] = value
                    self.assertFalse(first_run_setup.ai_setup_complete())
                    state[key] = previous
                Path(state["bootstrap_checkpoint"]).write_bytes(b"damaged")
                self.assertFalse(first_run_setup.ai_setup_complete())
                Path(state["bootstrap_checkpoint"]).write_bytes(b"landmark")
                validate.side_effect = RuntimeError("missing torch dependency")
                self.assertFalse(first_run_setup.ai_setup_complete())
                validate.side_effect = subprocess.TimeoutExpired("runtime info", 60)
                self.assertFalse(first_run_setup.ai_setup_complete())

    def test_frozen_missing_starters_never_download_even_after_persisted_consent(self):
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"LOCALAPPDATA": td}), patch("app.ai_starters.is_frozen", return_value=True), patch("urllib.request.urlopen") as network:
            first_run_setup._record_download_consent()
            for spec in ai_starters.STARTERS:
                with self.assertRaisesRegex(RuntimeError, "Set up AI support"):
                    ai_starters.local_starter(spec.role)
                with self.assertRaisesRegex(RuntimeError, "Set up AI support"):
                    ai_starters.install_starter(spec)
            self.assertFalse(first_run_setup.ai_setup_download_active())
            network.assert_not_called()

    def test_source_missing_starter_retains_explicit_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ", {"LOCALAPPDATA": td}), patch("app.ai_starters.is_frozen", return_value=False), patch("urllib.request.urlopen") as network:
            self.assertIsNone(ai_starters.local_starter("detector"))
            network.assert_not_called()
