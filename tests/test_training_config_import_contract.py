import json
import importlib.util
import tempfile
import unittest
from pathlib import Path

from app.rtmpose_dataset import generate_smoke_config


class TrainingConfigImportContractTests(unittest.TestCase):
    def test_default_training_config_has_no_missing_custom_module(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            manifest=root/"dataset.json"
            manifest.write_text(json.dumps({
                "format_version":1,
                "dataset_id":"d",
                "schema_sha256":"h",
                "schema_landmarks":[{"landmark_id":1,"abbr":"P"}],
                "images":[],
            }),encoding="utf-8")
            text=generate_smoke_config(
                manifest,
                data_root=root,
                train_coco=root/"train.json",
                val_coco=root/"val.json",
                output_path=root/"config.py",
                base_config=root/"base.py",
                base_checkpoint=root/"base.pth",
            ).read_text(encoding="utf-8")
            self.assertNotIn("rtmpose_augmentations",text)
            self.assertIn("custom_imports = None",text)


    def test_child_training_config_neutralizes_legacy_parent_custom_import(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            manifest=root/"dataset.json"
            manifest.write_text(json.dumps({
                "format_version":1,
                "dataset_id":"legacy-parent",
                "schema_sha256":"h",
                "schema_landmarks":[{"landmark_id":1,"abbr":"P"}],
                "images":[],
            }),encoding="utf-8")
            base=root/"legacy_config.py"
            base.write_text(
                "custom_imports = dict(imports=['rtmpose_augmentations'], allow_failed_imports=False)\n",
                encoding="utf-8",
            )
            child=generate_smoke_config(
                manifest,
                data_root=root,
                train_coco=root/"train.json",
                val_coco=root/"val.json",
                output_path=root/"child.py",
                base_config=base,
                base_checkpoint=root/"base.pth",
            )
            text=child.read_text(encoding="utf-8")
            self.assertIn("custom_imports = None",text)
            self.assertNotIn("imports=['rtmpose_augmentations']",text)

    def test_child_config_replaces_parent_init_cfg_without_losing_backbone(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            manifest=root/"dataset.json"
            manifest.write_text(json.dumps({
                "format_version":1,
                "dataset_id":"parent-inference-config",
                "schema_sha256":"h",
                "schema_landmarks":[{"landmark_id":1,"abbr":"P"}],
                "images":[],
            }),encoding="utf-8")
            base=root/"inference_config.py"
            base.write_text("model = dict(backbone=dict(type='CSPNeXt', init_cfg=None))\n",encoding="utf-8")
            child=generate_smoke_config(
                manifest,
                data_root=root,
                train_coco=root/"train.json",
                val_coco=root/"val.json",
                output_path=root/"config.py",
                base_config=base,
                base_checkpoint=root/"base.pth",
            )
            text=child.read_text(encoding="utf-8")
            self.assertIn('backbone=dict(init_cfg=dict(_delete_=True, type="Pretrained"',text)
            self.assertIn("checkpoint=dict(type='CheckpointHook'",text)
            self.assertIn("train_cfg = dict(type='EpochBasedTrainLoop'",text)
            if importlib.util.find_spec("mmengine") is not None:
                from mmengine.config import Config
                from mmengine.hooks import CheckpointHook
                from mmengine.registry import HOOKS
                backbone=Config.fromfile(str(child)).model.backbone
                self.assertEqual("CSPNeXt",backbone.type)
                self.assertEqual("Pretrained",backbone.init_cfg.type)
                self.assertEqual(str((root/"base.pth").resolve()),backbone.init_cfg.checkpoint)
                self.assertEqual("EpochBasedTrainLoop",Config.fromfile(str(child)).train_cfg.type)
                checkpoint_hook=HOOKS.build(Config.fromfile(str(child)).default_hooks.checkpoint)
                self.assertIsInstance(checkpoint_hook,CheckpointHook)

if __name__=="__main__":
    unittest.main()
