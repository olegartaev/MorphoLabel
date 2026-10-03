"""Built-in X-ray traits module with a trait-first workflow."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk
import webbrowser

from app.ui.tooltips import Tooltip
from app.ui.icons import TOPBAR_ICON_SIZE,tk_icon
from app.xray_icons import XRAY_ICON_SIZE,TRAIT_ICON_SIZE,tk_xray_icon,tk_rule_preview
from app.xray_project import XRayProject
from app.xray_crop_ui import XRayCropWorkspace
from app.xray_structures_ui import XRayStructureWorkspace
from app.xray_schema import (
    MARKER_COLORS,METHOD_BY_ID,SCHEME_RESOURCE_DIR,SHAPES,TRAIT_METHODS,blank_scheme,bundled_scheme,normalize_scheme,
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

EDITOR_METHOD_IDS=("count","count_to","count_between","derived")
EDITOR_METHODS=tuple(METHOD_BY_ID[item] for item in EDITOR_METHOD_IDS)
EDITOR_METHOD_LABELS={
    "count":"Count all",
    "count_to":"Count to a stop mark",
    "count_between":"Count between two reference marks",
    "derived":"Calculate from other traits",
}
METHOD_LABEL_TO_ID={item["label"]:item["id"] for item in TRAIT_METHODS}
METHOD_LABEL_TO_ID.update({label:key for key,label in EDITOR_METHOD_LABELS.items()})
METHOD_ID_TO_LABEL={item["id"]:EDITOR_METHOD_LABELS.get(item["id"],item["label"]) for item in TRAIT_METHODS}
REFERENCE_METHODS={"count_to","count_between","position","distance","angle"}
REPEATED_METHODS={"count","count_to","count_between","position"}
STOP_BEHAVIOR_LABELS={"before":"Do not count it","through":"Count it","from":"Start counting from it"}
STOP_BEHAVIOR_VALUES={value:key for key,value in STOP_BEHAVIOR_LABELS.items()}
COLOR_CHOICES=(
    ("Blue","#1976e9"),("Green","#20a447"),("Orange","#ef8a17"),
    ("Violet","#7e57c2"),("Red","#d9534f"),("Gray","#66727d"),
)
COLOR_NAME_TO_HEX=dict(COLOR_CHOICES)
COLOR_HEX_TO_NAME={value:key for key,value in COLOR_CHOICES}

def _next_structure_id(scheme,name,prefix="structure"):
    base=_safe_id(name,prefix);used={item["id"] for item in scheme.get("structures",())}
    value=base;index=2
    while value in used:
        value=f"{base}_{index}";index+=1
    return value

def _next_hotkey(scheme):
    used={str(item.get("hotkey","")) for item in scheme.get("structures",())}
    return next((str(number) for number in range(1,10) if str(number) not in used),"")

def _default_structure(scheme,name,repeated=False):
    index=len(scheme.get("structures",()))
    return {
        "id":_next_structure_id(scheme,name),
        "name":str(name).strip(),
        "annotation":"point",
        "repeated":bool(repeated),
        "required":True,
        "hotkey":_next_hotkey(scheme),
        "shape":SHAPES[index%len(SHAPES)],
        "color":MARKER_COLORS[index%len(MARKER_COLORS)],
        "description":"",
    }

def _trait_rule_summary(scheme,trait):
    structures={item["id"]:item for item in scheme.get("structures",())}
    ids=list(trait.get("structures",()))
    primary=structures.get(ids[0],{}).get("name","") if ids else ""
    reference=structures.get(ids[1],{}).get("name","") if len(ids)>1 else ""
    reference2=structures.get(ids[2],{}).get("name","") if len(ids)>2 else ""
    method=trait.get("method")
    if method=="count":return f"Count {primary}" if primary else "Count"
    if method=="count_to":
        side=(trait.get("rule") or {}).get("side")
        relation={"before":"before","from":"starting with","through":"through"}.get(side,"to")
        return f"{primary} {relation} {reference}".strip()
    if method=="count_between":
        return f"{primary}: {reference} → {reference2}".strip(" :→")
    if method=="derived":return "Calculated from other traits"
    return METHOD_BY_ID[method]["label"]

def orientation_preview_transform(head,bottom):
    """Pure orientation-preview state, also used by its focused regression test."""
    return {
        "flip_x":head=="right","flip_y":bottom=="up",
        "show_head":head!="none","show_tail":head!="none","show_bottom":bottom!="none",
        "neutral":head=="none",
    }


class OrientationSetupDialog(tk.Toplevel):
    """One-time project viewing convention; originals are never rewritten."""
    def __init__(self,parent,initial=None):
        super().__init__(parent);self.title("Object orientation");self.transient(parent);self.resizable(False,False)
        initial=initial or {"head":"left","bottom":"down"};self.result=None
        self.head=tk.StringVar(master=self,value=str(initial.get("head") or "left"))
        self.bottom=tk.StringVar(master=self,value=str(initial.get("bottom") or "down"))
        outer=ttk.Frame(self,padding=14);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Standard orientation",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(outer,text="Choose a consistent view for cropped animals.",style="PageSubtitle.TLabel",wraplength=600).pack(anchor="w",pady=(2,8))
        self.preview=tk.Canvas(outer,width=600,height=160,background="#f8fafc",highlightthickness=1,highlightbackground="#d6dbe0");self.preview.pack(fill="x")
        controls=ttk.Frame(outer);controls.pack(fill="x",pady=(8,0))
        head_box=ttk.LabelFrame(controls,text="Head faces",padding=9);head_box.pack(side="left",fill="x",expand=True,padx=(0,5))
        for text,value in (("Left","left"),("Right","right"),("Don't standardize","none")):
            ttk.Radiobutton(head_box,text=text,value=value,variable=self.head,command=self._draw).pack(anchor="w")
        bottom_box=ttk.LabelFrame(controls,text="Ventral side faces",padding=9);bottom_box.pack(side="left",fill="x",expand=True,padx=(5,0))
        for text,value in (("Down","down"),("Up","up"),("Don't standardize","none")):
            ttk.Radiobutton(bottom_box,text=text,value=value,variable=self.bottom,command=self._draw).pack(anchor="w")
        ttk.Label(outer,text="Blue = head · orange = ventral side. Confirmed crops teach orientation. Original X-rays stay unchanged.",style="Muted.TLabel",wraplength=600).pack(anchor="w",pady=(8,0))
        actions=ttk.Frame(outer);actions.pack(anchor="e",pady=(10,0))
        ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="left")
        ttk.Button(actions,text="Create project",style="Primary.TButton",command=self._accept).pack(side="left",padx=(6,0))
        self._draw();self.grab_set()

    def _draw(self):
        c=self.preview;c.delete("all");w=600;h=160;cx=w/2;cy=h/2
        head=self.head.get();bottom=self.bottom.get()
        state=orientation_preview_transform(head,bottom);flip_x=state["flip_x"];flip_y=state["flip_y"]
        def point(x,y):return (cx+(x-cx)*(-1 if flip_x else 1),cy+(y-cy)*(-1 if flip_y else 1))
        if not state["show_head"]:
            c.create_oval(cx-142,cy-35,cx+142,cy+35,fill="#edf2f5",outline="#71818d",width=2)
            c.create_line(cx-95,cy,cx+95,cy,fill="#a7b2ba",width=2)
        else:
            body=[(cx-118,cy-30),(cx-55,cy-42),(cx+45,cy-37),(cx+112,cy-20),(cx+132,cy),(cx+112,cy+20),(cx+45,cy+37),(cx-55,cy+42),(cx-118,cy+30),(cx-142,cy+12),(cx-142,cy-12)]
            tail=[(cx+108,cy-18),(cx+182,cy-50),(cx+160,cy),(cx+182,cy+50),(cx+108,cy+18)]
            coords=[v for p in body for v in point(*p)];c.create_polygon(*coords,fill="#edf2f5",outline="#71818d",width=2)
            coords=[v for p in tail for v in point(*p)];c.create_polygon(*coords,fill="#edf2f5",outline="#71818d",width=2)
            hx,hy=point(cx-139,cy);c.create_oval(hx-18,hy-20,hx+18,hy+20,fill="#dfe8ee",outline="#71818d",width=2)
            eye=point(cx-148,cy-7);c.create_oval(eye[0]-3,eye[1]-3,eye[0]+3,eye[1]+3,fill="#2196f3",outline="#ffffff")
            marker=point(cx-160,cy);c.create_polygon(marker[0]-9,marker[1],marker[0]+5,marker[1]-8,marker[0]+5,marker[1]+8,fill="#2196f3",outline="#ffffff")
            label=point(cx-126,cy-54);c.create_text(*label,text="Head",fill="#176fa7",font=("Segoe UI",9,"bold"))
        if state["show_bottom"]:
            y=cy+38
            line=[point(cx-62,y),point(cx+62,y)]
            c.create_line(*line[0],*line[1],fill="#ffad1f",width=6)
            tip=point(cx,y+19);base1=point(cx-9,y+2);base2=point(cx+9,y+2)
            c.create_polygon(*tip,*base1,*base2,fill="#ffad1f",outline="#ffffff")
            label=point(cx,y+45);c.create_text(*label,text="Ventral side",fill="#9a6500",font=("Segoe UI",9,"bold"))

    def _accept(self):
        self.result={"head":self.head.get(),"bottom":self.bottom.get()};self.destroy()


class XRayCountsRuntime:
    def __init__(self):self.host=None;self.project=None;self.stage="project";self._images={};self._tip=None;self._workspace=None
    def close(self):self.host=None;self._workspace=None;self._images.clear();self._tip=None
    def _selection(self):
        return self.project.current_selection() if self.project is not None else {"image_id":"","specimen_id":""}

    def _set_selection(self,image_id="",specimen_id=""):
        if self.project is None:return {"image_id":"","specimen_id":""}
        try:return self.project.set_current_selection(image_id=image_id,specimen_id=specimen_id)
        except (KeyError,ValueError):return self.project.current_selection()

    def _ensure_working_scheme(self):
        if self.project is None:return False
        return self.project.ensure_initial_bundled_scheme("phoxinus_vertebral_counts")

    @staticmethod
    def _sample_name(relative_path):
        parent=Path(str(relative_path)).parent.as_posix()
        return "Root" if parent in {"",".","/"} else parent

    def _selection_context(self):
        selection=self._selection();specimen_id=selection.get("specimen_id");image_id=selection.get("image_id")
        specimen=None
        if specimen_id:
            try:specimen=self.project.specimen(specimen_id);image_id=specimen["image_id"]
            except KeyError:specimen=None
        if not image_id:return ""
        try:image=self.project.source_image(image_id)
        except KeyError:return ""
        path=Path(image["relative_path"]);sample=self._sample_name(image["relative_path"])
        if specimen is not None:return f"Locality: {sample}  ·  Plate: {path.name}  ·  Specimen: №{int(specimen.get('ordinal') or 0)}"
        return f"Locality: {sample}  ·  Plate: {path.name}"

    def render(self,host):
        self.host=host;parent=host.container
        for child in parent.winfo_children():child.destroy()
        self._workspace=None;self._images={};self._tip=Tooltip(parent.winfo_toplevel())
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
    def _core_icon(self,master,name,size=TOPBAR_ICON_SIZE):
        key=("core",name,size)
        if key not in self._images:self._images[key]=tk_icon(master,name,size)
        return self._images[key]
    def _header(self,parent):
        nav=ttk.Frame(parent,style="Topbar.TFrame");nav.pack(fill="x",pady=(0,4))
        home=ttk.Button(nav,text="Modules",image=self._core_icon(nav,"modules"),compound="left",command=self.host.show_module_hub,style="Stage.TButton")
        home.pack(side="left",padx=(0,8));self._tip.bind(home,"Return to the MorphoLabel module hub.")
        for key,label,icon in STAGES:
            active=self.stage==key
            b=ttk.Button(nav,text=("● "+label) if active else label,image=self._icon(nav,icon,TOPBAR_ICON_SIZE),compound="left",style="StageActive.TButton" if active else "Stage.TButton",command=lambda k=key:self._select(k))
            if self.project is None and key!="project":b.state(["disabled"])
            b.pack(side="left",padx=(0,3));self._tip.bind(b,f"Open the {label} section.")
        standard_menu=getattr(self.host,"build_standard_menu",None)
        if callable(standard_menu):standard_menu(nav)

    def _select(self,key):
        if self.project is None and key!="project":return
        if key==self.stage:return
        flush=getattr(self._workspace,"flush_pending_edits",None)
        if callable(flush):
            try:flush()
            except Exception as exc:
                messagebox.showerror("X-ray Crops",f"Could not save the current Crop edits before changing section:\n{exc}",parent=self.host.container.winfo_toplevel())
                return
        if self.project is not None and key in {"structures","results","export"}:self._ensure_working_scheme()
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
        storage=self.project.storage_summary();policy=self.project.orientation_policy
        ttk.Label(source_box,text=f"{len(self.project.source_images())} indexed images",style="SectionTitle.TLabel").pack(anchor="w")
        storage_text="Self-contained project source" if storage["self_contained"] else "Legacy external source"
        ttk.Label(source_box,text=f"{storage_text} · {storage['source_bytes']/1024/1024:.1f} MB",style="Muted.TLabel").pack(anchor="w",pady=(2,0))
        ttk.Label(source_box,text=str(self.project.source),style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(2,4))
        head={"left":"left","right":"right","none":"not standardized"}[policy["head"]];bottom={"down":"down","up":"up","none":"not standardized"}[policy["bottom"]]
        ttk.Label(source_box,text=f"Canonical view: head {head} · bottom {bottom}",style="Muted.TLabel").pack(anchor="w",pady=(0,8))
        source_actions=ttk.Frame(source_box);source_actions.pack(anchor="w")
        self._button(source_actions,"Rescan for images",self._rescan_source,"Scan the project source X-ray folder for new images without changing existing project work.").pack(side="left")
        if not storage["self_contained"]:
            self._button(source_actions,"Make self-contained…",self._make_self_contained,"Import the indexed source X-rays into the project once; hard links are used when possible to avoid duplicate disk usage.").pack(side="left",padx=(6,0))
        if storage["cache_bytes"]:
            self._button(source_actions,"Clear reproducible cache",self._compact_project,"Remove only temporary/reproducible X-ray AI cache files; scientific data and final models are kept.").pack(side="left",padx=(6,0))

        scheme_box=ttk.LabelFrame(content,text="Traits",padding=10);scheme_box.grid(row=1,column=0,columnspan=2,sticky="nsew",pady=(0,7))
        ttk.Label(scheme_box,text=model["name"],style="SectionTitle.TLabel").pack(anchor="w")
        if model["description"]:ttk.Label(scheme_box,text=model["description"],style="Muted.TLabel",wraplength=1250).pack(anchor="w",pady=(2,0))
        ttk.Label(scheme_box,text=f"{model['trait_count']} traits",style="Muted.TLabel").pack(anchor="w",pady=(2,0))
        self._render_reference(scheme_box,model,1200)
        actions=ttk.Frame(scheme_box);actions.pack(anchor="w",pady=(8,0))
        self._button(actions,"Traits...",self._choose_scheme,"Choose what to measure, how to count it, and which marks are used on the X-ray.",True).pack(side="left")

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
        selection=self._selection()
        self._workspace=XRayCropWorkspace(
            parent,self.project,
            initial_image_id=selection.get("image_id"),initial_specimen_id=selection.get("specimen_id"),
            on_selection=self._set_selection,
        )

    def _render_structures(self,parent):
        self._ensure_working_scheme();selection=self._selection()
        self._workspace=XRayStructureWorkspace(
            parent,self.project,
            initial_image_id=selection.get("image_id"),initial_specimen_id=selection.get("specimen_id"),
            on_selection=self._set_selection,on_open_results=lambda:self._select("results"),
        )

    @staticmethod
    def _shape_symbol(s):return {"circle":"●","triangle":"▲","diamond":"◆","square":"■","cross":"✚","ring":"○"}.get(s.get("shape"),"●")

    def _render_results(self,parent):
        self._ensure_working_scheme()
        ttk.Label(parent,text="Results",style="PageTitle.TLabel").pack(anchor="w")
        context=self._selection_context()
        if context:ttk.Label(parent,text=context,style="SectionTitle.TLabel").pack(anchor="w",pady=(2,3))
        ttk.Label(parent,text="Calculated directly from the current saved structure markers; no separate results cache is used for display.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(0,8))
        scheme=self.project.scheme
        if not scheme.get("traits"):
            self._empty_scheme_state(parent,"No traits to calculate","Open a trait set or create traits in Project first.");return
        traits=list(scheme["traits"]);cols=("locality","plate","fish",*(t.get("abbr") or t["id"] for t in traits),"status")
        host=ttk.Frame(parent);host.pack(fill="both",expand=True);host.columnconfigure(0,weight=1);host.rowconfigure(0,weight=1)
        tree=ttk.Treeview(host,columns=cols,show="headings",selectmode="browse",height=16)
        tree.heading("locality",text="Locality");tree.column("locality",width=180,anchor="w")
        tree.heading("plate",text="Plate");tree.column("plate",width=220,anchor="w")
        tree.heading("fish",text="Specimen");tree.column("fish",width=62,anchor="center",stretch=False)
        for trait in traits:
            col=trait.get("abbr") or trait["id"];tree.heading(col,text=col);tree.column(col,width=78,anchor="center",stretch=False)
        tree.heading("status",text="Status");tree.column("status",width=90,anchor="center",stretch=False)
        current=self._selection().get("specimen_id")
        for index,row in enumerate(self.project.trait_rows()):
            path=Path(row["relative_path"]);values=row["trait_values"]
            display=[self._sample_name(row["relative_path"]),path.name,int(row.get("ordinal") or 0)]
            display.extend("" if values.get(trait["id"]) is None else str(values.get(trait["id"])) for trait in traits)
            status=str(row.get("result_status") or "not_started")
            tree.insert("","end",iid=row["specimen_id"],values=(*display,status),tags=("alternate",) if index%2 else ())
        tree.tag_configure("alternate",background="#f6f8fa")
        scroll=ttk.Scrollbar(host,orient="vertical",command=tree.yview);tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")
        if current and tree.exists(current):tree.selection_set(current);tree.focus(current);tree.see(current)
        def selected(_event=None):
            chosen=tree.selection()
            if not chosen:return
            specimen=self.project.specimen(chosen[0]);self._set_selection(specimen["image_id"],chosen[0])
        tree.bind("<<TreeviewSelect>>",selected)

    def _render_export(self,parent):
        ttk.Label(parent,text="Export",style="PageTitle.TLabel").pack(anchor="w")
        context=self._selection_context()
        if context:ttk.Label(parent,text=context,style="SectionTitle.TLabel").pack(anchor="w",pady=(2,3))
        ttk.Label(parent,text="Export verified traits together with scheme version, QC and provenance.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
        if not self.project.scheme.get("traits"):
            self._empty_scheme_state(parent,"Nothing to export","Open a trait set or create traits in Project first.")
            return
        card=ttk.LabelFrame(parent,text="Scientific table",padding=14);card.pack(fill="x")
        ttk.Label(card,text="Trait values + specimen IDs + QC + scheme provenance",style="ModuleTitle.TLabel").pack(anchor="w")
        ttk.Label(card,text="Export stays disabled until the calculation and verification layer is connected; no placeholder data will be written.",style="Muted.TLabel").pack(anchor="w",pady=(4,0))

    def _empty_scheme_state(self,parent,title,text):
        card=ttk.LabelFrame(parent,text="Traits needed",padding=12);card.pack(fill="x",anchor="n")
        ttk.Label(card,text=title,style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(card,text=text,style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=(2,9))
        actions=ttk.Frame(card);actions.pack(anchor="w")
        self._button(actions,"Traits...",self._choose_scheme,"Open all trait and annotation settings in one window.",True).pack(side="left")

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
        dialog=TraitSchemeDialog(root,self.project.scheme,self.project.annotation_counts_by_structure());self.host.container.wait_window(dialog)
        if dialog.result is None:return
        scheme,note=dialog.result
        self._apply_scheme_version(scheme,note,"Trait scheme")

    def _edit_scheme(self):
        self._choose_scheme()

    def _new_project(self):
        root=self.host.container.winfo_toplevel();name=simpledialog.askstring("New X-ray project","Project name:",parent=root)
        if not name:return
        source=filedialog.askdirectory(parent=root,title="Folder with X-ray images");dest=filedialog.askdirectory(parent=root,title="Folder where the X-ray project will be created")
        if not source or not dest:return
        dialog=OrientationSetupDialog(root);root.wait_window(dialog)
        if dialog.result is None:return
        try:self.project=XRayProject.create(name,source,dest,blank_scheme(),scheme_note="Blank scheme created with project",orientation_policy=dialog.result)
        except Exception as exc:messagebox.showerror("New X-ray project",str(exc),parent=root);return
        self.stage="project";self._rerender()

    def _make_self_contained(self):
        root=self.host.container.winfo_toplevel()
        if not messagebox.askyesno("Make project self-contained","Import the indexed X-rays into this project?\n\nOn the same disk MorphoLabel uses hard links when possible, so this normally does not duplicate image data. On another disk the originals are copied once.",parent=root,default="yes"):return
        try:result=self.project.make_self_contained()
        except Exception as exc:messagebox.showerror("Make project self-contained",str(exc),parent=root);return
        messagebox.showinfo("Project source",f"Project is self-contained.\nImages: {result['files']}\nHard-linked: {result['hardlinked']}\nCopied: {result['copied']}",parent=root);self._rerender()

    def _compact_project(self):
        result=self.project.compact_disposable_ai_artifacts()
        messagebox.showinfo("Project cache",f"Removed {result['removed_files']} reproducible file(s).\nFreed {result['removed_bytes']/1024/1024:.1f} MB.\n\nSource X-rays, SQLite data and final models were not touched.",parent=self.host.container.winfo_toplevel());self._rerender()

    def _rescan_source(self):
        try:self.project.scan_source()
        except Exception as exc:messagebox.showerror("Rescan source X-rays",str(exc),parent=self.host.container.winfo_toplevel());return
        self._rerender()

    def _open_project(self):
        root=self.host.container.winfo_toplevel();folder=filedialog.askdirectory(parent=root,title="Select X-ray project folder")
        if not folder:return
        try:
            self.project=XRayProject(folder)
            self.project.compact_disposable_ai_artifacts()
        except Exception as exc:messagebox.showerror("Open X-ray project",str(exc),parent=root);return
        self.stage="project";self._rerender()
class MarkerSettingsDialog(tk.Toplevel):
    """Optional second depth: appearance and keyboard shortcuts only."""
    def __init__(self,parent,scheme):
        super().__init__(parent);self.title("Colors & keys");self.transient(parent);self.geometry("690x420");self.minsize(620,380)
        self.scheme=deepcopy(normalize_scheme(scheme));self.result=None;self._editing_id=None
        self.hotkey=tk.StringVar();self.shape=tk.StringVar();self.color=tk.StringVar()
        self._build();self.grab_set()

    def _build(self):
        outer=ttk.Frame(self,padding=12);outer.pack(fill="both",expand=True);outer.columnconfigure(0,weight=1);outer.rowconfigure(2,weight=1)
        ttk.Label(outer,text="Colors & keys",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text="Only the appearance and shortcut of existing X-ray annotations are changed here.",style="PageSubtitle.TLabel").grid(row=1,column=0,sticky="w",pady=(2,8))
        body=ttk.Panedwindow(outer,orient="horizontal");body.grid(row=2,column=0,sticky="nsew")
        left=ttk.LabelFrame(body,text="X-ray annotations",padding=8);right=ttk.LabelFrame(body,text="Selected annotation",padding=10);body.add(left,weight=3);body.add(right,weight=2)
        left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1);right.columnconfigure(1,weight=1)
        self.tree=ttk.Treeview(left,columns=("name","kind","key","shape","color"),show="headings",selectmode="browse")
        for key,label,width,stretch in (
            ("name","Name",220,True),("kind","Role",100,False),("key","Key",42,False),("shape","Marker",68,False),("color","Color",65,False),
        ):
            self.tree.heading(key,text=label);self.tree.column(key,width=width,anchor="w" if key in {"name","kind"} else "center",stretch=stretch)
        scroll=ttk.Scrollbar(left,orient="vertical",command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns");self.tree.bind("<<TreeviewSelect>>",self._selected)

        self.name_label=ttk.Label(right,text="",style="SectionTitle.TLabel");self.name_label.grid(row=0,column=0,columnspan=2,sticky="w")
        key_label=ttk.Label(right,text="Shortcut key");key_label.grid(row=1,column=0,sticky="w",pady=(10,0))
        key_combo=ttk.Combobox(right,textvariable=self.hotkey,values=("",*tuple(str(i) for i in range(1,10))),state="readonly",width=7);key_combo.grid(row=1,column=1,sticky="w",padx=(7,0),pady=(10,0))
        marker_label=ttk.Label(right,text="Marker shape");marker_label.grid(row=2,column=0,sticky="w",pady=(7,0))
        marker_combo=ttk.Combobox(right,textvariable=self.shape,values=SHAPES,state="readonly");marker_combo.grid(row=2,column=1,sticky="ew",padx=(7,0),pady=(7,0))
        color_label=ttk.Label(right,text="Color");color_label.grid(row=3,column=0,sticky="w",pady=(7,0))
        color_combo=ttk.Combobox(right,textvariable=self.color,values=tuple(name for name,_ in COLOR_CHOICES),state="readonly");color_combo.grid(row=3,column=1,sticky="ew",padx=(7,0),pady=(7,0))
        ttk.Button(right,text="Save",command=self._update,style="Primary.TButton").grid(row=4,column=1,sticky="e",pady=(12,0))

        actions=ttk.Frame(outer);actions.grid(row=3,column=0,sticky="e",pady=(10,0))
        ttk.Button(actions,text="Cancel",command=self.destroy,style="P.TButton").pack(side="left")
        ttk.Button(actions,text="Done",command=self._done,style="Primary.TButton").pack(side="left",padx=(6,0))
        self._refresh()

    def _active_structures(self):
        usage=structure_usage(self.scheme)
        return [item for item in self.scheme.get("structures",()) if usage.get(item["id"]) or item.get("id")]

    def _refresh(self,select_id=None):
        self.tree.delete(*self.tree.get_children())
        for item in self._active_structures():
            role="Element to count" if item.get("repeated") else "Start / stop mark"
            self.tree.insert("","end",iid=item["id"],values=(item["name"],role,item.get("hotkey") or "—",item.get("shape","circle"),COLOR_HEX_TO_NAME.get(item.get("color"),"Custom")))
        ids=self.tree.get_children();target=select_id if select_id and self.tree.exists(select_id) else (ids[0] if ids else None)
        if target:self.tree.selection_set(target);self.tree.focus(target);self._load(target)
        else:self._clear()

    def _selected(self,_event=None):
        selected=self.tree.selection()
        if selected:self._load(selected[0])

    def _load(self,ident):
        item=next((x for x in self.scheme.get("structures",()) if x["id"]==ident),None)
        if item is None:return
        self._editing_id=ident;self.name_label.configure(text=item["name"]);self.hotkey.set(str(item.get("hotkey") or ""));self.shape.set(item.get("shape",SHAPES[0]));self.color.set(COLOR_HEX_TO_NAME.get(item.get("color"),COLOR_CHOICES[0][0]))

    def _clear(self):
        self._editing_id=None;self.name_label.configure(text="No annotation selected");self.hotkey.set("");self.shape.set(SHAPES[0]);self.color.set(COLOR_CHOICES[0][0])

    def _update(self):
        if not self._editing_id:return
        candidate=deepcopy(self.scheme);item=next(x for x in candidate["structures"] if x["id"]==self._editing_id)
        item["hotkey"]=self.hotkey.get().strip();item["shape"]=self.shape.get() or SHAPES[0];item["color"]=COLOR_NAME_TO_HEX.get(self.color.get(),MARKER_COLORS[0])
        try:self.scheme=normalize_scheme(candidate)
        except Exception as exc:messagebox.showerror("X-ray annotation",str(exc),parent=self);return
        self._refresh(self._editing_id)

    def _done(self):
        self.result=deepcopy(self.scheme);self.destroy()


class TraitSchemeDialog(tk.Toplevel):
    """Biologist-facing trait editor: traits, counted elements and reference marks in one window."""
    def __init__(self,parent,scheme,annotation_counts):
        super().__init__(parent);self.title("Traits");self.transient(parent);self.geometry("1180x800");self.minsize(1000,720)
        self.scheme=deepcopy(normalize_scheme(scheme));self.annotation_counts=dict(annotation_counts or {});self.result=None;self.note="Edited in MorphoLabel"
        self._tip=Tooltip(self);self._editing_trait_id=None;self._preview_image=None;self._images={}
        self.scheme_name=tk.StringVar();self.description=tk.StringVar();self.reference_label=tk.StringVar();self.reference_doi=tk.StringVar();self.reference_note=tk.StringVar()
        self.trait_name=tk.StringVar();self.trait_abbr=tk.StringVar();self.trait_method=tk.StringVar()
        self.trait_object=tk.StringVar();self.trait_reference=tk.StringVar();self.trait_reference2=tk.StringVar()
        self.trait_offset=tk.StringVar();self.trait_stop_behavior=tk.StringVar();self.trait_expression=tk.StringVar();self.trait_depends=tk.StringVar()
        self._build();self._load_scheme(self.scheme,self.note);self._maximize_window();self.grab_set()

    def _maximize_window(self):
        """Open the main Traits workspace maximized so both setup steps are visible."""
        try:
            self.state("zoomed")
            return
        except tk.TclError:
            pass
        try:
            self.attributes("-zoomed",True)
            return
        except tk.TclError:
            pass
        try:
            width=max(1000,int(self.winfo_screenwidth()))
            height=max(720,int(self.winfo_screenheight())-48)
            self.geometry(f"{width}x{height}+0+0")
        except tk.TclError:
            return

    def _button(self,parent,text,command,help_text="",primary=False):
        button=ttk.Button(parent,text=text,command=command,style="Primary.TButton" if primary else "P.TButton")
        if help_text:self._tip.bind(button,help_text)
        return button

    def _icon(self,master,name,size=TRAIT_ICON_SIZE):
        key=(name,size)
        if key not in self._images:self._images[key]=tk_xray_icon(master,name,size)
        return self._images[key]

    def _help(self,text,*widgets):
        for widget in widgets:
            if widget is not None:self._tip.bind(widget,text)

    def _section_header(self,parent,number,icon_name,title,subtitle):
        header=ttk.Frame(parent);header.grid(row=0,column=0,sticky="ew",pady=(0,8));header.columnconfigure(2,weight=1)
        icon=ttk.Label(header,image=self._icon(header,icon_name,48));icon.grid(row=0,column=0,rowspan=2,sticky="w",padx=(0,10))
        number_label=ttk.Label(header,text=str(number),style="PageTitle.TLabel",width=2,anchor="center");number_label.grid(row=0,column=1,rowspan=2,sticky="ns",padx=(0,8))
        title_label=ttk.Label(header,text=title,style="SectionTitle.TLabel");title_label.grid(row=0,column=2,sticky="w")
        subtitle_label=ttk.Label(header,text=subtitle,style="Muted.TLabel",wraplength=940);subtitle_label.grid(row=1,column=2,sticky="w",pady=(2,0))
        self._help(subtitle,icon,number_label,title_label,subtitle_label)

    def _build(self):
        outer=ttk.Frame(self,padding=12);outer.pack(fill="both",expand=True);outer.columnconfigure(0,weight=1);outer.rowconfigure(5,weight=1)
        heading=ttk.Frame(outer);heading.grid(row=0,column=0,sticky="ew")
        ttk.Label(heading,text="Traits",style="PageTitle.TLabel").pack(side="left")
        ttk.Label(heading,text="First define what you mark on the X-ray. Then build biological traits from those annotations.",style="PageSubtitle.TLabel").pack(side="left",padx=(10,0),pady=(5,0))

        toolbar=ttk.Frame(outer);toolbar.grid(row=1,column=0,sticky="ew",pady=(8,8))
        set_menu=ttk.Menubutton(toolbar,text="Trait set ▾",style="P.TButton");set_menu.pack(side="left")
        menu=tk.Menu(set_menu,tearoff=False)
        menu.add_command(label="New",command=self._new_draft)
        menu.add_command(label="Open...",command=self._open_saved)
        menu.add_separator();menu.add_command(label="Save copy...",command=self._save_copy)
        set_menu.configure(menu=menu);set_menu._menu=menu
        self.apply_button=self._button(toolbar,"Use these traits for project",self._use_for_project,"Apply this trait set as a new project version. Changes are not saved until you choose this button.",True)
        self.apply_button.pack(side="right",padx=(8,0))
        self.appearance_button=self._button(toolbar,"Colors & keys...",self._edit_markers,"Optional: change only the color, marker shape, and number key used during X-ray annotation.")
        self.appearance_button.pack(side="right")

        scheme=ttk.LabelFrame(outer,text="Trait set",padding=8);scheme.grid(row=2,column=0,sticky="ew");scheme.columnconfigure(1,weight=1);scheme.columnconfigure(3,weight=1)
        name_label=ttk.Label(scheme,text="Name");name_label.grid(row=0,column=0,sticky="w")
        name_entry=ttk.Entry(scheme,textvariable=self.scheme_name);name_entry.grid(row=0,column=1,columnspan=3,sticky="ew",padx=(7,0))
        desc_label=ttk.Label(scheme,text="Description");desc_label.grid(row=1,column=0,sticky="w",pady=(5,0))
        desc_entry=ttk.Entry(scheme,textvariable=self.description);desc_entry.grid(row=1,column=1,columnspan=3,sticky="ew",padx=(7,0),pady=(5,0))
        ref_label=ttk.Label(scheme,text="Reference");ref_label.grid(row=2,column=0,sticky="w",pady=(5,0))
        ref_entry=ttk.Entry(scheme,textvariable=self.reference_label);ref_entry.grid(row=2,column=1,sticky="ew",padx=(7,12),pady=(5,0))
        doi_label=ttk.Label(scheme,text="DOI");doi_label.grid(row=2,column=2,sticky="w",pady=(5,0))
        doi_entry=ttk.Entry(scheme,textvariable=self.reference_doi,width=28);doi_entry.grid(row=2,column=3,sticky="ew",padx=(7,0),pady=(5,0))
        self._help("Name of this reusable set of biological traits.",name_label,name_entry)
        self._help("Optional short description of what this trait set measures.",desc_label,desc_entry)
        self._help("Optional literature citation in compact form, for example: Bogutskaya et al. (2020).",ref_label,ref_entry)
        self._help("Optional DOI for the cited work. The project view will make it clickable.",doi_label,doi_entry)

        ttk.Separator(outer,orient="horizontal").grid(row=3,column=0,sticky="ew",pady=8)

        step1=ttk.LabelFrame(outer,padding=10);step1.grid(row=4,column=0,sticky="ew",pady=(0,8));step1.columnconfigure(0,weight=1)
        self._section_header(
            step1,1,"annotation_setup","Define what you will mark on the X-ray",
            "Choose the repeated anatomical elements you will count and the single anatomical boundaries used as start or stop marks."
        )
        annotations=ttk.Frame(step1);annotations.grid(row=1,column=0,sticky="ew");annotations.columnconfigure(0,weight=1)
        self._build_annotation_lists(annotations)

        step2=ttk.LabelFrame(outer,padding=10);step2.grid(row=5,column=0,sticky="nsew");step2.columnconfigure(0,weight=1);step2.rowconfigure(1,weight=1)
        self._section_header(
            step2,2,"trait_setup","Build biological traits from those annotations",
            "Select a trait, choose a counting rule, and tell MorphoLabel which elements and start/stop marks from step 1 define its value."
        )
        body=ttk.Panedwindow(step2,orient="horizontal");body.grid(row=1,column=0,sticky="nsew")
        left=ttk.LabelFrame(body,text="Traits",padding=8);right=ttk.LabelFrame(body,text="Selected trait",padding=10);body.add(left,weight=2);body.add(right,weight=3)
        self._build_trait_list(left);self._build_trait_editor(right)

        actions=ttk.Frame(outer);actions.grid(row=6,column=0,sticky="ew",pady=(10,0))
        self._button(actions,"Close",self.destroy,"Close without applying this draft to the project.").pack(side="right")

    def _build_trait_list(self,parent):
        parent.columnconfigure(0,weight=1);parent.rowconfigure(0,weight=1)
        self.trait_tree=ttk.Treeview(parent,columns=("name","rule"),show="headings",selectmode="browse",height=9)
        for key,label,width,stretch in (("name","Trait",220,True),("rule","Counting rule",205,True)):
            self.trait_tree.heading(key,text=label);self.trait_tree.column(key,width=width,anchor="w",stretch=stretch)
        scroll=ttk.Scrollbar(parent,orient="vertical",command=self.trait_tree.yview);self.trait_tree.configure(yscrollcommand=scroll.set)
        self.trait_tree.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")
        self.trait_tree.bind("<<TreeviewSelect>>",self._trait_selected);self.trait_tree.bind("<Double-1>",self._trait_double_click)
        self._help("The biological output values you want to obtain. Select one to define how it is counted.",self.trait_tree)
        row=ttk.Frame(parent);row.grid(row=1,column=0,columnspan=2,sticky="w",pady=(7,0))
        self._button(row,"+ Add trait",self._new_trait,"Add a biological result such as Total vertebrae or Abdominal vertebrae.").pack(side="left")
        self._button(row,"Remove",self._remove_trait,"Remove the selected trait from this draft; earlier project versions remain stored.").pack(side="left",padx=(4,0))

    def _build_annotation_lists(self,parent):
        parent.columnconfigure(0,weight=1);parent.columnconfigure(1,weight=1);parent.rowconfigure(1,weight=1)
        counted=ttk.LabelFrame(parent,text="Elements to count",padding=6);counted.grid(row=0,column=0,rowspan=2,sticky="nsew",padx=(0,4))
        refs=ttk.LabelFrame(parent,text="Start / stop marks",padding=6);refs.grid(row=0,column=1,rowspan=2,sticky="nsew",padx=(4,0))
        for frame in (counted,refs):frame.columnconfigure(0,weight=1);frame.rowconfigure(1,weight=1)

        ch=ttk.Frame(counted);ch.grid(row=0,column=0,sticky="ew",pady=(0,4))
        ttk.Label(ch,image=self._icon(ch,"counted_element",30)).pack(side="left",padx=(0,5))
        counted_help=ttk.Label(ch,text="Repeated anatomical elements",style="Muted.TLabel");counted_help.pack(side="left")
        self.counted_tree=ttk.Treeview(counted,show="tree",selectmode="browse",height=4);self.counted_tree.grid(row=1,column=0,sticky="nsew")
        counted_actions=ttk.Frame(counted);counted_actions.grid(row=2,column=0,sticky="w",pady=(5,0))
        self._button(counted_actions,"+ Add",lambda:self._add_structure(True),"Add something you will click repeatedly and count on the X-ray, for example Vertebrae.").pack(side="left")
        self._button(counted_actions,"Rename",lambda:self._rename_structure(True),"Rename the selected counted element.").pack(side="left",padx=(4,0))
        self._button(counted_actions,"Remove",lambda:self._remove_structure(True),"Remove the selected counted element if no trait or saved annotation uses it.").pack(side="left",padx=(4,0))
        self.counted_tree.bind("<Double-1>",lambda _e:self._rename_structure(True))
        self._help("Step 1A. Add the repeated anatomical elements you will click and count on each X-ray, for example vertebrae or pterygiophores.",counted_help,self.counted_tree)

        rh=ttk.Frame(refs);rh.grid(row=0,column=0,sticky="ew",pady=(0,4))
        ttk.Label(rh,image=self._icon(rh,"reference_mark",30)).pack(side="left",padx=(0,5))
        ref_help=ttk.Label(rh,text="Single anatomical boundaries",style="Muted.TLabel");ref_help.pack(side="left")
        self.reference_tree=ttk.Treeview(refs,show="tree",selectmode="browse",height=4);self.reference_tree.grid(row=1,column=0,sticky="nsew")
        ref_actions=ttk.Frame(refs);ref_actions.grid(row=2,column=0,sticky="w",pady=(5,0))
        self._button(ref_actions,"+ Add",lambda:self._add_structure(False),"Add one anatomical boundary that can be used to start or stop counting, for example First caudal vertebra.").pack(side="left")
        self._button(ref_actions,"Rename",lambda:self._rename_structure(False),"Rename the selected reference mark.").pack(side="left",padx=(4,0))
        self._button(ref_actions,"Remove",lambda:self._remove_structure(False),"Remove the selected reference mark if no trait or saved annotation uses it.").pack(side="left",padx=(4,0))
        self.reference_tree.bind("<Double-1>",lambda _e:self._rename_structure(False))
        self._help("Step 1B. Add the single anatomical boundaries that can start or stop a count, for example the first caudal vertebra.",ref_help,self.reference_tree)

    def _field_row(self,parent,row,icon_name,label_text,variable,help_text,values=(),readonly=True):
        icon=ttk.Label(parent,image=self._icon(parent,icon_name,22));icon.grid(row=row,column=0,sticky="w",pady=(7,0))
        label=ttk.Label(parent,text=label_text);label.grid(row=row,column=1,sticky="w",pady=(7,0),padx=(4,0))
        widget=ttk.Combobox(parent,textvariable=variable,values=values,state="readonly" if readonly else "normal")
        widget.grid(row=row,column=2,columnspan=2,sticky="ew",padx=(7,0),pady=(7,0))
        self._help(help_text,icon,label,widget)
        return widget,label,icon

    def _build_trait_editor(self,parent):
        parent.columnconfigure(2,weight=1);parent.columnconfigure(3,weight=1)
        name_label=ttk.Label(parent,text="Name");name_label.grid(row=0,column=0,sticky="w")
        self.trait_name_entry=ttk.Entry(parent,textvariable=self.trait_name);self.trait_name_entry.grid(row=0,column=1,columnspan=2,sticky="ew",padx=(7,10))
        abbr_label=ttk.Label(parent,text="Abbreviation");abbr_label.grid(row=0,column=3,sticky="e")
        abbr_entry=ttk.Entry(parent,textvariable=self.trait_abbr,width=12);abbr_entry.grid(row=0,column=4,sticky="ew",padx=(7,0))
        self._help("Biological name of the output value, for example Abdominal vertebrae.",name_label,self.trait_name_entry)
        self._help("Short column name used in results and export, for example abdV.",abbr_label,abbr_entry)

        method_label=ttk.Label(parent,text="Counting rule");method_label.grid(row=1,column=0,columnspan=2,sticky="w",pady=(8,0))
        self.method_combo=ttk.Combobox(parent,textvariable=self.trait_method,values=tuple(METHOD_ID_TO_LABEL[item] for item in EDITOR_METHOD_IDS),state="readonly")
        self.method_combo.grid(row=1,column=2,columnspan=3,sticky="ew",padx=(7,0),pady=(8,0));self.method_combo.bind("<<ComboboxSelected>>",lambda _e:self._refresh_method_fields())
        self._help("Choose one simple rule: count all elements, count to a reference mark, count between two reference marks, or calculate from other traits.",method_label,self.method_combo)

        self.annotation_frame=ttk.LabelFrame(parent,text="Counting on the X-ray",padding=8);self.annotation_frame.grid(row=2,column=0,columnspan=5,sticky="ew",pady=(10,0))
        self.annotation_frame.columnconfigure(2,weight=1);self.annotation_frame.columnconfigure(3,weight=1)
        self.object_combo,self.object_label,self.object_icon=self._field_row(
            self.annotation_frame,0,"counted_element","Element to count",self.trait_object,
            "Choose one of the Elements to count defined in step 1. This is the repeated anatomical structure that contributes to the trait.",
        )
        self.reference_combo,self.reference_label_widget,self.reference_icon=self._field_row(
            self.annotation_frame,1,"reference_mark","Stop at",self.trait_reference,
            "Choose one of the Start / stop marks defined in step 1. Counting stops at this anatomical boundary.",
        )
        self.reference2_combo,self.reference2_label_widget,self.reference2_icon=self._field_row(
            self.annotation_frame,2,"reference_mark","Second reference",self.trait_reference2,
            "Choose the second Start / stop mark from step 1 when the trait is counted between two anatomical boundaries.",
        )

        self.count_options=ttk.Frame(self.annotation_frame);self.count_options.grid(row=3,column=0,columnspan=4,sticky="ew",pady=(8,0));self.count_options.columnconfigure(4,weight=1)
        offset_label=ttk.Label(self.count_options,text="Add fixed number");offset_label.grid(row=0,column=0,sticky="w")
        self.offset_entry=ttk.Entry(self.count_options,textvariable=self.trait_offset,width=7);self.offset_entry.grid(row=0,column=1,sticky="w",padx=(7,16))
        self._help("Optional correction added after counting, for example known vertebrae that are not clicked individually. Leave blank for zero.",offset_label,self.offset_entry)
        self.stop_behavior_label=ttk.Label(self.count_options,text="At the stop mark");self.stop_behavior_label.grid(row=0,column=2,sticky="w")
        self.stop_behavior_combo=ttk.Combobox(self.count_options,textvariable=self.trait_stop_behavior,values=tuple(STOP_BEHAVIOR_VALUES),state="readonly",width=22)
        self.stop_behavior_combo.grid(row=0,column=3,columnspan=2,sticky="ew",padx=(7,0));self.stop_behavior_combo.bind("<<ComboboxSelected>>",lambda _e:self._refresh_rule_preview())
        self._help("Choose whether the stop mark itself belongs to the count, or whether counting begins from it.",self.stop_behavior_label,self.stop_behavior_combo)

        self.derived_frame=ttk.LabelFrame(parent,text="Calculation",padding=8);self.derived_frame.grid(row=3,column=0,columnspan=5,sticky="ew",pady=(10,0));self.derived_frame.columnconfigure(1,weight=1)
        formula_label=ttk.Label(self.derived_frame,text="Formula");formula_label.grid(row=0,column=0,sticky="w")
        formula_entry=ttk.Entry(self.derived_frame,textvariable=self.trait_expression);formula_entry.grid(row=0,column=1,sticky="ew",padx=(7,0))
        deps_label=ttk.Label(self.derived_frame,text="Uses traits");deps_label.grid(row=1,column=0,sticky="w",pady=(6,0))
        deps_entry=ttk.Entry(self.derived_frame,textvariable=self.trait_depends);deps_entry.grid(row=1,column=1,sticky="ew",padx=(7,0),pady=(6,0))
        self._help("Expression used to calculate this value from other traits.",formula_label,formula_entry)
        self._help("Comma-separated abbreviations of traits used by the formula.",deps_label,deps_entry)

        preview=ttk.LabelFrame(parent,text="What this rule means",padding=6);preview.grid(row=4,column=0,columnspan=5,sticky="ew",pady=(10,0))
        self.preview_label=ttk.Label(preview);self.preview_label.pack(anchor="center")
        self._help("Blue-highlighted bones contribute to the value. Green markers show anatomical boundaries.",preview,self.preview_label)
        for widget in (self.object_combo,self.reference_combo,self.reference2_combo):
            widget.bind("<<ComboboxSelected>>",lambda _e:self._refresh_rule_preview(),add="+")
        self.save_trait_button=self._button(parent,"Save trait",self._update_trait,"Save changes to the selected biological trait.",True)
        self.save_trait_button.grid(row=5,column=4,sticky="e",pady=(12,0))

    def _capture_scheme_fields(self):
        name=self.scheme_name.get().strip()
        if not name:raise ValueError("Enter a trait set name.")
        candidate=deepcopy(self.scheme);candidate["name"]=name;candidate["description"]=self.description.get().strip()
        candidate["reference"]=_clean_reference(self.reference_label.get(),self.reference_doi.get(),self.reference_note.get())
        self.scheme=normalize_scheme(candidate)

    def _load_scheme(self,scheme,note):
        self.scheme=deepcopy(normalize_scheme(scheme));self.note=str(note or "Edited in MorphoLabel")
        self.scheme_name.set(self.scheme.get("name",""));self.description.set(self.scheme.get("description",""))
        ref=self.scheme.get("reference") or {};self.reference_label.set(ref.get("label",""));self.reference_doi.set(ref.get("doi",""));self.reference_note.set(ref.get("note",""))
        self._refresh_all()

    def _new_draft(self):
        self._load_scheme(blank_scheme(),"Created in MorphoLabel")

    def _open_saved(self):
        path=filedialog.askopenfilename(parent=self,title="Open trait set",initialdir=str(SCHEME_RESOURCE_DIR),filetypes=(("MorphoLabel trait set","*.json"),("All files","*.*")))
        if not path:return
        try:self._load_scheme(load_scheme_file(path),f"Opened trait set: {Path(path).name}")
        except Exception as exc:messagebox.showerror("Open trait set",str(exc),parent=self)

    def _save_copy(self):
        try:self._capture_scheme_fields()
        except Exception as exc:messagebox.showerror("Save trait set",str(exc),parent=self);return
        safe=_safe_id(self.scheme.get("name","xray_traits"),"xray_traits")
        path=filedialog.asksaveasfilename(parent=self,title="Save trait set copy",initialfile=safe+".json",defaultextension=".json",filetypes=(("MorphoLabel trait set","*.json"),))
        if not path:return
        try:save_scheme_file(self.scheme,path)
        except Exception as exc:messagebox.showerror("Save trait set",str(exc),parent=self);return
        messagebox.showinfo("Save trait set","Copy saved.",parent=self)

    def _structure_names(self,repeated):
        return [item["name"] for item in self.scheme.get("structures",()) if bool(item.get("repeated"))==bool(repeated)]

    def _refresh_annotation_lists(self,select_id=None):
        self.counted_tree.delete(*self.counted_tree.get_children());self.reference_tree.delete(*self.reference_tree.get_children())
        counted_icon=self._icon(self.counted_tree,"counted_element",20);ref_icon=self._icon(self.reference_tree,"reference_mark",20)
        for item in self.scheme.get("structures",()):
            tree=self.counted_tree if item.get("repeated") else self.reference_tree
            tree.insert("","end",iid=item["id"],text=item["name"],image=counted_icon if item.get("repeated") else ref_icon)
        if select_id:
            for tree in (self.counted_tree,self.reference_tree):
                if tree.exists(select_id):tree.selection_set(select_id);tree.focus(select_id);tree.see(select_id)
        counted=self._structure_names(True);refs=self._structure_names(False)
        self.object_combo.configure(values=counted);self.reference_combo.configure(values=refs);self.reference2_combo.configure(values=refs)

    def _selected_structure_id(self,repeated):
        tree=self.counted_tree if repeated else self.reference_tree
        selected=tree.selection();return selected[0] if selected else None

    def _add_structure(self,repeated):
        title="Add element to count" if repeated else "Add start / stop mark"
        prompt="Name of the repeated anatomical element:" if repeated else "Name of the anatomical start / stop boundary:"
        name=simpledialog.askstring(title,prompt,parent=self)
        if not name or not name.strip():return
        candidate=deepcopy(self.scheme)
        if any(item["name"].strip().casefold()==name.strip().casefold() for item in candidate.get("structures",())):
            messagebox.showinfo(title,"An X-ray annotation with this name already exists.",parent=self);return
        item=_default_structure(candidate,name.strip(),repeated);candidate["structures"].append(item)
        try:self.scheme=normalize_scheme(candidate)
        except Exception as exc:messagebox.showerror(title,str(exc),parent=self);return
        self._refresh_annotation_lists(item["id"]);self._refresh_rule_preview();self.appearance_button.state(["!disabled"])

    def _rename_structure(self,repeated):
        ident=self._selected_structure_id(repeated)
        if not ident:return
        item=next((x for x in self.scheme.get("structures",()) if x["id"]==ident),None)
        if item is None:return
        title="Rename element to count" if repeated else "Rename start / stop mark"
        name=simpledialog.askstring(title,"Name:",initialvalue=item["name"],parent=self)
        if not name or not name.strip() or name.strip()==item["name"]:return
        if any(x["id"]!=ident and x["name"].strip().casefold()==name.strip().casefold() for x in self.scheme.get("structures",())):
            messagebox.showinfo(title,"An X-ray annotation with this name already exists.",parent=self);return
        candidate=deepcopy(self.scheme);next(x for x in candidate["structures"] if x["id"]==ident)["name"]=name.strip()
        self.scheme=normalize_scheme(candidate);self._refresh_annotation_lists(ident)
        if self._editing_trait_id:self._load_trait(self._editing_trait_id)

    def _remove_structure(self,repeated):
        ident=self._selected_structure_id(repeated)
        if not ident:return
        item=next((x for x in self.scheme.get("structures",()) if x["id"]==ident),None)
        if item is None:return
        users=[trait["name"] for trait in self.scheme.get("traits",()) if ident in trait.get("structures",())]
        if users:
            messagebox.showinfo("Cannot remove",f"‘{item['name']}’ is used by: "+", ".join(users)+".\n\nChange those traits first.",parent=self);return
        if int(self.annotation_counts.get(ident,0) or 0)>0:
            messagebox.showinfo("Cannot remove",f"‘{item['name']}’ already has saved annotations. It is kept to preserve project history.",parent=self);return
        if not messagebox.askyesno("Remove X-ray annotation",f"Remove ‘{item['name']}’?",parent=self):return
        candidate=deepcopy(self.scheme);candidate["structures"]=[x for x in candidate["structures"] if x["id"]!=ident]
        self.scheme=normalize_scheme(candidate);self._refresh_annotation_lists();self._refresh_rule_preview()

    def _refresh_all(self):
        self._refresh_trait_tree();self._refresh_annotation_lists()
        traits=self.scheme.get("traits",())
        if traits:
            first=traits[0]["id"];self.trait_tree.selection_set(first);self.trait_tree.focus(first);self._load_trait(first)
        else:self._new_trait()
        self.appearance_button.state(["!disabled"] if self.scheme.get("structures") else ["disabled"])

    def _refresh_trait_tree(self,select_id=None):
        self.trait_tree.delete(*self.trait_tree.get_children())
        for trait in self.scheme.get("traits",()):
            self.trait_tree.insert("","end",iid=trait["id"],values=(trait["name"],_trait_rule_summary(self.scheme,trait)))
        if select_id and self.trait_tree.exists(select_id):
            self.trait_tree.selection_set(select_id);self.trait_tree.focus(select_id);self.trait_tree.see(select_id)

    def _trait_selected(self,_event=None):
        selected=self.trait_tree.selection()
        if selected:self._load_trait(selected[0])

    def _trait_double_click(self,event):
        row=self.trait_tree.identify_row(event.y)
        if row:self.trait_tree.selection_set(row);self._load_trait(row);self.trait_name_entry.focus_set();self.trait_name_entry.selection_range(0,"end")

    def _new_trait(self):
        self._editing_trait_id=None
        for item in self.trait_tree.selection():self.trait_tree.selection_remove(item)
        self.trait_name.set("");self.trait_abbr.set("");self.trait_method.set(METHOD_ID_TO_LABEL["count"])
        self.trait_object.set("");self.trait_reference.set("");self.trait_reference2.set("");self.trait_offset.set("");self.trait_stop_behavior.set("")
        self.trait_expression.set("");self.trait_depends.set("");self._refresh_method_fields();self.trait_name_entry.focus_set()

    def _load_trait(self,trait_id):
        trait=next((item for item in self.scheme.get("traits",()) if item["id"]==trait_id),None)
        if trait is None:return
        self._editing_trait_id=trait_id;self.trait_name.set(trait["name"]);self.trait_abbr.set(trait.get("abbr") or "")
        method_id=trait["method"];self.trait_method.set(METHOD_ID_TO_LABEL[method_id] if method_id in EDITOR_METHOD_IDS else METHOD_ID_TO_LABEL["count"])
        structures={item["id"]:item for item in self.scheme.get("structures",())};ids=list(trait.get("structures",()))
        self.trait_object.set(structures.get(ids[0],{}).get("name","") if ids else "")
        self.trait_reference.set(structures.get(ids[1],{}).get("name","") if len(ids)>1 else "")
        self.trait_reference2.set(structures.get(ids[2],{}).get("name","") if len(ids)>2 else "")
        rule=trait.get("rule") or {};self.trait_offset.set("" if "offset" not in rule else str(rule.get("offset")))
        self.trait_stop_behavior.set(STOP_BEHAVIOR_LABELS.get(rule.get("side"),""))
        self.trait_expression.set(str(rule.get("expression") or ""));abbr={item["id"]:item.get("abbr") or item["id"] for item in self.scheme.get("traits",())};self.trait_depends.set(", ".join(abbr.get(dep,dep) for dep in (rule.get("depends_on") or ())))
        self._refresh_method_fields()

    def _show_reference_row(self,show,second=False):
        widgets=(self.reference2_icon,self.reference2_label_widget,self.reference2_combo) if second else (self.reference_icon,self.reference_label_widget,self.reference_combo)
        for widget in widgets:
            if show:widget.grid()
            else:widget.grid_remove()

    def _refresh_method_fields(self):
        method_id=METHOD_LABEL_TO_ID.get(self.trait_method.get(),"count")
        if method_id not in EDITOR_METHOD_IDS:method_id="count"
        if method_id=="derived":
            self.annotation_frame.grid_remove();self.derived_frame.grid()
        else:
            self.derived_frame.grid_remove();self.annotation_frame.grid();self.object_label.configure(text="Element to count")
            self._show_reference_row(method_id in {"count_to","count_between"})
            self._show_reference_row(method_id=="count_between",second=True)
            if method_id=="count_to":self.reference_label_widget.configure(text="Stop at")
            elif method_id=="count_between":
                self.reference_label_widget.configure(text="Start at");self.reference2_label_widget.configure(text="Stop at")
            self.count_options.grid();self.offset_entry.grid()
            if method_id=="count_to":
                self.stop_behavior_label.grid();self.stop_behavior_combo.grid()
                if not self.trait_stop_behavior.get():self.trait_stop_behavior.set(STOP_BEHAVIOR_LABELS["before"])
            else:
                self.stop_behavior_label.grid_remove();self.stop_behavior_combo.grid_remove();self.trait_stop_behavior.set("")
        self._refresh_rule_preview()

    def _structure_id_by_name(self,name,repeated):
        wanted=str(name or "").strip().casefold()
        for item in self.scheme.get("structures",()):
            if bool(item.get("repeated"))==bool(repeated) and item["name"].strip().casefold()==wanted:return item["id"]
        return None

    def _update_trait(self):
        name=self.trait_name.get().strip();abbr=self.trait_abbr.get().strip() or _safe_id(name,"trait")
        if not name:messagebox.showinfo("Trait","Enter the biological trait name.",parent=self);return False
        method_id=METHOD_LABEL_TO_ID.get(self.trait_method.get(),"count")
        if method_id not in EDITOR_METHOD_IDS:method_id="count"
        candidate=deepcopy(self.scheme);old=next((item for item in candidate.get("traits",()) if item["id"]==self._editing_trait_id),None)
        if old is None:
            trait_id=_safe_id(abbr,"trait");used={item["id"] for item in candidate.get("traits",())};base=trait_id;index=2
            while trait_id in used:trait_id=f"{base}_{index}";index+=1
        else:trait_id=old["id"]
        rule=deepcopy(old.get("rule") or {}) if old and old.get("method")==method_id else {};structures=[]
        try:
            if method_id=="derived":
                rule["expression"]=self.trait_expression.get().strip();tokens=[part.strip() for part in self.trait_depends.get().split(",") if part.strip()]
                lookup={}
                for item in candidate.get("traits",()):
                    if item["id"]==trait_id:continue
                    lookup[item["id"].casefold()]=item["id"];lookup[(item.get("abbr") or item["id"]).casefold()]=item["id"]
                missing=[token for token in tokens if token.casefold() not in lookup]
                if missing:raise ValueError("Unknown dependency: "+", ".join(missing))
                rule["depends_on"]=[lookup[token.casefold()] for token in tokens];rule.pop("reference",None);rule.pop("reference_end",None)
            else:
                object_id=self._structure_id_by_name(self.trait_object.get(),True)
                if object_id is None:raise ValueError("Choose an Element to count from step 1.")
                structures=[object_id]
                if method_id=="count_to":
                    reference_id=self._structure_id_by_name(self.trait_reference.get(),False)
                    if reference_id is None:raise ValueError("Choose a Stop at mark from step 1.")
                    structures.append(reference_id);rule["reference"]=reference_id;rule.pop("reference_end",None)
                    side=STOP_BEHAVIOR_VALUES.get(self.trait_stop_behavior.get(),"before");rule["side"]=side
                elif method_id=="count_between":
                    start_id=self._structure_id_by_name(self.trait_reference.get(),False);stop_id=self._structure_id_by_name(self.trait_reference2.get(),False)
                    if start_id is None or stop_id is None:raise ValueError("Choose both Start / stop marks from step 1.")
                    if start_id==stop_id:raise ValueError("Start and stop reference marks must be different.")
                    structures.extend((start_id,stop_id));rule["reference"]=start_id;rule["reference_end"]=stop_id;rule.pop("side",None)
                else:
                    rule.pop("reference",None);rule.pop("reference_end",None);rule.pop("side",None)
                text=self.trait_offset.get().strip()
                if text:rule["offset"]=int(text)
                else:rule.pop("offset",None)
            replacement={"id":trait_id,"name":name,"abbr":abbr,"method":method_id,"structures":structures,"rule":rule}
            if old is None:candidate["traits"].append(replacement)
            else:
                pos=next(i for i,item in enumerate(candidate["traits"]) if item["id"]==trait_id);candidate["traits"][pos]=replacement
            self.scheme=normalize_scheme(candidate)
        except Exception as exc:messagebox.showerror("Trait",str(exc),parent=self);return False
        self._refresh_trait_tree(trait_id);self._refresh_annotation_lists();self._load_trait(trait_id);return True

    def _refresh_rule_preview(self):
        method_id=METHOD_LABEL_TO_ID.get(self.trait_method.get(),"count")
        if method_id not in EDITOR_METHOD_IDS:method_id="count"
        side=STOP_BEHAVIOR_VALUES.get(self.trait_stop_behavior.get(),"before")
        obj=self.trait_object.get().strip() or "counted element";ref=self.trait_reference.get().strip() or "reference mark";ref2=self.trait_reference2.get().strip() or "second reference"
        self._preview_image=tk_rule_preview(self.preview_label,method_id,side,obj,ref,ref2,(430,150));self.preview_label.configure(image=self._preview_image)

    def _remove_trait(self):
        selected=self.trait_tree.selection()
        if not selected:return
        trait_id=selected[0];trait=next(item for item in self.scheme["traits"] if item["id"]==trait_id)
        if not messagebox.askyesno("Remove trait",f"Remove ‘{trait['name']}’ from this trait set?\n\nExisting project data remains in earlier versions.",parent=self):return
        candidate=deepcopy(self.scheme);candidate["traits"]=[item for item in candidate["traits"] if item["id"]!=trait_id]
        self.scheme=normalize_scheme(candidate);self._refresh_all()

    def _edit_markers(self):
        dialog=MarkerSettingsDialog(self,self.scheme);self.wait_window(dialog)
        if dialog.result is None:return
        self.scheme=dialog.result;self._refresh_annotation_lists()
        if self._editing_trait_id:self._load_trait(self._editing_trait_id)

    def _use_for_project(self):
        try:self._capture_scheme_fields()
        except Exception as exc:messagebox.showerror("Traits",str(exc),parent=self);return
        self.result=(deepcopy(self.scheme),self.note);self.destroy()
