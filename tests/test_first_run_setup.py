import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import first_run_setup
from tests.test_installer_hardening import ready_fixture


class FirstRunSetupTests(unittest.TestCase):
    def test_source_checkout_never_triggers_installed_first_run_setup(self):
        with patch("app.first_run_setup.is_frozen",return_value=False):
            self.assertFalse(first_run_setup.first_run_setup_required())

    def test_deferred_setup_suppresses_startup_prompt_without_granting_download_consent(self):
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ",{"LOCALAPPDATA":td},clear=False), patch("app.first_run_setup.is_frozen",return_value=True):
            first_run_setup.defer_first_run_setup()
            self.assertTrue(first_run_setup.ai_setup_deferred())
            self.assertFalse(first_run_setup.ai_download_consent_granted())
            self.assertFalse(first_run_setup.first_run_setup_required())

    def test_completed_setup_requires_runtime_and_bootstrap_to_still_exist(self):
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ",{"LOCALAPPDATA":td},clear=False), patch("app.first_run_setup.is_frozen",return_value=True):
            state,specs=ready_fixture(td)
            with patch("app.ai_starters.STARTERS",specs),patch("app.first_run_setup.read_setup_state",return_value=state),patch("app.ai_runtime_resolver.validate_ai_runtime"):
                self.assertFalse(first_run_setup.first_run_setup_required())
                Path(state["bootstrap_checkpoint"]).unlink()
                self.assertTrue(first_run_setup.first_run_setup_required())

    def test_setup_installs_ai_tests_inference_and_training_and_persists_defaults(self):
        hardware=SimpleNamespace(
            gpu_model="Test GPU",cuda_available=True,
            as_dict=lambda:{"gpu_model":"Test GPU","cuda_available":True},
        )
        ai_result={
            "status":"PASS","device":"cuda:0","cuda_available":True,"cuda_device_name":"Test GPU",
            "landmarks":17,"bootstrap_checkpoint":"C:/managed/bootstrap.pth","bootstrap_sha256":"a"*64,
            "training_smoke":{"status":"trained","duration_seconds":1.0,"checkpoint_sha256":"b"*64},
        }
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ",{"LOCALAPPDATA":td},clear=False), \
             patch("app.ai_delivery.ensure_ai_runtime",return_value=(Path("C:/managed/python.exe"),Path("runner.py"))) as ensure, \
             patch("app.landmark_bootstrap.resolve_landmark_bootstrap",return_value=SimpleNamespace(checkpoint_path=Path("C:/managed/bootstrap.pth"))) as resolve_bootstrap, \
             patch("app.ai_hardware.refresh_hardware_profile",return_value=hardware) as detect, \
             patch("app.ai_hardware.persist_machine_profile",return_value={
                 "hardware":hardware.as_dict(),
                 "training_default":{"device":"cuda:0","batch_size":4},
                 "inference_default":{"device":"cuda:0","batch_size":4},
             }) as persist, \
             patch("app.ai_starters.install_starter") as starters, \
             patch("app.verified_download.sha256_file",return_value="a"*64), \
             patch("app.self_test.run_ai_self_test",return_value=ai_result) as self_test:
            events=[]
            result=first_run_setup.run_first_run_setup(progress=lambda stage,detail:events.append((stage,detail)))
            self.assertEqual(3,starters.call_count)
            self.assertFalse(first_run_setup.ai_setup_download_active())
            ensure.assert_called_once()
            resolve_bootstrap.assert_called_once()
            self.assertTrue(first_run_setup.ai_download_consent_granted())
            detect.assert_called_once()
            persist.assert_called_once_with(hardware)
            self_test.assert_called_once()
            self.assertTrue(self_test.call_args.kwargs["include_training"])
            self.assertIsNotNone(self_test.call_args.kwargs["bootstrap"])
            stages=[stage for stage,_detail in events]
            for expected in ("AI ENGINE","PRETRAINED MODEL","HARDWARE","AI TEST","READY"):
                self.assertIn(expected,stages)
            self.assertLess(stages.index("AI ENGINE"),stages.index("PRETRAINED MODEL"))
            self.assertLess(stages.index("PRETRAINED MODEL"),stages.index("HARDWARE"))
            self.assertLess(stages.index("HARDWARE"),stages.index("AI TEST"))
            self.assertEqual("PASS",result["status"])
            saved=json.loads(first_run_setup.setup_state_path().read_text(encoding="utf-8"))
            self.assertEqual("PASS",saved["status"])
            self.assertTrue(saved["download_consent"])
            self.assertEqual("cuda:0",saved["recommended_defaults"]["training"]["device"])
            self.assertTrue(events)

    def test_failed_training_qualification_does_not_mark_setup_complete(self):
        hardware=SimpleNamespace(as_dict=lambda:{})
        bad={"status":"PASS","landmarks":17,"bootstrap_checkpoint":"x","training_smoke":{"status":"failed"}}
        with tempfile.TemporaryDirectory() as td, patch.dict("os.environ",{"LOCALAPPDATA":td},clear=False), \
             patch("app.ai_delivery.ensure_ai_runtime",return_value=(Path("python.exe"),Path("runner.py"))), \
             patch("app.landmark_bootstrap.resolve_landmark_bootstrap",return_value=SimpleNamespace(checkpoint_path=Path("bootstrap.pth"))), \
             patch("app.ai_hardware.refresh_hardware_profile",return_value=hardware), \
             patch("app.ai_hardware.persist_machine_profile",return_value={"training_default":{},"inference_default":{}}), \
             patch("app.ai_starters.install_starter"), \
             patch("app.self_test.run_ai_self_test",return_value=bad):
            with self.assertRaises(RuntimeError):
                first_run_setup.run_first_run_setup()
            state=first_run_setup.read_setup_state()
            self.assertEqual("PENDING",state["status"])
            self.assertTrue(state["download_consent"])


if __name__=="__main__":
    unittest.main()
