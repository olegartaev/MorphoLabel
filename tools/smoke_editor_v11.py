from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.editor_ready_v15 import ReadyEditorV15
app=ReadyEditorV15();app.after(900,lambda:print("editor_v15_alive",flush=True));app.after(1400,app.destroy);app.mainloop()
