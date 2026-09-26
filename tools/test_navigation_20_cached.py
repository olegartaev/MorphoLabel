"""Sequential GUI navigation test over 20 real, already cached PNG masters."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.developed_cache_v2 import cached_png_ready
from app.editor_ready_v11 import ReadyEditorV11
from app.gui_crop_debug import LOG
from app.normalization_pipeline import paths


before_log = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
app = ReadyEditorV11()
choices = [i for i, row in enumerate(app.images)
           if paths(Path(row["source_relpath"]))[2].exists()
           and paths(Path(row["source_relpath"]))[4].exists()
           and cached_png_ready(Path(row["source_relpath"]))][:20]
if len(choices) < 20:
 raise RuntimeError(f"Need 20 cached standardized images, found {len(choices)}")
result = {"visited": 0, "failures": [], "render_counts": []}


def select(position):
 if position == len(choices):
  added = LOG.read_text(encoding="utf-8")[len(before_log):] if LOG.exists() else ""
  result["rawpy_nef_calls"] = added.count("op=rawpy_nef_decode state=START")
  print(json.dumps(result), flush=True)
  app.quit(); app.destroy(); return
 app.index = choices[position]
 app.images_box.selection_clear(0, "end")
 app.images_box.selection_set(app.index)
 app.open_image()
 token = app._load_token
 deadline = app.tk.call("after", "info")  # forces a normal Tk roundtrip, no blocking work
 app.after(30, lambda: wait_for(position, token, 0))


def wait_for(position, token, ticks):
 if app._load_token != token:
  result["failures"].append(f"selection {position}: token superseded")
  app.after(1, lambda: select(position + 1)); return
 if token in app.navigation_render_counts:
  count = app.navigation_render_counts[token]
  result["visited"] += 1; result["render_counts"].append(count)
  if count != 1: result["failures"].append(f"selection {position}: renders={count}")
  app.after(10, lambda: select(position + 1)); return
 if ticks >= 300:
  result["failures"].append(f"selection {position}: timed out")
  app.after(1, lambda: select(position + 1)); return
 app.after(30, lambda: wait_for(position, token, ticks + 1))


app.after(400, lambda: select(0))
app.mainloop()
if result["failures"] or result["visited"] != 20 or any(n != 1 for n in result["render_counts"]):
 raise SystemExit(1)
