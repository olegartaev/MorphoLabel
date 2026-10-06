"""Persisted scientific and real-Tk regressions for the final release candidate."""
import copy
import hashlib
import json
import math
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from app.crop_workflow import apply_reviewed_crop
from app.landmark_frames import restore_standardized_frame
from app.landmark_dataset import v2_human_final_eligible_image_ids
from app.project_storage import Project
from app.transforms import Transform
from app.ui.context import UIContext
from app.xray_project import XRayProject
from app.xray_schema import bundled_scheme
from tests import test_release_torture as fixtures


class FrameHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="final_frames_"); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / "source"; self.source.mkdir()
        self.base = Image.new("RGB", (160, 100), "black")
        ImageDraw.Draw(self.base).ellipse((116, 46, 124, 54), fill="white")
        self.base.save(self.source / "fish.png")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role,category\n1,A,Alpha,BOTH,kept\n2,B,Beta,BOTH,outside\n3,C,Gamma,BOTH,missing\n", encoding="utf-8")
        self.project = Project.create("p", self.source, self.root, schema, source_layout="direct")
        self.ident = self.project.catalog_rows()[0]["image_id"]
        self.target = self.project.cache_root / "standardized" / f"{self.ident}.png"
        self.developed = self.project.cache_root / "developed" / f"{self.ident}.png"
        self.base.save(self.developed)

    def apply(self, bounds, angle):
        return apply_reviewed_crop(self.project, self.ident, self.base, bounds, angle, self.target, self.source / "fish.png")

    def test_transform_agrees_with_actual_pil_rotated_pixels(self):
        for angle in (90, -90, 23):
            with self.subTest(angle=angle):
                self.apply((0, 0, 160, 100), angle)
                t = Transform(**self.project.crop_record(self.ident)["transform_json"])
                x, y = t.original_to_standardized(120, 50)
                with Image.open(self.target) as image:
                    self.assertGreater(image.getpixel((round(x), round(y)))[0], 180)
                from app.ui.crop_canvas import crop_model_to_source
                from app.crop_model import CropModel
                model=CropModel(160,100,0,0,160,100,angle)
                np.testing.assert_allclose(crop_model_to_source(model,x,y),(120,50),atol=1e-9)

    def test_multiple_changes_remap_human_ai_missing_reopen_and_original_export(self):
        self.apply((10, 5, 150, 95), 0)
        self.project.save_landmark(self.ident, 1, 110, 45, "manual", "manual")
        self.project.save_landmark(self.ident, 2, 10, 10, "auto", "machine", model_id="ai", predicted_x=10, predicted_y=10)
        self.project.save_landmark(self.ident, 3, None, None, "missing", "missing")
        self.project.mark_checked(self.ident)
        for bounds, angle in (((5, 2, 155, 98), 15), ((30, 10, 155, 90), -20), ((70, 20, 145, 85), 0)):
            self.apply(bounds, angle)
            self.project = Project.open(self.project.root)
            points = self.project.load_landmarks(self.ident)
            t = Transform(**self.project.crop_record(self.ident)["transform_json"])
            point = points[1]
            original = t.standardized_to_original(point["x_standardized"], point["y_standardized"])
            np.testing.assert_allclose(original, (120, 50), atol=1e-9)
            np.testing.assert_allclose(self.project.canonical_coordinates(self.ident)[1], (120, 50), atol=1e-9)
            from app.export_formats import export_landmark_tps
            exported=export_landmark_tps(self.project,groups=("kept",))
            self.assertIn("120.00000 50.00000",exported.read_text(encoding="ascii"))
            self.assertEqual("missing", points[3]["state"])
            self.assertTrue(self.project.landmark_crop_review_required(self.ident))
            self.assertNotIn(self.ident, v2_human_final_eligible_image_ids(self.project))
        self.assertEqual("unresolved", points[2]["state"])
        self.assertIsNone(points[2]["x_standardized"])
        with self.project.transaction() as c:
            history = c.execute("SELECT * FROM corrections WHERE kind='landmark_transform_remap'").fetchall()
            self.assertEqual(3, len(history))
            self.assertFalse(c.execute("SELECT human_verified FROM image_review WHERE image_id=?", (self.ident,)).fetchone()[0])

    def test_crop_and_remap_rollback_together_on_history_failure(self):
        self.apply((10, 5, 150, 95), 0)
        self.project.save_landmark(self.ident, 1, 110, 45, "manual", "manual")
        before = self.project.crop_record(self.ident); points = self.project.load_landmarks(self.ident)
        with self.project.transaction() as c:
            c.execute("CREATE TRIGGER fail_remap BEFORE INSERT ON corrections WHEN NEW.kind='landmark_transform_remap' BEGIN SELECT RAISE(ABORT,'history failure'); END")
        with self.assertRaisesRegex(Exception, "history failure"):
            self.apply((20, 5, 150, 95), 0)
        self.assertEqual(before, self.project.crop_record(self.ident))
        self.assertEqual(points, self.project.load_landmarks(self.ident))
        restore_standardized_frame(self.project, self.ident)
        with Image.open(self.target) as image:self.assertEqual((140, 90), image.size)

    def test_stale_fingerprint_without_developed_must_rebuild_from_source(self):
        self.apply((10, 5, 150, 95), 0)
        # Mimic a DB frame saved by a neighboring writer while its old PNG remains.
        new = Transform(160, 100, 0, 80, 50, 20, 5, 140, 90)
        with self.project.transaction() as c:
            c.execute("UPDATE crops SET crop_json=?,transform_json=? WHERE image_id=?", (json.dumps([20, 5, 160, 95]), json.dumps(new.__dict__), self.ident))
        self.developed.unlink()
        target, rebuilt = restore_standardized_frame(self.project, self.ident)
        self.assertTrue(rebuilt)
        with Image.open(target) as image:self.assertGreater(image.getpixel((100, 45))[0], 180)

    def test_changed_crop_cannot_adopt_same_size_unmanifested_legacy_png(self):
        self.apply((10,5,150,95),0)
        self.target.with_name(self.target.name+".frame.json").unlink()
        t=Transform(160,100,0,80,50,20,5,140,90)
        self.project.save_reviewed_crop(self.ident,{"developed_full_relpath":f"cache/developed/{self.ident}.png","standardized_relpath":f"cache/standardized/{self.ident}.png","crop_bounds":[20,5,160,95],"transform":t.__dict__,"rotation_degrees":0})
        target,rebuilt=restore_standardized_frame(self.project,self.ident)
        self.assertTrue(rebuilt)
        with Image.open(target) as image:self.assertGreater(image.getpixel((100,45))[0],180)

    def test_untrusted_previous_transform_archives_points_without_guessing(self):
        self.apply((10,5,150,95),0);self.project.save_landmark(self.ident,1,110,45,"manual","manual")
        with self.project.transaction() as c:c.execute("UPDATE crops SET transform_json=NULL WHERE image_id=?",(self.ident,))
        result=self.apply((20,5,150,95),0)
        self.assertTrue(result["legacy_landmarks_invalidated"])
        self.assertEqual("unresolved",Project.open(self.project.root).load_landmarks(self.ident)[1]["state"])
        with self.project.transaction() as c:
            old=json.loads(c.execute("SELECT previous_json FROM corrections WHERE kind='landmark_frame_unknown_before_crop_change'").fetchone()[0])
            self.assertEqual(110,old["landmarks"][0]["x_standardized"])

    def test_seeded_crop_change_model_import_and_reopen_7_17_73_101(self):
        from app.ai_package import export_model_package,import_model_package
        from app.crop_training import predict
        import random
        directory=self.project.models_root/"seed_crop";directory.mkdir()
        weights=np.random.default_rng(7).normal(0,.0001,(769,6));weights[0]=[.1,.1,.9,.9,0,1]
        np.savez_compressed(directory/"model.npz",weights=weights)
        (directory/"model_manifest.json").write_text(json.dumps({"backend":"numpy_ridge_image_regression","input":"32x24 grayscale","output_schema":{"version":2}}),encoding="utf-8")
        self.project.register_model("seed_crop","crop",path=directory.relative_to(self.project.data_root).as_posix(),active=True)
        expected=predict(self.base,project=self.project)[0];package=self.root/"seed_crop.zip";export_model_package(self.project,"crop",package)
        self.apply((10,5,150,95),0);self.project.save_landmark(self.ident,1,110,45,"manual","manual")
        for seed in (7,17,73,101):
            rng=random.Random(seed)
            for step in range(8):
                if step%2:
                    local=import_model_package(self.project,package,"crop");self.project.set_active_model("crop",local)
                    actual=predict(self.base,project=self.project)[0]
                    np.testing.assert_allclose(actual["bounds"],expected["bounds"],atol=1e-12,rtol=0)
                    self.assertEqual(actual["rotation_degrees"],expected["rotation_degrees"])
                else:self.apply((rng.randrange(11),rng.randrange(11),155,95),rng.uniform(-15,15))
                self.project=Project.open(self.project.root)
                np.testing.assert_allclose(self.project.canonical_coordinates(self.ident)[1],(120,50),atol=1e-9)

    def test_changed_scheme_roles_require_explicit_review_after_reopen(self):
        from app.landmark_state import load_current_landmark_state
        self.apply((10,5,150,95),0)
        for ident in (1,2,3):self.project.save_landmark(self.ident,ident,20+ident,30,"manual","manual")
        self.project.mark_checked(self.ident)
        changed=self.root/"role_changed.csv"
        changed.write_text("id,abbr,name,role,category\n1,A,Alpha,GM,kept\n2,B,Beta,BOTH,outside\n3,C,Gamma,BOTH,missing\n",encoding="utf-8")
        before=self.project.load_landmarks(self.ident)
        self.project.apply_landmark_schema(changed)
        self.project=Project.open(self.project.root)
        self.assertEqual(before,self.project.load_landmarks(self.ident))
        self.assertFalse(load_current_landmark_state(self.project,self.ident).human_verified)
        self.assertNotIn(self.ident,v2_human_final_eligible_image_ids(self.project))
        self.assertEqual("yellow",self.project.annotation_status(self.ident)["color"])
        self.project.mark_checked(self.ident)
        self.assertIn(self.ident,v2_human_final_eligible_image_ids(Project.open(self.project.root)))


class FinalTkHardeningTests(unittest.TestCase):
    setUp = fixtures.ReleaseTortureTests.setUp
    def make_shell(self):
        shell, errors = fixtures.ReleaseTortureTests.make_shell(self)
        shell.open_module("landmarks"); shell.update()
        return shell, errors

    def active_landmarks(self):
        for ident in self.landmark_ids:
            fixtures.make_reviewed_crop(self.landmark, ident, 160, 100)
        ident = self.landmark_ids[0]
        self.landmark.save_landmark(ident, 1, 50, 45, "manual", "manual")
        shell, errors = self.make_shell(); shell.deiconify(); shell.geometry("1400x1000")
        runtime = shell._active_module_runtime; runtime.select("landmarks")
        controller = runtime.current_view.canvas
        deadline = time.monotonic() + 8
        while not controller.ready_for(ident) and time.monotonic() < deadline:
            shell.update(); time.sleep(.01)
        self.assertTrue(controller.ready_for(ident))
        return shell, runtime, controller, ident

    def test_real_delete_is_canvas_scoped_and_can_replace_reopen(self):
        import tkinter as tk
        from tkinter import ttk
        shell, runtime, controller, ident = self.active_landmarks()
        controller.set_choice(1); controller.canvas.focus_force(); shell.update()
        controller.canvas.event_generate("<Delete>"); shell.update()
        self.assertNotIn(1, self.landmark.load_landmarks(ident))
        self.assertNotIn(1, Project.open(self.landmark.root).load_landmarks(ident))
        x, y = controller._position(55, 45)
        controller.canvas.event_generate("<Button-1>", x=round(x), y=round(y)); shell.update()
        self.assertIn(1, self.landmark.load_landmarks(ident))
        entry = ttk.Entry(shell); entry.pack(); entry.insert(0, "abc"); entry.focus_force(); shell.update()
        entry.event_generate("<Delete>"); shell.update()
        self.assertIn(1, self.landmark.load_landmarks(ident)); entry.destroy()

    def test_crop_apply_switch_and_reopen_canvas_uses_current_frame(self):
        from app.crop_model import CropModel
        shell,runtime,controller,ident=self.active_landmarks()
        runtime.select("crop");shell.update();crop=runtime.current_view.canvas
        def wait_ready(canvas):
            deadline=time.monotonic()+8
            while not canvas.ready_for(ident) and time.monotonic()<deadline:shell.update();time.sleep(.01)
            self.assertTrue(canvas.ready_for(ident))
        wait_ready(crop);crop.model=CropModel(160,100,10,5,150,95,18)
        with patch("tkinter.messagebox.askyesno",return_value=True):self.assertEqual("SAVED",crop.apply())
        for reopen in (False,True):
            if reopen:runtime._attach_project(Project.open(self.landmark.root))
            runtime.select("landmarks");shell.update();controller=runtime.current_view.canvas;wait_ready(controller)
            record=runtime.context.project.crop_record(ident);point=controller._points[1]
            t=Transform(**record["transform_json"])
            np.testing.assert_allclose(t.standardized_to_original(point["x_standardized"],point["y_standardized"]),(50,45),atol=1e-9)
            with Image.open(controller.image_path) as image:np.testing.assert_array_equal(np.asarray(controller.image),np.asarray(image.convert("RGB")))
            self.assertEqual((140,90),controller.image.size)

    def test_real_drag_has_no_motion_io_and_release_refreshes_one_photo(self):
        shell, runtime, controller, ident = self.active_landmarks()
        view = runtime.current_view; panel = runtime.photo_panel
        x, y = controller._position(50, 45)
        controller.canvas.event_generate("<Button-1>", x=round(x), y=round(y)); shell.update()
        photos = controller.stats["photo_creations"]
        with patch.object(self.landmark, "connect", side_effect=AssertionError("drag SQLite")), \
             patch("PIL.Image.open", side_effect=AssertionError("drag decode")), \
             patch("PIL.ImageTk.PhotoImage", side_effect=AssertionError("drag raster")), \
             patch.object(runtime, "render", side_effect=AssertionError("drag render")):
            started = time.perf_counter()
            for i in range(100):controller.canvas.event_generate("<B1-Motion>",x=round(x+i/20),y=round(y+i/30))
            elapsed = time.perf_counter() - started
        print(f"DRAG 100 vector motions: {elapsed * 1000:.3f} ms")
        with patch.object(panel, "refresh", side_effect=AssertionError("full photo refresh")), \
             patch.object(self.landmark, "save_landmark", wraps=self.landmark.save_landmark) as save:
            controller.canvas.event_generate("<ButtonRelease-1>"); shell.update()
            self.assertEqual(1, save.call_count)
        self.assertEqual(photos, controller.stats["photo_creations"])
        self.assertEqual(1, controller.choice.get())

    def test_no_scheme_blocks_every_scientific_stage_with_warning(self):
        self.landmark.schema_path.write_text("id,abbr,name,role\n", encoding="utf-8")
        self.landmark = Project.open(self.landmark.root)
        shell, errors = self.make_shell(); runtime = shell._active_module_runtime
        for stage in ("crop", "landmarks", "measurements", "export"):
            with self.subTest(stage=stage), patch("tkinter.messagebox.showwarning") as warning:
                runtime.select(stage)
                self.assertEqual("project", runtime.context.section)
                self.assertEqual(1, warning.call_count)
                self.assertIn("Create", warning.call_args.args[1])

    def test_external_scheme_explicit_apply_preserves_history_cancel_invalid_reopen(self):
        from app.schema_editor import SchemaEditor
        shell, errors = self.make_shell(); runtime = shell._active_module_runtime
        ident=self.landmark_ids[0];self.landmark.save_landmark(ident,1,15,20,"manual","manual")
        before=self.landmark.schema_path.read_bytes()
        external=self.root/"external.csv"
        external.write_text("id,abbr,name,role,category\n1,A,Renamed Alpha,BOTH,Body\n2,C,New Gamma,GM,Head\n",encoding="utf-8")
        editor=SchemaEditor(runtime,self.landmark.schema_path,project=self.landmark)
        editor.load_path(external);shell.update()
        self.assertTrue(editor.apply_button.winfo_ismapped())
        self.assertEqual(before,self.landmark.schema_path.read_bytes())
        with patch("app.schema_editor.messagebox.askyesno",return_value=False):self.assertFalse(editor.apply_to_project())
        self.assertEqual(before,self.landmark.schema_path.read_bytes())
        with patch("app.schema_editor.messagebox.askyesno",return_value=True):self.assertTrue(editor.apply_to_project())
        reopened=Project.open(self.landmark.root)
        self.assertEqual(["A","C"],[r["abbr"] for r in reopened.schema])
        self.assertEqual(["Body","Head"],[r["category"] for r in reopened.schema])
        self.assertEqual(15,reopened.load_landmarks(ident)[1]["x_standardized"])
        self.assertTrue(list((self.landmark.root/"backups").glob("schema_identity_*")))
        bad=self.root/"invalid.csv";bad.write_text("id,abbr,name,role\n1,A,Alpha,INVALID\n",encoding="utf-8")
        with patch("app.schema_editor.messagebox.showerror") as error:editor.load_path(bad);self.assertTrue(error.called)
        self.assertEqual(self.landmark.schema_path,editor.path)
        editor.destroy()

    def test_external_scheme_apply_empty_and_compatible_projects(self):
        from app.schema_editor import SchemaEditor
        shell,errors=self.make_shell();runtime=shell._active_module_runtime
        external=self.root/"compatible.csv";external.write_text("id,abbr,name,role\n1,A,Alpha renamed,BOTH\n2,B,Beta renamed,BOTH\n",encoding="utf-8")
        editor=SchemaEditor(runtime,self.landmark.schema_path,project=self.landmark);editor.load_path(external)
        with patch("app.schema_editor.messagebox.askyesno",side_effect=AssertionError("empty project confirmation")):
            self.assertTrue(editor.apply_to_project())
        ident=self.landmark_ids[0];fixtures.make_reviewed_crop(self.landmark,ident,160,100)
        self.landmark.save_landmark(ident,1,10,20,"manual","manual");self.landmark.save_landmark(ident,2,30,40,"manual","manual");self.landmark.mark_checked(ident)
        external.write_text("id,abbr,name,role\n1,A,Alpha display,BOTH\n2,B,Beta display,BOTH\n",encoding="utf-8")
        editor.load_path(external)
        with patch("app.schema_editor.messagebox.askyesno",return_value=True):self.assertTrue(editor.apply_to_project())
        reopened=Project.open(self.landmark.root)
        self.assertEqual(self.landmark.load_landmarks(ident),reopened.load_landmarks(ident))
        self.assertIn(ident,v2_human_final_eligible_image_ids(reopened));editor.destroy()

    def test_new_project_initial_samples_before_resize_and_reopen(self):
        shell, errors=self.make_shell();shell.deiconify();shell.update()
        runtime=shell._active_module_runtime
        def walk(widget):
            for child in widget.winfo_children():yield child;yield from walk(child)
        for scale in (1.0,1.25,1.5):
            shell.tk.call("tk","scaling",scale*96/72)
            for width in (1440,1000):
                # Establish the supported window BEFORE creating/attaching the
                # project. No resize or user click may repair its first layout.
                shell.geometry(f"{width}x1100");shell.update()
                project=Project.create(f"new_empty_{scale}_{width}",self.landmark.source_root,self.root,source_layout="direct",source_types=["png"])
                runtime._attach_project(project,project.catalog_rows());shell.update_idletasks();shell.update()
                samples=next(w for w in walk(runtime.section_host) if w.winfo_class()=="TLabelframe" and w.cget("text")=="Samples")
                self.assertGreater(samples.winfo_width(),shell.winfo_width()*.38)
                initial=samples.winfo_width()
                runtime._attach_project(Project.open(project.root));shell.update_idletasks();shell.update()
                samples=next(w for w in walk(runtime.section_host) if w.winfo_class()=="TLabelframe" and w.cget("text")=="Samples")
                self.assertLess(abs(initial-samples.winfo_width()),8)

    def test_initial_samples_and_markers_geometry_at_three_scales(self):
        shell, errors = self.make_shell(); shell.deiconify()
        runtime = shell._active_module_runtime
        for scale in (1.0, 1.25, 1.5):
            shell.tk.call("tk", "scaling", scale * 96 / 72)
            for width in (1440, 1000):
                shell.geometry(f"{width}x1100"); shell.update()
                runtime.select("project"); shell.update_idletasks(); shell.update()
                def walk(widget):
                    for child in widget.winfo_children():yield child; yield from walk(child)
                samples = next(w for w in walk(runtime.current_view.parent) if w.winfo_class() == "TLabelframe" and w.cget("text") == "Samples")
                self.assertGreater(samples.winfo_width(), shell.winfo_width() * .38)
        shell.module_states.setdefault("xray_counts", {})["project"] = self.xray
        shell.open_module("xray_counts"); xruntime = shell._active_module_runtime
        for scale in (1.0, 1.25, 1.5):
            shell.tk.call("tk", "scaling", scale * 96 / 72)
            for width in (1600, 1000):
                shell.geometry(f"{width}x1100"); shell.update()
                xruntime._select("structures"); shell.update_idletasks(); shell.update()
                workspace = xruntime._workspace
                groups = workspace.marker_host.winfo_children()
                if width == 1600:
                    self.assertEqual(1, len({w.winfo_y() for w in groups}))
                self.assertTrue(all(w.winfo_x() >= 0 for w in groups))

    def test_orientation_labels_inside_preview_for_every_selection_and_scale(self):
        from app.modules.xray_counts import OrientationSetupDialog
        shell, errors = self.make_shell(); shell.deiconify()
        for scale in (1.0, 1.25, 1.5):
            shell.tk.call("tk", "scaling", scale * 96 / 72)
            dialog = OrientationSetupDialog(shell); shell.update()
            for head in ("left", "right", "none"):
                for bottom in ("down", "up", "none"):
                    dialog.head.set(head); dialog.bottom.set(bottom); dialog._draw(); shell.update_idletasks()
                    for item in dialog.preview.find_all():
                        if dialog.preview.type(item) == "text":
                            box = dialog.preview.bbox(item)
                            self.assertGreaterEqual(box[0], 0); self.assertGreaterEqual(box[1], 0)
                            self.assertLessEqual(box[2], dialog.preview.winfo_width())
                            self.assertLessEqual(box[3], dialog.preview.winfo_height())
            dialog.destroy()
