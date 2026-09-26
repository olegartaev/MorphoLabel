from pathlib import Path
import json,tkinter as tk
from app.crop_editor_async_v2 import AsyncCropEditorV2
ROOT=Path(__file__).resolve().parents[1]
row=json.loads((ROOT/"reports"/"visual_crop_acceptance_5.json").read_text(encoding="utf-8"))[0]
root=tk.Tk();root.withdraw();AsyncCropEditorV2(root,ROOT/row["source"],root.destroy);root.after(8000,root.destroy);root.mainloop();print("async crop smoke completed")
