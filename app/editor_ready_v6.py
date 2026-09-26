from pathlib import Path
from .editor_ready_v4 import ReadyEditorV4
from .io import read_json
from .normalization_pipeline_v2 import normalize
from .paths import WORK
from .standardize import decode,image_id
from .workflow import load_record,save_record
class ReadyEditorV6(ReadyEditorV4):
 def open_image(self):
  row=self.current();source=Path(row["source_relpath"]);mp=WORK/source.parent.name/"metadata"/f"{image_id(source)}.json";old=read_json(mp,{})
  meta=old if old.get("qc_reason")=="human_manual_correction" and Path(old.get("standardized_relpath","")).exists() else normalize(source)
  self.source=decode(source);self.standard=decode(Path(meta["standardized_relpath"]));self.source_mode=False;self.record=load_record(row,self.profile.profile_id,self.profile.version)
  if not self.record.get("source_sha256"):self.record["source_sha256"]=meta["source_sha256"];save_record(self.record)
  self.state.open_record(self.record);self.zoom=min(1.,1050/self.standard.width,720/self.standard.height);self.pan=[0.,0.];self.sync()
def run():ReadyEditorV6().mainloop()
if __name__=="__main__":run()
