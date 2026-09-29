"""Project setup page with compact, task-oriented cards."""
import tkinter as tk
from tkinter import ttk
from .section_base import SectionView

class ProjectSection(SectionView):
 def render(self):
  host=self.frame(padding=(22,14));host.pack(fill='both',expand=True);project=self.context.project
  if not project:
   ttk.Label(host,text='Project',style='PageTitle.TLabel').pack(anchor='w')
   ttk.Label(host,text='Create a project or open an existing portable MorphoLabel project.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(3,16))
   actions=ttk.Frame(host);actions.pack(anchor='w')
   self.button(actions,'New Project...',self.shell.new_project,'Create a new MorphoLabel project without changing original photographs.',primary=True).pack(side='left')
   self.button(actions,'Open Project...',self.shell.open_project,'Open an existing MorphoLabel project in this same window.').pack(side='left',padx=6)
   return

  ttk.Label(host,text='Project setup',style='PageTitle.TLabel').pack(anchor='w')
  ttk.Label(host,text='Project location, source photos, landmark scheme and image-preparation workflow.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(3,12))

  content=ttk.Frame(host);content.pack(fill='both',expand=True)
  content.columnconfigure(0,weight=1,uniform='project_cards');content.columnconfigure(1,weight=1,uniform='project_cards');content.rowconfigure(2,weight=1)

  project_box=ttk.LabelFrame(content,text='Project',padding=12);project_box.grid(row=0,column=0,sticky='nsew',padx=(0,6),pady=(0,8))
  ttk.Label(project_box,text=str(project.config.get('name',project.root.name)),style='SectionTitle.TLabel').pack(anchor='w')
  ttk.Label(project_box,text=str(project.root),style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(3,10))
  actions=ttk.Frame(project_box);actions.pack(anchor='w')
  self.button(actions,'Open another...',self.shell.open_project,'Open another project in this same MorphoLabel window.').pack(side='left')
  self.button(actions,'New project...',self.shell.new_project,'Create another MorphoLabel project.').pack(side='left',padx=(6,0))

  source=ttk.LabelFrame(content,text='Source photos',padding=12);source.grid(row=0,column=1,sticky='nsew',padx=(6,0),pady=(0,8))
  ttk.Label(source,text='Photo folder',style='SectionTitle.TLabel').pack(anchor='w')
  ttk.Label(source,text=str(project.source_root),style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(3,10))
  actions=ttk.Frame(source);actions.pack(anchor='w')
  self.button(actions,'Change folder...',self.shell.relink_source,'Choose the photo folder and safely match it to the existing catalog.').pack(side='left')
  self.button(actions,'Rescan for images',self.shell.add_samples,'Scan the source photo folder for new samples/images. Existing project work is preserved.').pack(side='left',padx=(6,0))

  scheme=ttk.LabelFrame(content,text='Landmark scheme',padding=12);scheme.grid(row=1,column=0,sticky='nsew',padx=(0,6),pady=(0,8))
  defined=bool(project.schema)
  groups=sorted({str(item.get('category') or item.get('role') or item.get('morphometry_role') or '') for item in project.schema if item.get('category') or item.get('role') or item.get('morphometry_role')})
  if defined:
   ttk.Label(scheme,text=f"{len(project.schema)} landmarks",style='SectionTitle.TLabel').pack(anchor='w')
   ttk.Label(scheme,text=f"{project.schema_path.name}\nRoles: {', '.join(groups) or 'Not grouped'}",style='Muted.TLabel',justify='left').pack(anchor='w',pady=(3,10))
  else:
   ttk.Label(scheme,text='Landmark scheme needs attention',style='SectionTitle.TLabel').pack(anchor='w')
   ttk.Label(scheme,text=project.schema_error or 'No landmark scheme is defined yet.',style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(3,10))
  self.button(scheme,'Edit scheme...' if defined else 'Create scheme...',self.shell.open_schema,'Open the active project landmark scheme in the established editor.').pack(anchor='w')

  workflow=ttk.LabelFrame(content,text='Image preparation',padding=12);workflow.grid(row=1,column=1,sticky='nsew',padx=(6,0),pady=(0,8))
  ttk.Label(workflow,text='Before landmarks',style='SectionTitle.TLabel').pack(anchor='w')
  ttk.Label(workflow,text='Choose whether each specimen is standardized with Crop before landmark annotation.',style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(3,8))
  crop=tk.BooleanVar(value=self.context.crop_enabled())
  def changed():self.context.set_crop_enabled(crop.get());self.shell.render()
  choices=ttk.Frame(workflow);choices.pack(anchor='w')
  use=ttk.Radiobutton(choices,text='Use Crop',variable=crop,value=True,command=changed);use.pack(side='left')
  skip=ttk.Radiobutton(choices,text='Skip Crop',variable=crop,value=False,command=changed);skip.pack(side='left',padx=(12,0))
  self.shell.tip.bind(use,'Focus each image on the specimen before landmarks.')
  self.shell.tip.bind(skip,'Go directly to landmarks while keeping existing crop data.')

  totals={}
  for row in self.context.rows:
   name=str(row.get('locality') or row.get('sample_id') or 'Unassigned');totals[name]=totals.get(name,0)+1
  samples=ttk.LabelFrame(content,text=f"Samples ({len(totals)}) · Images ({len(self.context.rows)})",padding=7);samples.grid(row=2,column=0,columnspan=2,sticky='nsew')
  samples.rowconfigure(0,weight=1);samples.columnconfigure(0,weight=1)
  table=ttk.Treeview(samples,columns=('sample','images'),show='headings',height=10)
  table.heading('sample',text='Sample');table.heading('images',text='Images')
  table.column('sample',width=360,stretch=True);table.column('images',width=80,stretch=False,anchor='e')
  scroll=ttk.Scrollbar(samples,orient='vertical',command=table.yview);table.configure(yscrollcommand=scroll.set)
  for name,count in sorted(totals.items(),key=lambda item:item[0].casefold()):table.insert('','end',values=(name,count))
  table.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns')
