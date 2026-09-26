from tkinter import messagebox
from pathlib import Path
from .editor_ready_v8 import ReadyEditorV8
from .crop_editor_async_v2 import AsyncCropEditorV2
from .gui_crop_debug import error, log
from .standardize import image_id
from .project_runtime import active_project
class ReadyEditorV9(ReadyEditorV8):
 def correct_normalization(self):
  row=self.current(); project=active_project() or getattr(self,"project",None); source=Path(row.get("source_path",row["source_relpath"])); ident=str(row.get("image_id")) if project and row.get("image_id") else image_id(source); log(ident,"correct_crop_button_click","START",path=str(source))
  try:
   log(ident,"correct_crop_button_click","END",path=str(source),detail="blocked_by_existing_landmarks=false");log(ident,"source_image_resolved","END",path=str(source));AsyncCropEditorV2(self,source,getattr(self,"post_crop_apply_refresh",self.open_image),project=project,image_id_value=ident);log(ident,"correct_crop_button_click","END",path=str(source))
  except Exception as exc:
   error(ident,"correct_crop_button_click",str(source),exc);raise
def run():ReadyEditorV9().mainloop()
if __name__=="__main__":run()
