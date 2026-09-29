import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import ai_hardware
from app.ui.landmarks_section import _prediction_failure_summary
from app.ui.photo_list_panel import PhotoListPanel
from app.ui.shell import ProductionShell


def _runner_module():
    import importlib.util
    path=Path(__file__).resolve().parents[1]/"ai_runtime"/"rtmpose_runner.py"
    spec=importlib.util.spec_from_file_location("rtmpose_runner_legacy_test",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class _Config(dict):
    __getattr__=dict.__getitem__
    __setattr__=dict.__setitem__


class _LegacyLoader:
    calls=0
    @classmethod
    def fromfile(cls,_path):
        cls.calls+=1
        if "rtmpose_augmentations" not in sys.modules:
            raise ImportError("Failed to import rtmpose_augmentations")
        return _Config(
            custom_imports={"imports":["rtmpose_augmentations"],"allow_failed_imports":False},
            test_dataloader=None,
            train_dataloader=_Config(dataset=_Config(type="CocoDataset",pipeline=["train"])),
            val_pipeline=["val"],
        )


class _Canvas:
    def __init__(self):self.selected=[];self.seen=[]
    def selection_set(self,index):self.selected.append(index)
    def see(self,index,align_top=False):self.seen.append((index,bool(align_top)))


class Beta10WorkflowRegressionTests(unittest.TestCase):
    def test_legacy_training_only_custom_import_does_not_break_inference(self):
        module=_runner_module();_LegacyLoader.calls=0
        sys.modules.pop("rtmpose_augmentations",None)
        config=module.prepare_inference_config("legacy_config.py",config_loader=_LegacyLoader)
        self.assertEqual(2,_LegacyLoader.calls)
        self.assertIsNone(config["custom_imports"])
        self.assertEqual(["val"],config.test_dataloader["dataset"]["pipeline"])
        self.assertNotIn("rtmpose_augmentations",sys.modules)

    def test_setup_qualified_hardware_wins_over_stale_warm_profile(self):
        good={
            "cpu_model":"CPU","physical_cores":8,"logical_cores":16,"ram_bytes":32*1024**3,
            "gpu_model":"GPU","gpu_vram_mib":12288,"gpu_driver":"1","cuda_available":True,
            "cuda_runtime":"12.1","acceleration":"CUDA","gpu_free_mib":8000,
        }
        stale={**good,"cuda_available":False,"cuda_runtime":None,"acceleration":"CPU"}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{"LOCALAPPDATA":td},clear=False):
            root=Path(td)/"MorphoLabel";root.mkdir()
            (root/"first_run_setup.json").write_text(json.dumps({"status":"PASS","hardware":good}),encoding="utf-8")
            (root/"hardware_profile.json").write_text(json.dumps({"hardware":stale}),encoding="utf-8")
            ai_hardware._HARDWARE_PROFILE=None
            try:
                with patch("app.ai_hardware.detect_hardware",side_effect=AssertionError("routine detection must not run")):
                    profile=ai_hardware.get_hardware_profile()
                self.assertTrue(profile.cuda_available)
                self.assertEqual("CUDA",profile.acceleration)
            finally:
                ai_hardware._HARDWARE_PROFILE=None

    def test_selected_photo_sync_reveals_after_refresh(self):
        panel=PhotoListPanel.__new__(PhotoListPanel)
        panel.context=SimpleNamespace(selected=9);panel.visible_indices=[3,9,11];panel.canvas=_Canvas()
        refresh=[]
        panel.refresh=lambda preserve_scroll=False:refresh.append(preserve_scroll)
        PhotoListPanel.sync_current(panel,reveal=True)
        self.assertEqual([False],refresh)
        self.assertEqual([1],panel.canvas.selected)
        self.assertEqual([(1,False)],panel.canvas.seen)

    def test_navigation_is_only_visible_for_persisted_batch_or_review(self):
        self.assertFalse(ProductionShell._workflow_navigation_visible(None))
        self.assertTrue(ProductionShell._workflow_navigation_visible({"kind":"landmark","text":"2 / 20"}))

    def test_all_failed_prediction_exposes_concise_cause(self):
        batch={"failures":{"a":"trace\nModuleNotFoundError: No module named 'rtmpose_augmentations'\nmore"}}
        self.assertEqual("ModuleNotFoundError: No module named 'rtmpose_augmentations'",_prediction_failure_summary(batch))

    def test_public_workflow_actions_and_menu_are_wired_to_the_named_operation(self):
        root=Path(__file__).resolve().parents[1]
        landmarks=(root/"app"/"ui"/"landmarks_section.py").read_text(encoding="utf-8")
        shell=(root/"app"/"ui"/"shell.py").read_text(encoding="utf-8")
        service=(root/"app"/"landmark_ai_service.py").read_text(encoding="utf-8")
        project=(root/"app"/"ui"/"project_section.py").read_text(encoding="utf-8")
        self.assertIn("'Apply next',lambda:self.predict(False,prediction.get())",landmarks)
        self.assertIn("'All remaining',lambda:self.predict(True,prediction.get())",landmarks)
        self.assertNotIn("'Reapply',self.reapply_unverified",landmarks)
        self.assertIn("'Review AI predictions',lambda:self.review_worst(prediction.get())",landmarks)
        self.assertIn("'Final data QC',lambda:open_complex_qc(self)",landmarks)
        self.assertNotIn('status("Detecting hardware…")',service)
        self.assertIn('ttk.Menubutton(row,text="Menu")',shell)
        self.assertNotIn('ttk.Menubutton(row,text="AI")',shell)
        self.assertNotIn('ttk.Menubutton(row,text="About")',shell)
        self.assertNotIn("threading.Thread(target=self._warm_ai_hardware",shell)
        self.assertIn("Project setup",project)
        self.assertIn("Image preparation",project)
        self.assertNotIn("Panedwindow",project)


if __name__=="__main__":
    unittest.main()
