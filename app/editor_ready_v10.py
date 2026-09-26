"""Cache-only interactive editor.

This entry point deliberately never calls the NEF decoder.  Annotation loads
the existing scientific PNG masters; crop correction owns any one-time cache
creation and does it in its worker thread.
"""
from pathlib import Path
from PIL import Image
from .editor_ready_v9 import ReadyEditorV9
from .developed_cache_v2 import cached_png_ready, ensure
from .io import read_json
from .normalization_pipeline import paths
from .standardize import image_id
from .workflow import load_record, save_record


class ReadyEditorV10(ReadyEditorV9):
 def _choose_available(self):
  """Prefer a prepared standardized PNG without touching a RAW source."""
  current = self.current()
  current_source = Path(current["source_relpath"] )
  if paths(current_source)[4].exists():
   return current, current_source
  for index, row in enumerate(self.images):
   source = Path(row["source_relpath"])
   if paths(source)[4].exists():
    self.index = index
    return row, source
  return self.current(), Path(self.current()["source_relpath"])

 def open_image(self):
  row, source = self._choose_available()
  # Validation may hash a legacy cache once, but never invokes rawpy/NEF here.
  developed = paths(source)[2]
  standard = paths(source)[4]
  if not developed.exists() or not standard.exists() or not cached_png_ready(source):
   raise RuntimeError("No prepared PNG is available. Run the local precache worker before interactive annotation.")
  meta = ensure(source)
  self.source = Image.open(developed).convert("RGB")
  self.standard = Image.open(standard).convert("RGB")
  self.source_mode = False
  self.record = load_record(row, self.profile.profile_id, self.profile.version)
  if not self.record.get("source_sha256"):
   self.record["source_sha256"] = meta["source_sha256"]
   save_record(self.record)
  self.state.open_record(self.record)
  self.zoom = min(1., 1050 / self.standard.width, 720 / self.standard.height)
  self.pan = [0., 0.]
  self.sync()


def run():
 ReadyEditorV10().mainloop()


if __name__ == "__main__":
 run()
