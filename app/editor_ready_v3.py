"""Current editor: fish-centered standardized masters for annotation."""
from pathlib import Path
from .editor_ready_v2 import ReadyEditorV2
from .standardize import decode
from .standardize_fish import standardized_master
from .workflow import load_record,save_record

class ReadyEditorV3(ReadyEditorV2):
 def open_image(self):
  row=self.current();source=Path(row["source_relpath"]);meta=standardized_master(source);self.source=decode(source);self.standard=decode(Path(meta["standardized_relpath"]));self.source_mode=False;self.record=load_record(row,self.profile.profile_id,self.profile.version)
  if not self.record.get("source_sha256"):self.record["source_sha256"]=meta["source_sha256"];save_record(self.record)
  self.state.open_record(self.record);self.zoom=min(1.,1050/self.standard.width,720/self.standard.height);self.pan=[0.,0.];self.sync()
def run():ReadyEditorV3().mainloop()
if __name__=="__main__":run()
