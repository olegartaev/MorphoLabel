import threading
import unittest
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.ui.context import UIContext
from app.ui.crop_canvas import CropCanvasController, crop_navigation_cache_budget
from pathlib import Path
from app.ui.photo_list_panel import PhotoListPanel


class _CropCountProject:
    def __init__(self):
        self.calls = 0
    def crop_section_counts(self):
        self.calls += 1
        return {"Total": 10, "Reviewed": 8, "AI pending": 1, "Train ready": 7, "Uncropped": 1}


class CropNavigationFastPathTests(unittest.TestCase):
    def test_plain_crop_open_never_runs_training_batch_preparation_or_leaves_stale_overlay(self):
        source=(Path(__file__).resolve().parents[1]/"app/ui/crop_canvas.py").read_text(encoding="utf-8")
        self.assertNotIn("prepare_crop_training_images",source)
        load=source[source.index(" def load_current"):source.index(" def _on_configure")]
        self.assertIn("self.canvas.delete('crop_overlay')",load)
        self.assertIn("base,proxy=load_project_developed(project,image_id)",load)
        self.assertIn("text='Loading image'",load)
        self.assertNotIn("Preparing image for crop",load)

    def test_crop_counts_are_cached_across_selection_only_changes(self):
        project = _CropCountProject()
        context = UIContext(project)
        self.assertEqual(10, context.crop_counts()["Total"])
        self.assertEqual(10, context.crop_counts()["Total"])
        self.assertEqual(1, project.calls)
        context.selected = 3
        self.assertEqual(10, context.crop_counts()["Total"])
        self.assertEqual(1, project.calls)
        context.invalidate_counts()
        self.assertEqual(10, context.crop_counts()["Total"])
        self.assertEqual(2, project.calls)

    def test_plain_list_selection_does_not_rebuild_all_rows(self):
        panel = object.__new__(PhotoListPanel)
        panel.canvas = SimpleNamespace(curselection=lambda: (1,))
        panel.visible_indices = [2, 5, 7]
        panel.context = SimpleNamespace(selected=0)
        calls = []
        panel._refresh_action = lambda: calls.append("action")
        panel._notify = lambda preserve: calls.append(("notify", preserve))
        panel.refresh = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("selection rebuilt full list"))
        PhotoListPanel._selected(panel)
        self.assertEqual(5, panel.context.selected)
        self.assertEqual(["action", ("notify", True)], calls)

    def test_navigation_cache_budget_scales_with_persisted_ram_and_is_bounded(self):
        with patch("app.ui.crop_canvas.persisted_hardware_profile", return_value=SimpleNamespace(ram_bytes=64 * 1024**3)):
            self.assertEqual(1024 * 1024**2, crop_navigation_cache_budget())
        with patch("app.ui.crop_canvas.persisted_hardware_profile", return_value=SimpleNamespace(ram_bytes=8 * 1024**3)):
            value = crop_navigation_cache_budget()
            self.assertGreaterEqual(value, 128 * 1024**2)
            self.assertLess(value, 256 * 1024**2)

    def _controller(self, budget=10_000_000):
        controller = object.__new__(CropCanvasController)
        controller._image_cache = OrderedDict()
        controller._image_cache_bytes = 0
        controller._image_cache_budget = budget
        controller._cache_lock = threading.Lock()
        return controller

    def test_decoded_cache_reuses_matching_source_and_invalidates_changed_source(self):
        controller = self._controller()
        row = {"image_id": "a", "file_size": 10, "mtime_ns": 20, "source_sha256": "x"}
        base = Image.new("RGB", (100, 60))
        proxy = Image.new("RGB", (50, 30))
        first = controller._cache_put(row, base, proxy)
        self.assertIs(first, controller._cache_get(dict(row)))
        changed = dict(row); changed["mtime_ns"] = 21
        self.assertIsNone(controller._cache_get(changed))
        self.assertEqual(0, len(controller._image_cache))

    def test_display_resize_is_reused_on_revisit(self):
        controller = self._controller()
        row = {"image_id": "a", "file_size": 10, "mtime_ns": 20, "source_sha256": "x"}
        entry = controller._cache_put(row, Image.new("RGB", (400, 300)), Image.new("RGB", (200, 150)))
        controller.base = entry["base"]
        controller._display_source = entry["proxy"]
        controller._current_cache_entry = entry
        controller._display_base = None
        controller._display_key = None
        controller._raster_key = None
        controller._display_dimensions = lambda: (160, 120)
        controller._ensure_display_base()
        first = controller._display_base
        self.assertEqual((160, 120), first.size)
        controller._display_base = None
        controller._display_key = None
        controller._ensure_display_base()
        self.assertIs(first, controller._display_base)


if __name__ == "__main__":
    unittest.main()
