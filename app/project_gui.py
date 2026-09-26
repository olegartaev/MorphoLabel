"""Small project chooser; it creates/opens portable project folders without touching originals."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog
from .project_storage import Project
from .identity import APP_TITLE, apply_window_identity
from .gui_crop_debug import log

class ProjectManager(tk.Tk):
 def __init__(self):
  super().__init__();apply_window_identity(self);self.geometry("520x260");self.current=None
  log("GLOBAL","app_start","START",detail="gui_mode=project launcher=START_APP.cmd entry_point=app.project_gui")
  tk.Label(self,text=APP_TITLE,font=("Segoe UI",16)).pack(pady=22)
  tk.Button(self,text="New Project",command=self.new_project,width=30).pack(pady=6)
  tk.Button(self,text="Open Project",command=self.open_project,width=30).pack(pady=6)
  self.status=tk.Label(self,text="Choose a project.",wraplength=460);self.status.pack(pady=18)
 def new_project(self):
  name=simpledialog.askstring("New project","Project name:",parent=self)
  if not name:return
  source=filedialog.askdirectory(title="Folder with original photographs",parent=self)
  destination=filedialog.askdirectory(title="Folder where the project will be created",parent=self)
  schema=filedialog.askopenfilename(title="Landmark schema CSV",filetypes=[("CSV","*.csv")],parent=self)
  if not all((source,destination,schema)):return
  layout,subfolder=self._source_layout(Path(source))
  try:self.current=Project.create(name,Path(source),Path(destination),Path(schema),source_layout=layout,source_image_subfolder=subfolder);self.status.config(text=f"Opened: {self.current.root}\nImages: {self.current.count('images')}; schema landmarks: {self.current.count('landmark_schema')}")
  except Exception as exc:messagebox.showerror("Cannot create project",str(exc),parent=self)
  else:self._launch()
 def _source_layout(self, source):
  direct=messagebox.askyesno("Original image layout","Are original photographs directly inside sample folders?\n\nYes = sample/image\nNo = sample/subfolder/image",parent=self)
  layout="direct" if direct else "subfolder"; subfolder=""
  if layout=="subfolder":
   subfolder=simpledialog.askstring("Source subfolder","Subfolder containing original photographs:",initialvalue="orig",parent=self) or "orig"
  candidates=[]
  for p in source.rglob("*"):
   if p.is_file() and (layout=="direct" and len(p.relative_to(source).parts)==2 or layout=="subfolder" and len(p.relative_to(source).parts)>=3 and p.relative_to(source).parts[-2].casefold()==subfolder.casefold()): candidates.append(p)
  localities={p.relative_to(source).parts[-2 if layout=="direct" else -3] for p in candidates}
  messagebox.showinfo("Catalog preview",f"Samples found: {len(localities)}\nSource images found: {len(candidates)}",parent=self)
  return layout,subfolder

 def _launch(self):
  from .ui.shell import ProductionShell
  project=self.current
  log("GLOBAL","project_launch","START",path=str(project.root),detail=f"gui_mode=project project_root={project.root} project_db={project.path} schema_path={project.schema_path} source_root={project.source_root}")
  shell=ProductionShell(project=project);self.destroy();shell.mainloop()
 def open_project(self):
  folder=filedialog.askdirectory(title="Select project folder",parent=self)
  if not folder:return
  try:self.current=Project.open(Path(folder));self.status.config(text=f"Opened: {self.current.root}\nImages: {self.current.count('images')}; schema landmarks: {self.current.count('landmark_schema')}")
  except Exception as exc:messagebox.showerror("Cannot open project",str(exc),parent=self)
  else:self._launch()
def run():ProjectManager().mainloop()
if __name__=="__main__":run()

