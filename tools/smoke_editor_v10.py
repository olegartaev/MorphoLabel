"""Short local Tk liveness check for the cache-only annotation entry."""
from pathlib import Path
import sys
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.editor_ready_v10 import ReadyEditorV10


app = ReadyEditorV10()
app.after(700, lambda: print("editor_v10_alive", flush=True))
app.after(1100, app.destroy)
app.mainloop()
