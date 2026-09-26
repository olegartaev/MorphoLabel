"""Editor entry point with explicit human normalization review/correction."""
import tkinter as tk
from tkinter import simpledialog, messagebox, ttk
from pathlib import Path
from .gui_full import Editor
from .io import atomic_json_write, read_json
from .normalization import apply_review_transform
from .paths import WORK
from .standardize import decode, image_id, provisional_standardize
from .workflow import load_record

class OperatorV2(Editor):
    def _layout(self):
        super()._layout()
        controls=ttk.Frame(self.canvas.master); controls.pack(fill=tk.X)
        ttk.Button(controls,text="Crop/rotate correction",command=self.correct_normalization).pack(side=tk.LEFT)
        ttk.Button(controls,text="Confirm normalization PASS",command=self.confirm_normalization).pack(side=tk.LEFT)
    def meta_path(self):
        source=Path(self.current()["source_relpath"]); return WORK/source.parent.name/"metadata"/f"{image_id(source)}.json"
    def open_current(self):
        row=self.current(); source=Path(row["source_relpath"]); meta=read_json(self.meta_path(),{})
        try:
            if meta.get("standardized_relpath") and Path(meta["standardized_relpath"]).exists(): self.image=decode(Path(meta["standardized_relpath"]))
            else:
                meta=provisional_standardize(source); self.image=decode(Path(meta["standardized_relpath"]))
        except Exception as exc: messagebox.showerror("Image",f"Cannot decode image: {exc}"); return
        self.record=load_record(row,self.profile.profile_id,self.profile.version); self.zoom=min(1.0,1050/self.image.width,720/self.image.height); self.render()
    def correct_normalization(self):
        if self.record.get("points"):
            messagebox.showwarning("Protected coordinates","Reset or export existing landmarks before changing the standardized transform. Existing coordinates are not silently remapped."); return
        source=Path(self.current()["source_relpath"])
        text=simpledialog.askstring("Manual crop / rotation","rotation degrees; crop left,top,right,bottom\nLeave crop blank for conservative proposal",initialvalue="0;")
        if text is None: return
        try:
            angle_text,crop_text=text.split(";",1); angle=float(angle_text.strip() or 0); crop=None
            if crop_text.strip(): crop=tuple(int(value.strip()) for value in crop_text.split(",")); assert len(crop)==4
            apply_review_transform(source,crop,angle,"human_manual_correction")
            self.open_current()
        except Exception as exc: messagebox.showerror("Invalid transform",str(exc))
    def confirm_normalization(self):
        path=self.meta_path(); meta=read_json(path,{})
        if not meta: messagebox.showwarning("Normalization","Open the image first."); return
        meta["normalization_status"]="PASS"; meta["qc_reason"]="human_confirmed"; atomic_json_write(path,meta); self.render(); messagebox.showinfo("Normalization","Marked PASS by human confirmation.")

def run():
    app=OperatorV2(); app.calibration_clicks=None; app.mainloop()

if __name__ == "__main__": run()
