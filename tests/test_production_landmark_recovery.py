import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.landmark_ai_workflow import STATE_KEY, begin_improvement
from app.project_storage import Project
from app.ui.context import UIContext
from app.ui.landmarks_section import LandmarksSection


class ProductionLandmarkRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"
        for locality in ("A", "B", "C"):
            folder = source / locality
            folder.mkdir(parents=True, exist_ok=True)
            for number in range(4):
                Image.new("RGB", (20, 20)).save(folder / f"fish_{number}.jpg")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name\n1,A,Alpha\n", encoding="utf-8")
        self.project = Project.create("project", source, self.root, schema, source_layout="direct")
        self.ids = [row["image_id"] for row in self.project.catalog_rows()]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_new_improvement_preserves_prior_sets_and_uses_diverse_selection(self):
        control, initial, old = self.ids[:2], self.ids[2:4], self.ids[4:7]
        for image_id in old:
            self.project.save_landmark(image_id, 1, 5, 5, "manual", "manual")
            self.project.mark_checked(image_id)
        state = {"stage": "READY_FOR_FULL_PREDICTION", "seed": 11, "control_image_ids": control, "initial_image_ids": initial, "improvement_image_ids": old, "improvement_history_ids": [], "improvement_target": 5}
        self.project.set_ui_state(STATE_KEY, state)
        with patch("app.landmark_ai_workflow.refresh_stage", return_value=dict(state)):
            result = begin_improvement(self.project, target=5)
        blocked = set(control) | set(initial) | set(old)
        self.assertEqual("MODEL_IMPROVEMENT", result["stage"])
        self.assertEqual(5, len(result["improvement_image_ids"]))
        self.assertFalse(blocked & set(result["improvement_image_ids"]))
        self.assertEqual(old, result["improvement_history_ids"])

    def test_completed_initial_stage_routes_production_button_to_improvement(self):
        state = {"stage": "READY_FOR_FULL_PREDICTION", "seed": 11, "control_image_ids": self.ids[:2], "initial_image_ids": self.ids[2:4], "improvement_image_ids": [], "improvement_history_ids": []}
        section = LandmarksSection.__new__(LandmarksSection)
        section.context = type("Context", (), {"project": self.project, "rows": self.project.catalog_rows()})()
        called = []
        section._start_improvement_batch = lambda count, value: called.append((count, value))
        with patch("app.ui.landmarks_section.stage_summary", return_value={"state": state, "stage": "READY_FOR_FULL_PREDICTION", "verified": 0, "total": 0}):
            section.start_training_batch(6)
        self.assertEqual([(6, state)], called)

    def test_single_authoritative_row_refresh_changes_red_yellow_green_and_reopens(self):
        context = UIContext(self.project)
        context.refresh(force=True)
        image_id = self.ids[0]
        self.assertEqual("red", next(row for row in context.rows if row["image_id"] == image_id)["status_color"])
        self.project.save_landmark(image_id, 1, 3, 4, "auto", "machine")
        self.assertTrue(context.refresh_landmark_state(image_id))
        self.assertEqual("yellow", next(row for row in context.rows if row["image_id"] == image_id)["status_color"])
        self.project.mark_checked(image_id)
        context.refresh_landmark_state(image_id)
        self.assertEqual("green", next(row for row in context.rows if row["image_id"] == image_id)["status_color"])
        reopened = Project.open(self.project.root)
        self.assertEqual("green", reopened.catalog_row(image_id)["status_color"])


if __name__ == "__main__":
    unittest.main()