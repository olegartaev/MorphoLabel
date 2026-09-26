"""Acceptance editor with protected human crop/rotation correction."""
from pathlib import Path
from tkinter import ttk,simpledialog,messagebox
from .editor_ready_v3 import ReadyEditorV3
from .io import read_json
from .normalization import apply_review_transform
from .paths import WORK
from .standardize import decode,image_id
from .standardize_fish import standardized_master
from .workflow import load_record,save_record

class ReadyEditorV4(ReadyEditorV3):
 def _layout(self):
  super()._layout();ttk.Button(self.landmark_pane,text="Correct crop / rotation",command=self.correct_normalization).pack(fill="x")
 def open_image(self):
  row=self.current();source=Path(row["source_relpath"]);mp=WORK/source.parent.name/"metadata"/f"{image_id(source)}.json";old=read_json(mp,{})
  meta=old if old.get("qc_reason")=="human_manual_correction" and Path(old.get("standardized_relpath","")).exists() else standardized_master(source)
  self.source=decode(source);self.standard=decode(Path(meta["standardized_relpath"]));self.source_mode=False;self.record=load_record(row,self.profile.profile_id,self.profile.version)
  if not self.record.get("source_sha256"):self.record["source_sha256"]=meta["source_sha256"];save_record(self.record)
  self.state.open_record(self.record);self.zoom=min(1.,1050/self.standard.width,720/self.standard.height);self.pan=[0.,0.];self.sync()
 def correct_normalization(self):
  if self.record.get("points"):messagebox.showwarning("Coordinates protected","Remove/export landmarks before changing transform; coordinates are never silently remapped.");return
  text=simpledialog.askstring("Crop / rotation","rotation degrees; left,top,right,bottom\nExample: 180; 1500,1700,5400,3650")
  if text is None:return
  try:
   a,c=text.split(";",1);crop=tuple(int(x.strip()) for x in c.split(","));assert len(crop)==4;apply_review_transform(Path(self.current()["source_relpath"]),crop,float(a.strip()),"human_manual_correction");self.open_image()
  except Exception as exc:messagebox.showerror("Invalid transform",str(exc))
def run():ReadyEditorV4().mainloop()
if __name__=="__main__":run()
