import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.editor_ready_v15 import ReadyEditorV15


class LandmarkProgressUiTests(unittest.TestCase):
    class Thread:
        created = []
        def __init__(self, *, target, **_kwargs): self.target = target; self.__class__.created.append(self)
        def start(self): pass

    def test_check_ai_quality_uses_background_control_evaluator(self):
        editor = ReadyEditorV15.__new__(ReadyEditorV15)
        editor.project = SimpleNamespace(active_model=lambda _kind: {"model_id": "active"})
        progress = Mock(); editor._show_nonmodal_progress = Mock(return_value=(progress, Mock()))
        editor._close_nonmodal_progress = Mock(); editor.after = lambda _delay, callback: callback()
        self.Thread.created = []
        result = {"aggregate": {"n_images": 2, "median_error_px": 1.0, "p90_error_px": 2.0, "p95_error_px": 3.0}}
        with patch("app.editor_ready_v15.threading.Thread", self.Thread), patch("app.editor_ready_v15.evaluate_control_set", return_value=result) as evaluate, patch("app.editor_ready_v15.messagebox.showinfo") as showinfo:
            editor.check_ai_quality()
            self.assertEqual(1, len(self.Thread.created))
            self.Thread.created[0].target()
        evaluate.assert_called_once_with(editor.project, "active")
        self.assertIn("Control images: 2", showinfo.call_args.args[1])
        editor._close_nonmodal_progress.assert_called_once_with(progress)

    def test_training_exception_reaches_failure_handler_without_name_error(self):
        editor = ReadyEditorV15.__new__(ReadyEditorV15)
        editor.project = object(); editor.after = lambda _delay, callback: callback()
        editor._landmark_training_failed = Mock()
        self.Thread.created = []
        original = RuntimeError("real training failure")
        with patch("app.editor_ready_v15.threading.Thread", self.Thread), patch("app.editor_ready_v15.run_landmark_training", side_effect=original):
            editor._run_landmark_training_worker(SimpleNamespace())
            self.assertEqual(1, len(self.Thread.created))
            self.Thread.created[0].target()
        editor._landmark_training_failed.assert_called_once_with(original)
    def test_training_progress_stays_open_through_control_comparison(self):
        editor = ReadyEditorV15.__new__(ReadyEditorV15)
        editor.project = object(); editor.landmark_train_button = Mock()
        progress = Mock(); progress.winfo_exists.return_value = True
        label = Mock(); editor._landmark_training_progress = progress; editor._landmark_training_progress_label = label
        editor._show_nonmodal_progress = Mock(); editor._close_nonmodal_progress = Mock(); editor._show_landmark_training_complete = Mock()
        editor.after = lambda _delay, callback: callback()
        self.Thread.created = []
        plan = SimpleNamespace(parent_model_id="old", model_id="new")
        comparison = {"metrics": {}, "result": "Mixed"}
        with patch("app.editor_ready_v15.threading.Thread", self.Thread), patch("app.editor_ready_v15.compare_control_models", return_value=comparison) as compare:
            editor._landmark_training_complete(plan, {"engineering_validation": {}})
            self.assertIn("Evaluating old and new models", label.config.call_args.kwargs["text"])
            editor._close_nonmodal_progress.assert_not_called()
            self.Thread.created[0].target()
        compare.assert_called_once_with(editor.project, "old", "new")
        editor._close_nonmodal_progress.assert_called_once_with(progress)
        editor._show_landmark_training_complete.assert_called_once()


if __name__ == "__main__":
    unittest.main()