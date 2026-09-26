import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

import app.timing_profile as timing
from app.ui.context import UIContext
from app.ui.crop_section import CropSection
from app.ui.shell import ProductionShell


class _Project:
    def __init__(self): self.crops = set()
    def crop_exists(self, image_id): return image_id in self.crops
    def landmark_crop_ready(self, image_id): return image_id in self.crops
    def crop_counts(self): return {"Cropped": len(self.crops), "Review": 2}


class _Label:
    def __init__(self): self.text = None
    def configure(self, **kwargs): self.text = kwargs.get("text", self.text)


class _Panel:
    def __init__(self): self.calls = []
    def refresh(self, **kwargs): self.calls.append(kwargs)


class CropStateUiRegressionTests(unittest.TestCase):
    def test_explicit_external_image_id_never_derives_from_source_path(self):
        old_reports, old_path = timing.REPORTS, timing.PATH
        try:
            root = Path(tempfile.mkdtemp())
            timing.REPORTS = root; timing.PATH = root / "timing.jsonl"
            timing.record(Path("D:/outside-project/fish.nef"), "decode", .01, image_id_value="canonical-5")
            self.assertEqual("canonical-5", json.loads(timing.PATH.read_text(encoding="utf-8"))["image_id"])
        finally:
            timing.REPORTS, timing.PATH = old_reports, old_path

    def test_crop_marker_refreshes_one_cached_row_from_project(self):
        project = _Project(); context = UIContext(project=project, section="crop", rows=[{"image_id": "one", "has_crop": False}])
        project.crops.add("one")
        self.assertTrue(context.refresh_crop_state("one"))
        self.assertTrue(context.rows[0]["has_crop"])

    def test_crop_section_refresh_preserves_photo_list_state(self):
        project = _Project(); project.crops.add("one")
        context = UIContext(project=project, section="crop", rows=[{"image_id": "one", "has_crop": False}])
        shell = type("Shell", (), {"photo_panel": _Panel(), "_update_status": lambda self: None})()
        section = CropSection.__new__(CropSection); section.context = context; section.shell = shell; section.remaining_label = _Label(); section.batch_status = lambda: "No active batch"
        section.refresh("one")
        self.assertTrue(context.rows[0]["has_crop"])
        self.assertEqual([{"preserve_scroll": True}], shell.photo_panel.calls)

    def test_crop_header_uses_crop_counts_after_refresh(self):
        project = _Project(); project.crops.add("one")
        context = type("Context", (), {"project": project, "section": "crop", "counts": lambda self: {"Cropped": 0}})()
        shell = ProductionShell.__new__(ProductionShell); shell.context = context
        self.assertEqual({"Cropped": 1, "Review": 2}, shell._section_counts())

    def test_apply_failure_text_includes_concrete_reason_and_log(self):
        source = Path("app/ui/crop_section.py").read_text(encoding="utf-8")
        self.assertIn("First failure: {reason}", source)
        self.assertIn("app.log (complete per-image failures)", source)

    def test_accept_all_ai_crops_is_one_explicit_bulk_confirmation(self):
        project = type("Project", (), {
            "pending_ai_crop_summary": lambda self: {"total": 546, "by_qc": {"REVIEW": 546}},
            "accept_all_ai_crops": Mock(return_value={"accepted": 546, "skipped": 0}),
        })()
        context = type("Context", (), {"project": project, "invalidate_catalog": Mock(), "refresh": Mock()})()
        shell = type("Shell", (), {"render": Mock()})()
        section = CropSection.__new__(CropSection); section.context = context; section.shell = shell
        with patch("app.ui.crop_section.messagebox.askyesno", return_value=True) as confirm, patch("app.ui.crop_section.messagebox.showinfo"):
            self.assertTrue(section.accept_all_ai_crops())
        confirm.assert_called_once()
        project.accept_all_ai_crops.assert_called_once()
        context.invalidate_catalog.assert_called_once(); context.refresh.assert_called_once_with(force=True); shell.render.assert_called_once()



if __name__ == "__main__":
    unittest.main()