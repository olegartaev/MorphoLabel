"""Project setup page with compact cards and a sortable sample overview."""
import tkinter as tk
from tkinter import ttk
from .section_base import SectionView


def project_sample_rows(project, rows):
    totals={}
    for row in rows:
        name=str(row.get("locality") or row.get("sample_id") or "Unassigned")
        totals[name]=totals.get(name,0)+1
    result=[]
    for name,count in totals.items():
        calibrated=False
        if name!="Unassigned":
            try: calibrated=bool(project.locality_calibration(name))
            except Exception: calibrated=False
        result.append({"sample":name,"images":int(count),"calibrated":calibrated})
    return result


def sorted_project_samples(rows, column="sample", descending=False):
    def key(item):
        value=item.get(column)
        if column=="images": return int(value or 0)
        if column=="calibrated": return int(bool(value))
        return str(value or "").casefold()
    return sorted(rows,key=key,reverse=bool(descending))


class ProjectSection(SectionView):
 def render(self):
  host=self.frame(padding=(18,12));host.pack(fill="both",expand=True);project=self.context.project
  if not project:
   ttk.Label(host,text="Project",style="PageTitle.TLabel").pack(anchor="w")
   ttk.Label(host,text="Create a project or open an existing portable MorphoLabel project.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(3,16))
   actions=ttk.Frame(host);actions.pack(anchor="w")
   self.button(actions,"New Project...",self.shell.new_project,"Create a new MorphoLabel project without changing original photographs.",primary=True).pack(side="left")
   self.button(actions,"Open Project...",self.shell.open_project,"Open an existing MorphoLabel project in this same window.").pack(side="left",padx=6)
   return

  ttk.Label(host,text="Project setup",style="PageTitle.TLabel").pack(anchor="w")
  ttk.Label(host,text="Project, source photos, landmark scheme and image-preparation workflow.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
  content=ttk.Frame(host);content.pack(fill="both",expand=True)
  content.columnconfigure(0,weight=1,uniform="project_cards");content.columnconfigure(1,weight=1,uniform="project_cards");content.rowconfigure(3,weight=1)

  # Project identity is deliberately a separate full-width strip. Opening or
  # creating a project changes the whole workspace; the cards below edit that
  # project's settings and therefore must not look like peer actions.
  project_box=ttk.LabelFrame(content,text="Current project",padding=14,style="ProjectIdentity.TLabelframe",borderwidth=2,relief="groove");project_box.grid(row=0,column=0,columnspan=2,sticky="ew",padx=4,pady=(4,12))
  ttk.Label(project_box,text=str(project.config.get("name",project.root.name)),style="SectionTitle.TLabel").pack(anchor="w")
  ttk.Label(project_box,text=str(project.root),style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,8))
  actions=ttk.Frame(project_box);actions.pack(anchor="w")
  self.button(actions,"Open",self.shell.open_project,"Open another project in this same MorphoLabel window.").pack(side="left")
  self.button(actions,"New project...",self.shell.new_project,"Create another MorphoLabel project.").pack(side="left",padx=(6,0))

  source=ttk.LabelFrame(content,text="Source photos",padding=10);source.grid(row=1,column=0,sticky="nsew",padx=(4,6),pady=(0,7))
  ttk.Label(source,text="Photo folder",style="SectionTitle.TLabel").pack(anchor="w")
  ttk.Label(source,text=str(project.source_root),style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,8))
  actions=ttk.Frame(source);actions.pack(anchor="w")
  self.button(actions,"Change folder...",self.shell.relink_source,"Choose the photo folder and safely match it to the existing catalog.").pack(side="left")
  self.button(actions,"Rescan for images",self.shell.add_samples,"Scan the source photo folder for new samples/images. Existing project work is preserved.").pack(side="left",padx=(6,0))

  scheme=ttk.LabelFrame(content,text="Landmark scheme",padding=10);scheme.grid(row=1,column=1,sticky="nsew",padx=(6,4),pady=(0,7))
  defined=bool(project.schema)
  groups=sorted({str(item.get("category") or item.get("role") or item.get("morphometry_role") or "") for item in project.schema if item.get("category") or item.get("role") or item.get("morphometry_role")})
  if defined:
   ttk.Label(scheme,text=f"{len(project.schema)} landmarks",style="SectionTitle.TLabel").pack(anchor="w")
   ttk.Label(scheme,text=f"{project.schema_path.name} · {', '.join(groups) or 'No groups'}",style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,8))
  else:
   ttk.Label(scheme,text="Landmark scheme needs attention",style="SectionTitle.TLabel").pack(anchor="w")
   ttk.Label(scheme,text=project.schema_error or "No landmark scheme is defined yet.",style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,8))
  self.button(scheme,"Edit scheme..." if defined else "Create scheme...",self.shell.open_schema,"Open the active project landmark scheme in the established editor.").pack(anchor="w")

  workflow=ttk.LabelFrame(content,text="Image preparation",padding=10);workflow.grid(row=2,column=0,columnspan=2,sticky="ew",padx=4,pady=(0,7))
  ttk.Label(workflow,text="Before landmarks",style="SectionTitle.TLabel").pack(anchor="w")
  ttk.Label(workflow,text="Standardize each specimen with Crop, or go directly to landmarks.",style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,6))
  crop=tk.BooleanVar(value=self.context.crop_enabled())
  def changed(): self.context.set_crop_enabled(crop.get());self.shell.render()
  choices=ttk.Frame(workflow);choices.pack(anchor="w")
  use=ttk.Radiobutton(choices,text="Use Crop",variable=crop,value=True,command=changed);use.pack(side="left")
  skip=ttk.Radiobutton(choices,text="Skip Crop",variable=crop,value=False,command=changed);skip.pack(side="left",padx=(12,0))
  self.shell.tip.bind(use,"Focus each image on the specimen before landmarks.")
  self.shell.tip.bind(skip,"Go directly to landmarks while keeping existing crop data.")

  sample_rows=project_sample_rows(project,self.context.rows)
  lower=ttk.Frame(content);lower.grid(row=3,column=0,columnspan=2,sticky="nsew",padx=4);lower.rowconfigure(0,weight=1)
  lower.columnconfigure(0,weight=4,uniform="project_lower");lower.columnconfigure(1,weight=1,uniform="project_lower")

  samples=ttk.LabelFrame(lower,text="Samples",padding=8);samples.grid(row=0,column=0,sticky="nsew",padx=(0,7))
  samples.rowconfigure(1,weight=1);samples.columnconfigure(0,weight=1)
  ttk.Label(samples,text=f"{len(sample_rows)} samples · click a column title to sort",style="Muted.TLabel").grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,5))
  columns=("sample","images","calibrated");table=ttk.Treeview(samples,columns=columns,show="headings",selectmode="browse",height=14)
  labels={"sample":"Sample","images":"Images","calibrated":"Calibration"}
  table.column("sample",width=330,stretch=True,anchor="w");table.column("images",width=72,stretch=False,anchor="e");table.column("calibrated",width=96,stretch=False,anchor="center")
  table.tag_configure("alternate",background="#f7f7f7")
  state={"column":"sample","descending":False}
  def sort_by(column):
   if state["column"]==column: state["descending"]=not state["descending"]
   else:
    state["column"]=column;state["descending"]=column in {"images","calibrated"}
   populate()
  def populate():
   table.delete(*table.get_children())
   for index,item in enumerate(sorted_project_samples(sample_rows,state["column"],state["descending"])):
    table.insert("","end",values=(item["sample"],item["images"],"Yes" if item["calibrated"] else "—"),tags=("alternate",) if index%2 else ())
   for column in columns:
    arrow=" ↓" if column==state["column"] and state["descending"] else " ↑" if column==state["column"] else ""
    table.heading(column,text=labels[column]+arrow,command=lambda c=column:sort_by(c))
  scroll=ttk.Scrollbar(samples,orient="vertical",command=table.yview);table.configure(yscrollcommand=scroll.set)
  table.grid(row=1,column=0,sticky="nsew");scroll.grid(row=1,column=1,sticky="ns");populate()

  details=ttk.Frame(lower);details.grid(row=0,column=1,sticky="nsew");details.columnconfigure(0,weight=1)
  overview=ttk.LabelFrame(details,text="Project overview",padding=(12,10));overview.grid(row=0,column=0,sticky="ew")
  overview.columnconfigure(0,weight=1);overview.columnconfigure(1,weight=1)
  calibrated=sum(1 for item in sample_rows if item["calibrated"])
  metrics=((str(len(self.context.rows)),"Images"),(str(len(sample_rows)),"Samples"),(f"{calibrated}/{len(sample_rows)}","Calibrated"),(str(len(project.schema)),"Landmarks"))
  for index,(value,label) in enumerate(metrics):
   block=ttk.Frame(overview,padding=(4,3));block.grid(row=index//2,column=index%2,sticky="nsew",padx=(0 if index%2==0 else 8,0),pady=(0,8))
   ttk.Label(block,text=value,font=("Segoe UI",17,"bold")).pack(anchor="w")
   ttk.Label(block,text=label,style="Muted.TLabel").pack(anchor="w")

