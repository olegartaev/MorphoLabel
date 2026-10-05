"""Real Tk runtime ownership, 100-cycle switching and disposable reopen proofs."""
import ast
import gc
import json
import random
import traceback
import unittest
import weakref
from dataclasses import dataclass, field, fields
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from app.extensions.api import ModuleHost, ModuleSpec
from app.modules.landmarks import LandmarksRuntime
from app.project_storage import Project
from app.ui.context import UIContext
from app.xray_project import XRayProject
from tests.test_architecture_compatibility import persisted_rows
from tests import test_release_torture as fixtures
from tests.current_fixtures import make_reviewed_crop


@dataclass
class ThirdProject:
    samples: list = field(default_factory=lambda: [(7, 9)])


class FourthProject:
    def __init__(self):
        self.graph = {"node": frozenset({"other"})}


class ArbitraryRuntime:
    def __init__(self, project):
        self.project = project
        self.close_count = 0
        self.widget = None

    def render(self, host):
        self.host = host
        self.project = host.state.setdefault("project", self.project)
        self.widget = ttk.Label(host.container, text="Arbitrary science")
        self.widget.pack()

    def close(self):
        self.close_count += 1
        self.widget = None
        self.host = None


def scientific_rows(project):
    rows = persisted_rows(project, include_ui=False)
    if isinstance(project, Project):
        rows["project"] = [r for r in rows["project"] if not r["key"].startswith("ui.")]
    return rows


class ArchitectureTortureTests(unittest.TestCase):
    def setUp(self):
        fixtures.ReleaseTortureTests.setUp(self)
        self.unraisable = []
        hook = patch("sys.unraisablehook", side_effect=lambda event: self.unraisable.append(str(event.exc_value)))
        hook.start();self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual([], self.unraisable, "Tcl object teardown failed"))
    make_shell = fixtures.ReleaseTortureTests.make_shell
    complete_xray = fixtures.ReleaseTortureTests.complete_xray
    export_bytes = fixtures.ReleaseTortureTests.export_bytes

    def prepare_science(self):
        for ident in self.landmark_ids:
            make_reviewed_crop(self.landmark, ident, 160, 100)
            self.landmark.save_landmark(ident, 1, 10, 10, "manual")
            self.landmark.save_landmark(ident, 2, 16, 18, "manual")
            self.landmark.mark_checked(ident)
        for sid in self.specimens:self.complete_xray(sid)
        self.landmark.set_ui_state("crop_active_batch", {"ids": self.landmark_ids, "position": 1})
        self.xray.set_ui_state("xray_structure_active_batch", {"ids": self.specimens, "position": 1, "pass_no": 1})
        self.xray.set_current_selection(specimen_id=self.specimens[1])

    def test_shell_has_no_landmark_scientific_construction_or_project_contract(self):
        from app.ui.shell import ProductionShell
        shell = Path(__file__).resolve().parents[1] / "app/ui/shell.py"
        tree = ast.parse(shell.read_text(encoding="utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(node.module and any(token in node.module for token in
                         ("project_storage", "internal_runtime", "landmarks", "crop_section", "measurements")) for node in imports))
        for name in ("_render_landmarks_workspace", "open_project", "new_project", "_attach_project",
                     "open_landmark_attention", "show_models", "select", "_landmark_queue_entries"):
            self.assertFalse(hasattr(ProductionShell, name), name)
        self.assertFalse(hasattr(LandmarksRuntime, "_bind_core"))
        self.assertFalse((shell.parents[1] / "extensions/internal_runtime.py").exists())
        self.assertFalse({"project", "open_project", "new_project"} & {f.name for f in fields(ModuleHost)})
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                self.assertNotIn("landmarks", ast.unparse(node.test))

    def register_arbitrary(self, shell):
        records = []
        for ident, project in (("third", ThirdProject()), ("fourth", FourthProject())):
            def factory(p=project):
                runtime = ArbitraryRuntime(p);records.append(runtime);return runtime
            shell.module_registry.register(ModuleSpec(ident, ident.title(), "Test science", "1", 1,
                                                       15, "available", factory, "test"))
        return records

    def test_100_cycles_stages_arbitrary_projects_exact_science_and_close(self):
        self.prepare_science()
        shell, errors = self.make_shell()
        records = self.register_arbitrary(shell)
        selected = self.landmark_ids[1]
        shell.module_states["landmarks"]["context"].select_image(selected)
        before = [scientific_rows(p) for p in (self.landmark, self.xray)]
        queues = (self.landmark.get_ui_state("crop_active_batch"), self.xray.structure_batch())
        released = []
        history = []
        for cycle in range(100):
            try:
                for key in ("landmarks", "xray_counts", "third"):
                    history.append((cycle, key))
                    shell.open_module(key)
                    runtime = shell._active_module_runtime
                    if key == "landmarks":
                        self.assertIs(self.landmark, runtime.project)
                        runtime.select(("project", "crop", "landmarks", "measurements", "export")[cycle % 5])
                        self.assertEqual(selected, runtime.context.current()["image_id"])
                        runtime.after_idle(lambda: None)
                    elif key == "xray_counts":
                        self.assertEqual(self.xray.root, runtime.project.root)
                        runtime._select(("project", "crops", "structures", "export")[cycle % 4])
                        self.assertEqual(self.specimens[1], runtime.project.current_selection()["specimen_id"])
                    else:
                        self.assertIsInstance(runtime.project, ThirdProject)
                        self.assertEqual([(7, 9)], runtime.project.samples)
                        released.append(weakref.ref(runtime.widget))
                    shell.update()
                    released.append(weakref.ref(runtime)) if key != "third" else None
                    with patch.object(runtime, "close", wraps=runtime.close) as close:
                        shell.show_module_hub();close.assert_called_once()
                    shell.update()
                    self.assertIsNone(shell._active_module_runtime)
                    self.assertEqual([], errors)
                    self.assertEqual([], shell.module_registry.diagnostics)
                    del runtime, close
                self.assertEqual(before, [scientific_rows(p) for p in (self.landmark, self.xray)])
                self.assertEqual(queues, (self.landmark.get_ui_state("crop_active_batch"), self.xray.structure_batch()))
                self.assertIsNone(self.landmark.get_ui_state("xray_structure_active_batch"))
                self.assertEqual({}, self.xray.get_ui_state("crop_active_batch"))
            except Exception:
                self.fail(f"cycle={cycle}; ordered_operations={history}\n{traceback.format_exc()}")
        shell.open_module("fourth")
        fourth = shell._active_module_runtime
        self.assertIsInstance(fourth.project, FourthProject)
        self.assertEqual({"node": frozenset({"other"})}, fourth.project.graph)
        shell.show_module_hub()
        self.assertTrue(all(r.close_count == 1 for r in records))
        gc.collect()
        self.assertTrue(all(ref() is None for ref in released), "Runtime or widget retained after close")

    def test_edit_save_switch_close_reopen_exports_four_lifecycles(self):
        self.prepare_science()
        for life in range(4):
            shell, errors = self.make_shell()
            shell.open_module("landmarks")
            runtime = shell._active_module_runtime
            ident = self.landmark_ids[0]
            self.landmark.save_landmark(ident, 1, 10 + life, 10, "corrected", provenance="corrected_by_human")
            self.landmark.mark_checked(ident)
            runtime.context.refresh(force=True);runtime.select("landmarks");shell.update()
            shell.show_module_hub()
            shell.open_module("xray_counts")
            sid = self.specimens[0]
            point = self.xray.annotations(sid)[0]
            self.xray.move_annotation(point["annotation_id"], .23 + life * .01, .5)
            self.xray.verify_annotations(sid)
            shell._active_module_runtime._select("structures");shell.update()
            before = [persisted_rows(p) for p in (self.landmark, self.xray)]
            exports = [self.export_bytes(p) for p in (self.landmark, self.xray)]
            shell.destroy();gc.collect()
            self.landmark = Project.open(self.landmark.root);self.xray = XRayProject(self.xray.root)
            self.assertEqual(before, [persisted_rows(p) for p in (self.landmark, self.xray)])
            self.assertEqual(exports, [self.export_bytes(p) for p in (self.landmark, self.xray)])
            self.assertEqual([], errors)

    def test_seeded_architecture_switch_reopen_101(self):
        self.prepare_science();shell, errors = self.make_shell()
        self.register_arbitrary(shell)
        rng = random.Random(101);history = []
        before = [scientific_rows(p) for p in (self.landmark, self.xray)]
        for _ in range(60):
            key = rng.choice(("landmarks", "xray_counts", "third", "fourth", "reopen"))
            history.append(key)
            try:
                if key == "reopen":
                    shell.show_module_hub()
                    self.landmark = Project.open(self.landmark.root);self.xray = XRayProject(self.xray.root)
                    shell.module_states["landmarks"]["context"] = UIContext(self.landmark)
                    shell.module_states.setdefault("xray_counts", {})["project"] = self.xray
                else:
                    shell.open_module(key);shell.update();shell.show_module_hub()
                self.assertEqual(before, [scientific_rows(p) for p in (self.landmark, self.xray)])
                self.assertEqual([], errors);self.assertEqual([], shell.module_registry.diagnostics)
            except Exception:
                self.fail(f"seed=101; ordered_operations={json.dumps(history)}\n{traceback.format_exc()}")

    def test_explicit_module_projects_override_unrelated_remembered_project(self):
        shell, errors = self.make_shell()
        shell.module_states["xray_counts"] = {"project": self.xray}
        with patch("app.modules.xray_counts.last_xray_project", side_effect=AssertionError("explicit project replaced")):
            shell.open_module("xray_counts")
            self.assertIs(self.xray, shell._active_module_runtime.project)
            shell.show_module_hub()
        shell.open_module("landmarks")
        self.assertEqual(self.landmark.root, shell._active_module_runtime._remembered_project_path)
        self.assertEqual([], errors)

    def test_closing_module_releases_pending_layout_and_schema_callbacks(self):
        from app.ui.design import FlowRow
        shell, errors = self.make_shell()
        shell.open_module("landmarks")
        runtime = shell._active_module_runtime
        runtime.open_schema()
        row = FlowRow(shell.root);row.relayout()
        with patch.object(runtime, "_run_background_task", side_effect=AssertionError("closed schema reload")):
            shell.show_module_hub()
            shell.update()
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
