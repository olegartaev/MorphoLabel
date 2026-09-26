"""Live-Tk acceptance for the checkpoint's review transition (disposable data)."""
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.landmark_frames import restore_standardized_frame
from app.project_storage import Project
from app.transforms import Transform
from app.ui.shell import ProductionShell


class CheckpointGuiAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        source = self.root / "source"; source.mkdir()
        for number in range(2):
            Image.new("RGB", (80, 50), (number * 30, 40, 90)).save(source / f"fish_{number}.png")
        schema = self.root / "schema.csv"
        schema.write_text("id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,BOTH\n", encoding="utf-8")
        self.project = Project.create("checkpoint-ui", source, self.root, schema, source_types=["png"], source_layout="direct")
        self.ids = [row["image_id"] for row in self.project.catalog_rows()]
        for image_id in self.ids:
            source_path = self.project.image_path(image_id)
            developed = self.project.cache_root / "developed" / f"{image_id}.png"
            developed.parent.mkdir(parents=True, exist_ok=True)
            Image.open(source_path).convert("RGB").save(developed)
            transform = Transform(80, 50, 0.0, 40.0, 25.0, 5, 4, 60, 36)
            self.project.save_reviewed_crop(image_id, {
                "developed_full_relpath": f"cache/developed/{image_id}.png",
                "standardized_relpath": f"cache/standardized/{image_id}.png",
                "crop_bounds": [5, 4, 65, 40], "rotation_degrees": 0.0,
                "transform": transform.__dict__, "normalization_status": "PASS",
            })
            restore_standardized_frame(self.project, image_id)
            for landmark_id, point in ((1, (10, 11)), (2, (20, 21))):
                self.project.save_landmark(image_id, landmark_id, *point, "auto", provenance="machine",
                                           model_id="rtmpose_v1", predicted_x=point[0], predicted_y=point[1],
                                           confidence=.8, prediction_run_id="qa-run", reviewed=False)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _pump(self, shell, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            shell.update(); shell.update_idletasks()
            if predicate(): return True
            time.sleep(.02)
        return False

    def test_yes_review_opens_first_predicted_image_and_top_confirm_advances(self):
        shell = None
        try:
            shell = ProductionShell(self.project)
            shell.withdraw(); shell.select("landmarks")
            view = shell.current_view
            batch = {"batch_id": "qa-prediction", "selected_images": [{"image_id": image_id} for image_id in self.ids],
                     "prediction_runs": {image_id: {"run_id": "qa-run"} for image_id in self.ids}, "failures": {}}
            # This is the actual post-worker Yes callback, with only the native
            # messagebox response supplied by the test.
            with patch("app.ui.landmarks_section.messagebox.askyesno", return_value=True):
                view._offer_prediction_review(batch)
            # Entering review deliberately rebuilds the workspace, so use the
            # newly displayed controller rather than the pre-prediction view.
            view = shell.current_view
            self.assertTrue(self._pump(shell, lambda: (shell.context.current() or {}).get("image_id") == self.ids[0]
                                           and view.canvas.ready_for(self.ids[0])))
            self.assertEqual("Confirm & Next", shell.status_next.cget("text"))
            self.assertIn("1 / 2", shell.status_index.cget("text"))
            shell.status_next.invoke()
            self.assertTrue(self._pump(shell, lambda: (shell.context.current() or {}).get("image_id") == self.ids[1]
                                           and view.canvas.ready_for(self.ids[1])))
            self.assertTrue(self.project.landmark_ai_review_ready(self.ids[0]))
            self.assertIn("2 / 2", shell.status_index.cget("text"))
        finally:
            if shell is not None:
                shell.destroy()


if __name__ == "__main__":
    unittest.main()
