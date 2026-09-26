"""Behavioral checks for the installed extension boundary."""
import json
import inspect
import tempfile
import tkinter as tk
import time
import unittest
from threading import Event
from pathlib import Path
from types import SimpleNamespace
from dataclasses import fields
from unittest.mock import patch
from PIL import Image

from app.ai import InferenceRequest, LandmarkBackend, MockBackend
from app.ai_batch import BatchError, backend_for_model
from app.extensions.api import BackendContext, BackendSpec, EXTENSION_API_VERSION, ModuleHost, ModuleSpec
from app.extensions.builtins import backend_registry, module_registry
from app.extensions.discovery import discover_backends, discover_modules
from app.extensions.registry import BackendRegistry, ModuleRegistry


def fake_module(module_id="external", order=5, api_version=1, factory=None):
    return ModuleSpec(module_id, "External science", "Test workspace", "1", api_version, order,
                      "available", factory or (lambda: FakeRuntime()), "test")


def fake_backend(backend_id="external", api_version=1):
    return BackendSpec(backend_id, "External backend", "landmark", "1", api_version,
                       lambda context: MockBackend("schema", model_id=context.model["model_id"]), "test")


class FakeRuntime:
    def __init__(self, project_path=None):
        self.rendered = False
        self.closed = False
        self.project_path = project_path
        self.project_seen = None
        self.label_text = None

    def render(self, host):
        self.rendered = True
        self.project_seen = host.project
        self.label_text = "Project loaded" if host.project is not None else "External workspace ready"
        tk.Label(host.container, text=self.label_text).pack()
        tk.Button(host.container, text="Modules", command=host.show_module_hub).pack()
        if self.project_path is not None and host.project is None:
            tk.Button(host.container, text="Open project", command=lambda: host.open_project(self.project_path)).pack()
        self.has_project_actions = callable(host.open_project) and callable(host.new_project)

    def close(self):
        self.closed = True


class CountingRuntime:
    def __init__(self, fail_render=False):
        self.close_count=0
        self.fail_render=fail_render
    def render(self, _host):
        if self.fail_render:raise RuntimeError("render exploded")
    def close(self):self.close_count+=1


class FakeEntryPoint:
    def __init__(self, name, provider=None, error=None):
        self.name = name
        self.value = f"test:{name}"
        self.provider = provider
        self.error = error

    def load(self):
        if self.error:
            raise self.error
        return self.provider


class FakeEntryPoints(list):
    def select(self, *, group):
        return self


class ExtensionArchitectureTests(unittest.TestCase):
    def _shell(self):
        from app.ui.shell import ProductionShell
        with patch("app.extensions.discovery.entry_points",return_value=FakeEntryPoints()), \
             patch("app.ui.shell.last_project",return_value=None), \
             patch.object(ProductionShell,"_warm_ai_hardware",return_value=None):
            shell=ProductionShell()
        shell.withdraw()
        shell.module_registry=module_registry()
        return shell

    @staticmethod
    def _destroy_shell(shell):
        try:shell.update()
        except tk.TclError:pass
        shell.destroy()

    def test_builtin_modules_and_order(self):
        registry = module_registry()
        self.assertEqual("Landmarks & measurements", registry.get("landmarks").display_name)
        self.assertEqual("builtin", registry.get("landmarks").source)
        self.assertEqual("X-ray counts", registry.get("xray_counts").display_name)
        self.assertEqual("Scales & meristics", registry.get("scales_meristics").display_name)
        self.assertEqual(("landmarks",), tuple(item.module_id for item in registry.available()))
        self.assertEqual(("xray_counts", "scales_meristics"), tuple(item.module_id for item in registry.planned()))

    def test_deterministic_order_and_duplicate_module(self):
        registry = ModuleRegistry()
        registry.register(fake_module("z", 2))
        registry.register(fake_module("b", 1))
        registry.register(fake_module("a", 1))
        self.assertEqual(("a", "b", "z"), tuple(item.module_id for item in registry.available()))
        with self.assertRaisesRegex(ValueError, "duplicate module id"):
            registry.register(fake_module("a"))

    def test_incompatible_module_is_disabled(self):
        registry = ModuleRegistry()
        self.assertFalse(registry.register(fake_module("future", api_version=EXTENSION_API_VERSION + 1)))
        self.assertIsNone(registry.get("future"))
        self.assertIn("incompatible API", registry.diagnostics[0])

    def test_broken_module_entry_point_is_isolated(self):
        entries = FakeEntryPoints((FakeEntryPoint("broken", error=ImportError("missing dependency")),
                                   FakeEntryPoint("good", provider=lambda: fake_module())))
        with patch("app.extensions.discovery.entry_points", return_value=entries):
            registry = module_registry()
        self.assertIsNotNone(registry.get("landmarks"))
        self.assertIsNotNone(registry.get("external"))
        self.assertIn("missing dependency", registry.diagnostics[0])

    def test_external_module_discovery_and_real_gui_open(self):
        from app.ui.shell import ProductionShell
        from app.project_storage import Project
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/"source";source.mkdir()
            Image.new("RGB",(40,30)).save(source/"fish.png")
            schema=root/"schema.csv";schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n",encoding="utf-8")
            project=Project.create("external-host",source,root,schema,source_types=["png"],source_layout="direct")
            runtime=FakeRuntime(project.root)
            entries = FakeEntryPoints((FakeEntryPoint("external", provider=lambda: fake_module(factory=lambda: runtime)),))
            with patch("app.extensions.discovery.entry_points", return_value=entries), \
                 patch("app.ui.shell.last_project", return_value=None), \
                 patch.object(ProductionShell, "_warm_ai_hardware", return_value=None):
                shell = ProductionShell()
            try:
                shell.withdraw()
                self.assertIn("external", [spec.module_id for spec in shell.module_registry.available()])
                labels = self._widget_texts(shell.section_host)
                self.assertIn("External science", labels)
                shell.open_module("external")
                shell.update_idletasks()
                self.assertTrue(runtime.rendered)
                self.assertIsNone(runtime.project_seen)
                self.assertTrue(runtime.has_project_actions)
                next(w for w in shell.root.winfo_children() if isinstance(w,tk.Button) and w.cget("text")=="Open project").invoke()
                deadline=time.monotonic()+5
                while shell.context.project is None and time.monotonic()<deadline:
                    shell.update()
                    time.sleep(0.02)
                self.assertIsNotNone(shell.context.project)
                self.assertEqual("external",shell.module_key)
                self.assertIs(runtime.project_seen,shell.context.project)
                self.assertEqual("Project loaded",runtime.label_text)
                next(w for w in shell.root.winfo_children() if isinstance(w,tk.Button) and w.cget("text")=="Modules").invoke()
                self.assertTrue(runtime.closed)
            finally:self._destroy_shell(shell)

    def test_module_switch_and_hub_close_each_runtime_once(self):
        shell=self._shell();a=CountingRuntime();b=CountingRuntime()
        try:
            shell.module_registry.register(fake_module("a",factory=lambda:a))
            shell.module_registry.register(fake_module("b",factory=lambda:b))
            shell.open_module("a")
            shell.open_module("b")
            self.assertEqual(1,a.close_count)
            self.assertEqual("b",shell.module_key)
            shell.show_module_hub()
            self.assertEqual(1,b.close_count)
            self.assertIsNone(shell._active_module_runtime)
        finally:self._destroy_shell(shell)

    def test_broken_factory_returns_to_hub_and_builtins_still_open(self):
        shell=self._shell();a=CountingRuntime()
        def broken_factory():raise RuntimeError("factory exploded")
        try:
            shell.module_registry.register(fake_module("a",factory=lambda:a))
            shell.module_registry.register(fake_module("broken",factory=broken_factory))
            shell.open_module("a")
            with patch("app.ui.shell.messagebox.showerror") as show_error:
                shell.open_module("broken")
            show_error.assert_called_once()
            self.assertEqual(1,a.close_count)
            self.assertIsNone(shell.module_key)
            self.assertIsNone(shell._active_module_runtime)
            self.assertIn("factory exploded",shell.module_registry.diagnostics[-1])
            shell.open_module("landmarks")
            self.assertEqual("landmarks",shell.module_key)
            self.assertIsNotNone(shell.current_view)
        finally:self._destroy_shell(shell)

    def test_broken_render_closes_once_and_returns_to_hub(self):
        shell=self._shell();broken=CountingRuntime(fail_render=True)
        try:
            shell.module_registry.register(fake_module("broken",factory=lambda:broken))
            with patch("app.ui.shell.messagebox.showerror") as show_error:
                shell.open_module("broken")
            show_error.assert_called_once()
            self.assertEqual(1,broken.close_count)
            self.assertIsNone(shell.module_key)
            self.assertIsNone(shell._active_module_runtime)
            self.assertIn("render exploded",shell.module_registry.diagnostics[-1])
        finally:self._destroy_shell(shell)

    @staticmethod
    def _widget_texts(widget):
        texts = []
        for child in widget.winfo_children():
            try:
                value = child.cget("text")
                if value:
                    texts.append(value)
            except tk.TclError:
                pass
            texts.extend(ExtensionArchitectureTests._widget_texts(child))
        return texts

    def test_hub_gets_names_from_registry_and_shell_dispatch_is_generic(self):
        root = Path(__file__).resolve().parents[1]
        hub = (root / "app/ui/module_hub.py").read_text(encoding="utf-8")
        shell = (root / "app/ui/shell.py").read_text(encoding="utf-8")
        for name in ("Landmarks & measurements", "X-ray counts", "Scales & meristics"):
            self.assertNotIn(name, hub)
        self.assertIn("self.shell.open_module(key)", hub)
        self.assertIn("spec.factory()", shell)
        self.assertNotIn('if module_id == "landmarks"', shell)
        self.assertNotIn('if module_id != "landmarks"', shell)
        public_api=(root/"app/extensions/api.py").read_text(encoding="utf-8")
        self.assertNotIn("_render_core",public_api)
        self.assertNotIn("_open_core",public_api)
        self.assertNotIn("ProductionShell",inspect.getsource(FakeRuntime))
        self.assertNotIn("._",inspect.getsource(FakeRuntime))
        self.assertEqual({"container","project","show_module_hub","open_project","new_project"},
                         {item.name for item in fields(ModuleHost)})
        registry_source=(root/"app/extensions/registry.py").read_text(encoding="utf-8")
        self.assertNotIn("LandmarkBackend",registry_source+public_api)

    def test_builtin_landmarks_opens_existing_core_sections(self):
        from app.project_storage import Project
        from app.ui.shell import ProductionShell
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            Image.new("RGB", (64, 40)).save(source / "fish.png")
            schema = root / "schema.csv"
            schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n", encoding="utf-8")
            project = Project.create("extension-smoke", source, root, schema, source_types=["png"], source_layout="direct")
            with patch("app.ui.shell.last_project", return_value=None), \
                 patch.object(ProductionShell, "_warm_ai_hardware", return_value=None):
                shell = ProductionShell()
            try:
                shell.withdraw()
                shell.open_module("landmarks")
                shell.context.project = project
                shell.context.invalidate_catalog()
                for section in ("project", "crop", "landmarks", "measurements", "export"):
                    shell.select(section)
                    shell.update_idletasks()
                    self.assertEqual(section, shell.context.section)
                    self.assertIsNotNone(shell.current_view)
                self.assertEqual("landmarks", shell.module_key)
            finally:
                shell.destroy()

    def test_builtin_and_fake_backend_contract(self):
        registry = backend_registry()
        self.assertEqual("RTMPose", registry.get("rtmpose").display_name)
        self.assertEqual("builtin", registry.get("rtmpose").source)
        registry = BackendRegistry()
        registry.register(fake_backend())
        backend = registry.get("external").factory(SimpleNamespace(model={"model_id": "fake"}))
        self.assertIsInstance(backend, LandmarkBackend)
        request = InferenceRequest("fish", Path("fish.png"), ({"id": 1},), "schema", 100, 100)
        self.assertEqual("fish", backend.predict(request).image_id)

    def test_task_neutral_registry_accepts_xray_but_landmark_consumer_rejects_it(self):
        registry=BackendRegistry()
        xray=BackendSpec("external_xray","X-ray backend","xray","1",1,lambda _ctx:object(),"test")
        self.assertTrue(registry.register(xray))
        self.assertIs(xray,registry.get("external_xray"))
        with tempfile.TemporaryDirectory() as folder:
            artifact=Path(folder)/"model";artifact.mkdir()
            (artifact/"model.json").write_text(json.dumps({"backend_id":"external_xray"}),encoding="utf-8")
            project=SimpleNamespace(data_root=Path(folder),schema_path=Path(folder)/"schema.csv")
            model={"model_id":"fish","kind":"landmark","path":"model"}
            with patch("app.ai_batch.landmark_model_schema_compatible",return_value=True), \
                 patch("app.ai_batch.auto_performance_config",return_value={"device":"cpu","batch_size":1}):
                with self.assertRaisesRegex(BatchError,"backend is unavailable: external_xray"):
                    backend_for_model(project,"fish",model=model,registry=registry)

    def test_landmark_consumer_rejects_wrong_backend_protocol(self):
        registry=BackendRegistry()
        registry.register(BackendSpec("wrong","Wrong","landmark","1",1,lambda _ctx:object(),"test"))
        with tempfile.TemporaryDirectory() as folder:
            artifact=Path(folder)/"model";artifact.mkdir()
            (artifact/"model.json").write_text(json.dumps({"backend_id":"wrong"}),encoding="utf-8")
            project=SimpleNamespace(data_root=Path(folder),schema_path=Path(folder)/"schema.csv")
            model={"model_id":"fish","kind":"landmark","path":"model"}
            with patch("app.ai_batch.landmark_model_schema_compatible",return_value=True), \
                 patch("app.ai_batch.auto_performance_config",return_value={"device":"cpu","batch_size":1}):
                with self.assertRaisesRegex(BatchError,"did not return a LandmarkBackend"):
                    backend_for_model(project,"fish",model=model,registry=registry)

    def test_rtmpose_builtin_provider_preserves_existing_artifacts(self):
        from app.rtmpose_backend import RTMPoseBackend
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            schema = root / "schema.csv"
            schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n", encoding="utf-8")
            artifact = root / "model"
            artifact.mkdir()
            (artifact / "config.py").write_text("# test config\n", encoding="utf-8")
            (artifact / "best_engineering_validation.pth").write_bytes(b"test checkpoint")
            context = BackendContext(SimpleNamespace(schema_path=schema), {"model_id": "old_model"},
                                     artifact, {}, (512, 256), {"device": "cpu", "batch_size": 1})
            backend = backend_registry().get("rtmpose").factory(context)
            self.assertIsInstance(backend, RTMPoseBackend)
            self.assertEqual("old_model", backend.model_id)
            self.assertEqual(artifact / "config.py", backend.spec.config_path)

    def test_backend_duplicate_and_incompatible(self):
        registry = BackendRegistry()
        registry.register(fake_backend())
        with self.assertRaisesRegex(ValueError, "duplicate backend id"):
            registry.register(fake_backend())
        self.assertFalse(registry.register(fake_backend("future", EXTENSION_API_VERSION + 1)))
        self.assertIsNone(registry.get("future"))
        self.assertIn("incompatible API", registry.diagnostics[0])

    def test_backend_discovery_isolates_broken_provider(self):
        entries = FakeEntryPoints((FakeEntryPoint("bad", error=ImportError("broken backend")),
                                   FakeEntryPoint("good", provider=lambda: fake_backend())))
        with patch("app.extensions.discovery.entry_points", return_value=entries):
            registry = discover_backends(BackendRegistry())
        self.assertIsNotNone(registry.get("external"))
        self.assertIn("broken backend", registry.diagnostics[0])

    def test_slow_entry_point_is_disabled_without_stalling_startup(self):
        release = Event()
        def slow_provider():
            release.wait(1)
            return fake_module("slow")
        entries = FakeEntryPoints((FakeEntryPoint("slow", provider=slow_provider),))
        try:
            with patch("app.extensions.discovery.entry_points", return_value=entries), \
                 patch("app.extensions.discovery.LOAD_TIMEOUT_SECONDS", 0.01):
                registry = discover_modules(ModuleRegistry())
            self.assertIsNone(registry.get("slow"))
            self.assertIn("load exceeded", registry.diagnostics[0])
        finally:
            release.set()

    def test_core_backend_construction_uses_provider_id_without_rtmpose_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = Path(folder) / "model"
            artifact.mkdir()
            (artifact / "model.json").write_text(json.dumps({"backend_id": "external"}), encoding="utf-8")
            project = SimpleNamespace(data_root=Path(folder), schema_path=Path(folder) / "schema.csv")
            model = {"model_id": "fake", "kind": "landmark", "path": "model"}
            registry = BackendRegistry()
            registry.register(fake_backend())
            with patch("app.ai_batch.landmark_model_schema_compatible", return_value=True), \
                 patch("app.ai_batch.auto_performance_config", return_value={"device": "cpu", "batch_size": 1}):
                selected, backend = backend_for_model(project, "fake", model=model, registry=registry)
            self.assertIs(selected, model)
            self.assertIsInstance(backend, LandmarkBackend)

    def test_existing_metrics_select_backend_without_package_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact = Path(folder) / "model"
            artifact.mkdir()
            (artifact / "model.json").write_text("{}", encoding="utf-8")
            project = SimpleNamespace(data_root=Path(folder), schema_path=Path(folder) / "schema.csv")
            model = {"model_id": "fake", "kind": "landmark", "path": "model",
                     "metrics_json": json.dumps({"backend": "external"})}
            registry = BackendRegistry()
            registry.register(fake_backend())
            with patch("app.ai_batch.landmark_model_schema_compatible", return_value=True), \
                 patch("app.ai_batch.auto_performance_config", return_value={"device": "cpu", "batch_size": 1}):
                _, backend = backend_for_model(project, "fake", model=model, registry=registry)
            self.assertIsInstance(backend, LandmarkBackend)


if __name__ == "__main__":
    unittest.main()
