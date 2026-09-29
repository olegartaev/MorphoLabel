"""Built-in X-ray traits module with a trait-first workflow."""
from __future__ import annotations

from copy import deepcopy
import json
import re
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk
import webbrowser

from app.ui.tooltips import Tooltip
from app.xray_icons import XRAY_ICON_SIZE,TRAIT_ICON_SIZE,tk_xray_icon
from app.xray_project import XRayProject
from app.xray_schema import (
    MARKER_COLORS,METHOD_BY_ID,SHAPES,TRAIT_METHODS,blank_scheme,normalize_scheme,
    load_scheme_file,phoxinus_vertebral_preset,preset_catalog,preset_scheme,save_scheme_file,scheme_change_impact,structure_usage,
)

STAGES=(
    ("project","Project","xray_project"),("crops","Crops","xray_crops"),
    ("structures","Structures","xray_structures"),("results","Results","xray_results"),
    ("export","Export","xray_export"),
)

def _safe_id(text,prefix="item"):
    value=re.sub(r"[^a-z0-9]+","_",str(text).strip().lower()).strip("_");return value or prefix

class XRayCountsRuntime:
    def __init__(self):self.host=None;self.project=None;self.stage="project";self._images={};self._tip=None
    def close(self):self.host=None;self._images.clear();self._tip=None
    def render(self,host):
        self.host=host;parent=host.container
        for child in parent.winfo_children():child.destroy()
        self._images={};self._tip=Tooltip(parent.winfo_toplevel())
        outer=ttk.Frame(parent,padding=(10,7));outer.pack(fill="both",expand=True)
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
        ttk.Label(row,image=self._icon(row,"xray",32)).pack(side="left",padx=(0,7))
        ttk.Label(row,text="X-ray traits",style="PageTitle.TLabel").pack(side="left")
        if self.project:ttk.Label(row,text=f"  {self.project.name}",style="Muted.TLabel").pack(side="left",pady=(5,0))
        nav=ttk.Frame(parent,style="Topbar.TFrame");nav.pack(fill="x",pady=(7,0))
        for key,label,icon in STAGES:
            b=ttk.Button(nav,text=label,image=self._icon(nav,icon),compound="left",style="StageActive.TButton" if self.stage==key else "Stage.TButton",command=lambda k=key:self._select(k))
            if self.project is None and key!="project":b.state(["disabled"])
            b.pack(side="left",padx=(0,4))
    def _select(self,key):
        if self.project is None and key!="project":return
        self.stage=key;self._rerender()

    def _render_project(self,parent):
        ttk.Label(parent,text="Project",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Define the biological traits first. MorphoLabel then shows exactly what must be annotated.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,12))
        if self.project is None:
            card=ttk.LabelFrame(parent,text="Start",padding=16);card.pack(fill="x",anchor="n")
            ttk.Label(card,text="New X-ray project",style="ModuleTitle.TLabel").pack(anchor="w")
            ttk.Label(card,text="A ready-made trait scheme is offered first; a blank scheme remains available for other organisms and characters.",style="Muted.TLabel",wraplength=920).pack(anchor="w",pady=(3,10))
            self._button(card,"New project",self._new_project,"Create a versioned X-ray project.",True,image=self._icon(card,"xray_project")).pack(side="left")
            self._button(card,"Open project",self._open_project,"Open an existing X-ray project.").pack(side="left",padx=(8,0));return

        scheme=self.project.scheme
        if not scheme.get("traits"):
            empty=ttk.LabelFrame(parent,text="Trait scheme",padding=18);empty.pack(fill="x")
            title=ttk.Frame(empty);title.pack(fill="x")
            ttk.Label(title,image=self._icon(title,"xray",42)).pack(side="left",padx=(0,12))
            words=ttk.Frame(title);words.pack(side="left",fill="x",expand=True)
            ttk.Label(words,text="No traits yet",style="ModuleTitle.TLabel").pack(anchor="w")
            ttk.Label(words,text="Apply a ready-made scheme or create traits from scratch. You can change the scheme later without deleting earlier project data.",style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=(2,0))
            actions=ttk.Frame(empty);actions.pack(fill="x",pady=(14,0))
            self._button(actions,"Apply scheme…",self._apply_preset,"Choose a built-in trait scheme.",True,image=self._icon(actions,"xray_structures")).pack(side="left")
            self._button(actions,"New scheme…",self._new_blank_scheme,"Create a new empty trait scheme.").pack(side="left",padx=(7,0))
            self._button(actions,"Open scheme file…",self._import_scheme,"Open a JSON trait scheme from disk.").pack(side="left",padx=(7,0))
            ttk.Label(empty,text=f"Current scheme: {scheme['name']} · {len(self.project.schema_history())} saved version(s)",style="Muted.TLabel").pack(anchor="w",pady=(12,0))
            return

        info=ttk.LabelFrame(parent,text="Trait scheme",padding=14);info.pack(fill="x")
        top=ttk.Frame(info);top.pack(fill="x")
        ttk.Label(top,image=self._icon(top,"xray_structures",34)).pack(side="left",padx=(0,8))
        ttk.Label(top,text=scheme["name"],style="ModuleTitle.TLabel").pack(side="left")
        actions=ttk.Frame(top);actions.pack(side="right")
        self._button(actions,"Apply scheme…",self._apply_preset,"Apply a built-in scheme as a new version.",image=self._icon(actions,"xray_project")).pack(side="left")
        self._button(actions,"Edit current scheme…",self._edit_scheme,"Edit the active scheme; earlier versions stay stored.",True).pack(side="left",padx=(6,0))
        self._button(actions,"New scheme…",self._new_blank_scheme,"Start a new scheme version without deleting earlier data.").pack(side="left",padx=(6,0))
        self._button(actions,"Open scheme file…",self._import_scheme,"Open a JSON scheme from disk.").pack(side="left",padx=(6,0))
        self._button(actions,"Save current as…",self._save_scheme_as,"Save the active scheme to a JSON file.").pack(side="left",padx=(6,0))
        ttk.Label(info,text=scheme.get("description",""),style="Muted.TLabel",wraplength=920).pack(anchor="w",pady=(5,8))
        for trait in scheme["traits"]:
            method=METHOD_BY_ID[trait["method"]];row=ttk.Frame(info);row.pack(fill="x",pady=2)
            icon=ttk.Label(row,image=self._icon(row,method["icon"],TRAIT_ICON_SIZE));icon.pack(side="left",padx=(0,7));self._tip.bind(icon,method["help"])
            ttk.Label(row,text=trait.get("abbr") or trait["name"],style="SectionTitle.TLabel",width=10).pack(side="left")
            ttk.Label(row,text=f"{trait['name']}  ·  {method['label']}",style="Muted.TLabel").pack(side="left")
        ref=scheme.get("reference") or {}
        if ref:
            row=ttk.Frame(info);row.pack(fill="x",pady=(9,0));ttk.Label(row,text="Reference:",style="Muted.TLabel").pack(side="left")
            link=ttk.Label(row,text=ref.get("label",""),foreground="#256d9e",cursor="hand2");link.pack(side="left",padx=(4,0))
            if ref.get("doi"):link.bind("<Button-1>",lambda _e:webbrowser.open("https://doi.org/"+ref["doi"]))
            self._tip.bind(link,ref.get("note",""))
        abbreviations=", ".join(item.get("abbr") or item["id"] for item in scheme["traits"])
        ttk.Label(info,text=f"Traits: {abbreviations}",style="Muted.TLabel",wraplength=1100).pack(anchor="w",pady=(9,0))
        ttk.Label(info,text=f"{len(scheme['traits'])} traits · {len(scheme['structures'])} structure groups · {len(self.project.schema_history())} scheme version(s)",style="Muted.TLabel").pack(anchor="w",pady=(3,0))

    def _render_crops(self,parent):
        ttk.Label(parent,text="Crops",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Separate specimens from X-ray plates before annotation.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,12))
        card=ttk.LabelFrame(parent,text="Source X-rays",padding=14);card.pack(fill="x")
        ttk.Label(card,text=f"{len(self.project.source_images())} source image(s) indexed",style="ModuleTitle.TLabel").pack(anchor="w")
        ttk.Label(card,text="The legacy automatic plate splitter will be connected here next. Originals remain read-only; crop corrections and exclusions will live in SQLite.",style="Muted.TLabel",wraplength=900).pack(anchor="w",pady=(4,0))

    def _render_structures(self,parent):
        ttk.Label(parent,text="Structures",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent,text="Annotate only the structures required by the selected traits.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
        scheme=self.project.scheme
        if not scheme.get("structures"):
            self._empty_scheme_state(parent,"No annotation structures","Choose or create traits first; MorphoLabel will derive the required annotation structures automatically.")
            return
        pane=ttk.Panedwindow(parent,orient="horizontal");pane.pack(fill="both",expand=True)
        canvas=ttk.LabelFrame(pane,text="X-ray",padding=12);tools=ttk.LabelFrame(pane,text="Annotation structures",padding=10);pane.add(canvas,weight=3);pane.add(tools,weight=1)
        ttk.Label(canvas,text="Specimen image / annotation canvas",style="Muted.TLabel").pack(expand=True)
        ttk.Label(tools,text="Current annotation",style="SectionTitle.TLabel").pack(anchor="w")
        active_row=ttk.Frame(tools);active_row.pack(fill="x",pady=(4,9))
        active_marker=tk.Label(active_row,text="●",font=("Segoe UI Symbol",16,"bold"),width=2)
        active_marker.pack(side="left")
        active=ttk.Label(active_row,text="",style="ModuleTitle.TLabel");active.pack(side="left",fill="x",expand=True)
        ttk.Label(tools,text="Choose a structure or press its number key. The selected tool stays active for repeated structures.",style="Muted.TLabel",wraplength=300).pack(anchor="w",pady=(0,7))
        buttons={};markers={}
        def choose(s):
            active.configure(text=f"{s['name']}   [{s.get('hotkey','')}]")
            active_marker.configure(text=self._shape_symbol(s),foreground=s.get("color","#256d9e"))
            for ident,b in buttons.items():b.configure(style="Primary.TButton" if ident==s["id"] else "P.TButton")
            for ident,m in markers.items():m.configure(font=("Segoe UI Symbol",15,"bold") if ident==s["id"] else ("Segoe UI Symbol",13,"bold"))
        for s in scheme["structures"]:
            row=ttk.Frame(tools);row.pack(fill="x",pady=2)
            marker=tk.Label(row,text=self._shape_symbol(s),foreground=s.get("color","#256d9e"),font=("Segoe UI Symbol",13,"bold"),width=2)
            marker.pack(side="left",padx=(0,4));markers[s["id"]]=marker
            b=self._button(row,f"[{s.get('hotkey','')}]  {s['name']}",lambda item=s:choose(item),s.get("description",""));b.pack(side="left",fill="x",expand=True);buttons[s["id"]]=b
            self._tip.bind(marker,s.get("description","") or f"Annotation structure: {s['name']}.")
            if s.get("hotkey"):tools.winfo_toplevel().bind(s["hotkey"],lambda _e,item=s:choose(item),add="+")
        if scheme["structures"]:choose(scheme["structures"][0])
        ttk.Separator(tools).pack(fill="x",pady=10)
        ttk.Label(tools,text="Manual repeatability",style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(tools,text="Annotation 1 and Annotation 2 will be independent saved passes, using the same logic as Landmarks.",style="Muted.TLabel",wraplength=300).pack(anchor="w",pady=(3,0))

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
        card=ttk.LabelFrame(parent,text="Trait scheme needed",padding=18);card.pack(fill="x",anchor="n")
        top=ttk.Frame(card);top.pack(fill="x")
        ttk.Label(top,image=self._icon(top,"xray",40)).pack(side="left",padx=(0,11))
        words=ttk.Frame(top);words.pack(side="left",fill="x",expand=True)
        ttk.Label(words,text=title,style="ModuleTitle.TLabel").pack(anchor="w")
        ttk.Label(words,text=text,style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=(2,0))
        actions=ttk.Frame(card);actions.pack(anchor="w",pady=(12,0))
        self._button(actions,"Apply scheme…",self._apply_preset,"Choose a ready-made trait scheme.",True,image=self._icon(actions,"xray_structures")).pack(side="left")
        self._button(actions,"Edit current scheme…",self._edit_scheme,"Create or edit the active trait scheme.").pack(side="left",padx=(7,0))

    def _apply_scheme_version(self,new_scheme,note,title):
        root=self.host.container.winfo_toplevel()
        try:new=normalize_scheme(new_scheme);old=normalize_scheme(self.project.scheme);impact=scheme_change_impact(old,new,self.project.annotation_counts_by_structure())
        except Exception as exc:messagebox.showerror(title,str(exc),parent=root);return False
        if old==new:
            messagebox.showinfo(title,"This scheme is already active.",parent=root);return False
        lines=[
            f"Use ‘{new['name']}’ as the active trait scheme?",
            "",
            "Existing project data and earlier scheme versions will be kept.",
            f"New scheme: {len(new['traits'])} traits · {len(new['structures'])} structure groups.",
        ]
        if impact["added_traits"]:lines.append(f"New traits: {len(impact['added_traits'])}.")
        if impact["archived_traits"]:lines.append(f"Current traits not used by the new scheme: {len(impact['archived_traits'])}.")
        if impact["affected_annotations"]:lines.append(f"{impact['affected_annotations']} existing annotation(s) remain stored with the earlier scheme version.")
        if not messagebox.askyesno(title,"\n".join(lines),parent=root,default="yes"):return False
        try:self.project.save_scheme(new,note)
        except Exception as exc:messagebox.showerror(title,str(exc),parent=root);return False
        self.stage="project";self._rerender();return True

    def _apply_preset(self):
        dialog=PresetDialog(self.host.container.winfo_toplevel());self.host.container.wait_window(dialog)
        if dialog.result is None:return
        if dialog.result=="open":return self._import_scheme()
        if dialog.result=="new":return self._new_blank_scheme()
        try:scheme=preset_scheme(dialog.result)
        except Exception as exc:messagebox.showerror("Apply preset",str(exc),parent=self.host.container.winfo_toplevel());return
        self._apply_scheme_version(scheme,f"Applied scheme: {scheme['name']}","Apply scheme")

    def _new_blank_scheme(self):
        root=self.host.container.winfo_toplevel()
        name=simpledialog.askstring("New trait scheme","Scheme name:",initialvalue="Untitled X-ray trait scheme",parent=root)
        if not name:return
        self._apply_scheme_version(blank_scheme(name),"Started a new blank trait scheme","New trait scheme")

    def _import_scheme(self):
        root=self.host.container.winfo_toplevel()
        path=filedialog.askopenfilename(parent=root,title="Open X-ray trait scheme",filetypes=(("JSON files","*.json"),("All files","*.*")))
        if not path:return
        try:
            scheme=load_scheme_file(path)
        except Exception as exc:messagebox.showerror("Open scheme file",f"Could not read this trait scheme.\n\n{exc}",parent=root);return
        self._apply_scheme_version(scheme,f"Opened scheme file: {scheme['name']}","Open scheme file")

    def _save_scheme_as(self):
        root=self.host.container.winfo_toplevel()
        path=filedialog.asksaveasfilename(parent=root,title="Save current scheme as",defaultextension=".json",filetypes=(("JSON files","*.json"),("All files","*.*")))
        if not path:return
        try:save_scheme_file(self.project.scheme,path)
        except Exception as exc:messagebox.showerror("Save scheme",f"Could not save this trait scheme.\n\n{exc}",parent=root);return
        messagebox.showinfo("Save scheme",f"Scheme saved to:\n{path}",parent=root)

    def _new_project(self):
        root=self.host.container.winfo_toplevel();name=simpledialog.askstring("New X-ray project","Project name:",parent=root)
        if not name:return
        source=filedialog.askdirectory(parent=root,title="Folder with X-ray images");dest=filedialog.askdirectory(parent=root,title="Folder where the X-ray project will be created")
        if not source or not dest:return
        choice=messagebox.askyesnocancel("Trait scheme","Start with the built-in Phoxinus vertebral-count scheme?\n\nYes = recommended starter scheme (7 traits)\nNo = blank custom scheme\n\nYou can apply another scheme later.",parent=root,default="yes")
        if choice is None:return
        try:self.project=XRayProject.create(name,source,dest,phoxinus_vertebral_preset() if choice else blank_scheme())
        except Exception as exc:messagebox.showerror("New X-ray project",str(exc),parent=root);return
        self.stage="project";self._rerender()
        if not choice:self._edit_scheme()
    def _open_project(self):
        root=self.host.container.winfo_toplevel();folder=filedialog.askdirectory(parent=root,title="Select X-ray project folder")
        if not folder:return
        try:self.project=XRayProject(folder)
        except Exception as exc:messagebox.showerror("Open X-ray project",str(exc),parent=root);return
        self.stage="project";self._rerender()
    def _edit_scheme(self):
        dialog=TraitSchemeDialog(self.host.container.winfo_toplevel(),self.project.scheme,self.project.annotation_counts_by_structure());self.host.container.wait_window(dialog)
        if dialog.result is None:return
        try:self.project.save_scheme(dialog.result,"Edited in Trait scheme")
        except Exception as exc:messagebox.showerror("Trait scheme",str(exc),parent=self.host.container.winfo_toplevel());return
        self._rerender()

class PresetDialog(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent);self.title("Trait schemes");self.transient(parent);self.resizable(False,False);self.result=None
        self._catalog=preset_catalog();self.choice=tk.StringVar(value=self._catalog[0]["id"] if self._catalog else "");self._build();self.grab_set()

    def _build(self):
        outer=ttk.Frame(self,padding=16);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Trait schemes",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(outer,text="Choose a scheme to apply. Earlier scheme versions and project data stay stored.",style="PageSubtitle.TLabel",wraplength=680).pack(anchor="w",pady=(2,12))
        for item in self._catalog:
            card=ttk.LabelFrame(outer,text=item["name"],padding=10);card.pack(fill="x",pady=(0,8))
            row=ttk.Frame(card);row.pack(fill="x")
            ttk.Radiobutton(row,text="Select scheme",variable=self.choice,value=item["id"]).pack(side="left")
            ttk.Label(row,text=f"{item['trait_count']} traits · {item['structure_count']} structure groups",style="Muted.TLabel").pack(side="right")
            ttk.Label(card,text=item["description"],style="Muted.TLabel",wraplength=650).pack(anchor="w",pady=(5,2))
            ttk.Label(card,text="Traits: "+", ".join(item["trait_abbrs"]),style="SectionTitle.TLabel").pack(anchor="w",pady=(3,0))
            ref=item.get("reference") or {}
            if ref:ttk.Label(card,text=ref.get("label",""),style="Muted.TLabel").pack(anchor="w",pady=(4,0))
        actions=ttk.Frame(outer);actions.pack(fill="x",pady=(6,0))
        ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="right")
        ttk.Button(actions,text="Apply",command=self._apply,style="Primary.TButton").pack(side="right",padx=(0,6))
        ttk.Button(actions,text="Open file…",command=lambda:self._close_with("open")).pack(side="right",padx=(0,6))
        ttk.Button(actions,text="New scheme…",command=lambda:self._close_with("new")).pack(side="right",padx=(0,6))

    def _apply(self):
        value=self.choice.get().strip()
        if not value:return
        self.result=value;self.destroy()

    def _close_with(self,value):
        self.result=value;self.destroy()


class TraitSchemeDialog(tk.Toplevel):
    def __init__(self,parent,scheme,annotation_counts):
        super().__init__(parent);self.title("Trait scheme");self.transient(parent);self.geometry("980x650");self.minsize(820,520)
        self.scheme=deepcopy(normalize_scheme(scheme));self.original=deepcopy(self.scheme);self.annotation_counts=dict(annotation_counts or {});self.result=None
        self._build();self.grab_set()
    def _build(self):
        outer=ttk.Frame(self,padding=14);outer.pack(fill="both",expand=True);outer.columnconfigure(0,weight=1);outer.rowconfigure(2,weight=1)
        ttk.Label(outer,text="Trait scheme",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text="Start with the biological trait. MorphoLabel records which annotation structures are needed to obtain it.",style="PageSubtitle.TLabel").grid(row=1,column=0,sticky="w",pady=(2,10))
        self.tree=ttk.Treeview(outer,columns=("abbr","method","structures"),show="headings")
        for key,label,width in (("abbr","Trait",120),("method","How obtained",230),("structures","What must be annotated",430)):self.tree.heading(key,text=label);self.tree.column(key,width=width,anchor="w",stretch=key=="structures")
        self.tree.grid(row=2,column=0,sticky="nsew")
        actions=ttk.Frame(outer);actions.grid(row=3,column=0,sticky="ew",pady=(10,0));ttk.Button(actions,text="Add trait…",command=self._add,style="Primary.TButton").pack(side="left");ttk.Button(actions,text="Remove / archive",command=self._remove).pack(side="left",padx=(6,0));ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="right");ttk.Button(actions,text="Apply changes",command=self._apply,style="Primary.TButton").pack(side="right",padx=(0,6));self._refresh()
    def _refresh(self):
        self.tree.delete(*self.tree.get_children());structures={x["id"]:x for x in self.scheme["structures"]}
        for t in self.scheme["traits"]:
            needed=", ".join(structures[s]["name"] for s in t.get("structures",()) if s in structures) or "No image annotation"
            self.tree.insert("","end",iid=t["id"],values=(t.get("abbr") or t["name"],METHOD_BY_ID[t["method"]]["label"],needed))
    def _add(self):
        w=TraitWizard(self,self.scheme);self.wait_window(w)
        if w.result is None:return
        trait,new_structures=w.result;self.scheme["structures"].extend(new_structures);self.scheme["traits"].append(trait);self._refresh()
    def _remove(self):
        selected=self.tree.selection()
        if not selected:return
        ident=selected[0];trait=next(x for x in self.scheme["traits"] if x["id"]==ident)
        if not messagebox.askyesno("Archive trait",f"Stop using ‘{trait['name']}’ in the new scheme version?\n\nExisting data and earlier scheme versions will be kept.",parent=self):return
        self.scheme["traits"]=[x for x in self.scheme["traits"] if x["id"]!=ident];usage=structure_usage(self.scheme)
        self.scheme["structures"]=[x for x in self.scheme["structures"] if usage.get(x["id"]) or int(self.annotation_counts.get(x["id"],0) or 0)>0];self._refresh()
    def _apply(self):
        try:new=normalize_scheme(self.scheme);impact=scheme_change_impact(self.original,new,self.annotation_counts)
        except Exception as exc:messagebox.showerror("Trait scheme",str(exc),parent=self);return
        lines=["Existing data will be kept."]
        if impact["added_traits"]:lines.append(f"New traits: {len(impact['added_traits'])}.")
        if impact["archived_traits"]:lines.append(f"Traits no longer used: {len(impact['archived_traits'])}.")
        if impact["added_structures"]:lines.append(f"New structure groups: {len(impact['added_structures'])}.")
        if impact["affected_annotations"]:lines.append(f"{impact['affected_annotations']} existing annotation(s) stay under the earlier scheme version.")
        if messagebox.askyesno("Scheme change","\n".join(lines)+"\n\nApply this new scheme version?",parent=self):self.result=new;self.destroy()

class TraitWizard(tk.Toplevel):
    def __init__(self,parent,scheme):
        super().__init__(parent);self.title("Add trait");self.transient(parent);self.resizable(False,False);self.scheme=scheme;self.result=None;self._images={};self._tip=Tooltip(self)
        self.name=tk.StringVar();self.abbr=tk.StringVar();self.method=tk.StringVar(value="count");self._build();self.grab_set()
    def _icon(self,name):
        if name not in self._images:self._images[name]=tk_xray_icon(self,name,TRAIT_ICON_SIZE)
        return self._images[name]
    def _build(self):
        outer=ttk.Frame(self,padding=16);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="What trait do you want to obtain?",style="PageTitle.TLabel").grid(row=0,column=0,columnspan=4,sticky="w")
        ttk.Label(outer,text="Trait name").grid(row=1,column=0,sticky="w",pady=(12,3));ttk.Entry(outer,textvariable=self.name,width=48).grid(row=2,column=0,columnspan=3,sticky="ew")
        ttk.Label(outer,text="Abbreviation").grid(row=1,column=3,sticky="w",padx=(8,0),pady=(12,3));ttk.Entry(outer,textvariable=self.abbr,width=14).grid(row=2,column=3,sticky="ew",padx=(8,0))
        ttk.Label(outer,text="How is this trait obtained?",style="SectionTitle.TLabel").grid(row=3,column=0,columnspan=4,sticky="w",pady=(14,5))
        for i,item in enumerate(TRAIT_METHODS):
            r,c=divmod(i,2);b=ttk.Radiobutton(outer,text=item["label"],value=item["id"],variable=self.method,image=self._icon(item["icon"]),compound="left",padding=(8,6));b.grid(row=4+r,column=c*2,columnspan=2,sticky="ew",padx=(0 if c==0 else 4,4 if c==0 else 0),pady=2);self._tip.bind(b,item["help"])
        actions=ttk.Frame(outer);actions.grid(row=8,column=0,columnspan=4,sticky="e",pady=(14,0));ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="left");ttk.Button(actions,text="Next",command=self._next,style="Primary.TButton").pack(side="left",padx=(6,0))
    def _next(self):
        name=self.name.get().strip();abbr=self.abbr.get().strip() or _safe_id(name,"trait")
        if not name:messagebox.showinfo("Add trait","Enter the biological trait name.",parent=self);return
        method=self.method.get();trait_id=_safe_id(abbr,"trait");used={x["id"] for x in self.scheme["traits"]};base=trait_id;i=2
        while trait_id in used:trait_id=f"{base}_{i}";i+=1
        if method=="derived":
            if not self.scheme["traits"]:messagebox.showinfo("Add trait","Add at least one directly observed trait first.",parent=self);return
            self.result=({"id":trait_id,"name":name,"abbr":abbr,"method":method,"structures":[],"rule":{"expression":"","depends_on":[]}},[]);self.destroy();return
        prompt="What anatomical object do you annotate?" if method in {"count","presence"} else "What repeated anatomical object do you count?" if method in {"count_to","count_between","position"} else "What anatomical reference do you annotate?"
        object_name=simpledialog.askstring("Annotation structure",prompt,parent=self)
        if not object_name:return
        existing=next((x for x in self.scheme["structures"] if x["name"].strip().casefold()==object_name.strip().casefold()),None);new=[];used_keys={str(x.get("hotkey","")) for x in self.scheme["structures"]}
        if existing is None:
            idx=len(self.scheme["structures"]);hotkey=next((str(n) for n in range(1,10) if str(n) not in used_keys),"")
            existing={"id":_safe_id(object_name,"structure"),"name":object_name.strip(),"annotation":"point","repeated":method in {"count","count_to","count_between","position"},"required":True,"hotkey":hotkey,"shape":SHAPES[idx%len(SHAPES)],"color":MARKER_COLORS[idx%len(MARKER_COLORS)],"description":""};new.append(existing)
        structures=[existing["id"]];rule={}
        if method in {"count_to","count_between","position","distance","angle"}:
            ref_name=simpledialog.askstring("Reference structure","What reference marks the boundary / position?",parent=self)
            if not ref_name:return
            reference=next((x for x in [*self.scheme["structures"],*new] if x["name"].strip().casefold()==ref_name.strip().casefold()),None)
            if reference is None:
                idx=len(self.scheme["structures"])+len(new);used_keys={str(x.get("hotkey","")) for x in [*self.scheme["structures"],*new]};hotkey=next((str(n) for n in range(1,10) if str(n) not in used_keys),"")
                reference={"id":_safe_id(ref_name,"reference"),"name":ref_name.strip(),"annotation":"point","repeated":False,"required":True,"hotkey":hotkey,"shape":SHAPES[idx%len(SHAPES)],"color":MARKER_COLORS[idx%len(MARKER_COLORS)],"description":""};new.append(reference)
            structures.append(reference["id"]);rule["reference"]=reference["id"]
        self.result=({"id":trait_id,"name":name,"abbr":abbr,"method":method,"structures":structures,"rule":rule},new);self.destroy()
