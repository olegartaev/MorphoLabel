"""Exercise the actual editor button -> crop-window path with diagnostics."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.editor_ready_v10 import ReadyEditorV10

app = ReadyEditorV10()
app.after(500, app.correct_normalization)
app.after(23_000, app.destroy)
app.mainloop()
print("full_editor_button_flow_completed", flush=True)
