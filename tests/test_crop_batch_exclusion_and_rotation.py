import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.crop_batch_state import remove_crop_batch_member
from app.crop_model import CropModel
from app.crop_training import _project_target
from app.project_storage import Project
from app.ui.crop_canvas import CropCanvasController
from app.ui.shell import ProductionShell


class CropBatchExclusionAndRotationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source" / "A"
        source.mkdir(parents=True)
        for name in "ABCDEFGH":
            Image.new("RGB", (24, 18)).save(source / f"{name}.jpg")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name\n1,A,Alpha\n", encoding="utf-8")
        self.project = Project.create("p", source.parent, self.root, schema, source_layout="direct")
        self.ids = [row["image_id"] for row in self.project.catalog_rows()]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _state(self):
        ids = self.ids
        return {
            "batch_id": "crop-test", "batch_type": "training", "ids": ids[:],
            "prepared_ids": ids[:], "completed_ids": ids[1:4],
            "proposals": {ids[2]: [1, 2, 15, 16], ids[4]: [1, 2, 15, 16]},
            "position": 2,
        }

    def test_remove_current_uses_next_and_cleans_every_membership(self):
        self.project.set_ui_state("crop_active_batch", self._state())
        state, target, empty = remove_crop_batch_member(self.project, self.ids[2], self.ids[2])
        self.assertFalse(empty)
        self.assertEqual(self.ids[3], target)
        self.assertEqual(self.ids[:2] + self.ids[3:], state["ids"])
        self.assertEqual(2, state["position"])
        self.assertNotIn(self.ids[2], state["prepared_ids"])
        self.assertNotIn(self.ids[2], state["completed_ids"])
        self.assertNotIn(self.ids[2], state["proposals"])

    def test_remove_last_uses_previous_and_noncurrent_keeps_current(self):
        self.project.set_ui_state("crop_active_batch", self._state())
        state, target, empty = remove_crop_batch_member(self.project, self.ids[-1], self.ids[-1])
        self.assertFalse(empty)
        self.assertEqual(self.ids[-2], target)
        self.assertEqual(len(self.ids) - 2, state["position"])
        self.project.set_ui_state("crop_active_batch", self._state())
        state, target, empty = remove_crop_batch_member(self.project, self.ids[1], self.ids[3])
        self.assertFalse(empty)
        self.assertEqual(self.ids[3], target)
        self.assertEqual(state["ids"].index(self.ids[3]), state["position"])

    def test_prediction_review_uses_the_same_membership_contract(self):
        state = self._state()
        state["batch_type"] = "prediction_review"
        self.project.set_ui_state("crop_active_batch", state)
        updated, target, empty = remove_crop_batch_member(self.project, self.ids[2], self.ids[2])
        self.assertFalse(empty)
        self.assertEqual(self.ids[3], target)
        self.assertEqual("prediction_review", updated["batch_type"])
        self.assertEqual(updated["ids"].index(target), updated["position"])

    def test_remove_sole_member_is_empty_and_restore_does_not_reinsert(self):
        self.project.set_ui_state("crop_active_batch", {"ids": [self.ids[0]], "prepared_ids": [self.ids[0]], "completed_ids": [self.ids[0]], "proposals": {self.ids[0]: [1, 2, 3, 4]}})
        state, target, empty = remove_crop_batch_member(self.project, self.ids[0], self.ids[0])
        self.assertTrue(empty)
        self.assertIsNone(target)
        self.assertEqual([], state["ids"])
        self.project.restore_image(self.ids[0])
        state, target, empty = remove_crop_batch_member(self.project, self.ids[0], None)
        self.assertEqual([], state["ids"])
        self.assertIsNone(target)
        self.assertTrue(empty)

    def test_excluded_reviewed_crop_is_not_training_eligible(self):
        image_id = self.ids[0]
        crop = {"crop_bounds": [1, 1, 20, 16]}
        self.project.save_reviewed_crop(image_id, crop)
        self.assertIn(image_id, self.project.crop_training_eligible_ids())
        self.project.exclude_image(image_id, "test")
        self.assertNotIn(image_id, self.project.crop_training_eligible_ids())

    def test_real_photo_panel_exclude_button_is_one_click_and_advances_batch(self):
        """The visible production button must not open a reason/note dialog."""
        self.project.set_ui_state("crop_active_batch", {
            "batch_id": "exclude-button", "batch_type": "training",
            "ids": self.ids[:2], "prepared_ids": self.ids[:2],
            "completed_ids": [], "position": 0, "proposals": {},
        })
        shell = None
        try:
            shell = ProductionShell(self.project)
            shell.withdraw()
            shell.select("crop")
            shell.context.selected = next(i for i, row in enumerate(shell.context.rows) if row["image_id"] == self.ids[0])
            shell.photo_panel.sync_current(reveal=True)
            with patch("app.ui.photo_list_panel.messagebox.askyesno", side_effect=AssertionError("Exclude must not ask for a reason or note")):
                shell.photo_panel.exclude_button.invoke()
            self.assertTrue(next(row for row in self.project.catalog_rows() if row["image_id"] == self.ids[0])["excluded"])
            self.assertEqual(self.ids[1], (shell.context.current() or {}).get("image_id"))
            state = self.project.get_ui_state("crop_active_batch", {})
            self.assertEqual([self.ids[1]], state["ids"])
            self.assertEqual(0, state["position"])
        finally:
            if shell is not None:
                shell.destroy()

    def test_production_training_target_contains_rotation(self):
        target = _project_target(
            {"crop_bounds": [10, 20, 90, 80], "rotation_degrees": 30.0},
            100, 100,
        )
        self.assertEqual(6, len(target))
        self.assertAlmostEqual(0.5, target[4], places=6)
        self.assertAlmostEqual(0.8660254, target[5], places=6)

    def test_manual_crop_review_candidates_are_human_manual_only(self):
        image_id = self.ids[0]
        self.project.save_reviewed_crop(image_id, {"crop_bounds": [1, 1, 20, 16]})
        self.assertIn(image_id, self.project.crop_manual_review_candidates())

    def test_rotation_handle_has_priority_and_drag_uses_legacy_geometry(self):
        canvas = CropCanvasController.__new__(CropCanvasController)
        canvas.model = CropModel(100, 100, 20, 20, 80, 80, 0)
        canvas.scale = 1.0
        self.assertEqual("rotate", canvas._hit(50, -15))
        canvas.mode = "rotate"
        canvas.anchor = (50, -15)
        canvas.initial = (20, 20, 80, 80, 0)
        canvas.displayed_image_id = "A"
        canvas.ready_for = lambda image_id: image_id == "A"
        canvas._point = lambda x, y: (100, 50)
        canvas._raster_key = None
        canvas._draw_overlay = lambda **_kwargs: None
        canvas._schedule_rotation_preview = lambda: None
        canvas.drag(type("Event", (), {"x": 0, "y": 0})())
        self.assertEqual(90.0, canvas.model.angle)

    def test_rotation_preview_coalesces_motion_events(self):
        canvas = CropCanvasController.__new__(CropCanvasController)
        calls = []
        canvas._rotation_render_job = None
        canvas.canvas = SimpleNamespace(after_idle=lambda callback: (calls.append(callback), "preview-job")[1])
        canvas._schedule_rotation_preview()
        canvas._schedule_rotation_preview()
        self.assertEqual(1, len(calls))

    def test_apply_routes_rotation_through_reviewed_crop_service(self):
        image_id = self.ids[0]
        canvas = CropCanvasController.__new__(CropCanvasController)
        canvas.base = Image.new("RGB", (100, 100))
        canvas.model = CropModel(100, 100, 10, 12, 90, 92, 17.5)
        canvas.context = SimpleNamespace(
            current=lambda: {"image_id": image_id}, project=self.project,
            refresh_crop_state=lambda ident: self.assertEqual(image_id, ident),
        )
        canvas.parent = None
        canvas.changed = lambda ident: self.assertEqual(image_id, ident)
        canvas.ready_for = lambda ident: ident == image_id
        with patch("app.ui.crop_canvas.apply_reviewed_crop") as save:
            self.assertEqual("SAVED", canvas.apply())
        self.assertEqual(image_id, save.call_args.args[1])
        self.assertEqual(17.5, save.call_args.args[3 + 1])

    def test_real_tk_crop_canvas_rotates_applies_and_exclusion_stays_in_batch(self):
        """Exercise the real main-window canvas and shell exclusion callback."""
        for image_id in self.ids:
            Image.new("RGB", (1600, 1200), (40, 50, 60)).save(
                self.project.cache_root / "developed" / f"{image_id}.png"
            )
        self.project.set_ui_state("crop_active_batch", {
            "batch_id": "gui-crop", "batch_type": "training", "ids": self.ids[:],
            "prepared_ids": self.ids[:], "completed_ids": [], "position": 3, "proposals": {},
        })
        shell = None
        try:
            shell = ProductionShell(self.project)
            shell.geometry("1000x700")
            shell.deiconify()
            shell.context.selected = 3
            shell.select("crop")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                shell.update()
                canvas = shell.current_view.canvas
                if canvas.ready_for(self.ids[3]):
                    break
                time.sleep(.02)
            self.assertTrue(canvas.ready_for(self.ids[3]))
            old_scale, old_offset = canvas.scale, canvas.offset
            shell.geometry("1000x760")
            shell.update()
            # This width-only resize preserves scale for the tiny disposable image but moves it.
            self.assertEqual(old_scale, canvas.scale)
            self.assertNotEqual(old_offset, canvas.offset)
            image_item = canvas.canvas.find_withtag("image")[0]
            self.assertEqual(tuple(map(float, canvas.offset)), tuple(map(float, canvas.canvas.coords(image_item))))
            left0, top0 = canvas.model.left, canvas.model.top
            overlay_item = canvas.canvas.find_withtag("crop_overlay")[0]
            self.assertAlmostEqual(canvas.offset[0] + left0 * canvas.scale, canvas.canvas.coords(overlay_item)[0])
            self.assertAlmostEqual(canvas.offset[1] + top0 * canvas.scale, canvas.canvas.coords(overlay_item)[1])
            self.assertAlmostEqual(left0, canvas._point(canvas.offset[0] + left0 * canvas.scale, canvas.offset[1] + top0 * canvas.scale)[0])
            # A sash move is another Configure source and must retain the same transform agreement.
            shell.workspace_panes.sashpos(0, 360)
            shell.update()
            self.assertEqual(tuple(map(float, canvas.offset)), tuple(map(float, canvas.canvas.coords(image_item))))
            stable_scale = canvas.scale
            shell.geometry("980x650")
            shell.update()
            self.assertNotEqual(stable_scale, canvas.scale)
            self.assertEqual(tuple(map(float, canvas.offset)), tuple(map(float, canvas.canvas.coords(image_item))))
            left, top, right, _bottom = canvas.model.left, canvas.model.top, canvas.model.right, canvas.model.bottom
            handle_x = int(canvas.offset[0] + ((left + right) / 2) * canvas.scale)
            handle_y = int(canvas.offset[1] + top * canvas.scale - 35)
            canvas.canvas.event_generate("<ButtonPress-1>", x=handle_x, y=handle_y)
            shell.update()
            self.assertEqual("rotate", canvas.mode)
            canvas.canvas.event_generate("<B1-Motion>", x=handle_x + 20, y=handle_y + 35)
            canvas.canvas.event_generate("<ButtonRelease-1>", x=handle_x + 20, y=handle_y + 35)
            shell.update()
            angle = canvas.model.angle
            self.assertNotEqual(0.0, angle)
            self.assertTrue(canvas.preview_rotate_source_sizes)
            self.assertLessEqual(max(width for width, _height in canvas.preview_rotate_source_sizes), canvas.base.width)
            self.assertLess(max(width for width, _height in canvas.preview_rotate_source_sizes), canvas.base.width)
            self.assertEqual("SAVED", canvas.apply())
            self.assertAlmostEqual(angle, self.project.crop_record(self.ids[3])["rotation_degrees"], places=5)
            self.project.exclude_image(self.ids[3], "GUI exclusion test")
            shell._photo_exclusion_changed(self.ids[3])
            self.assertEqual(self.ids[4], (shell.context.current() or {}).get("image_id"))
            state = self.project.get_ui_state("crop_active_batch", {})
            self.assertEqual(self.ids[4], state["ids"][state["position"]])
            self.assertEqual(7, len(state["ids"]))
            # The identical main-window path also owns prediction-review navigation.
            state["batch_type"] = "prediction_review"
            self.project.set_ui_state("crop_active_batch", state)
            shell.render()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                shell.update()
                canvas = shell.current_view.canvas
                if canvas.ready_for(self.ids[4]):
                    break
                time.sleep(.02)
            self.assertTrue(canvas.ready_for(self.ids[4]))
            shell.status_next.invoke()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and (shell.context.current() or {}).get("image_id") != self.ids[5]:
                shell.update()
                time.sleep(.02)
            self.assertEqual(self.ids[5], (shell.context.current() or {}).get("image_id"))
            # Last-item Next completes the persisted batch and removes finite navigation.
            self.project.set_ui_state("crop_active_batch", {
                "batch_id": "gui-crop-final", "batch_type": "prediction_review",
                "ids": [self.ids[5]], "prepared_ids": [self.ids[5]],
                "completed_ids": [], "position": 0,
            })
            shell.context.selected = next(i for i, row in enumerate(shell.context.rows) if row["image_id"] == self.ids[5])
            shell.render()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                shell.update()
                canvas = shell.current_view.canvas
                if canvas.ready_for(self.ids[5]):
                    break
                time.sleep(.02)
            self.assertTrue(canvas.ready_for(self.ids[5]))
            with patch("app.ui.crop_section.messagebox.showinfo"):
                shell.status_next.invoke()
                shell.update()
            finished = self.project.get_ui_state("crop_active_batch", {})
            self.assertEqual([], finished["ids"])
            self.assertTrue(finished["finished"])
            self.assertFalse(shell.status_navigation.winfo_ismapped())
        finally:
            if shell is not None:
                shell.destroy()

    def test_crop_navigation_is_global_only_and_hidden_without_an_active_batch(self):
        shell = None
        try:
            shell = ProductionShell(self.project)
            shell.geometry("1000x700")
            shell.deiconify()
            shell.select("crop")
            shell.update()
            def labels(widget):
                found = [widget.cget("text")] if "text" in widget.keys() else []
                for child in widget.winfo_children():
                    found.extend(labels(child))
                return found
            local_text = labels(shell.section_host)
            self.assertIn("Apply crop", local_text)
            self.assertIn("Help", local_text)
            self.assertNotIn("Previous", local_text)
            self.assertNotIn("Next", local_text)
            def widget_with_text(widget, text):
                if "text" in widget.keys() and widget.cget("text") == text:
                    return widget
                for child in widget.winfo_children():
                    found=widget_with_text(child,text)
                    if found:return found
                return None
            guide=widget_with_text(shell.section_host,"Help");self.assertTrue(guide and guide.winfo_ismapped())
            guide.invoke();shell.update()
            guides=[child for child in shell.winfo_children() if child.winfo_class()=="Toplevel" and child.title()=="Crop — quick guide"]
            self.assertEqual(1,len(guides));guides[0].destroy()
            self.assertFalse(shell.status_navigation.winfo_ismapped())
            shell.select("landmarks");shell.update()
            landmark_guide=widget_with_text(shell.section_host,"Help");self.assertTrue(landmark_guide and landmark_guide.winfo_ismapped())
            landmark_guide.invoke();shell.update()
            guides=[child for child in shell.winfo_children() if child.winfo_class()=="Toplevel" and child.title()=="Landmarks — quick guide"]
            self.assertEqual(1,len(guides));guides[0].destroy()
            shell.select("crop");shell.update()
            self.project.set_ui_state("crop_active_batch", {"batch_id": "one", "batch_type": "training", "ids": self.ids[:2], "prepared_ids": self.ids[:2], "position": 0})
            shell.context.selected = 0
            shell.render()
            shell.update()
            self.assertTrue(shell.status_navigation.winfo_ismapped())
            self.assertIn("1 / 2", shell.status_index.cget("text"))
        finally:
            if shell is not None:
                shell.destroy()


if __name__ == "__main__":
    unittest.main()
