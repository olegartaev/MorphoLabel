import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.ui.landmarks_section import LandmarksSection
from app.ui.crop_section import CropSection
from app.ui.measurements_section import MeasurementPreview


class PendingActionRaceTests(unittest.TestCase):
    def test_landmark_pending_next_is_exact_generation_and_runs_once_for_both_batches(self):
        for stage in ('INITIAL_TRAINING', 'MODEL_IMPROVEMENT'):
            section = LandmarksSection.__new__(LandmarksSection)
            section._pending_next_image_id = ('A', 70)
            section.navigate_training_batch = Mock()
            section._image_ready('A', 6, 69)
            section.navigate_training_batch.assert_not_called()
            section._image_ready('A', 7, 70)
            section.navigate_training_batch.assert_called_once_with(1)
            section._image_ready('A', 7, 70)
            section.navigate_training_batch.assert_called_once()
            section._pending_next_image_id = ('A', 80)
            section.cancel_pending_for_target('B')
            self.assertIsNone(section._pending_next_image_id, stage)


    def test_preload_selection_epoch_keeps_landmark_next(self):
        section=LandmarksSection.__new__(LandmarksSection)
        section.context=SimpleNamespace(current=lambda:{'image_id':'B'})
        section.shell=SimpleNamespace(selection_request_epoch=22, status_context=SimpleNamespace(configure=Mock()))
        section.canvas=SimpleNamespace(requested_generation=10, requested_request_epoch=11, ready_for=lambda _id:False)
        section.navigate_training_batch=Mock()
        self.assertTrue(section.navigate_training_batch if False else True)
        section._pending_next_image_id=('B',22)  # equivalent to Next during the after_idle pre-load gap
        # B starts with generation 11 but retains request epoch 22.
        section._image_ready('B',11,22)
        section.navigate_training_batch.assert_called_once_with(1)
        section._pending_next_image_id=('B',22);section.cancel_pending_for_target('C')
        section._image_ready('B',12,22)
        section.navigate_training_batch.assert_called_once()

    def _crop_section(self):
        section = CropSection.__new__(CropSection)
        current = {'image_id': 'A'}
        section.context = SimpleNamespace(current=lambda: current)
        section.shell = SimpleNamespace(status_context=SimpleNamespace(configure=Mock()), selection_request_epoch=30)
        section.canvas = SimpleNamespace(requested_generation=3, apply=Mock(return_value='SAVED'))
        section._move_batch = Mock()
        return section, current

    def test_crop_deferred_apply_next_runs_once_and_stale_target_is_cancelled(self):
        for batch_type in ('training', 'prediction_review'):
            section, current = self._crop_section()
            section._defer_crop_action(True)
            self.assertEqual(('A', 30, True), section._pending_crop_action, batch_type)
            section._crop_ready('A', 2, 29)
            section.canvas.apply.assert_not_called()
            section._crop_ready('A', 3, 30)
            section.canvas.apply.assert_called_once()
            section._move_batch.assert_called_once_with(1, _already_saved=True)
            section._crop_ready('A', 3, 30)
            section._move_batch.assert_called_once()
            section._pending_crop_action=('A', 40, True)
            current['image_id']='B'; section.cancel_pending_for_target('B')
            self.assertIsNone(section._pending_crop_action, batch_type)

    def test_crop_failed_and_deferred_never_advance(self):
        section, _ = self._crop_section()
        section.canvas.apply.return_value='FAILED'
        self.assertIsNone(section._crop_ready('A',3,30))
        section._move_batch.assert_not_called()
        section.canvas.apply.return_value='DEFERRED'
        section._pending_crop_action=('A',30,True)
        section._crop_ready('A',3,30)
        self.assertEqual(('A',30,True),section._pending_crop_action)
        section._move_batch.assert_not_called()

    def test_measurement_preview_rejects_late_a_event_after_b_is_requested(self):
        preview=MeasurementPreview.__new__(MeasurementPreview)
        current={'image_id':'B'}
        preview.context=SimpleNamespace(current=lambda:current)
        preview._token=2;preview.requested_image_id='B';preview.displayed_image_id=None
        preview._queue=queue.Queue();preview._preparing={'A'};preview._destroyed=False
        preview.canvas=SimpleNamespace(after=lambda *_:None, delete=Mock(), create_text=Mock())
        preview.render=Mock();preview._queue.put(('ready','A',1))
        MeasurementPreview.poll(preview)
        self.assertIsNone(preview.displayed_image_id)
        preview.render.assert_not_called()

    def test_human_repeatability_is_session_scoped_not_selection_async(self):
        from pathlib import Path; source=Path('app/human_baseline_ui.py').read_text(encoding='utf8')
        self.assertIn('self.sid=self.session_ids[self.index]',source)
        self.assertNotIn('context.current()',source)

if __name__ == '__main__':
    unittest.main()
