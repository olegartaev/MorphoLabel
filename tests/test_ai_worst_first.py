import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.active_learning import select_ai_worst_first
from app.editor_ready_v15 import ReadyEditorV15


class FakeProject:
    schema = [{"id": 1}, {"id": 2}]
    def __init__(self):
        self.catalog = [
            {"image_id": "excluded", "excluded": True},
            {"image_id": "verified"},
            {"image_id": "corrected"},
            {"image_id": "high"},
            {"image_id": "low"},
        ]
        machine = lambda c: {1: {"state": "placed", "provenance": "machine", "confidence": c}, 2: {"state": "placed", "provenance": "machine", "confidence": c}}
        self.rows = {"excluded": machine(.1), "verified": machine(.1), "corrected": {1: {"state": "placed", "provenance": "corrected", "confidence": .1}, 2: {"state": "placed", "provenance": "machine", "confidence": .1}}, "high": machine(.95), "low": machine(.2)}
    def catalog_rows(self): return self.catalog
    def annotation_status(self, image_id): return {"complete": True, "verified": image_id == "verified"}
    def load_landmarks(self, image_id): return self.rows[image_id]


class WorstFirstTests(unittest.TestCase):
    def test_filters_and_deterministic_confidence_order(self):
        project = FakeProject()
        warnings = {"low": [{"kind": "bounds", "landmark_id": 1}], "high": []}
        with patch("app.active_learning.review_warnings", side_effect=lambda _p, image_id, *_a, **_k: warnings.get(image_id, [])):
            items = select_ai_worst_first(project, 25)
        self.assertEqual([item["image_id"] for item in items], ["low", "high"])
        self.assertEqual(items[0]["reason"], "structural")

    def test_startup_gate_suppresses_programmatic_click(self):
        editor = ReadyEditorV15.__new__(ReadyEditorV15)
        editor._canvas_landmark_input_ready = False
        self.assertIsNone(editor.left_down(SimpleNamespace(x=1, y=1)))

if __name__ == "__main__":
    unittest.main()
class WorstWorkerTests(unittest.TestCase):
    class Editor:
        def __init__(self):
            self.project = SimpleNamespace(active_model_readonly=lambda _kind: {"model_id": "m"})
            self.queue = []; self.progress = object(); self.ai_worst_next_button = SimpleNamespace(grid=lambda: None); self.opened = []
        def after(self, _delay, callback): self.queue.append(callback)
        def _show_nonmodal_progress(self, *_args): return self.progress, SimpleNamespace()
        def _close_nonmodal_progress(self, *_args): pass
        def _set_landmark_workflow_controls(self): pass
        def _open_landmark_workflow_item(self, index): self.opened.append(index)
    def test_worker_returns_immediately_and_opens_first_ranked_item(self):
        import time
        editor = self.Editor(); ranked = [{"image_id": "worst"}, {"image_id": "next"}]
        with patch("app.editor_ready_v15.simpledialog.askinteger", return_value=25), patch("app.editor_ready_v15.select_ai_worst_first", side_effect=lambda *_: (time.sleep(.05), ranked)[1]):
            started = time.monotonic(); ReadyEditorV15.start_review_ai_worst_first(editor); self.assertLess(time.monotonic() - started, .04)
        for _ in range(100):
            while editor.queue: editor.queue.pop(0)()
            if editor.opened: break
            time.sleep(.005)
        self.assertEqual(editor.opened, [0]); self.assertEqual(editor._landmark_workflow_ids, ["worst", "next"])
    def test_worker_exception_reports_and_restores(self):
        import time
        editor = self.Editor()
        with patch("app.editor_ready_v15.simpledialog.askinteger", return_value=25), patch("app.editor_ready_v15.select_ai_worst_first", side_effect=RuntimeError("boom")), patch("app.editor_ready_v15.messagebox.showerror") as error:
            ReadyEditorV15.start_review_ai_worst_first(editor)
            for _ in range(100):
                while editor.queue: editor.queue.pop(0)()
                if error.called: break
                time.sleep(.005)
            error.assert_called_once()
        self.assertFalse(getattr(editor, "_ai_worst_selection_worker", True))
if __name__ == "__main__":
    unittest.main()
