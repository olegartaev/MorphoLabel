"""CPU tests for the safe UI adapter around continued multires training."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from app.xray_multires_training import (
    create_read_only_source_project_copy,
    is_universal_multires_model,
    run_high_resolution_training,
)
from app.xray_schema import phoxinus_vertebral_preset
from app.xray_structure_ai import structure_schema_digest
from app.xray_structures_ui import XRayStructureWorkspace


class FakeProject:
    def __init__(self, root, model):
        self.root = Path(root)
        self.db_path = self.root / "xray_project.sqlite3"
        self.models_root = self.root / "models"
        self.source = self.root / "source"
        self.scheme = phoxinus_vertebral_preset()
        self._model = model

    def structure_models(self):
        return [self._model]


class HighResolutionTrainingUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "read-only.txt").write_text("source", encoding="utf-8")
        model_dir = self.root / "models" / "hybrid"
        model_dir.mkdir(parents=True)
        self.hashes = {}
        for name, payload in (("model.pth", b"base"), ("detail.pth", b"detail"), ("native.pth", b"native")):
            (model_dir / name).write_bytes(payload)
            self.hashes[name] = hashlib.sha256(payload).hexdigest()
        self.scheme = phoxinus_vertebral_preset()
        metadata = {
            "input_size": [768, 256], "output_stride": 2,
            "structures": [{"id": row["id"]} for row in self.scheme["structures"]],
            "inference_pipeline": {
                "name": "multires_heatmap_v1", "version": 1, "mode": "tiled_native",
                "detail": {"checkpoint": "detail.pth", "sha256": self.hashes["detail.pth"], "input_size": [768, 384]},
                "native": {"checkpoint": "native.pth", "sha256": self.hashes["native.pth"], "input_size": [1536, 512]},
                "tiles": {"nx": 4, "ny": 2, "width_fraction": .38, "height_fraction": .62},
            },
        }
        (model_dir / "model.json").write_text(json.dumps(metadata), encoding="utf-8")
        c=sqlite3.connect(self.root / "xray_project.sqlite3")
        try:
            c.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            c.executemany("INSERT INTO meta VALUES(?,?)", (("source", "source"), ("source_storage", "managed_v1")))
            c.commit()
        finally:c.close()
        self.model = {"model_id": "hybrid", "path": "models/hybrid/model.pth",
                      "metadata_path": "models/hybrid/model.json",
                      "schema_digest": structure_schema_digest(self.scheme)}
        self.project = FakeProject(self.root, self.model)
        self.before_db = hashlib.sha256(self.project.db_path.read_bytes()).hexdigest()
        self.before_weights = hashlib.sha256((model_dir / "model.pth").read_bytes()).hexdigest()

    def test_recognizes_only_valid_multires_models(self):
        self.assertTrue(is_universal_multires_model(self.project, "hybrid"))
        self.assertFalse(is_universal_multires_model(self.project, "missing"))
        bad = self.root / "models" / "hybrid" / "model.json"
        metadata = json.loads(bad.read_text(encoding="utf-8"))
        metadata["inference_pipeline"]["mode"] = "tiled"
        bad.write_text(json.dumps(metadata), encoding="utf-8")
        self.assertFalse(is_universal_multires_model(self.project, "hybrid"))

    def test_copy_uses_external_source_and_preserves_original(self):
        target = Path(self.temp.name) / "training_copy"
        create_read_only_source_project_copy(self.project, "hybrid", target)
        c=sqlite3.connect(target / "xray_project.sqlite3")
        try:meta = dict(c.execute("SELECT key,value FROM meta"))
        finally:c.close()
        self.assertEqual(meta["source_storage"], "external_v0")
        self.assertEqual(Path(meta["source"]).resolve(), self.source.resolve())
        self.assertFalse((target / "source").exists())
        self.assertEqual((target / "models" / "hybrid" / "detail.pth").read_bytes(), b"detail")
        self.assertEqual(hashlib.sha256(self.project.db_path.read_bytes()).hexdigest(), self.before_db)
        self.assertEqual(hashlib.sha256((self.root / "models" / "hybrid" / "model.pth").read_bytes()).hexdigest(), self.before_weights)

    def test_copy_refuses_overwrite(self):
        with self.assertRaises(FileExistsError):
            create_read_only_source_project_copy(self.project, "hybrid", self.root)

    def test_ui_runner_imports_only_a_valid_inactive_candidate_zip(self):
        runner=Path(self.temp.name)/"fake_training.py"
        runner.write_text(
            "import argparse,json,zipfile\n"
            "p=argparse.ArgumentParser();p.add_argument('--output');a,_=p.parse_known_args()\n"
            "print(json.dumps({'stage':'PREPARED','training_specimens':1,'validation_specimens':1,'train_plates':1,'val_plates':1}),flush=True)\n"
            "with zipfile.ZipFile(a.output,'w') as z:z.writestr('manifest.json',json.dumps({'model_id':'test_candidate'}))\n",
            encoding="utf-8",
        )
        output=Path(self.temp.name)/"candidate.zip"
        progress=[]
        with patch("app.xray_multires_training.resource_path",return_value=runner):
            result=run_high_resolution_training(
                self.project,"hybrid",output,python_executable=Path(sys.executable),
                progress=progress.append,cancelled=threading.Event(),
            )
        self.assertEqual(result["model_id"],"test_candidate")
        self.assertEqual(Path(result["path"]).resolve(),output.resolve())
        self.assertTrue(any("PREPARED" in line for line in progress))
        self.assertEqual(hashlib.sha256(self.project.db_path.read_bytes()).hexdigest(),self.before_db)

    def test_ordinary_train_routes_multires_parent_to_two_branch_training(self):
        workspace=object.__new__(XRayStructureWorkspace)
        workspace._busy=False
        workspace.project=self.project
        workspace.training_parent_choice=SimpleNamespace(get=lambda:"hybrid")
        with patch("app.xray_multires_training.is_universal_multires_model",return_value=True), \
             patch.object(workspace,"train_highres_structure_ai") as highres:
            workspace.train_structure_ai()
        highres.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
