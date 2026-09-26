from tkinter import messagebox
from .editor_ready_v6 import ReadyEditorV6
from .crop_editor import CropEditor

class ReadyEditorV7(ReadyEditorV6):
 def correct_normalization(self):
  if self.record.get("points"):messagebox.showwarning("Coordinates protected","Remove/export landmarks before changing transform; coordinates are never silently remapped.");return
  CropEditor(self,self.source,self.open_image)
def run():ReadyEditorV7().mainloop()
if __name__=="__main__":run()
