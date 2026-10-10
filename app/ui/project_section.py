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
  host=self.frame(padding=(18,12));host.pack(fill="both",expand=True)
  from .design import FlowRow
  project=self.context.project
  if not project:
   ttk.Label(host,text="Project",style="PageTitle.TLabel").pack(anchor="w")
   ttk.Label(host,text="Create a project or open an existing MorphoLabel project.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(3,16))
   actions=ttk.Frame(host);actions.pack(anchor="w")
   self.button(actions,"New Project...",self.shell.new_project,"Create a new MorphoLabel project without changing original photographs.",primary=True).pack(side="left")
   self.button(actions,"Open Project...",self.shell.open_project,"Open an existing MorphoLabel project in this same window.").pack(side="left",padx=6)
   return

  ttk.Label(host,text="Project setup",style="PageTitle.TLabel").pack(anchor="w")
  ttk.Label(host,text="Project, source photos, landmark scheme and image-preparation workflow.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
  from .project_layout import project_columns,bind_settings_navigation,wrapped_label
  content=ttk.Frame(host);content.pack(fill="both",expand=True)
  content.columnconfigure(0,weight=1);content.rowconfigure(1,weight=1)

  # Project identity is deliberately a separate full-width strip. Opening or
  # creating a project changes the whole workspace; the cards below edit that
  # project's settings and therefore must not look like peer actions.
  path_label=wrapped_label
  project_box=ttk.LabelFrame(content,text="Current project",padding=(10,6),style="ProjectIdentity.TLabelframe",borderwidth=2,relief="groove");project_box.grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,10))
  project_box.columnconfigure(0,weight=1)
  identity=ttk.Frame(project_box);identity.grid(row=0,column=0,sticky="ew",padx=(0,12))
  path_label(identity,project.config.get("name",project.root.name),"SectionTitle.TLabel")
  path_label(identity,project.root)
  actions=ttk.Frame(project_box);actions.grid(row=0,column=1,sticky="e")
  self.button(actions,"Open",self.shell.open_project,"Open another project in this same MorphoLabel window.").pack(side="left")
  self.button(actions,"New project...",self.shell.new_project,"Create another MorphoLabel project.").pack(side="left",padx=(6,0))
  body=ttk.Frame(content);body.grid(row=1,column=0,columnspan=2,sticky="nsew")
  settings,catalog,canvas=project_columns(body);self.scroll_canvas=canvas

  source=ttk.LabelFrame(settings,text="Source photos",padding=10);source.pack(fill="x",pady=(0,8))
  ttk.Label(source,text="Photo folder",style="SectionTitle.TLabel").pack(anchor="w")
  path_label(source,project.source_root)
  actions=FlowRow(source);actions.pack(fill="x")
  self.button(actions,"Change folder...",self.shell.relink_source,"Choose the photo folder and safely match it to the existing catalog.").pack(side="left")
  self.button(actions,"Rescan for images",self.shell.add_samples,"Scan the source photo folder for new samples/images. Existing project work is preserved.").pack(side="left",padx=(6,0))

  scheme=ttk.LabelFrame(settings,text="Landmark scheme",padding=10);scheme.pack(fill="x",pady=(0,8))
  defined=bool(project.schema)
  groups=sorted({str(item.get("category") or item.get("role") or item.get("morphometry_role") or "") for item in project.schema if item.get("category") or item.get("role") or item.get("morphometry_role")})
  if defined:
   ttk.Label(scheme,text=f"{len(project.schema)} landmarks",style="SectionTitle.TLabel").pack(anchor="w")
   path_label(scheme,f"{project.schema_path.name} · {', '.join(groups) or 'No groups'}")
  else:
   ttk.Label(scheme,text="Landmark scheme needs attention",style="SectionTitle.TLabel").pack(anchor="w")
   path_label(scheme,project.schema_error or "No landmark scheme is defined yet.")
  self.button(scheme,"Edit scheme..." if defined else "Create scheme...",self.shell.open_schema,"Open the active project landmark scheme in the established editor.").pack(anchor="w")
  definitions=ttk.LabelFrame(scheme,text="Measurement definitions",padding=6);definitions.pack(fill="x",pady=(8,0))
  actions=FlowRow(definitions);actions.pack(fill="x")
  state="normal" if defined else "disabled"
  self.button(actions,"+ Add",self.shell.add_measurement,"Add a distance between two landmarks.",state=state).pack(side="left")
  self.button(actions,"Edit…",self.shell.open_measurements,"Define distances between landmarks.",state=state).pack(side="left",padx=4)
  self.button(actions,"Import…",self.shell.import_measurement_definitions,"Apply measurement definitions by landmark abbreviation.",state=state).pack(side="left",padx=4)
  self.button(actions,"Save…",self.shell.export_measurement_definitions,"Save measurement definitions as a portable CSV.",state=state).pack(side="left")

  workflow=ttk.LabelFrame(source,text="Image preparation",padding=10);workflow.pack(fill="x",pady=(8,0))
  ttk.Label(workflow,text="Before landmarks",style="SectionTitle.TLabel").pack(anchor="w")
  path_label(workflow,"Standardize each specimen with Crop, or go directly to landmarks.")
  crop=tk.BooleanVar(value=self.context.crop_enabled())
  def changed(): self.context.set_crop_enabled(crop.get());self.shell.render()
  choices=ttk.Frame(workflow);choices.pack(anchor="w")
  use=ttk.Radiobutton(choices,text="Use Crop",variable=crop,value=True,command=changed);use.pack(side="left")
  skip=ttk.Radiobutton(choices,text="Skip Crop",variable=crop,value=False,command=changed);skip.pack(side="left",padx=(12,0))
  self.shell.tip.bind(use,"Focus each image on the specimen before landmarks.")
  self.shell.tip.bind(skip,"Go directly to landmarks while keeping existing crop data.")

  sample_rows=project_sample_rows(project,self.context.rows)
  from .model_transfer import model_transfer_card
  for kind,title in (("crop","Crop model"),("landmark","Landmark model")):
   models=project.models(kind);active=next((model for model in models if model.get("active")),None)
   card=model_transfer_card(settings,title,active,lambda k=kind:self.shell._import_model(k),lambda k=kind:self.shell._export_model(k),models=models)
   card.pack(fill="x",pady=(0,8))
  lower=ttk.Frame(catalog);lower.pack(fill="both",expand=True);lower.rowconfigure(1,weight=1);lower.columnconfigure(0,weight=1)
  samples=ttk.LabelFrame(lower,text="Samples",padding=8);samples.grid(row=1,column=0,sticky="nsew")
  samples.rowconfigure(1,weight=1);samples.columnconfigure(0,weight=1)
  ttk.Label(samples,text=f"{len(sample_rows)} samples · click a column title to sort",style="Muted.TLabel").grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,5))
  columns=("sample","images","calibrated");table=ttk.Treeview(samples,columns=columns,show="headings",selectmode="browse",height=6)
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

  overview=ttk.LabelFrame(lower,text="Project overview",padding=(8,4));overview.grid(row=0,column=0,sticky="ew",pady=(0,8))
  calibrated=sum(1 for item in sample_rows if item["calibrated"])
  metrics=((str(len(self.context.rows)),"Images"),(str(len(sample_rows)),"Samples"),(f"{calibrated}/{len(sample_rows)}","Calibrated"),(str(len(project.schema)),"Landmarks"))
  for index,(value,label) in enumerate(metrics):
   overview.columnconfigure(index,weight=1)
   block=ttk.Frame(overview,padding=(4,2));block.grid(row=0,column=index,sticky="ew")
   ttk.Label(block,text=value,font=("Segoe UI",13,"bold")).pack(anchor="w")
   ttk.Label(block,text=label,style="Muted.TLabel").pack(anchor="w")
  bind_settings_navigation(settings,canvas)
