import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.editor_ready_v15 import ReadyEditorV15


class _Button:
 def __init__(self): self.states = []
 def config(self, **kwargs): self.states.append(kwargs)


class _Dialog:
 def __init__(self): self.destroyed = False
 def destroy(self): self.destroyed = True


class _Diagnostics:
 def __init__(self): self.events = []
 def end(self, *args, **kwargs): self.events.append(("end", args, kwargs))
 def event(self, *args, **kwargs): self.events.append(("event", args, kwargs))
 def close(self): self.events.append(("close", (), {}))


class CropBatchGuiSequenceTests(unittest.TestCase):
 def _finish_editor(self):
  editor = SimpleNamespace(
   _crop_batch_preparing=True, crop_training_batch_button=_Button(), _crop_batch_diagnostics=_Diagnostics(),
   _crop_training_queue=[], _crop_training_summary=None, _crop_batch_completed=False,
  )
  editor._open_next_crop_training = lambda: setattr(editor, "opened_next", getattr(editor, "opened_next", 0) + 1)
  return editor

 def test_preparation_completion_does_not_show_summary_before_first_editor(self):
  editor = self._finish_editor(); dialog = _Dialog()
  summary = {"selected": 2, "prepared_ids": ("one", "two"), "skipped": (), "proposal_failures": ()}
  with patch("app.editor_ready_v15.messagebox.showinfo") as show:
   ReadyEditorV15._finish_crop_training_preparation(editor, dialog, summary, 2)
  self.assertTrue(dialog.destroyed)
  self.assertEqual(1, editor.opened_next)
  show.assert_not_called()

 def test_summary_is_only_shown_after_queue_is_empty(self):
  editor = self._finish_editor(); editor._crop_training_summary = {"selected": 2, "prepared_ids": ("one", "two"), "skipped": ()}
  with patch("app.editor_ready_v15.messagebox.showinfo") as show:
   ReadyEditorV15._show_crop_training_batch_summary(editor)
  show.assert_called_once()

 def test_editor_close_callback_schedules_next_only_after_editor_reference_cleared(self):
  order = []
  editor = self._finish_editor(); editor._crop_training_editor = object()
  editor.after_idle = lambda callback: (order.append("after_idle"), callback())
  editor._open_next_crop_training = lambda: order.append("open_next")
  ReadyEditorV15._crop_training_editor_finished(editor, "one")
  self.assertIsNone(editor._crop_training_editor)
  self.assertEqual(["after_idle", "open_next"], order)

 def test_existing_editor_blocks_overlap(self):
  class Existing:
   def winfo_exists(self): return True
  editor = self._finish_editor(); editor._crop_training_editor = Existing(); editor._crop_training_queue = ["two"]
  ReadyEditorV15._open_next_crop_training(editor)
  self.assertEqual(["event"], [kind for kind, _, _ in editor._crop_batch_diagnostics.events if kind == "event"])

if __name__ == "__main__": unittest.main()
