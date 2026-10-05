"""Executable third-module, inference adapter and scientific isolation proofs."""
import copy
import hashlib
import json
import sqlite3
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from app.ai import MockBackend
from app.ai_batch import BatchError, backend_for_model
from app.ai_package import AIPackageError, export_model_package, import_model_package
from app.extensions.api import BackendSpec, ModuleSpec
from app.extensions.registry import BackendRegistry
from app.extensions.builtins import backend_registry
from app.landmark_ai_service import LandmarkAIService
from app.project_storage import Project, schema_hash
from app.xray_project import XRayProject
from app.xray_structure_ai import (
    STRUCTURE_BACKEND, XRayStructureAIError, XRayStructurePackageError,
    export_structure_model_package, import_structure_model_package,
    predict_structures, structure_schema_digest, train_structure_model,
    compare_structure_model_to_human, backend_for_structure_model,
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

    def structure_registry(self):
        operations = []
        registry = BackendRegistry()
        registry.register(backend_registry().get(STRUCTURE_BACKEND))

        class Alternate:
            def train(inner, payload, timeout):
                operations.append("train")
                manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual("alternate_structure", manifest["backend"])
                self.assertEqual({"objects", "boundary"}, {s["id"] for s in manifest["structures"]})
                self.assertFalse({r["image_id"] for r in manifest["train"]} & {r["image_id"] for r in manifest["val"]})
                target = Path(payload["work_dir"]); target.mkdir(parents=True)
                checkpoint, metadata = target / "alternate.bin", target / "metadata.json"
                checkpoint.write_bytes(b"alternate independent provider")
                metadata.write_text(json.dumps({"backend": "alternate_structure", "structures": manifest["structures"],
                                               "input_size": [160, 100], "training_objective": "synthetic"}), encoding="utf-8")
                return {"checkpoint": str(checkpoint), "metadata": str(metadata),
                        "metrics": {"test_metric": .75, "backend": "cannot_override_truth", "schema_digest": "cannot_override_truth"}}

            def predict_many(inner, payload, timeout):
                operations.append("predict_many")
                self.assertEqual("alternate_structure", json.loads(Path(payload["metadata"]).read_text())["backend"])
                return {"results": [{"structures": [
                    {"structure_id": "objects", "points": [{"x": .2, "y": .5, "score": .9}, {"x": .6, "y": .5, "score": .9}]},
                    {"structure_id": "boundary", "points": [{"x": .6, "y": .5, "score": .9}]},
                ]} for _ in payload["images"]]}

        def factory(context):
            self.assertFalse(hasattr(context, "project"))
            return Alternate()
        registry.register(BackendSpec("alternate_structure", "Independent structure provider", "xray_structure", "1", 1, factory, "test"))
        return registry, operations

    def test_registered_structure_provider_train_predict_compare_package_activate_reopen(self):
        for sid in self.specimens:self.complete_xray(sid)
        registry, operations = self.structure_registry()
        p = self.xray
        with closing(sqlite3.connect(p.db_path)) as db:
            schema = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        settings = {"training": {"device": "cpu", "batch_size": 2}, "inference": {"device": "cpu", "batch_size": 2}}
        # An independent registered provider must never reach managed runtime/runner.
        with patch("app.xray_structure_ai.ensure_ai_runtime", side_effect=AssertionError("built-in runtime used")), \
             patch("app.xray_structure_ai._run", side_effect=AssertionError("built-in runner used")), \
             patch("app.xray_structure_ai.structure_performance_settings", return_value=settings):
            parent = train_structure_model(p, seed=17, epochs=1, registry=registry, backend_id="alternate_structure")
            child = train_structure_model(p, seed=17, epochs=1, registry=registry)
            self.assertEqual(parent["model_id"], p.active_structure_model()["parent_model_id"])
            self.assertEqual("alternate_structure", child["metrics"]["backend"])
            self.assertEqual(structure_schema_digest(p.scheme), child["metrics"]["schema_digest"])
            self.assertEqual(.75, child["metrics"]["test_metric"])
            from tests.test_architecture_compatibility import persisted_rows
            before_compare = persisted_rows(p)
            report = compare_structure_model_to_human(p, registry=registry)
            self.assertEqual(1.0, report["summary"]["exact_trait_accuracy"])
            self.assertEqual(before_compare, persisted_rows(p), "Comparison must be read-only")
            sid = self.specimens[0]
            prediction = predict_structures(p, [sid], allow_verified=True, registry=registry)
            self.assertEqual([], prediction["failures"])
            event = p.annotation_events(sid)[-1]
            self.assertEqual(child["model_id"], event["payload"]["model_id"])
            p.move_annotation(p.annotations(sid)[0]["annotation_id"], .23, .5);p.verify_annotations(sid)
            package = self.root / "registered-provider.zip"
            export_structure_model_package(p, package)
            with zipfile.ZipFile(package) as archive:
                original = {name: archive.read(name) for name in archive.namelist()}
            # Provider/task/schema checks happen before any scientific registration.
            for field, value, message in (("backend", "wrong_task", "unavailable or incompatible"),
                                          ("backend", STRUCTURE_BACKEND, "backend"),
                                          ("schema_digest", "incompatible", "scheme")):
                payload = dict(original)
                manifest = json.loads(payload["manifest.json"]);manifest[field] = value
                payload["manifest.json"] = json.dumps(manifest).encode()
                bad = self.root / f"bad-{field}-{value}.zip"
                with zipfile.ZipFile(bad, "w") as archive:
                    for name, data in payload.items():archive.writestr(name, data)
                before = persisted_rows(p)
                with self.assertRaisesRegex(XRayStructurePackageError, message):
                    import_structure_model_package(p, bad, registry=registry)
                self.assertEqual(before, persisted_rows(p))
            payload = dict(original)
            metadata = json.loads(payload["artifacts/model.json"]);metadata["backend"] = STRUCTURE_BACKEND
            payload["artifacts/model.json"] = json.dumps(metadata).encode()
            manifest = json.loads(payload["manifest.json"])
            manifest["files"]["artifacts/model.json"] = hashlib.sha256(payload["artifacts/model.json"]).hexdigest()
            payload["manifest.json"] = json.dumps(manifest).encode()
            bad = self.root / "bad-provider-metadata.zip"
            with zipfile.ZipFile(bad, "w") as archive:
                for name, data in payload.items():archive.writestr(name, data)
            before = persisted_rows(p)
            with self.assertRaisesRegex(XRayStructurePackageError, "backend"):
                import_structure_model_package(p, bad, registry=registry)
            self.assertEqual(before, persisted_rows(p))
            imported = import_structure_model_package(p, package, registry=registry)
            p.activate_structure_model(imported)
            reopened = XRayProject(p.root)
            self.assertEqual("alternate_structure", reopened.active_structure_model()["backend"])
            self.assertEqual(child["model_id"], reopened.active_structure_model()["metrics"]["original_model_id"])
            self.assertEqual([], reopened.structure_model_membership(imported))
            members = reopened.structure_model_membership(child["model_id"])
            self.assertEqual(8, len(members));self.assertEqual({"train", "val"}, {r["split"] for r in members})
            self.assertIn(event, reopened.annotation_events(sid))
            self.assertEqual(2, reopened.trait_rows()[0]["trait_values"]["number"])
            self.assertEqual([], predict_structures(reopened, [sid], allow_verified=True, registry=registry)["failures"])
        self.assertIsNotNone(registry.get(STRUCTURE_BACKEND))
        self.assertIsNotNone(registry.get("alternate_structure"))
        self.assertEqual(["train", "train", "predict_many", "predict_many", "predict_many"], operations)
        with closing(sqlite3.connect(p.db_path)) as db:
            self.assertEqual(schema, db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall())

    def test_structure_provider_rejects_wrong_task_protocol_parent_and_package(self):
        registry, _ = self.structure_registry()
        registry.register(BackendSpec("wrong_task", "Landmark task", "landmark", "1", 1, lambda c: object(), "test"))
        registry.register(BackendSpec("bad_protocol", "Bad provider", "xray_structure", "1", 1, lambda c: object(), "test"))
        with self.assertRaisesRegex(XRayStructureAIError, "unavailable or incompatible"):
            train_structure_model(self.xray, backend_id="wrong_task", registry=registry)
        with self.assertRaisesRegex(XRayStructureAIError, "StructureBackend"):
            train_structure_model(self.xray, backend_id="bad_protocol", registry=registry)
        self.xray.register_structure_model("builtin_parent", "unused", "unused", None,
                                           structure_schema_digest(self.xray.scheme), STRUCTURE_BACKEND, {})
        with self.assertRaisesRegex(XRayStructureAIError, "parent model is incompatible"):
            train_structure_model(self.xray, backend_id="alternate_structure", registry=registry)
        mismatch = dict(self.xray.active_structure_model(), backend="wrong_task")
        with self.assertRaisesRegex(XRayStructureAIError, "unavailable or incompatible"):
            predict_structures(self.xray, model=mismatch, registry=registry)
        with self.assertRaisesRegex(XRayStructureAIError, "incompatible"):
            backend_for_structure_model(self.xray, dict(mismatch, schema_digest="different"), registry=registry)
        directory = self.xray.models_root / "bad_identity";directory.mkdir()
        (directory / "model.pth").write_bytes(b"test")
        (directory / "model.json").write_text(json.dumps({"backend": STRUCTURE_BACKEND}))
        model = dict(self.xray.active_structure_model(), backend="alternate_structure",
                     path=str((directory / "model.pth").relative_to(self.xray.root)),
                     metadata_path=str((directory / "model.json").relative_to(self.xray.root)))
        with self.assertRaisesRegex(XRayStructureAIError, "backend identity"):
            backend_for_structure_model(self.xray, model, registry=registry)

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
                    self.assertIs(self.landmark, runtime.project)
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
