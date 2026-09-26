"""Project page with a persisted, movable Samples pane."""
import tkinter as tk
from tkinter import ttk
from .section_base import SectionView
class ProjectSection(SectionView):
 def render(self):
  host=self.frame(padding=10);host.pack(fill='both',expand=True);project=self.context.project
  if not project:
   ttk.Label(host,text='Project',style='PageTitle.TLabel').pack(anchor='w');ttk.Label(host,text='Create a project or open an existing portable MorphoLabel project.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(3,16));actions=ttk.Frame(host);actions.pack(anchor='w');self.button(actions,'New Project...',self.shell.new_project,'Create a new MorphoLabel project without changing original photographs.',primary=True).pack(side='left');self.button(actions,'Open Project...',self.shell.open_project,'Open an existing MorphoLabel project in this same window.').pack(side='left',padx=6);return
  pane=ttk.Panedwindow(host,orient='horizontal');pane.pack(fill='both',expand=True);self.pane=pane
  totals={}
  for row in self.context.rows:
   name=str(row.get('locality') or row.get('sample_id') or 'Unassigned');totals[name]=totals.get(name,0)+1
  samples=ttk.Labelframe(pane,text=f'Samples ({len(totals)})',padding=5);right=ttk.Frame(pane,padding=(12,0,0,0));pane.add(samples,weight=0);pane.add(right,weight=1)
  samples.rowconfigure(0,weight=1);samples.columnconfigure(0,weight=1);table=ttk.Treeview(samples,columns=('sample','images'),show='headings');table.heading('sample',text='Sample');table.heading('images',text='Images');table.column('sample',width=190,stretch=True);table.column('images',width=58,stretch=False,anchor='e');scroll=ttk.Scrollbar(samples,orient='vertical',command=table.yview);table.configure(yscrollcommand=scroll.set)
  for name,count in sorted(totals.items(),key=lambda item:item[0].casefold()):table.insert('','end',values=(name,count))
  table.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns')
  right.columnconfigure(0,weight=1);ttk.Label(right,text='Project',style='PageTitle.TLabel').grid(row=0,column=0,sticky='w')
  project_box=ttk.LabelFrame(right,text='Project',padding=10);project_box.grid(row=1,column=0,sticky='ew',pady=(8,5));ttk.Label(project_box,text=f"Name: {project.config.get('name',project.root.name)}").pack(anchor='w');ttk.Label(project_box,text=f'Path: {project.root}',wraplength=780).pack(anchor='w',pady=(2,6));actions=ttk.Frame(project_box);actions.pack(anchor='w');self.button(actions,'New Project...',self.shell.new_project,'Create another project in this same MorphoLabel window.').pack(side='left');self.button(actions,'Open Project...',self.shell.open_project,'Open another project in this same MorphoLabel window.').pack(side='left',padx=5)
  source=ttk.LabelFrame(right,text='Source photos',padding=10);source.grid(row=2,column=0,sticky='ew',pady=5);ttk.Label(source,text=f'Root photo folder: {project.source_root}',wraplength=700).pack(side='left',fill='x',expand=True);self.button(source,'Browse...',self.shell.relink_source,'Choose the photo folder and safely match it to the existing catalog.').pack(side='right',padx=4);self.button(source,'Rescan catalog',self.shell.add_samples,'Scan the source photo folder for new samples/images. Existing project work is preserved.').pack(side='right',padx=4)
  scheme=ttk.LabelFrame(right,text='Landmark Scheme',padding=10);scheme.grid(row=3,column=0,sticky='ew',pady=5)
  defined=bool(project.schema);groups=sorted({str(item.get('category') or item.get('role') or item.get('morphometry_role') or '') for item in project.schema if item.get('category') or item.get('role') or item.get('morphometry_role')})
  scheme_text=(f"{project.schema_path.name} | {len(project.schema)} landmarks\nGroups: {', '.join(groups) or 'Not grouped'}" if defined else (f"Landmark scheme needs attention\n{project.schema_error}" if project.schema_error else 'No landmark scheme defined yet. Create it when you are ready to annotate.'))
  ttk.Label(scheme,text=scheme_text).pack(side='left')
  self.button(scheme,'Edit scheme...' if defined else 'Create scheme...',self.shell.open_schema,'Open the active project landmark scheme in the established editor.').pack(side='right')
  workflow=ttk.LabelFrame(right,text='Workflow',padding=10);workflow.grid(row=4,column=0,sticky='ew',pady=5);crop=tk.BooleanVar(value=self.context.crop_enabled())
  def changed():self.context.set_crop_enabled(crop.get());self.shell.render()
  use=ttk.Radiobutton(workflow,text='Use crop',variable=crop,value=True,command=changed);use.pack(side='left');skip=ttk.Radiobutton(workflow,text='Skip crop',variable=crop,value=False,command=changed);skip.pack(side='left',padx=7);self.shell.tip.bind(use,'Focus each image on the specimen before landmarks.');self.shell.tip.bind(skip,'Go directly to landmarks while keeping existing crop data.')
  def restore():
   try:pane.sashpos(0,max(220,min(360,int(project.get_ui_state('project_samples_sash',270)))))
   except Exception:pass
  def save(_event=None):
   try:project.set_ui_state('project_samples_sash',int(pane.sashpos(0)))
   except Exception:pass
  host.after_idle(restore);pane.bind('<ButtonRelease-1>',save,add='+')