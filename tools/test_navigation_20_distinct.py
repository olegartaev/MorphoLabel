"""Exercise 20 distinct Listbox rows through the real selection binding."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.developed_cache_v2 import cached_png_ready
from app.editor_ready_v13 import ReadyEditorV13
from app.gui_crop_debug import LOG
from app.normalization_pipeline import paths
from app.standardize import image_id

before = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
app = ReadyEditorV13()
indices = [i for i, row in enumerate(app.images)
           if paths(Path(row["source_relpath"]))[2].exists()
           and paths(Path(row["source_relpath"]))[4].exists()
           and cached_png_ready(Path(row["source_relpath"]))][:20]
expected = [image_id(Path(app.images[i]["source_relpath"])) for i in indices]
result = {"expected_image_ids": expected, "displayed_image_ids": [], "render_counts": [], "failures": []}

def click(position):
 if position == len(indices):
  added = LOG.read_text(encoding="utf-8")[len(before):] if LOG.exists() else ""
  result["rawpy_nef_calls"] = added.count("op=rawpy_nef_decode state=START")
  result["distinct_expected"] = len(set(expected))
  print(json.dumps(result), flush=True)
  app.quit(); app.destroy(); return
 index = indices[position]
 app.images_box.selection_clear(0, "end")
 app.images_box.selection_set(index)
 app.images_box.event_generate("<<ListboxSelect>>")
 token = app._load_token
 app.after(25, lambda: wait(position, token, 0))

def wait(position, token, ticks):
 if token in app.navigation_render_counts:
  count = app.navigation_render_counts[token]
  shown = app.navigation_results[-1][2] if app.navigation_results else None
  result["displayed_image_ids"].append(shown); result["render_counts"].append(count)
  if shown != expected[position]: result["failures"].append(f"row {position}: expected={expected[position]} displayed={shown}")
  if count != 1: result["failures"].append(f"row {position}: renders={count}")
  app.after(10, lambda: click(position + 1)); return
 if ticks >= 300:
  result["failures"].append(f"row {position}: timed_out")
  app.after(1, lambda: click(position + 1)); return
 app.after(25, lambda: wait(position, token, ticks + 1))

app.after(400, lambda: click(0))
app.mainloop()
if result["failures"] or result["rawpy_nef_calls"] or result["displayed_image_ids"] != expected or len(set(expected)) != 20:
 raise SystemExit(1)
