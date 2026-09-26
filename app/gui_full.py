"""Operator-facing Block 1 editor (offline, source-safe)."""
from __future__ import annotations
from .identity import apply_window_identity
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from pathlib import Path
from .paths import ORIGINALS, ROOT
from .profile import load_schema_profile
from .standardize import decode, provisional_standardize, image_id
from .workflow import image_catalog, load_record, save_record, set_human_point
from .storage import load_calibration, save_calibration

class Editor(tk.Tk):
    def __init__(self):
        super().__init__(); apply_window_identity(self); self.geometry("1400x900")
        self.profile = load_schema_profile(ROOT / "landmark_schema.csv")
        self.images = image_catalog(); self.index = 0; self.record = {}; self.image = None; self.photo = None
        self.zoom = 1.0; self.drag_number = None; self.calibration_clicks = []; self.select_number = 1
        self._layout(); self.open_current()
    def _layout(self):
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL); outer.pack(fill=tk.BOTH, expand=True)
        side = ttk.Frame(outer, padding=8); outer.add(side, weight=1)
        ttk.Label(side, text="Images / samples").pack(anchor="w")
        self.listing = tk.Listbox(side, width=42, exportselection=False); self.listing.pack(fill=tk.BOTH, expand=True)
        for row in self.images: self.listing.insert(tk.END, f"{row['sample_id']} | {Path(row['source_relpath']).name}")
        self.listing.bind("<<ListboxSelect>>", self.pick_image); self.listing.selection_set(0)
        ttk.Button(side, text="Previous", command=lambda:self.move(-1)).pack(fill=tk.X, pady=(8,0))
        ttk.Button(side, text="Next", command=lambda:self.move(1)).pack(fill=tk.X)
        ttk.Separator(side).pack(fill=tk.X, pady=8)
        self.point_list = tk.Listbox(side, height=14, exportselection=False); self.point_list.pack(fill=tk.X)
        for point in self.profile.landmarks: self.point_list.insert(tk.END, f"{point.number:02d} {point.code} — {point.name}")
        self.point_list.bind("<<ListboxSelect>>", self.pick_point); self.point_list.selection_set(0)
        ttk.Button(side, text="Missing (M)", command=self.missing).pack(fill=tk.X, pady=(8,0))
        ttk.Button(side, text="Reset selected", command=self.reset_point).pack(fill=tk.X)
        ttk.Button(side, text="Calibrate: two ruler clicks", command=self.start_calibration).pack(fill=tk.X, pady=(8,0))
        self.info = ttk.Label(side, wraplength=280, justify=tk.LEFT); self.info.pack(fill=tk.X, pady=8)
        main = ttk.Frame(outer, padding=8); outer.add(main, weight=5)
        self.status = ttk.Label(main, font=("Segoe UI", 11)); self.status.pack(anchor="w")
        self.canvas = tk.Canvas(main, background="#222", highlightthickness=0); self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.click); self.canvas.bind("<B1-Motion>", self.drag); self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<MouseWheel>", self.wheel); self.bind("m", lambda _:self.missing()); self.bind("<Left>", lambda _:self.move(-1)); self.bind("<Right>", lambda _:self.move(1))
    def pick_image(self, _=None):
        choice = self.listing.curselection()
        if choice: self.index = choice[0]; self.open_current()
    def pick_point(self, _=None):
        selection = self.point_list.curselection()
        if selection: self.select_number = selection[0]+1; self.render()
    def current(self): return self.images[self.index]
    def selected(self): return self.profile.landmarks[self.select_number-1]
    def open_current(self):
        row = self.current(); source = Path(row["source_relpath"])
        # Full-frame provisional standardization is a transparent safe fallback, never final QC.
        try:
            meta = provisional_standardize(source)
            self.image = decode(Path(meta["standardized_relpath"]))
        except Exception as exc:
            messagebox.showerror("Image", f"Cannot decode image: {exc}"); return
        self.record = load_record(row, self.profile.profile_id, self.profile.version)
        self.zoom = min(1.0, 1050 / self.image.width, 720 / self.image.height); self.render()
    def display_to_image(self, x, y): return x / self.zoom, y / self.zoom
    def render(self):
        if self.image is None: return
        from PIL import ImageTk
        shown = self.image.resize((max(1, round(self.image.width*self.zoom)), max(1, round(self.image.height*self.zoom))))
        self.photo = ImageTk.PhotoImage(shown, master=self.canvas); self.canvas.delete("all"); self.canvas.create_image(0,0,anchor=tk.NW,image=self.photo)
        points = self.record.get("points", {})
        for key, point in points.items():
            if point.get("state") != "missing" and point.get("x_standardized") is not None:
                x, y = point["x_standardized"]*self.zoom, point["y_standardized"]*self.zoom
                color = "#ff7f00" if int(key)==self.select_number else "#00e5ff"
                self.canvas.create_oval(x-5,y-5,x+5,y+5,outline=color,width=2); self.canvas.create_text(x+8,y-8,text=key,anchor=tk.SW,fill=color)
        point = self.selected(); calibration = load_calibration(self.current()["sample_id"])
        state = points.get(str(point.number), {}).get("state", "unplaced")
        self.status.config(text=f"{self.index+1}/{len(self.images)} | {point.number}. {point.code}: {point.name} | {state} | provisional standardization: REVIEW")
        self.info.config(text=f"{point.instruction}\n\nClick to place; drag an existing point to correct it. M = Missing.\n\nCalibration: {calibration.get('pixels_per_mm', 'not set')} px/mm")
    def _nearest(self, x, y):
        closest = None; best = 14/self.zoom
        for key, point in self.record.get("points", {}).items():
            if point.get("x_standardized") is not None:
                distance=((point["x_standardized"]-x)**2+(point["y_standardized"]-y)**2)**.5
                if distance < best: closest, best = int(key), distance
        return closest
    def click(self, event):
        x,y = self.display_to_image(event.x,event.y)
        if self.calibration_clicks is not None and len(self.calibration_clicks) < 2:
            self.calibration_clicks.append((x,y))
            if len(self.calibration_clicks)==2: self.finish_calibration()
            return
        near = self._nearest(x,y)
        if near: self.drag_number = near; return
        point=self.selected(); set_human_point(self.record,point.number,point.code,x,y,corrected=str(point.number) in self.record.get("points",{})); save_record(self.record)
        if point.number < len(self.profile.landmarks): self.select_number += 1; self.point_list.selection_clear(0,tk.END); self.point_list.selection_set(self.select_number-1)
        else: self.move(1)
        self.render()
    def drag(self,event):
        if self.drag_number:
            x,y=self.display_to_image(event.x,event.y); point=self.profile.landmarks[self.drag_number-1]
            set_human_point(self.record,point.number,point.code,x,y,corrected=True); self.select_number=point.number; self.render()
    def release(self,event):
        if self.drag_number: save_record(self.record); self.drag_number=None
    def missing(self):
        point=self.selected(); set_human_point(self.record,point.number,point.code,None,None); save_record(self.record); self.render()
    def reset_point(self):
        self.record.setdefault("points",{}).pop(str(self.select_number),None); save_record(self.record); self.render()
    def move(self, delta):
        self.index=max(0,min(len(self.images)-1,self.index+delta)); self.listing.selection_clear(0,tk.END); self.listing.selection_set(self.index); self.listing.see(self.index); self.open_current()
    def wheel(self,event):
        self.zoom=max(.08,min(2.5,self.zoom*(1.12 if event.delta>0 else .89))); self.render()
    def start_calibration(self):
        self.calibration_clicks=[]; self.status.config(text="Calibration: click two known ruler endpoints (default length 10.0 mm)")
    def finish_calibration(self):
        length=simpledialog.askfloat("Calibration","Ruler distance (mm)",initialvalue=10.0,minvalue=.001)
        if not length: self.calibration_clicks=[]; return
        (x1,y1),(x2,y2)=self.calibration_clicks; distance=((x2-x1)**2+(y2-y1)**2)**.5
        save_calibration(self.current()["sample_id"], {"physical_length_mm":length,"points_standardized":[[x1,y1],[x2,y2]],"pixels_per_mm":distance/length,"state":"manual"})
        self.calibration_clicks=None; self.render()

def run(): Editor().mainloop()

if __name__ == "__main__": run()



