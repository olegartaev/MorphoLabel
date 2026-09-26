from .identity import apply_window_identity
import hashlib
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from pathlib import Path
from .paths import ORIGINALS, ROOT
from .profile import load_schema_profile
from .storage import load_calibration, load_landmarks, save_calibration, save_landmarks

class App(tk.Tk):
    def __init__(self):
        super().__init__(); apply_window_identity(self); self.geometry("1180x760")
        self.profile = load_schema_profile(ROOT / "landmark_schema.csv")
        self.sample_id = next((p.name for p in ORIGINALS.iterdir() if p.is_dir()), None)
        self.images = sorted((ORIGINALS / self.sample_id).iterdir()) if self.sample_id else []
        self.index = 0; self.record = {"points": {}}; self.photo = None
        self._build(); self.load_image()
    def _build(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL); pane.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(pane, padding=8); pane.add(left, weight=1)
        ttk.Label(left, text="Samples").pack(anchor="w")
        self.samples = tk.Listbox(left); self.samples.pack(fill=tk.BOTH, expand=True)
        for p in sorted(ORIGINALS.iterdir()):
            if p.is_dir(): self.samples.insert(tk.END, p.name)
        self.samples.selection_set(0); self.samples.bind("<<ListboxSelect>>", self.change_sample)
        ttk.Button(left, text="Calibrate (10.0 mm)", command=self.calibrate).pack(fill=tk.X, pady=4)
        ttk.Label(left, text="M marks current point missing\nClick places point; drag corrects.\nRAW display requires optional Pillow/rawpy.").pack(anchor="w")
        right = ttk.Frame(pane, padding=8); pane.add(right, weight=5)
        self.status = ttk.Label(right, text=""); self.status.pack(anchor="w")
        self.canvas = tk.Canvas(right, background="#303030"); self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.place); self.bind("m", lambda e: self.mark_missing())
        controls = ttk.Frame(right); controls.pack(fill=tk.X)
        ttk.Button(controls, text="Previous image", command=lambda:self.move(-1)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Next image", command=lambda:self.move(1)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Missing (M)", command=self.mark_missing).pack(side=tk.LEFT)
    def change_sample(self, event=None):
        pick = self.samples.curselection()
        if pick:
            self.sample_id = self.samples.get(pick[0]); self.images = sorted((ORIGINALS / self.sample_id).iterdir()); self.index = 0; self.load_image()
    def image_id(self): return hashlib.sha256(str(self.images[self.index].relative_to(ORIGINALS)).encode()).hexdigest()[:16]
    def load_image(self):
        self.canvas.delete("all")
        if not self.images: return
        self.record = load_landmarks(self.sample_id, self.image_id()); point = self.current_point()
        self.status.config(text=f"{self.sample_id} — {self.images[self.index].name} ({self.index+1}/{len(self.images)}) | Point {point.number}: {point.code} — {point.instruction}")
        try:
            from PIL import Image, ImageTk
            image = Image.open(self.images[self.index]); image.thumbnail((900, 640)); self.photo = ImageTk.PhotoImage(image, master=self.canvas)
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        except Exception as exc:
            self.canvas.create_text(40, 40, anchor=tk.NW, fill="white", text=f"Preview unavailable for this file.\nInstall optional image support for RAW NEF display.\n{exc}")
        for key, value in self.record.get("points", {}).items():
            if value.get("state") != "missing": self.draw_point(int(key), value["x_standardized"], value["y_standardized"])
    def current_point(self):
        points = self.record.get("points", {})
        for item in self.profile.landmarks:
            if str(item.number) not in points: return item
        return self.profile.landmarks[-1]
    def place(self, event):
        point = self.current_point(); self.record.setdefault("points", {})[str(point.number)] = {"state":"manual", "x_standardized":event.x, "y_standardized":event.y, "point_code":point.code}
        save_landmarks(self.sample_id, self.image_id(), self.record); self.load_image()
    def mark_missing(self):
        point = self.current_point(); self.record.setdefault("points", {})[str(point.number)] = {"state":"missing", "x_standardized":None, "y_standardized":None, "point_code":point.code}
        save_landmarks(self.sample_id, self.image_id(), self.record); self.load_image()
    def draw_point(self, number, x, y):
        self.canvas.create_oval(x-4,y-4,x+4,y+4,fill="#ffcf00"); self.canvas.create_text(x+8,y-8,anchor=tk.SW,fill="#ffcf00",text=str(number))
    def move(self, delta): self.index = max(0, min(len(self.images)-1, self.index+delta)); self.load_image()
    def calibrate(self):
        value = simpledialog.askfloat("Calibration", "Known ruler distance in mm", initialvalue=10.0, minvalue=0.001)
        if value: save_calibration(self.sample_id, {"physical_length_mm":value, "status":"requires two ruler clicks", "pixels_per_mm":None}); messagebox.showinfo("Calibration", "Calibration record saved. Clickable ruler-line editor is the next UI enhancement.")

def run(): App().mainloop()



