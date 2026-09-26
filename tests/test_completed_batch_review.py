import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.annotation_check import AnnotationCheckResult
from app.editor_ready_v15 import ReadyEditorV15


class CompletedBatchReviewTests(unittest.TestCase):
    def _completed_editor(self, stage):
        image_id = "completed-image"
        editor = ReadyEditorV15.__new__(ReadyEditorV15)
        editor._annotation_check_for_current = lambda: AnnotationCheckResult(image_id, (), ())
        editor._load_current_landmark_state = lambda: SimpleNamespace(image_id=image_id, complete=True)
        editor.current = lambda: {"image_id": image_id}
        editor.mark_checked = lambda: None
        editor._landmark_workflow_review_only = False
        editor._landmark_workflow_active = True
        editor._landmark_workflow_ids = [image_id]
        editor._set_landmark_workflow_controls = lambda: None
        editor._refresh_landmark_ai_panel = lambda: None
        editor.review_landmark_set = Mock()

        class Project:
            def annotation_status(self, _image_id): return {"verified": True}
            def clear_annotation_draft(self, _image_id): pass
        editor.project = Project()
        info = {"stage": stage, "friendly_stage": "Initial training" if stage == "INITIAL_TRAINING" else "Improve model", "current_ids": (image_id,), "verified": 1, "total": 1, "active_model_id": "old-model", "state": {}}
        return editor, info

    def _assert_completed_batch_starts_review(self, stage):
        editor, info = self._completed_editor(stage)
        with patch("app.editor_ready_v15.stage_summary", return_value=info), patch("app.editor_ready_v15.messagebox.showinfo") as showinfo:
            editor.workflow_confirm_next()
        editor.review_landmark_set.assert_called_once_with(stage, problems_only=True)
        self.assertTrue(any(call.args[0] == "Marking complete" for call in showinfo.call_args_list))

    def test_completed_initial_batch_starts_problems_only_review(self):
        self._assert_completed_batch_starts_review("INITIAL_TRAINING")

    def test_completed_improvement_batch_starts_problems_only_review(self):
        self._assert_completed_batch_starts_review("MODEL_IMPROVEMENT")


if __name__ == "__main__":
    unittest.main()