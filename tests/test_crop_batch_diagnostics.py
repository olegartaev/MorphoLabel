import time
import unittest
from pathlib import Path

from app.crop_training_batch import CropBatchDiagnostics


class CropBatchDiagnosticsTests(unittest.TestCase):
 def setUp(self):
  self.records = []; self.errors = []; self.dumps = []
  self.rows = [{"image_id": "one", "relative_path": "A/one.nef"}, {"image_id": "two", "relative_path": "B/two.nef"}]
  def logger(image_id, operation, state, elapsed=0.0, path="", detail=""):
   self.records.append((operation, state, image_id, detail))
  self.diag = CropBatchDiagnostics("batch-test", requested_count=2, selected_rows=self.rows, active_model_id="crop_v1", watchdog_seconds=5, log_fn=logger, error_fn=lambda *args: self.errors.append(args), dump_threads_fn=lambda *args: self.dumps.append(args))
 def tearDown(self): self.diag.close()

 def test_normal_two_image_batch_has_ordered_preparation_events(self):
  self.diag.begin("crop_batch_preparation")
  for index, row in enumerate(self.rows, 1):
   self.diag.begin("crop_batch_prepare_image", image_id=row["image_id"], batch_index=index, batch_total=2)
   self.diag.end("crop_batch_prepare_image", image_id=row["image_id"], batch_index=index, batch_total=2, detail="result=prepared")
  self.diag.end("crop_batch_preparation")
  events = [(name, state, image_id) for name, state, image_id, _ in self.records]
  self.assertEqual(events[:6], [("crop_batch_start", "START", "GLOBAL"), ("crop_batch_preparation", "START", "GLOBAL"), ("crop_batch_prepare_image", "START", "one"), ("crop_batch_prepare_image", "END", "one"), ("crop_batch_prepare_image", "START", "two"), ("crop_batch_prepare_image", "END", "two")])

 def test_apply_save_and_next_transition_are_recorded(self):
  self.diag.event("crop_batch_apply_pressed", image_id="one", batch_index=1, batch_total=2)
  self.diag.begin("crop_batch_crop_save", image_id="one", batch_index=1, batch_total=2)
  self.diag.end("crop_batch_crop_save", image_id="one", batch_index=1, batch_total=2)
  self.diag.event("crop_batch_editor_close", "END", image_id="one", batch_index=1, batch_total=2)
  self.diag.event("crop_batch_next_image_requested", "START", image_id="two", batch_index=2, batch_total=2)
  names = [record[0] for record in self.records]
  self.assertLess(names.index("crop_batch_apply_pressed"), names.index("crop_batch_crop_save"))
  self.assertLess(names.index("crop_batch_editor_close"), names.index("crop_batch_next_image_requested"))

 def test_failure_routes_exception_to_full_traceback_logger(self):
  failure = RuntimeError("simulated preparation failure")
  self.diag.begin("crop_batch_prepare_image", image_id="one", batch_index=1)
  self.diag.failure("crop_batch_prepare_image", failure, image_id="one", batch_index=1, path="A/one.nef")
  self.assertIs(self.errors[0][3], failure)
  self.assertIn("failure=RuntimeError", self.records[-1][3])

 def test_watchdog_logs_and_dumps_threads_without_project_mutation(self):
  self.diag.close()
  self.diag = CropBatchDiagnostics("batch-watchdog", requested_count=1, selected_rows=self.rows[:1], active_model_id="crop_v1", watchdog_seconds=.01, log_fn=lambda image_id, operation, state, elapsed=0.0, path="", detail="": self.records.append((operation, state, image_id, detail)), error_fn=lambda *args: self.errors.append(args), dump_threads_fn=lambda *args: self.dumps.append(args))
  self.diag.begin("crop_batch_editor_open", image_id="one", batch_index=1)
  time.sleep(.08)
  self.assertTrue(any(row[0] == "crop_batch_watchdog" and row[1] == "WARNING" for row in self.records))
  self.assertEqual("one", self.dumps[0][0])

 def test_editor_contains_batch_action_and_ready_events(self):
  source = (Path(__file__).parents[1] / "app" / "crop_editor_async_v2.py").read_text(encoding="utf8")
  for event in ("crop_batch_editor_opened", "crop_batch_editor_ready", "crop_batch_apply_pressed", "crop_batch_cancel_pressed", "crop_batch_crop_save", "crop_batch_editor_close"):
   self.assertIn(event, source)

if __name__ == "__main__": unittest.main()
