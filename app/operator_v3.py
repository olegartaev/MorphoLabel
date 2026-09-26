"""Final operator entry point adds append-only edit history and Undo."""
from tkinter import ttk, messagebox
from .operator_v2 import OperatorV2
from .recovery import restore_latest, snapshot
from .workflow import save_record

class OperatorV3(OperatorV2):
    def _layout(self):
        super()._layout()
        ttk.Button(self.canvas.master,text="Undo last saved edit",command=self.undo).pack(anchor="w")
    def click(self,event):
        if self.calibration_clicks is None: snapshot(self.record,"before_click")
        return super().click(event)
    def drag(self,event):
        if self.drag_number and not getattr(self,"_drag_snapshotted",False):
            snapshot(self.record,"before_drag"); self._drag_snapshotted=True
        return super().drag(event)
    def release(self,event):
        result=super().release(event); self._drag_snapshotted=False; return result
    def missing(self):
        snapshot(self.record,"before_missing"); return super().missing()
    def reset_point(self):
        snapshot(self.record,"before_reset"); return super().reset_point()
    def undo(self):
        restored=restore_latest(self.record)
        if not restored: messagebox.showinfo("Undo","No local saved state available."); return
        snapshot(self.record,"before_undo"); self.record=restored; save_record(self.record); self.render()

def run():
    app=OperatorV3(); app.calibration_clicks=None; app.mainloop()

if __name__ == "__main__": run()
