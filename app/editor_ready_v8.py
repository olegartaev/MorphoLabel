from tkinter import messagebox
from .editor_ready_v7 import ReadyEditorV7
from .crop_editor_async import AsyncCropEditor
from .recovery import snapshot
from .workflow import save_record
from .project_runtime import active_project

class ReadyEditorV8(ReadyEditorV7):
 def correct_normalization(self):
  if self.record.get("points"):messagebox.showwarning("Coordinates protected","Clear/export landmarks before changing transform; coordinates are never silently remapped.");return
  AsyncCropEditor(self,self.source,self.open_image)
 def _layout(self):
  super()._layout();import tkinter as tk
  from tkinter import ttk
  ttk.Button(self.landmark_pane,text="Clear all landmarks",command=self.clear_all).pack(fill="x");self.bind("<Control-Shift-Delete>",lambda _:self.clear_all())
 def clear_all(self):
  if not self.record.get("points"):return
  if not messagebox.askyesno("Clear all landmarks",f"Clear all {len(self.profile.landmarks)} landmarks for this image?"):return
  if active_project() is None: snapshot(self.record,"before_clear_all_landmarks")
  self.record["points"]={};save_record(self.record);self.state.open_record(self.record);self.sync()
def run():ReadyEditorV8().mainloop()
if __name__=="__main__":run()


