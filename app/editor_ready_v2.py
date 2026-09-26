"""Corrected editor with append-only undo snapshots."""
from tkinter import messagebox
from .editor_ready import ReadyEditor
from .recovery import snapshot,restore_latest
from .workflow import save_record

class ReadyEditorV2(ReadyEditor):
 def left_down(self,event):
  if not self.source_mode and self.calibration is None and self.record.get("image_id"):snapshot(self.record,"before_left_action")
  return super().left_down(event)
 def missing(self):
  if not self.source_mode and self.record.get("image_id"):snapshot(self.record,"before_missing")
  return super().missing()
 def remove(self):
  if not self.source_mode and self.record.get("image_id"):snapshot(self.record,"before_remove")
  return super().remove()
 def undo(self):
  old=restore_latest(self.record)
  if not old:messagebox.showinfo("Undo","No saved state.");return
  self.record=old;save_record(self.record);self.state.open_record(self.record);self.sync()
def run():ReadyEditorV2().mainloop()
if __name__=="__main__":run()

