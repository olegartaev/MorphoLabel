"""Operator UI with visible export/report actions; all remain local/offline."""
from tkinter import ttk, messagebox
from .operator_v3 import OperatorV3
from .canonical_export import export_canonical_csv
from .dataset import export_training_dataset
from .review_report import summarize_review
from .io import read_json
from .paths import WORK

class OperatorV4(OperatorV3):
    def _layout(self):
        super()._layout()
        tools=ttk.Frame(self.canvas.master); tools.pack(fill="x")
        ttk.Button(tools,text="Export canonical CSV",command=self.export_csv).pack(side="left")
        ttk.Button(tools,text="Export training data",command=self.export_training).pack(side="left")
        ttk.Button(tools,text="Review report",command=self.review_report).pack(side="left")
    def export_csv(self): messagebox.showinfo("Export",str(export_canonical_csv()))
    def export_training(self):
        result=export_training_dataset(self.profile.profile_id); messagebox.showinfo("Training export",f"Human-final images exported: {len(result['images'])}")
    def review_report(self):
        records=[read_json(path,{}) for path in WORK.glob("*/landmarks/*.json")]
        result=summarize_review(records); messagebox.showinfo("Review report",f"{result['status']}\nReviewed landmarks: {result['landmarks_reviewed']}")

def run():
    app=OperatorV4(); app.calibration_clicks=None; app.mainloop()

if __name__ == "__main__": run()
