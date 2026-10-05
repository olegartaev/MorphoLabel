"""Deterministic release journeys using disposable projects and real Tk views.

Run with python -m unittest -v tests.test_release_torture. AI uses MockBackend
or schema-level seeds; no runtime installation, downloads or training occur.
"""
import copy
import gc
import json
import os
import random
import tempfile
import traceback
import unittest
import weakref
from pathlib import Path
from importlib.metadata import EntryPoints
from contextlib import closing
import sqlite3
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.ai import MockBackend
from app.landmark_ai_service import LandmarkAIService
from app.landmark_attention_queue import clear, move, start
from app.landmark_dataset import training_ready_image_ids
from app.measurements import export_measurements, save_measurements, values_for_image
from app.project_runtime import record, scoped_project
from app.project_storage import Project, schema_hash
from app.ui.context import UIContext
from app.ui.preferences import (last_project, last_xray_project, remember_project,
                                remember_xray_project)
from app.workflow import save_record, set_human_point
from app.xray_crop import crop_from_geometry
from app.xray_crop_ui import PlateCropEditSession, apply_and_confirm_plate
from app.xray_project import XRayProject
from app.xray_result_qc import (build_result_qc, clear_result_review_queue,
                               result_review_queue, start_result_review_queue)
from app.xray_schema import blank_scheme, normalize_scheme
from app.xray_structure_ai import (XRayStructureAIError, predict_structures,
                                   prepare_structure_training_dataset,
                                   structure_schema_digest)
from app.xray_trait_export import export_trait_rows
from tests.current_fixtures import make_reviewed_crop


class ReleaseTortureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="morpholabel_release_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        isolated = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local"),
                                           "APPDATA": str(self.root / "roaming")})
        isolated.start()
        self.addCleanup(isolated.stop)
        source = self.root / "source"
        source.mkdir()
        for index in range(4):
            image = Image.new("RGB", (160, 100), (30 + index, 50, 70))
            ImageDraw.Draw(image).rectangle((20, 30, 140, 70), fill=(160, 170, 180))
            image.save(source / f"{index}.png")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        self.landmark = Project.create("landmark", source, self.root, schema,
                                       source_types=["png"], source_layout="direct")
        self.landmark_ids = [r["image_id"] for r in self.landmark.catalog_rows()]
        scheme = blank_scheme("Synthetic taxon-neutral objects")
        scheme["structures"] = [
            {"id": "objects", "name": "Objects", "repeated": True},
            {"id": "boundary", "name": "Boundary", "reuse_from": ["objects"],
             "learning_relation": "role_on_structure"},
        ]
        scheme["traits"] = [
            {"id": "number", "name": "Number", "abbr": "N", "method": "count",
             "structures": ["objects"], "rule": {}},
        ]
        self.xray = XRayProject.create("xray", source, self.root, normalize_scheme(scheme))
        self.plates = [r["image_id"] for r in self.xray.source_images()]
        self.specimens = []
        for plate in self.plates:
            for cx in (45, 115):
                crop = crop_from_geometry(cx, 50, 65, 50, 0, (160, 100), algorithm="manual")
                self.specimens.append(self.xray.add_manual_specimen(plate, crop))
            self.xray.confirm_plate(plate)

    def complete_xray(self, sid, pass_no=1, offset=0):
        first = self.xray.add_annotation(sid, "objects", .2 + offset, .5, pass_no)
        second = self.xray.add_annotation(sid, "objects", .6 + offset, .5, pass_no)
        self.xray.assign_annotation_role(second, "boundary")
        self.xray.verify_annotations(sid, pass_no)
        return first, second

    def export_bytes(self, project):
        if isinstance(project, XRayProject):
            path = self.root / "traits.csv"
            export_trait_rows(project, path)
            return path.read_bytes()
        outputs = project.sync_results()
        return {key: value.read_bytes() for key, value in outputs.items() if isinstance(value, Path)}

    def test_landmarks_journey_and_reopen(self):
        p = self.landmark
        ident = self.landmark_ids[0]
        make_reviewed_crop(p, ident, 160, 100)
        predicted = LandmarkAIService(p, MockBackend(schema_hash(p.schema_path))).predict_one(ident)
        manifest = predicted.manifest_path.read_bytes()
        before = p.load_landmarks(ident)[1]
        with scoped_project(p):
            current = record(p, p.catalog_row(ident))
            set_human_point(current, 1, "A", 10, 10, corrected=True)
            set_human_point(current, 2, "B", 16, 18, corrected=True)
            save_record(current)
        p.delete_landmark(ident, 2)
        p.save_landmark(ident, 2, 16, 18, "manual")
        p.mark_checked(ident)
        self.assertTrue(p.annotation_status(ident)["verified"])
        self.assertIn(ident, training_ready_image_ids(p))
        context = UIContext(p)
        context.refresh()
        context.select_image(ident)
        self.assertEqual(1, context.landmark_counts()["Human verified"])
        self.assertEqual(ident, context.current()["image_id"])
        start(p, self.landmark_ids[1:], batch_id="release")
        self.assertEqual(self.landmark_ids[2], move(p, 1)["image_id"])
        clear(p)
        annotations = p.load_landmarks(ident)
        p.exclude_image(ident, "synthetic test")
        self.assertNotIn(ident, training_ready_image_ids(p))
        p.restore_image(ident)
        self.assertEqual(annotations, p.load_landmarks(ident))
        locality = p.catalog_row(ident)["locality"]
        p.set_locality_calibration(locality, ident, 2, "mm", {})
        save_measurements(p, [{"abbr": "LEN", "name": "Length", "point1": 1, "point2": 2}])
        self.assertEqual(5, values_for_image(p, p.catalog_row(ident))[0]["LEN"])
        export_measurements(p)
        exported = self.export_bytes(p)
        # A UI-only row mutation cannot change exported scientific truth.
        context.rows[context.selected]["human_verified"] = False
        self.assertEqual(exported, self.export_bytes(p))
        for _ in range(8):
            p = Project.open(p.root)
            self.assertEqual(annotations, p.load_landmarks(ident))
            self.assertTrue(p.annotation_status(ident)["verified"])
            self.assertFalse(p.get_ui_state("landmark_attention_queue", {}).get("active"))
            self.assertEqual([], p.get_ui_state("landmark_attention_queue", {}).get("image_ids"))
            self.assertEqual(exported, self.export_bytes(p))
            self.assertEqual(manifest, predicted.manifest_path.read_bytes())
            after = p.load_landmarks(ident)[1]
            for field in ("predicted_x", "predicted_y", "model_id", "prediction_run_id"):
                self.assertEqual(before[field], after[field])

    def test_xray_journey_repeatability_and_reopen(self):
        p = self.xray
        sid = self.specimens[0]
        session = PlateCropEditSession(p.specimens(self.plates[0]), sid)
        session.flip_horizontal()
        session.flip_vertical()
        draft = session.add(crop_from_geometry(80, 80, 25, 20, 0, (160, 100), algorithm="manual"))
        session.delete_selected()
        self.assertNotIn(draft, session.items)
        session.select(sid)
        self.assertEqual(sid, apply_and_confirm_plate(p, self.plates[0], session))
        self.assertEqual("right", p.specimen(sid)["crop"]["head_side"])
        self.assertEqual("top", p.specimen(sid)["crop"]["bottom_side"])
        p.set_current_selection(specimen_id=sid)
        with self.assertRaisesRegex(ValueError, "Missing"):
            p.verify_annotations(sid)
        seed = [{"structure_id": "objects", "x": .2, "y": .5, "score": .9},
                {"structure_id": "objects", "x": .6, "y": .5, "score": .9},
                {"structure_id": "boundary", "x": .6, "y": .5, "score": .9}]
        p.seed_structure_predictions(sid, seed, "synthetic_structure")
        provenance = copy.deepcopy(p.annotation_events(sid)[-1])
        first = p.annotations(sid)[0]["annotation_id"]
        p.move_annotation(first, .25, .5)
        extra = p.add_annotation(sid, "objects", .8, .5)
        p.delete_annotation(extra)
        p.verify_annotations(sid)
        for item in self.specimens[1:]:
            self.complete_xray(item)
        # Re-open draft navigation, exercise Previous/Next, then close it.
        p.move_annotation(first, .26, .5)
        batch = p.start_structure_batch(6)
        self.assertIn(sid, batch["ids"])
        self.assertEqual(sid, p.move_structure_batch(sid, -1)["specimen_id"])
        p.verify_annotations(sid)
        self.assertTrue(p.move_structure_batch(sid, 1)["finished"])
        p.set_ui_state("xray_structure_active_batch", {})
        before = p.effective_annotations(sid)
        numbers = {r["specimen_id"]: (r["workflow_no"], r["ordinal"]) for r in p.structure_specimens()}
        p.set_specimen_excluded(sid)
        self.assertIn(self.specimens[1], {r["specimen_id"] for r in p.structure_specimens()})
        p.set_specimen_excluded(sid, False)
        self.assertEqual(before, p.effective_annotations(sid))
        self.assertEqual(numbers, {r["specimen_id"]: (r["workflow_no"], r["ordinal"]) for r in p.structure_specimens()})
        run = p.start_structure_repeatability(2, seed=17)
        for item in run["ids"]:
            for number, offset in ((run["annotation1_pass_no"], .01), (run["annotation2_pass_no"], .03)):
                self.complete_xray(item, number, offset)
        self.assertEqual("completed", p.structure_repeatability(run["run_id"])["status"])
        self.assertEqual(before, p.effective_annotations(sid))
        dataset = prepare_structure_training_dataset(p, self.root / "dataset", seed=17)
        manifest = json.loads(dataset["manifest"].read_text(encoding="utf-8"))
        for item in manifest["train"] + manifest["val"]:
            self.assertEqual({.5}, {float(point["y"]) for point in item["points"]})
            self.assertFalse(any(abs(float(point["x"]) - .21) < 1e-8 or abs(float(point["x"]) - .23) < 1e-8 for point in item["points"]))
        p.register_structure_model("s1", "fake.pth", "fake.json", None,
                                   structure_schema_digest(p.scheme), "synthetic", {}, dataset["membership"])
        p.register_structure_model("s2", "fake2.pth", "fake2.json", "s1",
                                   structure_schema_digest(p.scheme), "synthetic", {}, dataset["membership"])
        qc = build_result_qc(p)
        start_result_review_queue(p, qc["issues"])
        clear_result_review_queue(p)
        for row in p.trait_rows():
            self.assertEqual(2, row["trait_values"]["number"])
        all_path, verified_path = self.root / "all.csv", self.root / "verified.csv"
        self.assertEqual(len(self.specimens), export_trait_rows(p, all_path)["rows"])
        self.assertEqual(len(self.specimens), export_trait_rows(p, verified_path, True)["rows"])
        p.move_annotation(first, .27, .5)
        self.assertEqual(len(self.specimens)-1, export_trait_rows(p, verified_path, True)["rows"])
        p.verify_annotations(sid)
        exported = self.export_bytes(p)
        for _ in range(8):
            p = XRayProject(p.root)
            self.assertEqual(exported, self.export_bytes(p))
            self.assertEqual(sid, p.current_selection()["specimen_id"])
            self.assertEqual({}, p.structure_batch())
            self.assertFalse(result_review_queue(p))
            self.assertEqual("completed", p.structure_repeatability(run["run_id"])["status"])
            self.assertEqual("s1", p.active_structure_model()["parent_model_id"])
            self.assertEqual(len(self.specimens), len(p.structure_model_membership("s2")))
            self.assertIn(provenance, p.annotation_events(sid))
        changed = copy.deepcopy(p.scheme)
        changed["structures"][0]["id"] = "other"
        changed["structures"][1]["reuse_from"] = ["other"]
        changed["traits"][0]["structures"] = ["other"]
        p.save_scheme(changed)
        with self.assertRaisesRegex(XRayStructureAIError, "incompatible"):
            predict_structures(p, [sid])

    def run_seeded_state_sequence(self, seed):
        for ident in self.landmark_ids:
            make_reviewed_crop(self.landmark, ident, 160, 100)
            self.landmark.save_landmark(ident, 1, 10, 10, "manual")
            self.landmark.save_landmark(ident, 2, 20, 20, "manual")
        for sid in self.specimens:
            self.complete_xray(sid)
        for model_id in ("chaos_lm_a", "chaos_lm_b"):
            directory = self.landmark.models_root / model_id
            directory.mkdir()
            (directory / "model.json").write_text(json.dumps({"backend": "test_only"}), encoding="utf-8")
            self.landmark.register_model(model_id, "landmark", path=directory.relative_to(self.landmark.data_root).as_posix(), active=True)
        for model_id in ("chaos_xr_a", "chaos_xr_b"):
            self.xray.register_structure_model(model_id, "test_only", "test_only.json", None,
                                               structure_schema_digest(self.xray.scheme), "synthetic", {})
        shell, errors = self.make_shell()
        rng = random.Random(seed)
        sequence = []
        for index in range(60):
            kind = rng.choice(("selection", "marker", "exclude", "queue", "crop", "export", "reopen", "verify", "stage", "module", "model"))
            sid = rng.choice(self.specimens)
            ident = rng.choice(self.landmark_ids)
            detail = {"operation": kind, "specimen_index": self.specimens.index(sid),
                      "image_index": self.landmark_ids.index(ident)}
            sequence.append(detail)
            try:
                if kind == "selection":
                    self.xray.set_current_selection(specimen_id=sid)
                elif kind == "marker":
                    point = self.xray.annotations(sid)[0]
                    x = rng.choice((.21, .24, .28))
                    detail["x"] = x
                    self.xray.move_annotation(point["annotation_id"], x, .5)
                    self.landmark.save_landmark(ident, 1, 10 + x, 10, "manual")
                elif kind == "exclude":
                    truth = self.xray.effective_annotations(sid)
                    self.xray.set_specimen_excluded(sid)
                    self.landmark.exclude_image(ident, "chaos")
                    self.xray.set_specimen_excluded(sid, False)
                    self.landmark.restore_image(ident)
                    self.assertEqual(truth, self.xray.effective_annotations(sid))
                elif kind == "queue":
                    self.xray.start_structure_batch(6)
                    self.xray.set_ui_state("xray_structure_active_batch", {})
                    start(self.landmark, self.landmark_ids)
                    clear(self.landmark)
                elif kind == "crop":
                    # A reversible orientation delta on another isolated plate.
                    session = PlateCropEditSession(self.xray.specimens(self.plates[0]), self.specimens[0])
                    session.flip_horizontal()
                    session.flip_horizontal()
                    apply_and_confirm_plate(self.xray, self.plates[0], session)
                    # Applying orientation edits intentionally archives the old
                    # coordinate frame. Re-annotate before later marker edits.
                    edited = self.specimens[0]
                    if not self.xray.annotations(edited):
                        self.assertTrue(self.xray.annotation_archives(edited))
                        self.complete_xray(edited)
                elif kind == "verify":
                    self.xray.verify_annotations(sid)
                    self.landmark.mark_checked(ident)
                elif kind == "reopen":
                    self.landmark = Project.open(self.landmark.root)
                    self.xray = XRayProject(self.xray.root)
                    shell.context = UIContext(self.landmark)
                    shell.context.refresh()
                elif kind == "export":
                    self.assertEqual(self.export_bytes(self.xray), self.export_bytes(XRayProject(self.xray.root)))
                    self.assertEqual(self.export_bytes(self.landmark), self.export_bytes(Project.open(self.landmark.root)))
                elif kind in {"stage", "module"}:
                    key = rng.choice(("landmarks", "xray_counts"))
                    detail["module"] = key
                    shell.open_module(key)
                    if kind == "stage":
                        stages = ("project", "crop", "landmarks", "measurements", "export") if key == "landmarks" else ("project", "crops", "structures", "export")
                        stage = rng.choice(stages)
                        detail["stage"] = stage
                        if key == "landmarks":
                            shell.select(stage)
                        else:
                            shell._active_module_runtime._select(stage)
                    shell.update()
                    shell.show_module_hub()
                elif kind == "model":
                    lm = rng.choice(("chaos_lm_a", "chaos_lm_b"))
                    xr = rng.choice(("chaos_xr_a", "chaos_xr_b"))
                    detail.update(landmark_model=lm, structure_model=xr)
                    self.landmark.set_active_model("landmark", lm)
                    self.xray.activate_structure_model(xr)
                    self.assertEqual(lm, Project.open(self.landmark.root).active_model("landmark")["model_id"])
                    self.assertEqual(xr, XRayProject(self.xray.root).active_structure_model()["model_id"])
                reopened = XRayProject(self.xray.root)
                self.assertEqual(self.xray.effective_annotations(sid), reopened.effective_annotations(sid))
                self.assertEqual(self.xray.current_selection(), reopened.current_selection())
                self.assertEqual(self.landmark.load_landmarks(ident), Project.open(self.landmark.root).load_landmarks(ident))
                self.assertEqual(len(self.specimens), len(reopened.structure_specimens()))
                self.assertEqual([], errors)
                self.assertEqual([], shell.module_registry.diagnostics)
            except Exception:
                self.fail(f"seed={seed}; last_success={index-1}; ordered_operations={json.dumps(sequence)}\n{traceback.format_exc()}")

    def test_seeded_state_sequence_7(self):
        self.run_seeded_state_sequence(7)

    def test_seeded_state_sequence_17(self):
        self.run_seeded_state_sequence(17)

    def test_seeded_state_sequence_73(self):
        self.run_seeded_state_sequence(73)

    def make_shell(self):
        from app.ui.shell import ProductionShell
        dialogs = patch("tkinter.messagebox.showerror", side_effect=lambda title, message, **kw:
                        (_ for _ in ()).throw(AssertionError(f"{title}: {message}")))
        dialogs.start()
        self.addCleanup(dialogs.stop)
        remember_project(self.landmark.root)
        remember_xray_project(self.xray.root)
        with patch("app.ui.shell.first_run_setup_required", return_value=False), \
             patch("app.extensions.discovery.entry_points", return_value=EntryPoints()):
            shell = ProductionShell()
        shell.withdraw()
        shell.update_idletasks()
        shell.context = UIContext(self.landmark)
        shell.context.refresh()
        def destroy_shell():
            if not getattr(shell, "_morpholabel_destroying", False):
                shell.update_idletasks()
                shell.destroy()
            self.assertEqual([], errors, "Tk callbacks failed during shell teardown")
        self.addCleanup(destroy_shell)
        errors = []
        shell.report_callback_exception = lambda *error: errors.append(error)
        shell.tk.createcommand("bgerror", lambda message: errors.append(str(message)))
        return shell, errors

    def test_crop_root_bindings_are_released_after_view_destroy(self):
        shell, errors = self.make_shell()
        baseline = shell.bind("<Return>")
        shell.open_module("xray_counts")
        runtime = shell._active_module_runtime
        runtime._select("crops")
        shell.update()
        self.assertNotEqual(baseline, shell.bind("<Return>"))
        runtime._select("structures")
        shell.update()
        self.assertEqual(baseline.strip(), shell.bind("<Return>").strip())
        self.assertEqual([], errors)

    def test_xray_tooltip_root_bindings_are_released_on_return_to_hub(self):
        shell, errors = self.make_shell()
        baseline = shell.bind("<ButtonPress>")
        shell.open_module("xray_counts")
        runtime = shell._active_module_runtime
        for stage in ("crops", "structures", "export"):
            runtime._select(stage)
            shell.update()
        shell.show_module_hub()
        shell.update()
        self.assertEqual(baseline.strip(), shell.bind("<ButtonPress>").strip())
        self.assertEqual([], errors)

    def test_search_panel_variable_callbacks_release_destroyed_panels(self):
        from app.ui.photo_list_panel import PhotoListPanel
        from app.xray_crop_ui import XRayPlateListPanel
        from app.xray_structures_ui import XRaySpecimenListPanel
        shell, errors = self.make_shell()
        panels = [PhotoListPanel(shell.root, shell.context, lambda *_: None, shell.tip),
                  XRayPlateListPanel(shell.root, self.xray, lambda *_: None, shell.tip),
                  XRaySpecimenListPanel(shell.root, self.xray, lambda *_: None, shell.tip)]
        references = [weakref.ref(panel) for panel in panels]
        for panel in panels:
            panel.destroy()
        del panel, panels
        gc.collect()
        self.assertEqual([None, None, None], [reference() for reference in references])
        self.assertEqual([], errors)

    def test_landmark_export_view_releases_variable_callbacks(self):
        shell, errors = self.make_shell()
        shell.open_module("landmarks")
        shell.select("export")
        shell.update()
        released = weakref.ref(shell.current_view)
        def controls(widget):
            result = []
            for child in widget.winfo_children():
                result.extend(controls(child))
                result.append(weakref.ref(child))
            return result
        released_controls = controls(shell.current_view.parent)
        shell.show_module_hub()
        gc.collect()
        self.assertIsNone(released())
        self.assertTrue(all(reference() is None for reference in released_controls))
        self.assertEqual([], errors)

    def test_landmark_display_dialog_releases_color_variable_callbacks(self):
        shell, errors = self.make_shell()
        shell.open_module("landmarks")
        shell.select("landmarks")
        shell.current_view.open_display_settings()
        dialog = next(widget for widget in shell.winfo_children() if widget.winfo_class() == "Toplevel")
        released = weakref.ref(dialog)
        dialog.destroy()
        del dialog
        shell.update()
        gc.collect()
        self.assertIsNone(released())
        self.assertEqual([], errors)

    def test_landmark_schema_editor_releases_name_variable_callback(self):
        from app.schema_editor import SchemaEditor
        shell, errors = self.make_shell()
        editor = SchemaEditor(shell, self.landmark.schema_path)
        released = weakref.ref(editor)
        editor.destroy()
        del editor
        gc.collect()
        self.assertIsNone(released())
        self.assertEqual([], errors)

    def test_structure_workspace_releases_source_cache_and_key_binding(self):
        shell, errors = self.make_shell()
        baseline = shell.bind("<KeyPress>").strip()
        shell.open_module("xray_counts")
        runtime = shell._active_module_runtime
        runtime._select("structures")
        shell.update()
        workspace = runtime._workspace
        source_cache = weakref.ref(workspace._source_cache)
        released = weakref.ref(workspace)
        runtime._select("export")
        del workspace
        gc.collect()
        self.assertIsNone(released())
        self.assertIsNone(source_cache())
        self.assertEqual(baseline, shell.bind("<KeyPress>").strip())
        self.assertEqual([], errors)

    def test_module_switching_and_pending_save_20_cycles(self):
        shell, errors = self.make_shell()
        selected = self.landmark_ids[1]
        shell.context.select_image(selected)
        return_binding = shell.bind("<Return>").strip()
        click_binding = shell.bind("<ButtonPress>").strip()
        for cycle in range(20):
            with self.subTest(cycle=cycle):
                shell.open_module("landmarks")
                lm = shell._active_module_runtime
                self.assertIs(self.landmark, lm._host.project)
                self.assertEqual(selected, shell.context.current()["image_id"])
                with patch.object(lm, "close", wraps=lm.close) as close_lm:
                    shell.show_module_hub()
                    close_lm.assert_called_once()
                shell.open_module("xray_counts")
                xr = shell._active_module_runtime
                self.assertEqual(self.xray.root, xr.project.root)
                self.assertIs(self.landmark, shell.context.project)
                xr._select("crops")
                shell.update()
                workspace = xr._workspace
                released_workspace = weakref.ref(workspace)
                sid = workspace.selected_specimen_id
                if not sid:
                    sid = workspace.session.active_items()[0]["specimen_id"]
                    workspace.session.select(sid)
                original = dict(workspace.session.item()["crop"])
                workspace.session.flip_horizontal()
                with patch.object(xr, "close", wraps=xr.close) as close_xr:
                    xr._show_module_hub()
                    close_xr.assert_called_once()
                persisted = XRayProject(self.xray.root).specimen(sid)["crop"]
                self.assertNotEqual(original.get("head_side", "left"), persisted["head_side"])
                self.assertIsNone(shell._active_module_runtime)
                self.assertEqual(selected, shell.context.current()["image_id"])
                self.assertEqual(self.landmark.root, last_project())
                self.assertEqual(self.xray.root, last_xray_project())
                self.assertEqual([], errors)
                self.assertEqual([], shell.module_registry.diagnostics)
                self.assertEqual(return_binding, shell.bind("<Return>").strip())
                self.assertEqual(click_binding, shell.bind("<ButtonPress>").strip())
                del workspace, xr
                gc.collect()
                self.assertIsNone(released_workspace())

    def test_repeated_shell_open_stages_destroy_and_readonly_science(self):
        for _ in range(4):
            shell, errors = self.make_shell()
            for key in ("landmarks", "xray_counts"):
                shell.open_module(key)
                if key == "landmarks":
                    for stage in ("project", "crop", "landmarks", "measurements", "export"):
                        shell.select(stage)
                        shell.update()
                else:
                    runtime = shell._active_module_runtime
                    scientific_before = [self.xray.effective_annotations(sid) for sid in self.specimens]
                    with closing(sqlite3.connect(self.xray.db_path)) as db:
                        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('ui_state','sqlite_sequence') ORDER BY name")]
                        saved_before = {table: db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
                    for stage in ("project", "crops", "structures", "export"):
                        runtime._select(stage)
                        shell.update()
                    self.assertEqual(scientific_before, [self.xray.effective_annotations(sid) for sid in self.specimens])
                    with closing(sqlite3.connect(self.xray.db_path)) as db:
                        saved_after = {table: db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
                    self.assertEqual(saved_before, saved_after)
                shell.show_module_hub()
            self.assertEqual([], errors)
            self.assertEqual([], shell.module_registry.diagnostics)
            shell.update()
            shell.destroy()
            gc.collect()
            self.assertEqual([], errors, "Tk callbacks failed during repeated shell teardown")


if __name__ == "__main__":
    unittest.main()
