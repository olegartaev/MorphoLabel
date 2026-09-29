"""Built-in X-ray traits module with a trait-first workflow."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk
import webbrowser

from app.ui.tooltips import Tooltip
from app.xray_icons import XRAY_ICON_SIZE,TRAIT_ICON_SIZE,tk_xray_icon
from app.xray_project import XRayProject
from app.xray_schema import (
    MARKER_COLORS,METHOD_BY_ID,SHAPES,TRAIT_METHODS,blank_scheme,bundled_scheme,bundled_scheme_catalog,normalize_scheme,
    load_scheme_file,save_scheme_file,scheme_change_impact,structure_usage,
)

STAGES=(
    ("project","Project","xray_project"),("crops","Crops","xray_crops"),
    ("structures","Structures","xray_structures"),("results","Results","xray_results"),
    ("export","Export","xray_export"),
)

def _safe_id(text,prefix="item"):
    value=re.sub(r"[^a-z0-9]+","_",str(text).strip().lower()).strip("_");return value or prefix

def _clean_reference(label="",doi="",note=""):
    reference={}
    if str(label or "").strip():reference["label"]=str(label).strip()
    if str(doi or "").strip():reference["doi"]=str(doi).strip()
    if str(note or "").strip():reference["note"]=str(note).strip()
    return reference

def _scheme_display_model(scheme,source=""):
    value=normalize_scheme(scheme);reference=value.get("reference") or {}
    label=str(reference.get("label") or "").strip();doi=str(reference.get("doi") or "").strip()
    return {
        "name":str(value.get("name") or "Untitled trait scheme"),
        "description":str(value.get("description") or "").strip(),
        "trait_count":len(value.get("traits") or ()),
        "structure_count":len(value.get("structures") or ()),
        "trait_abbrs":tuple(item.get("abbr") or item["id"] for item in value.get("traits") or ()),
        "source":str(source or "").strip(),
        "reference_text":label or (f"DOI: {doi}" if doi else ""),
        "reference_doi":doi,
        "reference_note":str(reference.get("note") or "").strip(),
    }

def _replace_trait_definition(scheme,trait_id,replacement,new_structures=(),annotation_counts=None):
    """Replace one trait while preserving annotated legacy structures."""
    updated=deepcopy(normalize_scheme(scheme));annotation_counts=dict(annotation_counts or {})
    index=next((i for i,item in enumerate(updated["traits"]) if item["id"]==trait_id),None)
    if index is None:raise KeyError(f"Unknown trait: {trait_id}")
    known={item["id"] for item in updated["structures"]}
    for item in new_structures:
        if item["id"] not in known:
            updated["structures"].append(deepcopy(item));known.add(item["id"])
    updated["traits"][index]=deepcopy(replacement)
    usage=structure_usage(updated)
    updated["structures"]=[
        item for item in updated["structures"]
        if usage.get(item["id"]) or int(annotation_counts.get(item["id"],0) or 0)>0
    ]
    return normalize_scheme(updated)

class XRayCountsRuntime:
    def __init__(self):self.host=None;self.project=None;self.stage="project";self._images={};self._tip=None
    def close(self):self.host=None;self._images.clear();self._tip=None
    def render(self,host):
        self.host=host;parent=host.container
        for child in parent.winfo_children():child.destroy()
        self._images={};self._tip=Tooltip(parent.winfo_toplevel())
        outer=ttk.Frame(parent,padding=(8,6));outer.pack(fill="both",expand=True)
        self._header(outer);body=ttk.Frame(outer);body.pack(fill="both",expand=True,pady=(7,0));getattr(self,f"_render_{self.stage}")(body)
    def _icon(self,master,name,size=XRAY_ICON_SIZE):
        key=(name,size)
        if key not in self._images:self._images[key]=tk_xray_icon(master,name,size)
        return self._images[key]
    def _button(self,parent,text,command,help_text="",primary=False,image=None):
        b=ttk.Button(parent,text=text,command=command,style="Primary.TButton" if primary else "P.TButton",image=image,compound="left")
        if help_text:self._tip.bind(b,help_text)
        return b
    def _rerender(self):
        if self.host:self.render(self.host)
    def _header(self,parent):
        row=ttk.Frame(parent);row.pack(fill="x")
        self._button(row,"Modules",self.host.show_module_hub,"Return to the MorphoLabel module chooser.").pack(side="left",padx=(0,10))
        ttk.Label(row,image=self._icon(row,"xray",42)).pack(side="left",padx=(0,8))
        ttk.Label(row,text="X-ray traits",style="PageTitle.TLabel").pack(side="left")
        if self.project:ttk.Label(row,text=f"  {self.project.name}",style="Muted.TLabel").pack(side="left",pady=(5,0))
        nav=ttk.Frame(parent,style="Topbar.TFrame");nav.pack(fill="x",pady=(7,0))
        for key,label,icon in STAGES:
            active=self.stage==key
            b=ttk.Button(nav,text=("● "+label) if active else label,image=self._icon(nav,icon),compound="left",style="StageActive.TButton" if active else "Stage.TButton",command=lambda k=key:self._select(k))
            if self.project is None and key!="project":b.state(["disabled"])
            b.pack(side="left",padx=(0,3));self._tip.bind(b,f"Open the {label} section.")
    def _select(self,key):
        if self.project is None and key!="project":return
        self.stage=key;self._rerender()

    def _render_reference(self,parent,model,wraplength=650):
        if not model.get("reference_text"):return
        row=ttk.Frame(parent);row.pack(anchor="w",fill="x",pady=(3,0))
        ttk.Label(row,text="Reference:",style="Muted.TLabel").pack(side="left")
        citation=ttk.Label(row,text=model["reference_text"],style="Muted.TLabel",wraplength=wraplength);citation.pack(side="left",padx=(4,0))
        if model.get("reference_note"):self._tip.bind(citation,model["reference_note"])
        if model.get("reference_doi") and model["reference_text"]!=f"DOI: {model['reference_doi']}":
            link=ttk.Label(row,text=f"DOI {model['reference_doi']}",foreground="#256d9e",cursor="hand2")
            link.pack(side="left",padx=(7,0));link.bind("<Button-1>",lambda _e,doi=model["reference_doi"]:webbrowser.open("https://doi.org/"+doi))
            if model.get("reference_note"):self._tip.bind(link,model["reference_note"])
        elif model.get("reference_doi"):
            citation.configure(foreground="#256d9e",cursor="hand2");citation.bind("<Button-1>",lambda _e,doi=model["reference_doi"]:webbrowser.open("https://doi.org/"+doi))

    def _render_project(self,parent):
        ttk.Label(parent,text="Project setup",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Project, source X-rays, trait scheme and annotation workflow.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
        if self.project is None:
            actions=ttk.Frame(parent);actions.pack(anchor="w")
            self._button(actions,"New Project...",self._new_project,"Create a new X-ray project.",True).pack(side="left")
            self._button(actions,"Open Project...",self._open_project,"Open an existing X-ray project.").pack(side="left",padx=6)
            return

        record=self.project.active_scheme_record();scheme=record["scheme"];model=_scheme_display_model(scheme,record.get("note") or "Project scheme")
        content=ttk.Frame(parent);content.pack(fill="both",expand=True)
        content.columnconfigure(0,weight=1,uniform="project_cards");content.columnconfigure(1,weight=1,uniform="project_cards");content.rowconfigure(2,weight=1)

        project_box=ttk.LabelFrame(content,text="Project",padding=10);project_box.grid(row=0,column=0,sticky="nsew",padx=(0,5),pady=(0,7))
        ttk.Label(project_box,text=self.project.name,style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(project_box,text=str(self.project.root),style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,8))
        actions=ttk.Frame(project_box);actions.pack(anchor="w")
        self._button(actions,"Open another...",self._open_project,"Open another X-ray project in this same MorphoLabel window.").pack(side="left")
        self._button(actions,"New project...",self._new_project,"Create another X-ray project.").pack(side="left",padx=(6,0))

        source_box=ttk.LabelFrame(content,text="Source X-rays",padding=10);source_box.grid(row=0,column=1,sticky="nsew",padx=(5,0),pady=(0,7))
        ttk.Label(source_box,text=f"{len(self.project.source_images())} indexed images",style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(source_box,text=str(self.project.source),style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,8))
        self._button(source_box,"Rescan for images",self._rescan_source,"Scan the source X-ray folder for new images without changing existing project work.").pack(anchor="w")

        scheme_box=ttk.LabelFrame(content,text="Trait scheme",padding=10);scheme_box.grid(row=1,column=0,columnspan=2,sticky="nsew",pady=(0,7))
        ttk.Label(scheme_box,text=model["name"],style="SectionTitle.TLabel").pack(anchor="w")
        if model["description"]:ttk.Label(scheme_box,text=model["description"],style="Muted.TLabel",wraplength=1250).pack(anchor="w",pady=(2,0))
        ttk.Label(scheme_box,text=f"{model['trait_count']} traits · {model['structure_count']} structure groups · project version {len(self.project.schema_history())}",style="Muted.TLabel").pack(anchor="w",pady=(2,0))
        self._render_reference(scheme_box,model,1200)
        actions=ttk.Frame(scheme_box);actions.pack(anchor="w",pady=(8,0))
        self._button(actions,"Choose traits...",self._choose_scheme,"Choose a ready-made trait set, open a saved one, or create your own.",True).pack(side="left")
        self._button(actions,"Edit traits...",self._edit_scheme,"Edit the traits used by this project.").pack(side="left",padx=(6,0))
        more=ttk.Menubutton(actions,text="More...",style="P.TButton");more.pack(side="left",padx=(6,0))
        more_menu=tk.Menu(more,tearoff=False)
        more_menu.add_command(label="Save scheme copy...",command=self._save_scheme_as)
        more.configure(menu=more_menu);more._menu=more_menu

        traits=ttk.LabelFrame(content,text="Traits",padding=8);traits.grid(row=2,column=0,columnspan=2,sticky="nsew")
        traits.columnconfigure(0,weight=1);traits.rowconfigure(1,weight=1)
        if not scheme.get("traits"):
            ttk.Label(traits,text="No traits are defined in the active scheme.",style="SectionTitle.TLabel").grid(row=0,column=0,sticky="w")
            ttk.Label(traits,text="Edit the scheme, choose another scheme, or create a new one.",style="Muted.TLabel").grid(row=1,column=0,sticky="nw",pady=(3,0))
            return
        ttk.Label(traits,text=f"{len(scheme['traits'])} traits",style="Muted.TLabel").grid(row=0,column=0,sticky="w",pady=(0,5))
        cols=("abbr","name","method","structures")
        table=ttk.Treeview(traits,columns=cols,show="tree headings",selectmode="browse",height=10)
        table.heading("#0",text="");table.column("#0",width=38,stretch=False,anchor="center")
        headers={"abbr":"Trait","name":"Meaning","method":"How obtained","structures":"What must be annotated"}
        widths={"abbr":90,"name":270,"method":220,"structures":420}
        for key in cols:
            table.heading(key,text=headers[key]);table.column(key,width=widths[key],anchor="w",stretch=key in {"name","structures"})
        structures={item["id"]:item for item in scheme.get("structures",())}
        for index,trait in enumerate(scheme["traits"]):
            method=METHOD_BY_ID[trait["method"]]
            needed=", ".join(structures[s]["name"] for s in trait.get("structures",()) if s in structures) or "Calculated from other traits"
            table.insert("","end",iid=str(trait["id"]),image=self._icon(table,method["icon"],20),values=(trait.get("abbr") or trait["id"],trait["name"],method["label"],needed),tags=("alternate",) if index%2 else ())
        table.tag_configure("alternate",background="#f6f8fa")
        self._tip.bind(table,"Each row shows the biological trait, how it is obtained, and which image annotations it requires.")
        scroll=ttk.Scrollbar(traits,orient="vertical",command=table.yview);table.configure(yscrollcommand=scroll.set)
        table.grid(row=1,column=0,sticky="nsew");scroll.grid(row=1,column=1,sticky="ns")

    def _render_crops(self,parent):
        ttk.Label(parent,text="Crops",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Separate specimens from X-ray plates before annotation.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,12))
        card=ttk.LabelFrame(parent,text="Source X-rays",padding=14);card.pack(fill="x")
        ttk.Label(card,text=f"{len(self.project.source_images())} source image(s) indexed",style="ModuleTitle.TLabel").pack(anchor="w")
        ttk.Label(card,text="The legacy automatic plate splitter will be connected here next. Originals remain read-only; crop corrections and exclusions will live in SQLite.",style="Muted.TLabel",wraplength=900).pack(anchor="w",pady=(4,0))

    def _render_structures(self,parent):
        ttk.Label(parent,text="Structures",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Place only the anatomical structures required by the current trait scheme.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
        scheme=self.project.scheme
        if not scheme.get("structures"):
            self._empty_scheme_state(parent,"No annotation structures","Choose a scheme or define traits first; required annotation structures are derived from the traits.")
            return
        pane=ttk.Panedwindow(parent,orient="horizontal");pane.pack(fill="both",expand=True)
        canvas=ttk.LabelFrame(pane,text="X-ray",padding=10);tools=ttk.Frame(pane,padding=(8,0,0,0));pane.add(canvas,weight=3);pane.add(tools,weight=1)
        ttk.Label(canvas,text="Specimen image / annotation canvas",style="Muted.TLabel").pack(expand=True)

        active_box=ttk.LabelFrame(tools,text="Active structure",padding=10);active_box.pack(fill="x",pady=(0,7))
        active_row=ttk.Frame(active_box);active_row.pack(fill="x")
        active_marker=tk.Label(active_row,text="●",font=("Segoe UI Symbol",17,"bold"),width=2)
        active_marker.pack(side="left",padx=(0,5))
        active_text=ttk.Frame(active_row);active_text.pack(side="left",fill="x",expand=True)
        active=ttk.Label(active_text,text="",style="SectionTitle.TLabel");active.pack(anchor="w")
        active_meta=ttk.Label(active_text,text="",style="Muted.TLabel");active_meta.pack(anchor="w",pady=(1,0))
        ttk.Label(active_box,text="Click repeatedly for repeated structures. Press the number key to switch tools.",style="Muted.TLabel",wraplength=320).pack(anchor="w",pady=(7,0))

        list_box=ttk.LabelFrame(tools,text="Structure keys",padding=8);list_box.pack(fill="x",pady=(0,7))
        buttons={};markers={}
        def choose(s):
            active.configure(text=s["name"])
            active_meta.configure(text=f"Key {s.get('hotkey') or '—'} · {'Repeated points' if s.get('repeated') else 'Single reference'}")
            active_marker.configure(text=self._shape_symbol(s),foreground=s.get("color","#1976e9"))
            for ident,b in buttons.items():b.configure(style="Primary.TButton" if ident==s["id"] else "P.TButton")
            for ident,m in markers.items():m.configure(font=("Segoe UI Symbol",15,"bold") if ident==s["id"] else ("Segoe UI Symbol",13,"bold"))
        for s in scheme["structures"]:
            row=ttk.Frame(list_box);row.pack(fill="x",pady=2)
            marker=tk.Label(row,text=self._shape_symbol(s),foreground=s.get("color","#1976e9"),font=("Segoe UI Symbol",13,"bold"),width=2)
            marker.pack(side="left",padx=(0,4));markers[s["id"]]=marker
            b=self._button(row,s["name"],lambda item=s:choose(item),s.get("description",""));b.pack(side="left",fill="x",expand=True);buttons[s["id"]]=b
            ttk.Label(row,text=s.get("hotkey") or "—",style="SectionTitle.TLabel",width=3,anchor="center").pack(side="right",padx=(6,0))
            self._tip.bind(marker,s.get("description","") or f"Annotation structure: {s['name']}.")
            if s.get("hotkey"):tools.winfo_toplevel().bind(s["hotkey"],lambda _e,item=s:choose(item),add="+")
        if scheme["structures"]:choose(scheme["structures"][0])

        repeat=ttk.LabelFrame(tools,text="Manual repeatability",padding=10);repeat.pack(fill="x")
        ttk.Label(repeat,text="Two independent manual annotation passes will use the same specimens and structure keys, matching the Landmarks repeatability workflow.",style="Muted.TLabel",wraplength=320).pack(anchor="w")

    @staticmethod
    def _shape_symbol(s):return {"circle":"●","triangle":"▲","diamond":"◆","square":"■","cross":"✚","ring":"○"}.get(s.get("shape"),"●")

    def _render_results(self,parent):
        ttk.Label(parent,text="Results",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Calculated traits and QC will update from verified structures.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
        if not self.project.scheme.get("traits"):
            self._empty_scheme_state(parent,"No traits to calculate","Apply a ready-made scheme or create traits in Project first.")
            return
        cols=[t.get("abbr") or t["id"] for t in self.project.scheme["traits"]];tree=ttk.Treeview(parent,columns=("specimen",*cols),show="headings",height=12);tree.pack(fill="both",expand=True)
        tree.heading("specimen",text="Specimen");tree.column("specimen",width=180,anchor="w")
        for col in cols:tree.heading(col,text=col);tree.column(col,width=90,anchor="center")
    def _render_export(self,parent):
        ttk.Label(parent,text="Export",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Export verified traits together with scheme version, QC and provenance.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
        if not self.project.scheme.get("traits"):
            self._empty_scheme_state(parent,"Nothing to export","Apply a ready-made scheme or create traits in Project first.")
            return
        card=ttk.LabelFrame(parent,text="Scientific table",padding=14);card.pack(fill="x")
        ttk.Label(card,text="Trait values + specimen IDs + QC + scheme provenance",style="ModuleTitle.TLabel").pack(anchor="w")
        ttk.Label(card,text="Export stays disabled until the calculation and verification layer is connected; no placeholder data will be written.",style="Muted.TLabel").pack(anchor="w",pady=(4,0))

    def _empty_scheme_state(self,parent,title,text):
        card=ttk.LabelFrame(parent,text="Trait scheme needed",padding=12);card.pack(fill="x",anchor="n")
        ttk.Label(card,text=title,style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(card,text=text,style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=(2,9))
        actions=ttk.Frame(card);actions.pack(anchor="w")
        self._button(actions,"Choose traits...",self._choose_scheme,"Choose a ready-made trait set, open a saved one, or create your own.",True).pack(side="left")
        self._button(actions,"Edit traits...",self._edit_scheme,"Edit this project's traits.").pack(side="left",padx=(6,0))

    def _apply_scheme_version(self,new_scheme,note,title):
        root=self.host.container.winfo_toplevel()
        try:new=normalize_scheme(new_scheme);old=normalize_scheme(self.project.scheme);impact=scheme_change_impact(old,new,self.project.annotation_counts_by_structure())
        except Exception as exc:messagebox.showerror(title,str(exc),parent=root);return False
        if old==new:
            messagebox.showinfo(title,"This scheme is already active.",parent=root);return False
        lines=[
            f"Apply ‘{new['name']}’ to this project?",
            "",
            "Existing annotations and earlier scheme versions will be kept.",
            f"New scheme: {len(new['traits'])} traits · {len(new['structures'])} structure groups.",
        ]
        if impact["added_traits"]:lines.append(f"New traits requiring results: {len(impact['added_traits'])}.")
        if impact["archived_traits"]:lines.append(f"Traits no longer active: {len(impact['archived_traits'])}.")
        if impact["affected_annotations"]:lines.append(f"{impact['affected_annotations']} existing annotation(s) stay linked to the earlier scheme version.")
        if not messagebox.askyesno(title,"\n".join(lines),parent=root,default="yes"):return False
        try:self.project.save_scheme(new,note)
        except Exception as exc:messagebox.showerror(title,str(exc),parent=root);return False
        self.stage="project";self._rerender();return True

    def _choose_scheme(self):
        root=self.host.container.winfo_toplevel()
        dialog=SchemeLibraryDialog(root);self.host.container.wait_window(dialog)
        if dialog.result is None:return
        scheme,note=dialog.result
        self._apply_scheme_version(scheme,note,"Choose trait scheme")

    def _new_scheme(self):
        root=self.host.container.winfo_toplevel()
        dialog=TraitSchemeDialog(root,blank_scheme(),{});self.host.container.wait_window(dialog)
        if dialog.result is not None:self._apply_scheme_version(dialog.result,"Created in MorphoLabel","New trait scheme")

    def _open_scheme_json(self):
        root=self.host.container.winfo_toplevel()
        path=filedialog.askopenfilename(parent=root,title="Open saved trait scheme",filetypes=(("MorphoLabel trait scheme","*.json"),("All files","*.*")))
        if not path:return
        try:scheme=load_scheme_file(path)
        except Exception as exc:messagebox.showerror("Open saved scheme",f"Could not read this scheme.\n\n{exc}",parent=root);return
        self._apply_scheme_version(scheme,f"Opened saved scheme: {Path(path).name}","Open saved scheme")

    def _save_scheme_as(self):
        root=self.host.container.winfo_toplevel()
        safe=_safe_id(self.project.scheme.get("name","xray_trait_scheme"),"xray_trait_scheme")
        path=filedialog.asksaveasfilename(parent=root,title="Save trait scheme copy",initialfile=safe+".json",defaultextension=".json",filetypes=(("MorphoLabel trait scheme","*.json"),("JSON files","*.json")))
        if not path:return
        try:save_scheme_file(self.project.scheme,path)
        except Exception as exc:messagebox.showerror("Save scheme",f"Could not save this trait scheme.\n\n{exc}",parent=root);return
        messagebox.showinfo("Save scheme copy",f"Trait scheme copy saved.\n\n{path}",parent=root)

    def _new_project(self):
        root=self.host.container.winfo_toplevel();name=simpledialog.askstring("New X-ray project","Project name:",parent=root)
        if not name:return
        source=filedialog.askdirectory(parent=root,title="Folder with X-ray images");dest=filedialog.askdirectory(parent=root,title="Folder where the X-ray project will be created")
        if not source or not dest:return
        try:self.project=XRayProject.create(name,source,dest,blank_scheme(),scheme_note="Blank scheme created with project")
        except Exception as exc:messagebox.showerror("New X-ray project",str(exc),parent=root);return
        self.stage="project";self._rerender()

    def _rescan_source(self):
        try:self.project.scan_source()
        except Exception as exc:messagebox.showerror("Rescan source X-rays",str(exc),parent=self.host.container.winfo_toplevel());return
        self._rerender()

    def _open_project(self):
        root=self.host.container.winfo_toplevel();folder=filedialog.askdirectory(parent=root,title="Select X-ray project folder")
        if not folder:return
        try:self.project=XRayProject(folder)
        except Exception as exc:messagebox.showerror("Open X-ray project",str(exc),parent=root);return
        self.stage="project";self._rerender()
    def _edit_scheme(self):
        dialog=TraitSchemeDialog(self.host.container.winfo_toplevel(),self.project.scheme,self.project.annotation_counts_by_structure());self.host.container.wait_window(dialog)
        if dialog.result is None:return
        try:self.project.save_scheme(dialog.result,"Edited in MorphoLabel")
        except Exception as exc:messagebox.showerror("Trait scheme",str(exc),parent=self.host.container.winfo_toplevel());return
        self._rerender()

class SchemeLibraryDialog(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent);self.title("Choose traits");self.transient(parent);self.geometry("820x470");self.minsize(720,420);self.result=None;self._entries={}
        self._build();self.grab_set()

    def _add_entry(self,scheme,entry_id):
        value=normalize_scheme(scheme);model=_scheme_display_model(value)
        self._entries[entry_id]={"scheme":value,"model":model}
        self.list.insert("","end",iid=entry_id,values=(model["name"],model["trait_count"],model["structure_count"]))

    def _build(self):
        outer=ttk.Frame(self,padding=14);outer.pack(fill="both",expand=True);outer.columnconfigure(0,weight=1);outer.rowconfigure(2,weight=1)
        ttk.Label(outer,text="Choose traits",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text="Start with a ready-made set, open one shared by a colleague, or create your own.",style="PageSubtitle.TLabel").grid(row=1,column=0,sticky="w",pady=(2,10))
        body=ttk.Panedwindow(outer,orient="horizontal");body.grid(row=2,column=0,sticky="nsew")
        left=ttk.LabelFrame(body,text="Ready-made sets",padding=8);right=ttk.LabelFrame(body,text="What it contains",padding=10);body.add(left,weight=3);body.add(right,weight=2)
        left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1)
        self.list=ttk.Treeview(left,columns=("name","traits","structures"),show="headings",selectmode="browse",height=12)
        for key,label,width,stretch in (("name","Name",300,True),("traits","Traits",60,False),("structures","Markers",75,False)):
            self.list.heading(key,text=label);self.list.column(key,width=width,anchor="w" if key=="name" else "center",stretch=stretch)
        scroll=ttk.Scrollbar(left,orient="vertical",command=self.list.yview);self.list.configure(yscrollcommand=scroll.set)
        self.list.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")
        self.list.bind("<<TreeviewSelect>>",lambda _e:self._show_selection());self.list.bind("<Double-1>",lambda _e:self._use_selected())
        self.detail=ttk.Frame(right);self.detail.pack(fill="both",expand=True)

        actions=ttk.Frame(outer);actions.grid(row=3,column=0,sticky="ew",pady=(10,0))
        ttk.Button(actions,text="Open saved scheme...",command=self._open_saved).pack(side="left")
        ttk.Button(actions,text="Create my own...",command=self._create_new).pack(side="left",padx=(6,0))
        ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="right")
        self.apply=ttk.Button(actions,text="Use selected",command=self._use_selected,style="Primary.TButton");self.apply.pack(side="right",padx=(0,6))

        for item in bundled_scheme_catalog():
            self._add_entry(bundled_scheme(item["id"]),"bundled:"+item["id"])
        if self._entries:
            first=next(iter(self._entries));self.list.selection_set(first);self.list.focus(first);self._show_selection()
        else:
            self.apply.state(["disabled"]);ttk.Label(self.detail,text="No ready-made trait sets are installed.",style="Muted.TLabel").pack(anchor="w")

    def _selected_entry(self):
        selected=self.list.selection()
        return self._entries.get(selected[0]) if selected else None

    def _show_selection(self):
        for child in self.detail.winfo_children():child.destroy()
        entry=self._selected_entry()
        if not entry:
            self.apply.state(["disabled"]);return
        self.apply.state(["!disabled"])
        model=entry["model"]
        ttk.Label(self.detail,text=model["name"],style="ModuleTitle.TLabel").pack(anchor="w")
        if model["description"]:ttk.Label(self.detail,text=model["description"],style="Muted.TLabel",wraplength=330).pack(anchor="w",pady=(3,8))
        ttk.Label(self.detail,text=f"{model['trait_count']} traits · {model['structure_count']} annotation structures",style="Muted.TLabel").pack(anchor="w")
        ttk.Label(self.detail,text="Traits",style="SectionTitle.TLabel").pack(anchor="w",pady=(10,0))
        ttk.Label(self.detail,text=", ".join(model["trait_abbrs"]) or "None",style="Muted.TLabel",wraplength=330).pack(anchor="w",pady=(2,0))
        if model["reference_text"]:
            row=ttk.Frame(self.detail);row.pack(anchor="w",fill="x",pady=(10,0));ttk.Label(row,text="Reference:",style="Muted.TLabel").pack(side="left")
            citation=ttk.Label(row,text=model["reference_text"],style="Muted.TLabel",wraplength=265);citation.pack(side="left",padx=(4,0))
            if model["reference_doi"] and model["reference_text"]!=f"DOI: {model['reference_doi']}":
                link=ttk.Label(row,text=f"DOI {model['reference_doi']}",foreground="#256d9e",cursor="hand2");link.pack(side="left",padx=(6,0));link.bind("<Button-1>",lambda _e,doi=model["reference_doi"]:webbrowser.open("https://doi.org/"+doi))
            elif model["reference_doi"]:
                citation.configure(foreground="#256d9e",cursor="hand2");citation.bind("<Button-1>",lambda _e,doi=model["reference_doi"]:webbrowser.open("https://doi.org/"+doi))

    def _use_selected(self):
        entry=self._selected_entry()
        if not entry:return
        self.result=(deepcopy(entry["scheme"]),"Ready-made trait set");self.destroy()

    def _open_saved(self):
        path=filedialog.askopenfilename(parent=self,title="Open saved trait scheme",filetypes=(("MorphoLabel trait scheme","*.json"),("All files","*.*")))
        if not path:return
        try:scheme=load_scheme_file(path)
        except Exception as exc:messagebox.showerror("Open saved scheme",f"Could not read this trait scheme.\n\n{exc}",parent=self);return
        self.result=(scheme,f"Opened saved scheme: {Path(path).name}");self.destroy()

    def _create_new(self):
        editor=TraitSchemeDialog(self,blank_scheme(),{});self.wait_window(editor)
        if editor.result is None:return
        self.result=(editor.result,"Created in MorphoLabel");self.destroy()


class SchemeReferenceDialog(tk.Toplevel):
    def __init__(self,parent,reference):
        super().__init__(parent);self.title("Scheme reference");self.transient(parent);self.resizable(False,False);self.result=None
        reference=reference or {};self.label=tk.StringVar(value=reference.get("label",""));self.doi=tk.StringVar(value=reference.get("doi",""));self.note=tk.StringVar(value=reference.get("note",""))
        frame=ttk.Frame(self,padding=14);frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="Optional literature reference",style="SectionTitle.TLabel").grid(row=0,column=0,columnspan=2,sticky="w")
        ttk.Label(frame,text="Leave all fields empty when the scheme does not need a citation.",style="Muted.TLabel").grid(row=1,column=0,columnspan=2,sticky="w",pady=(2,10))
        for row,(label,var,width) in enumerate((("Citation",self.label,64),("DOI",self.doi,38),("Note",self.note,64)),start=2):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky="w",pady=3);ttk.Entry(frame,textvariable=var,width=width).grid(row=row,column=1,sticky="ew",padx=(8,0),pady=3)
        actions=ttk.Frame(frame);actions.grid(row=5,column=0,columnspan=2,sticky="e",pady=(12,0))
        ttk.Button(actions,text="Remove reference",command=self._remove).pack(side="left")
        ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="left",padx=(8,0))
        ttk.Button(actions,text="Save",command=self._save,style="Primary.TButton").pack(side="left",padx=(6,0))
    def _remove(self):self.result={};self.destroy()
    def _save(self):self.result=_clean_reference(self.label.get(),self.doi.get(),self.note.get());self.destroy()


class TraitSchemeDialog(tk.Toplevel):
    def __init__(self,parent,scheme,annotation_counts):
        super().__init__(parent);self.title("Trait scheme");self.transient(parent);self.geometry("820x560");self.minsize(720,480)
        self.scheme=deepcopy(normalize_scheme(scheme));self.original=deepcopy(self.scheme);self.annotation_counts=dict(annotation_counts or {});self.result=None
        self.scheme_name=tk.StringVar(value=self.scheme.get("name",""));self.description=tk.StringVar(value=self.scheme.get("description",""))
        self._reference_status=None;self._build();self.grab_set()
    def _build(self):
        outer=ttk.Frame(self,padding=8);outer.pack(fill="both",expand=True);outer.columnconfigure(0,weight=1);outer.rowconfigure(4,weight=1)
        namebar=ttk.Frame(outer);namebar.grid(row=0,column=0,sticky="ew",pady=(0,4))
        ttk.Label(namebar,text="Scheme name:").pack(side="left")
        ttk.Entry(namebar,textvariable=self.scheme_name,width=42).pack(side="left",padx=(6,12),fill="x",expand=True)
        ttk.Button(namebar,text="Reference...",command=self._edit_reference).pack(side="right")
        descbar=ttk.Frame(outer);descbar.grid(row=1,column=0,sticky="ew",pady=(0,4))
        ttk.Label(descbar,text="Description:").pack(side="left")
        ttk.Entry(descbar,textvariable=self.description).pack(side="left",padx=(6,0),fill="x",expand=True)
        self.reference_host=ttk.Frame(outer);self.reference_host.grid(row=2,column=0,sticky="ew")
        self._refresh_reference_status()
        ttk.Label(outer,text="Double-click a trait to edit it. The biological trait stays primary; annotation structures follow from it.",style="Muted.TLabel").grid(row=3,column=0,sticky="w",pady=(2,6))
        self.tree=ttk.Treeview(outer,columns=("abbr","method","structures"),show="headings",selectmode="browse")
        for key,label,width in (("abbr","Trait",110),("method","How obtained",210),("structures","What must be annotated",390)):self.tree.heading(key,text=label);self.tree.column(key,width=width,anchor="w",stretch=key=="structures")
        self.tree.grid(row=4,column=0,sticky="nsew")
        self.tree.bind("<Double-1>",self._edit_selected,add="+");self.tree.bind("<Return>",self._edit_selected,add="+")
        actions=ttk.Frame(outer);actions.grid(row=5,column=0,sticky="ew",pady=(8,0))
        ttk.Button(actions,text="+ Add trait",command=self._add).pack(side="left")
        ttk.Button(actions,text="Edit",command=self._edit_selected).pack(side="left",padx=(4,0))
        ttk.Button(actions,text="Remove / archive",command=self._remove).pack(side="left",padx=(4,0))
        ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="right")
        ttk.Button(actions,text="Apply changes",command=self._apply,style="Primary.TButton").pack(side="right",padx=(0,6));self._refresh()

    def _refresh_reference_status(self):
        for child in self.reference_host.winfo_children():child.destroy()
        model=_scheme_display_model(self.scheme)
        if not model["reference_text"]:return
        ttk.Label(self.reference_host,text="Reference:",style="Muted.TLabel").pack(side="left")
        text=model["reference_text"]+(" · "+model["reference_doi"] if model["reference_doi"] and model["reference_text"]!=f"DOI: {model['reference_doi']}" else "")
        ttk.Label(self.reference_host,text=text,style="Muted.TLabel").pack(side="left",padx=(4,0))

    def _edit_reference(self):
        dialog=SchemeReferenceDialog(self,self.scheme.get("reference") or {});self.wait_window(dialog)
        if dialog.result is None:return
        self.scheme["reference"]=dialog.result;self._refresh_reference_status()
    def _refresh(self,select_id=None):
        self.tree.delete(*self.tree.get_children());structures={x["id"]:x for x in self.scheme["structures"]}
        for t in self.scheme["traits"]:
            needed=", ".join(structures[s]["name"] for s in t.get("structures",()) if s in structures) or "No image annotation"
            self.tree.insert("","end",iid=t["id"],values=(t.get("abbr") or t["name"],METHOD_BY_ID[t["method"]]["label"],needed))
        if select_id and self.tree.exists(select_id):
            self.tree.selection_set(select_id);self.tree.focus(select_id);self.tree.see(select_id)
    def _add(self):
        w=TraitWizard(self,self.scheme);self.wait_window(w)
        if w.result is None:return
        trait,new_structures=w.result;self.scheme["structures"].extend(new_structures);self.scheme["traits"].append(trait);self._refresh(select_id=trait["id"])
    def _edit_selected(self,event=None):
        if event is not None and hasattr(event,"y"):
            row=self.tree.identify_row(event.y)
            if row:self.tree.selection_set(row);self.tree.focus(row)
        selected=self.tree.selection()
        if not selected:return
        ident=selected[0];trait=next(x for x in self.scheme["traits"] if x["id"]==ident)
        w=TraitWizard(self,self.scheme,trait=trait);self.wait_window(w)
        if w.result is None:return
        replacement,new_structures=w.result
        try:self.scheme=_replace_trait_definition(self.scheme,ident,replacement,new_structures,self.annotation_counts)
        except Exception as exc:messagebox.showerror("Edit trait",str(exc),parent=self);return
        self._refresh(select_id=replacement["id"])
    def _remove(self):
        selected=self.tree.selection()
        if not selected:return
        ident=selected[0];trait=next(x for x in self.scheme["traits"] if x["id"]==ident)
        if not messagebox.askyesno("Archive trait",f"Stop using ‘{trait['name']}’ in the new scheme version?\n\nExisting data and earlier scheme versions will be kept.",parent=self):return
        self.scheme["traits"]=[x for x in self.scheme["traits"] if x["id"]!=ident];usage=structure_usage(self.scheme)
        self.scheme["structures"]=[x for x in self.scheme["structures"] if usage.get(x["id"]) or int(self.annotation_counts.get(x["id"],0) or 0)>0];self._refresh()
    def _apply(self):
        name=self.scheme_name.get().strip()
        if not name:messagebox.showinfo("Trait scheme","Enter a scheme name.",parent=self);return
        self.scheme["name"]=name;self.scheme["description"]=self.description.get().strip()
        try:new=normalize_scheme(self.scheme);impact=scheme_change_impact(self.original,new,self.annotation_counts)
        except Exception as exc:messagebox.showerror("Trait scheme",str(exc),parent=self);return
        lines=["Existing data will be kept."]
        if impact["added_traits"]:lines.append(f"New traits: {len(impact['added_traits'])}.")
        if impact["archived_traits"]:lines.append(f"Traits no longer used: {len(impact['archived_traits'])}.")
        if impact["added_structures"]:lines.append(f"New structure groups: {len(impact['added_structures'])}.")
        if impact["affected_annotations"]:lines.append(f"{impact['affected_annotations']} existing annotation(s) stay under the earlier scheme version.")
        if messagebox.askyesno("Scheme change","\n".join(lines)+"\n\nApply this new scheme version?",parent=self):self.result=new;self.destroy()

class TraitWizard(tk.Toplevel):
    def __init__(self,parent,scheme,trait=None):
        super().__init__(parent);self.transient(parent);self.resizable(False,False);self.scheme=scheme;self.original_trait=deepcopy(trait) if trait else None;self.result=None;self._images={};self._tip=Tooltip(self)
        self.title("Edit trait" if trait else "Add trait")
        self.name=tk.StringVar(value=(trait or {}).get("name",""));self.abbr=tk.StringVar(value=(trait or {}).get("abbr",""));self.method=tk.StringVar(value=(trait or {}).get("method","count"));self._build();self.grab_set()
    def _icon(self,name):
        if name not in self._images:self._images[name]=tk_xray_icon(self,name,TRAIT_ICON_SIZE)
        return self._images[name]
    def _build(self):
        outer=ttk.Frame(self,padding=16);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Edit biological trait" if self.original_trait else "What trait do you want to obtain?",style="PageTitle.TLabel").grid(row=0,column=0,columnspan=4,sticky="w")
        ttk.Label(outer,text="Trait name").grid(row=1,column=0,sticky="w",pady=(12,3));ttk.Entry(outer,textvariable=self.name,width=48).grid(row=2,column=0,columnspan=3,sticky="ew")
        ttk.Label(outer,text="Abbreviation").grid(row=1,column=3,sticky="w",padx=(8,0),pady=(12,3));ttk.Entry(outer,textvariable=self.abbr,width=14).grid(row=2,column=3,sticky="ew",padx=(8,0))
        ttk.Label(outer,text="How is this trait obtained?",style="SectionTitle.TLabel").grid(row=3,column=0,columnspan=4,sticky="w",pady=(14,5))
        for i,item in enumerate(TRAIT_METHODS):
            r,c=divmod(i,2);b=ttk.Radiobutton(outer,text=item["label"],value=item["id"],variable=self.method,image=self._icon(item["icon"]),compound="left",padding=(8,6));b.grid(row=4+r,column=c*2,columnspan=2,sticky="ew",padx=(0 if c==0 else 4,4 if c==0 else 0),pady=2);self._tip.bind(b,item["help"])
        actions=ttk.Frame(outer);actions.grid(row=8,column=0,columnspan=4,sticky="e",pady=(14,0));ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="left");ttk.Button(actions,text="Save changes" if self.original_trait else "Next",command=self._next,style="Primary.TButton").pack(side="left",padx=(6,0))
    def _next(self):
        name=self.name.get().strip();abbr=self.abbr.get().strip() or _safe_id(name,"trait")
        if not name:messagebox.showinfo("Add trait","Enter the biological trait name.",parent=self);return
        method=self.method.get()
        if self.original_trait:trait_id=self.original_trait["id"]
        else:
            trait_id=_safe_id(abbr,"trait");used={x["id"] for x in self.scheme["traits"]};base=trait_id;i=2
            while trait_id in used:trait_id=f"{base}_{i}";i+=1
        if method=="derived":
            available=[item for item in self.scheme["traits"] if not self.original_trait or item["id"]!=self.original_trait["id"]]
            if not available:messagebox.showinfo("Trait","Add at least one directly observed trait first.",parent=self);return
            rule=deepcopy((self.original_trait or {}).get("rule") or {}) if (self.original_trait or {}).get("method")=="derived" else {"expression":"","depends_on":[]}
            self.result=({"id":trait_id,"name":name,"abbr":abbr,"method":method,"structures":[],"rule":rule},[]);self.destroy();return
        prompt="What anatomical object do you annotate?" if method in {"count","presence"} else "What repeated anatomical object do you count?" if method in {"count_to","count_between","position"} else "What anatomical reference do you annotate?"
        structures_by_id={item["id"]:item for item in self.scheme["structures"]}
        current_ids=list((self.original_trait or {}).get("structures") or ())
        initial_object=structures_by_id.get(current_ids[0],{}).get("name","") if current_ids else ""
        object_name=simpledialog.askstring("Annotation structure",prompt,parent=self,initialvalue=initial_object)
        if not object_name:return
        existing=next((x for x in self.scheme["structures"] if x["name"].strip().casefold()==object_name.strip().casefold()),None);new=[];used_keys={str(x.get("hotkey","")) for x in self.scheme["structures"]}
        if existing is None:
            idx=len(self.scheme["structures"]);hotkey=next((str(n) for n in range(1,10) if str(n) not in used_keys),"")
            existing={"id":_safe_id(object_name,"structure"),"name":object_name.strip(),"annotation":"point","repeated":method in {"count","count_to","count_between","position"},"required":True,"hotkey":hotkey,"shape":SHAPES[idx%len(SHAPES)],"color":MARKER_COLORS[idx%len(MARKER_COLORS)],"description":""};new.append(existing)
        structures=[existing["id"]];rule={}
        if method in {"count_to","count_between","position","distance","angle"}:
            initial_reference=structures_by_id.get(current_ids[1],{}).get("name","") if len(current_ids)>1 else ""
            ref_name=simpledialog.askstring("Reference structure","What reference marks the boundary / position?",parent=self,initialvalue=initial_reference)
            if not ref_name:return
            reference=next((x for x in [*self.scheme["structures"],*new] if x["name"].strip().casefold()==ref_name.strip().casefold()),None)
            if reference is None:
                idx=len(self.scheme["structures"])+len(new);used_keys={str(x.get("hotkey","")) for x in [*self.scheme["structures"],*new]};hotkey=next((str(n) for n in range(1,10) if str(n) not in used_keys),"")
                reference={"id":_safe_id(ref_name,"reference"),"name":ref_name.strip(),"annotation":"point","repeated":False,"required":True,"hotkey":hotkey,"shape":SHAPES[idx%len(SHAPES)],"color":MARKER_COLORS[idx%len(MARKER_COLORS)],"description":""};new.append(reference)
            structures.append(reference["id"]);rule["reference"]=reference["id"]
        self.result=({"id":trait_id,"name":name,"abbr":abbr,"method":method,"structures":structures,"rule":rule},new);self.destroy()
