"""Executable third-module, inference adapter and scientific isolation proofs."""
import copy
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from app.ai import MockBackend
from app.ai_batch import BatchError, backend_for_model
from app.ai_package import AIPackageError, export_model_package, import_model_package
from app.extensions.api import BackendSpec, ModuleSpec
from app.extensions.registry import BackendRegistry
from app.landmark_ai_service import LandmarkAIService
from app.project_storage import Project, schema_hash
from app.xray_project import XRayProject
from app.xray_structure_ai import (
    STRUCTURE_BACKEND, XRayStructureAIError, XRayStructurePackageError,
    export_structure_model_package, import_structure_model_package,
    predict_structures, structure_schema_digest, train_structure_model,
)
from tests import test_release_torture as fixtures
from tests.current_fixtures import make_reviewed_crop


class ThirdRuntime:
    def __init__(self, state):
        self.state = state
        self.close_count = 0
        self.render_count = 0

    def render(self, host):
        self.render_count += 1
        self.host = host
        ttk.Label(host.container, text="Synthetic third science").pack()
        ttk.Button(host.container, text="Modules", command=host.show_module_hub).pack()

    def close(self):
        self.close_count += 1
        self.host = None


class ReleaseExtensionBoundaryTests(unittest.TestCase):
    setUp = fixtures.ReleaseTortureTests.setUp
    make_shell = fixtures.ReleaseTortureTests.make_shell
    complete_xray = fixtures.ReleaseTortureTests.complete_xray
    export_bytes = fixtures.ReleaseTortureTests.export_bytes

    def landmark_model(self, ident="alternate"):
        directory = self.landmark.models_root / ident
        directory.mkdir()
        (directory / "model.json").write_text(json.dumps({
            "backend_id": "alternate", "schema_sha256": schema_hash(self.landmark.schema_path),
            "input_size": [160, 100],
        }), encoding="utf-8")
        self.landmark.register_model(ident, "landmark", active=True,
                                     path=directory.relative_to(self.landmark.data_root).as_posix())
        return self.landmark.model_metadata(ident)

    def test_third_scientific_module_registry_render_switch_and_close(self):
        shell, errors = self.make_shell()
        own_state = {"project": "third-only", "annotations": [(1, 2)],
                     "queue": ["third-item"], "model": "third-model"}
        runtimes = []

        def factory():
            runtime = ThirdRuntime(own_state)
            runtimes.append(runtime)
            return runtime

        spec = ModuleSpec("synthetic_third", "Synthetic third science", "Test-only module",
                          "1", 1, 15, "available", factory, "test")
        self.assertTrue(shell.module_registry.register(spec))
        shell.render()

        def texts(widget):
            result = []
            for child in widget.winfo_children():
                if "text" in child.keys():
                    result.append(str(child.cget("text")))
                result.extend(texts(child))
            return result

        self.assertIn(spec.display_name, texts(shell.root))
        for _ in range(5):
            shell.open_module(spec.module_id)
            current = runtimes[-1]
            self.assertGreater(current.render_count, 0)
            self.assertIs(own_state, current.state)
            self.assertIn(spec.display_name, texts(shell.root))
            current.host.show_module_hub()
            self.assertEqual(1, current.close_count)
            for key in ("landmarks", "xray_counts"):
                shell.open_module(key)
                runtime = shell._active_module_runtime
                if key == "landmarks":
                    self.assertIs(self.landmark, runtime._host.project)
                else:
                    self.assertEqual(self.xray.root, runtime.project.root)
                with patch.object(runtime, "close", wraps=runtime.close) as close:
                    shell.show_module_hub()
                    close.assert_called_once()
            self.assertEqual("third-only", own_state["project"])
            self.assertEqual(["third-item"], own_state["queue"])
        self.assertTrue(all(runtime.close_count == 1 for runtime in runtimes))
        for key in ("landmarks", "xray_counts"):
            shell.open_module(spec.module_id)
            current = runtimes[-1]
            shell.open_module(key)
            self.assertEqual(1, current.close_count)
            shell.show_module_hub()
        self.assertEqual([], errors)
        self.assertEqual([], shell.module_registry.diagnostics)

    def test_alternate_landmark_backend_dispatch_prediction_edit_reopen(self):
        model = self.landmark_model()
        ident = self.landmark_ids[0]
        make_reviewed_crop(self.landmark, ident, 160, 100)
        requests = []

        class Alternate(MockBackend):
            def predict(self, request):
                requests.append(request)
                return super().predict(request)

        registry = BackendRegistry()
        registry.register(BackendSpec("alternate", "Alternate test implementation", "landmark",
                                      "1", 1, lambda ctx: Alternate(schema_hash(ctx.project.schema_path),
                                      model_id=ctx.model["model_id"], coordinate_overrides={1: (13, 17), 2: (31, 29)}), "test"))
        with patch("app.ai_batch.auto_performance_config", return_value={"device": "cpu", "batch_size": 1}):
            selected, backend = backend_for_model(self.landmark, model["model_id"], registry=registry)
        self.assertEqual(model["model_id"], selected["model_id"])
        result = LandmarkAIService(self.landmark, backend).predict_one(ident)
        self.assertEqual(ident, requests[0].image_id)
        self.assertEqual((13, 17), tuple(self.landmark.load_landmarks(ident)[1][key] for key in ("x_standardized", "y_standardized")))
        immutable = result.manifest_path.read_bytes()
        self.landmark.save_landmark(ident, 1, 14, 18, "corrected", provenance="corrected_by_human")
        self.landmark.mark_checked(ident)
        reopened = Project.open(self.landmark.root)
        self.assertEqual("alternate", reopened.active_model("landmark")["model_id"])
        self.assertEqual(result.prediction_run_id, reopened.load_landmarks(ident)[1]["prediction_run_id"])
        self.assertEqual(immutable, result.manifest_path.read_bytes())
        wrong = BackendRegistry()
        wrong.register(BackendSpec("alternate", "Wrong task", "xray", "1", 1, lambda ctx: backend, "test"))
        with patch("app.ai_batch.auto_performance_config", return_value={"device": "cpu", "batch_size": 1}):
            with self.assertRaisesRegex(BatchError, "unavailable"):
                backend_for_model(reopened, "alternate", registry=wrong)

    def test_alternate_structure_runner_abi_preserves_scientific_schema_and_lineage(self):
        for sid in self.specimens:
            self.complete_xray(sid)
        p = self.xray
        scheme_before = copy.deepcopy(p.scheme)
        with closing(sqlite3.connect(p.db_path)) as db:
            schema_before = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        operations = []

        def fake_runner(runtime, operation, payload, timeout):
            operations.append(operation)
            if operation == "train":
                manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual({"objects", "boundary"}, {s["id"] for s in manifest["structures"]})
                target = Path(payload["work_dir"])
                target.mkdir(parents=True)
                checkpoint, metadata = target / "alternate.pth", target / "alternate.json"
                checkpoint.write_bytes(b"deterministic alternate implementation")
                metadata.write_text(json.dumps({"backend": STRUCTURE_BACKEND,
                                               "training_objective": "synthetic_alternate",
                                               "structures": manifest["structures"], "input_size": [160, 100]}), encoding="utf-8")
                return {"checkpoint": str(checkpoint), "metadata": str(metadata), "metrics": {"test_only": True}}
            self.assertEqual("predict_many", operation)
            return {"results": [{"structures": [
                {"structure_id": "objects", "points": [{"x": .2, "y": .5, "score": .9}, {"x": .6, "y": .5, "score": .9}]},
                {"structure_id": "boundary", "points": [{"x": .6, "y": .5, "score": .9}]},
            ]} for _ in payload["images"]]}

        settings = {"training": {"device": "cpu", "batch_size": 2},
                    "inference": {"device": "cpu", "batch_size": 2}}
        with patch("app.xray_structure_ai.ensure_ai_runtime", return_value=(object(), {})), \
             patch("app.xray_structure_ai.structure_performance_settings", return_value=settings), \
             patch("app.xray_structure_ai._run", side_effect=fake_runner):
            parent = train_structure_model(p, seed=17, epochs=1)
            child = train_structure_model(p, seed=17, epochs=1)
            self.assertEqual(parent["model_id"], p.active_structure_model()["parent_model_id"])
            sid = self.specimens[0]
            prediction = predict_structures(p, [sid], allow_verified=True)
            self.assertEqual([], prediction["failures"])
            self.assertEqual(sid, prediction["success"][0]["specimen_id"])
        event = p.annotation_events(sid)[-1]
        p.move_annotation(p.annotations(sid)[0]["annotation_id"], .23, .5)
        p.verify_annotations(sid)
        package = self.root / "structure.zip"
        export_structure_model_package(p, package)
        imported = import_structure_model_package(p, package)
        p.activate_structure_model(imported)
        self.assertEqual([], p.structure_model_membership(imported))
        reopened = XRayProject(p.root)
        self.assertEqual(event, next(e for e in reopened.annotation_events(sid) if e["event_id"] == event["event_id"]))
        self.assertEqual(child["model_id"], event["payload"]["model_id"])
        self.assertEqual(8, len(reopened.structure_model_membership(child["model_id"])))
        self.assertEqual(scheme_before, reopened.scheme)
        with closing(sqlite3.connect(reopened.db_path)) as db:
            self.assertEqual(schema_before, db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall())
        self.assertEqual(["train", "train", "predict_many"], operations)
        self.assertEqual(2, reopened.trait_rows()[0]["trait_values"]["number"])
        with self.assertRaisesRegex(AIPackageError, "wrong model package type"):
            import_model_package(self.landmark, package, "landmark")
        # Existing Landmark package is rejected before touching X-ray storage.
        landmark_dir = self.landmark.models_root / "lm_package"
        landmark_dir.mkdir()
        (landmark_dir / "best_engineering_validation.pth").write_bytes(b"fake")
        (landmark_dir / "inference_config.py").write_text("default_scope='mmpose'\n", encoding="utf-8")
        (landmark_dir / "model.json").write_text(json.dumps({"backend": "rtmpose", "input_size": [160, 100]}), encoding="utf-8")
        self.landmark.register_model("lm_package", "landmark", path=landmark_dir.relative_to(self.landmark.data_root).as_posix(), active=True)
        lm_package = self.root / "landmark.zip"
        export_model_package(self.landmark, "landmark", lm_package)
        with self.assertRaisesRegex(XRayStructurePackageError, "format"):
            import_structure_model_package(reopened, lm_package)

    def test_models_queues_and_projects_remain_module_specific_across_switch(self):
        self.landmark_model("lm_only")
        self.xray.register_structure_model("xr_only", "fake", "fake.json", None,
                                           structure_schema_digest(self.xray.scheme), "synthetic", {},
                                           [{"specimen_id": self.specimens[0], "split": "train"}])
        with self.assertRaises(KeyError):
            self.xray.activate_structure_model("lm_only")
        with self.assertRaises(KeyError):
            self.landmark.set_active_model("landmark", "xr_only")
        with self.assertRaisesRegex(BatchError, "unavailable"):
            backend_for_model(self.landmark, "xr_only", model=self.xray.active_structure_model())
        with self.assertRaisesRegex(ValueError, "schema hash"):
            self.landmark.register_model("bad_schema", "landmark", schema_digest="incompatible")
        mismatch = dict(self.xray.active_structure_model(), schema_digest="incompatible")
        with self.assertRaisesRegex(XRayStructureAIError, "incompatible"):
            predict_structures(self.xray, [self.specimens[0]], model=mismatch)
        lm_queue = {"ids": self.landmark_ids, "kind": "landmark"}
        self.landmark.set_ui_state("crop_active_batch", lm_queue)
        xr_queue = self.xray.start_structure_batch(8)
        shell, errors = self.make_shell()
        for _ in range(5):
            for key in ("landmarks", "xray_counts"):
                shell.open_module(key)
                shell.update()
                shell.show_module_hub()
            self.assertEqual("lm_only", Project.open(self.landmark.root).active_model("landmark")["model_id"])
            self.assertEqual("xr_only", XRayProject(self.xray.root).active_structure_model()["model_id"])
            self.assertEqual(lm_queue, self.landmark.get_ui_state("crop_active_batch"))
            self.assertEqual(xr_queue, self.xray.structure_batch())
            self.assertIsNone(self.landmark.get_ui_state("xray_structure_active_batch"))
            self.assertEqual({}, self.xray.get_ui_state("crop_active_batch"))
        self.assertEqual([], errors)
        self.assertEqual([], shell.module_registry.diagnostics)


if __name__ == "__main__":
    unittest.main()
