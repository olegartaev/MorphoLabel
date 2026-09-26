"""Run the exact crop-editor flow long enough for watchdog diagnostics."""
from pathlib import Path
import json
import sys
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.crop_editor_async_v2 import AsyncCropEditorV2
from app.gui_crop_debug import log
from app.standardize import image_id

row = json.loads((ROOT / "reports" / "visual_crop_acceptance_5.json").read_text(encoding="utf-8"))[0]
source = ROOT / row["source"]
ident = image_id(source)
root = tk.Tk(); root.withdraw()
editor = AsyncCropEditorV2(root, source, root.destroy)

def finish():
 log(ident, "diagnostic_gui_finish", "END", path=str(source), detail=f"rendered={editor.rendered}")
 print(f"rendered={editor.rendered}", flush=True)
 editor.destroy(); root.destroy()

root.after(22_000, finish)
root.mainloop()
