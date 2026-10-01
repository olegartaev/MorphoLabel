"""Interactive X-ray structure annotation workspace."""
from __future__ import annotations

import math
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from app.photo_list import PhotoListCanvas
from app.ui.icons import CONTROL_ICON_SIZE, tk_icon
from app.ui.photo_list_panel import filtered_photo_indices
from app.ui.tooltips import Tooltip
from .xray_crop import oriented_crop
from .xray_structure_display import (
    DEFAULT_LABEL_SIZE, DEFAULT_SIZE, SYMBOL_LABELS, SYMBOL_NAMES,
    draw_xray_marker, load_xray_structure_display, marker_style,
    normalize_xray_structure_display, save_xray_structure_display,
)


def _display_ready(image):
    arr=np.asarray(image)
    if arr.ndim==3:
        arr=(0.299*arr[...,0]+0.587*arr[...,1]+0.114*arr[...,2]) if arr.shape[-1]>=3 else arr[...,0]
    arr=np.asarray(arr,dtype=np.float32);finite=arr[np.isfinite(arr)]
    if not finite.size:return Image.new("L",image.size,0)
    lo=float(np.percentile(finite,0.5));hi=float(np.percentile(finite,99.5))
    if hi<=lo:hi=lo+1.0
    return Image.fromarray(np.clip((arr-lo)*255.0/(hi-lo),0,255).astype(np.uint8),"L")


def _shape_symbol(symbol):
    return {"circle":"○","filled_circle":"●","target":"⊙","cross":"✚","diamond":"◆","square":"■","triangle":"▲"}.get(symbol,"●")


def _structure_button_order(structures):
    """Display marker tools in explicit hotkey order; scheme order breaks ties."""
    indexed=list(enumerate(structures or ()))
    def key(item):
        index,structure=item;hotkey=str(structure.get("hotkey") or "").strip()
        return (0,int(hotkey),index) if hotkey.isdigit() else (1,index,index)
    return [structure for _index,structure in sorted(indexed,key=key)]


class XRaySpecimenListPanel(ttk.Frame):
    """Compact searchable specimen list matching Crop/Landmarks visual language."""

    def __init__(self,parent,project,on_select,tooltip):
        super().__init__(parent,padding=(7,5))
        self.project=project;self.on_select=on_select;self.tooltip=tooltip
        self.sample_query=tk.StringVar(master=self);self.specimen_query=tk.StringVar(master=self)
        self.selected_specimen_id=None;self.pass_no=1;self._rows=[];self.visible_indices=[];self._cache=()

        search=ttk.Frame(self,padding=(0,0,0,4));search.pack(fill="x");search.columnconfigure(0,weight=1);search.columnconfigure(1,weight=1)
        ttk.Label(search,text="Sample",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(search,text="Specimen",style="Muted.TLabel").grid(row=0,column=1,sticky="w",padx=(6,0))
        self.sample_entry=ttk.Entry(search,textvariable=self.sample_query);self.sample_entry.grid(row=1,column=0,sticky="ew",pady=(2,0))
        self.specimen_entry=ttk.Entry(search,textvariable=self.specimen_query);self.specimen_entry.grid(row=1,column=1,sticky="ew",padx=(6,0),pady=(2,0))
        tooltip.bind(self.sample_entry,"Find specimens by locality / source subfolder.")
        tooltip.bind(self.specimen_entry,"Find a specimen by plate filename or specimen label.")

        legend=ttk.Frame(self);legend.pack(fill="x",pady=(0,4))
        for color,text in (("#d93025"," not started"),("#e6a700"," draft"),("#188038"," verified")):
            square=tk.Canvas(legend,width=13,height=13,highlightthickness=0,bd=0)
            square.create_rectangle(2,2,10,10,fill="white",outline=color,width=3);square.pack(side="left")
            ttk.Label(legend,text=text,style="Muted.TLabel").pack(side="left",padx=(0,7))

        host=ttk.Frame(self);host.pack(fill="both",expand=True)
        self.canvas=PhotoListCanvas(host,height=24,bg="white",status_shape="square")
        scroll=ttk.Scrollbar(host,orient="vertical",command=self.canvas.yview);self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        self.canvas.bind("<<ListboxSelect>>",self._selected)
        for variable in (self.sample_query,self.specimen_query):variable.trace_add("write",lambda *_:self.refresh(preserve_scroll=True))

    @staticmethod
    def _sample(relative_path):
        parent=Path(str(relative_path)).parent.as_posix()
        return "Root" if parent in {"",".","/"} else parent

    def _catalog(self):
        rows=[]
        for row in self.project.structure_specimens(self.pass_no):
            status=str(row.get("annotation_status") or "")
            rows.append({
                **row,"sample_id":self._sample(row["relative_path"]),"source_relpath":row["relative_path"],
                "status_color":"green" if status=="verified" else "yellow" if status else "red",
            })
        return rows

    def _row_data(self,index,row):
        path=Path(str(row["relative_path"]));status=str(row.get("annotation_status") or "")
        tip="Verified structures" if status=="verified" else "Crop changed — annotate this specimen again" if status.startswith("stale") else "Saved draft — review required" if status else "Not started"
        return {
            "number":str(index+1),"cal":"","has_crop":True,"excluded":False,
            "text":f"{row['sample_id']} | {path.name} | №{int(row.get('ordinal') or 0)}",
            "status":row["status_color"],"tooltip":tip,"review_warning":False,
        }

    def refresh(self,preserve_scroll=False,reveal=False):
        self._rows=self._catalog()
        self._cache=tuple(
            (str(row["sample_id"]).casefold(),(str(row.get("label") or "")+" "+Path(str(row["relative_path"])).name).casefold())
            for row in self._rows
        )
        yview=self.canvas.yview()[0] if preserve_scroll and self.canvas.rows else None
        self.visible_indices=filtered_photo_indices(self._rows,self._cache,self.specimen_query.get(),self.sample_query.get(),show_excluded=True)
        self.canvas.set_rows([self._row_data(i,self._rows[i]) for i in self.visible_indices])
        selected_index=next((i for i,row in enumerate(self._rows) if row["specimen_id"]==self.selected_specimen_id),None)
        if selected_index in self.visible_indices:
            visible=self.visible_indices.index(selected_index);self.canvas.selection_set(visible)
            if reveal:self.canvas.see(visible,align_top=True)
        if yview is not None and not reveal:self.canvas.yview_moveto(yview)

    def select(self,specimen_id,reveal=True):
        self.selected_specimen_id=str(specimen_id or "");self.refresh(preserve_scroll=not reveal,reveal=reveal)

    def rows(self):return list(self._rows)
    def visible_ids(self):return [self._rows[index]["specimen_id"] for index in self.visible_indices]

    def _selected(self,_event=None):
        selection=self.canvas.curselection()
        if not selection:return
        visible=selection[0]
        if not 0<=visible<len(self.visible_indices):return
        row=self._rows[self.visible_indices[visible]]
        self.selected_specimen_id=row["specimen_id"];self.on_select(row["specimen_id"]);self.refresh(preserve_scroll=True)


class XRayStructureWorkspace:
    """Landmarks-style X-ray marker workspace with cached zoom/pan and finite batches."""

    def __init__(
        self,parent,project,on_changed=None,initial_image_id=None,initial_specimen_id=None,
        on_selection=None,on_open_results=None,
    ):
        self.parent=parent;self.root=parent.winfo_toplevel();self.project=project;self.on_changed=on_changed or (lambda:None)
        self.on_selection=on_selection or (lambda _image_id,_specimen_id:None);self.on_open_results=on_open_results or (lambda:None)
        self.tip=Tooltip(self.root);self.pass_no=tk.IntVar(value=1);self.batch_size=tk.IntVar(value=24)
        self.selected_specimen_id=str(initial_specimen_id or "");self.preferred_image_id=str(initial_image_id or "")
        self.active_structure_id=None;self.selected_annotation_id=None
        self.crop_image=None;self.photo=None;self.zoom=1.0;self.pan=None;self.pan_drag=None;self._raster_key=None;self._image_item=None
        self.annotations=[];self._drag_annotation=None;self._drag_last_screen=None;self._marker_buttons={};self._icons={}
        self.display_settings=load_xray_structure_display(self.project,self.project.scheme.get("structures",()))
        self._source_cache_id="";self._source_cache=None
        self._key_bind_id=None
        self._build();self._bind_keys();self.refresh()

    def _icon(self,master,name):
        key=(name,CONTROL_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_icon(master,name,CONTROL_ICON_SIZE)
        return self._icons[key]

    def _build(self):
        outer=ttk.Frame(self.parent,padding=(0,0));outer.pack(fill="both",expand=True);self.outer=outer
        outer.bind("<Destroy>",self._destroy,add="+")
        panes=ttk.Panedwindow(outer,orient="horizontal");panes.pack(fill="both",expand=True)
        left=ttk.Frame(panes);main=ttk.Frame(panes);panes.add(left,weight=0);panes.add(main,weight=1);self.panes=panes
        main.columnconfigure(0,weight=1);main.rowconfigure(1,weight=1)

        self.specimen_list=XRaySpecimenListPanel(left,self.project,self._list_selected,self.tip);self.specimen_list.pack(fill="both",expand=True)
        self.root.after_idle(self._set_initial_sash)

        header=ttk.Frame(main,style="Toolbar.TFrame");header.grid(row=0,column=0,sticky="ew",pady=(0,4));header.columnconfigure(1,weight=1)
        pass_host=ttk.Frame(header,style="Toolbar.TFrame");pass_host.grid(row=0,column=0,sticky="w")
        ttk.Label(pass_host,text="Manual pass").pack(side="left")
        self.pass_box=ttk.Combobox(pass_host,state="readonly",width=17,values=("1 · primary","2 · repeatability"))
        self.pass_box.current(0);self.pass_box.pack(side="left",padx=(5,8));self.pass_box.bind("<<ComboboxSelected>>",self._pass_changed)
        self.context_label=ttk.Label(header,text="",style="SectionTitle.TLabel",anchor="center");self.context_label.grid(row=0,column=1,sticky="ew",padx=10)
        nav=ttk.Frame(header,style="Toolbar.TFrame");nav.grid(row=0,column=2,sticky="e")
        self.previous_button=ttk.Button(nav,text="‹ Previous",style="Nav.TButton",command=lambda:self._navigate(-1));self.previous_button.pack(side="left")
        self.summary_label=ttk.Label(nav,text="",style="Muted.TLabel");self.summary_label.pack(side="left",padx=8)
        self.verify_button=ttk.Button(nav,text="Verify & Next ›",style="NavPrimary.TButton",image=self._icon(nav,"verify"),compound="left",command=self.verify_next)
        self.verify_button.pack(side="left")

        canvas_host=ttk.Frame(main);canvas_host.grid(row=1,column=0,sticky="nsew");canvas_host.pack_propagate(False)
        self.canvas=tk.Canvas(canvas_host,background="#202020",highlightthickness=0,takefocus=True,cursor="crosshair");self.canvas.pack(fill="both",expand=True)
        for event,handler in (
            ("<Configure>",lambda _e:self._draw()),
            ("<Button-1>",self._canvas_down),("<B1-Motion>",self._canvas_drag),("<ButtonRelease-1>",self._canvas_up),
            ("<Button-3>",self._pan_start),("<B3-Motion>",self._pan_motion),("<ButtonRelease-3>",self._pan_end),
            ("<Button-2>",self._pan_start),("<B2-Motion>",self._pan_motion),("<ButtonRelease-2>",self._pan_end),
            ("<MouseWheel>",self._wheel),
        ):self.canvas.bind(event,handler)
        self.canvas.bind("<Delete>",self.delete_selected);self.canvas.bind("<BackSpace>",self.delete_selected)

        marker_dock=ttk.Frame(main,style="WorkflowDock.TFrame",padding=(6,5));marker_dock.grid(row=2,column=0,sticky="ew",pady=(4,0));marker_dock.columnconfigure(1,weight=1)
        ttk.Label(marker_dock,text="Marker actions:",style="SectionTitle.TLabel").grid(row=0,column=0,sticky="w",padx=(0,6))
        self.marker_host=ttk.Frame(marker_dock,style="WorkflowDock.TFrame");self.marker_host.grid(row=0,column=1,sticky="ew")
        actions=ttk.Frame(marker_dock,style="WorkflowDock.TFrame");actions.grid(row=0,column=2,sticky="e")
        self.display_button=ttk.Button(actions,text="Display…",image=self._icon(actions,"display"),compound="left",style="Icon.TButton",command=self.open_display_settings)
        self.display_button.pack(side="left",padx=2);self.tip.bind(self.display_button,"Marker size, icons and colors. Mouse wheel zooms; right-drag pans; number keys switch markers; Delete removes the selected marker.")
        self.counts_label=ttk.Label(marker_dock,text="",style="Muted.TLabel");self.counts_label.grid(row=1,column=0,columnspan=3,sticky="w",pady=(4,0))
        self.save_label=ttk.Label(marker_dock,text="",style="Muted.TLabel");self.save_label.grid(row=1,column=2,sticky="e",pady=(4,0))

        workflow=ttk.Frame(main,style="WorkflowDock.TFrame",padding=(0,4,0,0));workflow.grid(row=3,column=0,sticky="ew")
        workflow.columnconfigure(0,weight=1);workflow.columnconfigure(1,weight=1);workflow.columnconfigure(2,weight=1);workflow.columnconfigure(3,weight=1)
        one=self._workflow_card(workflow,0,"1. Annotation batch","Work through a finite saved set with Verify & Next.")
        self.batch_summary=ttk.Label(one,text="",style="Muted.TLabel");self.batch_summary.grid(row=0,column=0,columnspan=3,sticky="w")
        ttk.Label(one,text="Batch").grid(row=1,column=0,sticky="w",pady=(4,0))
        ttk.Spinbox(one,from_=1,to=500,textvariable=self.batch_size,width=5).grid(row=1,column=1,sticky="w",padx=4,pady=(4,0))
        self.batch_button=ttk.Button(one,text="Start batch",command=self.start_batch);self.batch_button.grid(row=2,column=0,columnspan=3,sticky="w",pady=(5,0))

        two=self._workflow_card(workflow,1,"2. Repeatability","Annotate the same verified specimens independently in pass 2.")
        self.repeat_summary=ttk.Label(two,text="",style="Muted.TLabel");self.repeat_summary.grid(row=0,column=0,columnspan=2,sticky="w")
        self.pass1_button=ttk.Button(two,text="Pass 1",command=lambda:self._switch_pass(1));self.pass1_button.grid(row=1,column=0,sticky="w",pady=(5,0))
        self.pass2_button=ttk.Button(two,text="Pass 2",command=lambda:self._switch_pass(2));self.pass2_button.grid(row=1,column=1,sticky="w",padx=(5,0),pady=(5,0))

        three=self._workflow_card(workflow,2,"3. Training data","Human-verified marker sets are the authoritative future AI training truth.")
        self.training_summary=ttk.Label(three,text="",style="Muted.TLabel");self.training_summary.grid(row=0,column=0,sticky="w")
        ttk.Button(three,text="Next unfinished",command=self.next_unfinished).grid(row=1,column=0,sticky="w",pady=(5,0))

        four=self._workflow_card(workflow,3,"4. Results","Trait values are recalculated from the current saved markers.")
        self.results_summary=ttk.Label(four,text="",style="Muted.TLabel");self.results_summary.grid(row=0,column=0,sticky="w")
        ttk.Button(four,text="Open Results",command=self.on_open_results).grid(row=1,column=0,sticky="w",pady=(5,0))

    def _workflow_card(self,parent,column,title,help_text):
        label=ttk.Frame(parent);ttk.Label(label,text=title,style="WorkflowCardTitle.TLabel").pack(side="left")
        card=ttk.LabelFrame(parent,labelwidget=label,padding=(7,5),style="WorkflowCard.TLabelframe")
        card.grid(row=0,column=column,sticky="nsew",padx=(0 if column==0 else 4,0));self.tip.bind(card,help_text);return card

    def _bind_keys(self):
        self._key_bind_id=self.root.bind("<KeyPress>",self._key_pressed,add="+")

    def _destroy(self,event):
        if event.widget is not self.outer:return
        if self._key_bind_id:
            try:self.root.unbind("<KeyPress>",self._key_bind_id)
            except tk.TclError:pass
            self._key_bind_id=None
        self._source_cache=None;self._source_cache_id=""

    def _source_for(self,image_id):
        image_id=str(image_id)
        if image_id==self._source_cache_id and self._source_cache is not None:return self._source_cache
        with Image.open(self.project.source_image_path(image_id)) as source:
            source.load();loaded=source.copy()
        self._source_cache_id=image_id;self._source_cache=loaded
        return loaded

    def _key_pressed(self,event):
        cls=event.widget.winfo_class()
        if cls in {"Entry","TEntry","TCombobox","Spinbox","TSpinbox","Text"}:return
        key=str(event.keysym or "")
        if key in {"Left","KP_Left"}:
            self._navigate(-1);return "break"
        if key in {"Right","KP_Right","space"}:
            self.verify_next();return "break"
        if key.isdigit():
            structure=next((item for item in self.project.scheme.get("structures",()) if str(item.get("hotkey") or "")==key),None)
            if structure:
                self._choose_structure(structure["id"]);return "break"

    def _set_initial_sash(self):
        try:
            width=max(900,self.panes.winfo_width());self.panes.sashpos(0,max(300,min(400,int(width*.21))))
        except Exception:pass

    def _sample(self,relative_path):return XRaySpecimenListPanel._sample(relative_path)

    def _context(self,item):
        image=self.project.source_image(item["image_id"]);path=Path(image["relative_path"])
        return f"Locality: {self._sample(image['relative_path'])}  ·  Plate: {path.name}  ·  Fish №{int(item.get('ordinal') or 0)}"

    def _notify_selection(self):
        if not self.selected_specimen_id:return
        item=self.project.specimen(self.selected_specimen_id);self.on_selection(item["image_id"],self.selected_specimen_id)

    def _styles(self):
        structures=list(self.project.scheme.get("structures") or ())
        self.display_settings=load_xray_structure_display(self.project,structures)
        return structures,self.display_settings

    def _build_marker_buttons(self):
        for child in self.marker_host.winfo_children():child.destroy()
        structures,settings=self._styles();ids={item["id"] for item in structures}
        if self.active_structure_id not in ids:self.active_structure_id=structures[0]["id"] if structures else None
        counts={}
        for row in self.annotations:counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        self._marker_buttons={}
        for structure in _structure_button_order(structures):
            index=structures.index(structure);style=marker_style(settings,structure,index);group=ttk.Frame(self.marker_host,style="WorkflowDock.TFrame");group.pack(side="left",padx=2)
            swatch=tk.Label(group,text=_shape_symbol(style["symbol"]),foreground=style["color"],background="#f5f5f5",font=("Segoe UI Symbol",12,"bold"),width=2)
            swatch.pack(side="left")
            hotkey=str(structure.get("hotkey") or "");count=counts.get(structure["id"],0)
            button=ttk.Button(group,text=f"{hotkey+'. ' if hotkey else ''}{structure['name']} ({count})",style="Primary.TButton" if structure["id"]==self.active_structure_id else "P.TButton",command=lambda sid=structure["id"]:self._choose_structure(sid))
            button.pack(side="left");self._marker_buttons[structure["id"]]=button;self.tip.bind(button,structure.get("description") or structure["name"])
        if not structures:ttk.Label(self.marker_host,text="No structures configured",style="Muted.TLabel").pack(side="left")

    def _choose_structure(self,structure_id):
        self.active_structure_id=structure_id;self.selected_annotation_id=None;self._build_marker_buttons();self._draw_overlays();self.canvas.focus_set()

    def _structure(self,structure_id=None):
        structure_id=structure_id or self.active_structure_id
        return next((item for item in self.project.scheme.get("structures",()) if item["id"]==structure_id),None)

    def refresh(self):
        self.specimen_list.pass_no=self.pass_no.get();rows=self.project.structure_specimens(self.pass_no.get());ids=[row["specimen_id"] for row in rows]
        batch=self.project.structure_batch(self.pass_no.get());batch_ids=list(batch.get("ids") or ())
        preferred_batch=batch_ids[int(batch.get("position",0) or 0)] if batch_ids else None
        target=self.selected_specimen_id if self.selected_specimen_id in ids else preferred_batch if preferred_batch in ids else next((row["specimen_id"] for row in rows if row["image_id"]==self.preferred_image_id),None)
        self.selected_specimen_id=target or (ids[0] if ids else "")
        self.specimen_list.selected_specimen_id=self.selected_specimen_id;self.specimen_list.refresh(reveal=True)
        if self.selected_specimen_id:self._load_specimen(self.selected_specimen_id)
        else:self._clear()
        self._refresh_summary();self._refresh_workflow()

    def _list_selected(self,specimen_id):
        if specimen_id!=self.selected_specimen_id:self._load_specimen(specimen_id)

    def _load_specimen(self,specimen_id):
        self.selected_specimen_id=specimen_id;self.selected_annotation_id=None;item=self.project.specimen(specimen_id)
        self.preferred_image_id=item["image_id"];self.context_label.configure(text=self._context(item))
        try:
            source=self._source_for(item["image_id"])
            crop=oriented_crop(source,item["crop"],self.project.orientation_policy)
            self.crop_image=_display_ready(crop)
        except Exception as exc:
            messagebox.showerror("Structures",f"Could not open specimen crop:\n{exc}",parent=self.root);self.crop_image=None
        self.annotations=self.project.annotations(specimen_id,self.pass_no.get())
        self.zoom=1.0;self.pan=None;self.pan_drag=None;self._raster_key=None;self._image_item=None;self.photo=None;self.canvas.delete("all")
        self.specimen_list.select(specimen_id,reveal=True);self._build_marker_buttons();self._update_counts();self._draw();self._refresh_summary();self._refresh_workflow();self._notify_selection();self.canvas.focus_set()

    def _clear(self):
        self.selected_specimen_id="";self.crop_image=self.photo=None;self.annotations=[];self.context_label.configure(text="No eligible specimen")
        self._image_item=None;self._raster_key=None;self.pan=None;self.canvas.delete("all");self._build_marker_buttons();self._update_counts()

    def _refresh_summary(self):
        summary=self.project.annotation_summary(self.pass_no.get());batch=self.project.structure_batch(self.pass_no.get())
        batch_text=""
        if batch and self.selected_specimen_id in batch.get("ids",()):
            pos=batch["ids"].index(self.selected_specimen_id);batch_text=f"Batch {pos+1}/{len(batch['ids'])} · "
        self.summary_label.configure(text=batch_text+f"{summary['verified']} verified · {summary['draft']} draft · {summary['unstarted']} not started")
        state="normal" if self.selected_specimen_id else "disabled";self.verify_button.configure(state=state);self.previous_button.configure(state=state)

    def _refresh_workflow(self):
        p1=self.project.annotation_summary(1);p2=self.project.annotation_summary(2);batch=self.project.structure_batch(self.pass_no.get())
        self.batch_summary.configure(text=f"{p1['verified']} verified · {p1['draft']} draft · {p1['unstarted']} not started" if self.pass_no.get()==1 else f"{p2['verified']} verified · {p2['draft']} draft · {p2['unstarted']} not started")
        self.batch_button.configure(text="Continue batch" if batch else "Start batch")
        self.repeat_summary.configure(text=f"P1 {p1['verified']}/{p1['eligible']} · P2 {p2['verified']}/{p2['eligible']}")
        self.pass2_button.configure(state="normal" if p2["eligible"] else "disabled")
        self.training_summary.configure(text=f"{p1['verified']} human-verified specimens")
        self.results_summary.configure(text=f"{len(self.project.scheme.get('traits') or ())} live traits · updates on every edit")

    def _update_counts(self):
        counts={}
        for row in self.annotations:counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        structures=list(self.project.scheme.get("structures") or ())
        self.counts_label.configure(text="   ·   ".join(f"{item['name']}: {counts.get(item['id'],0)}" for item in structures))
        run=self.project.annotation_run(self.selected_specimen_id,self.pass_no.get(),create=False) if self.selected_specimen_id else None
        self.save_label.configure(text="Verified" if run and run.get("status")=="verified" else "Saved · draft" if run else "Not started")

    def _fit_scale(self):
        if self.crop_image is None:return 1.0
        width=max(1,self.canvas.winfo_width());height=max(1,self.canvas.winfo_height())
        fit=min(max(1,width-20)/self.crop_image.width,max(1,height-20)/self.crop_image.height)
        return max(0.001,fit*self.zoom)

    def _ensure_raster(self):
        if self.crop_image is None:return None
        scale=self._fit_scale();cw=max(1,self.canvas.winfo_width());ch=max(1,self.canvas.winfo_height())
        dw=max(1,round(self.crop_image.width*scale));dh=max(1,round(self.crop_image.height*scale))
        if self.pan is None:self.pan=((cw-dw)/2,(ch-dh)/2)
        key=(id(self.crop_image),dw,dh)
        if key!=self._raster_key:
            shown=self.crop_image if (dw,dh)==self.crop_image.size else self.crop_image.resize((dw,dh),Image.Resampling.BILINEAR)
            self.photo=ImageTk.PhotoImage(shown,master=self.canvas);self._raster_key=key
            if self._image_item is None:self._image_item=self.canvas.create_image(*self.pan,anchor="nw",image=self.photo,tags=("xray_image",))
            else:self.canvas.itemconfigure(self._image_item,image=self.photo)
        if self._image_item is not None:self.canvas.coords(self._image_item,*self.pan)
        return self.photo

    def _screen(self,x,y):
        scale=self._fit_scale();pan=self.pan or (0.0,0.0)
        return pan[0]+float(x)*self.crop_image.width*scale,pan[1]+float(y)*self.crop_image.height*scale

    def _normal(self,x,y):
        scale=self._fit_scale();pan=self.pan or (0.0,0.0)
        px=(float(x)-pan[0])/max(1e-9,scale);py=(float(y)-pan[1])/max(1e-9,scale)
        return max(0.0,min(1.0,px/max(1,self.crop_image.width))),max(0.0,min(1.0,py/max(1,self.crop_image.height)))

    def _draw(self):
        if self.crop_image is None:return
        self._ensure_raster();self._draw_overlays()

    def _draw_overlays(self):
        self.canvas.delete("structure_overlay");self.canvas.delete("structure_hint")
        if self.crop_image is None:return
        structures,settings=self._styles();by_id={item["id"]:(index,item) for index,item in enumerate(structures)}
        grouped={}
        for row in self.annotations:grouped.setdefault(row["structure_id"],[]).append(row)
        for sid,rows in grouped.items():
            pair=by_id.get(sid)
            if pair is None:continue
            index,structure=pair;style=marker_style(settings,structure,index);rows=sorted(rows,key=lambda row:(row["sort_order"],row["annotation_id"]))
            for seq,row in enumerate(rows,1):
                sx,sy=self._screen(row["x"],row["y"]);label=str(seq) if structure.get("repeated") else ""
                draw_xray_marker(
                    self.canvas,sx,sy,color=style["color"],size=style["size"],symbol=style["symbol"],label=label,label_size=style["label_size"],
                    selected=row["annotation_id"]==self.selected_annotation_id,tags=(f"annotation:{row['annotation_id']}",),
                )
        hint="Selected marker · drag to move · Delete to remove" if self.selected_annotation_id else "Choose a marker below, then click the anatomy"
        self.canvas.create_text(12,12,anchor="nw",text=hint,fill="white",font=("Segoe UI",9,"bold"),tags=("structure_hint",))

    def _nearest(self,event):
        size=int(self.display_settings.get("size",DEFAULT_SIZE));best=None;limit=max(14,size+8)
        for row in self.annotations:
            sx,sy=self._screen(row["x"],row["y"]);distance=math.hypot(event.x-sx,event.y-sy)
            if distance<=limit and (best is None or distance<best[0]):best=(distance,row)
        return best[1] if best else None

    def _after_edit(self,text="Saved · draft"):
        self.annotations=self.project.annotations(self.selected_specimen_id,self.pass_no.get())
        self.save_label.configure(text=text);self.specimen_list.refresh(preserve_scroll=True);self._build_marker_buttons();self._update_counts();self._refresh_summary();self._refresh_workflow();self._draw_overlays();self.on_changed()

    def _canvas_down(self,event):
        if self.crop_image is None or not self.selected_specimen_id:return
        self.canvas.focus_set();near=self._nearest(event)
        if near is not None:
            self.selected_annotation_id=near["annotation_id"];self.active_structure_id=near["structure_id"];self._drag_annotation=near["annotation_id"]
            self._drag_last_screen=self._screen(near["x"],near["y"]);self._build_marker_buttons();self._draw_overlays();return
        structure=self._structure()
        if structure is None:return
        nx,ny=self._normal(event.x,event.y)
        self.selected_annotation_id=self.project.add_annotation(
            self.selected_specimen_id,structure["id"],nx,ny,self.pass_no.get(),replace_single=not bool(structure.get("repeated")),
        )
        self._after_edit()

    def _canvas_drag(self,event):
        if self._drag_annotation is None or self.crop_image is None:return
        nx,ny=self._normal(event.x,event.y);sx,sy=self._screen(nx,ny);last=self._drag_last_screen or (sx,sy)
        dx=sx-last[0];dy=sy-last[1];self.canvas.move(f"annotation:{self._drag_annotation}",dx,dy);self._drag_last_screen=(sx,sy)
        for row in self.annotations:
            if row["annotation_id"]==self._drag_annotation:row["x"]=nx;row["y"]=ny;break

    def _canvas_up(self,event):
        if self._drag_annotation is None:return
        annotation_id=self._drag_annotation;self._drag_annotation=None;self._drag_last_screen=None;nx,ny=self._normal(event.x,event.y)
        try:self.project.move_annotation(annotation_id,nx,ny)
        except Exception as exc:messagebox.showerror("Structures",str(exc),parent=self.root);return
        self._after_edit()

    def _pan_start(self,event):
        if self.crop_image is None:return
        self.pan_drag=(event.x,event.y,self.pan or (0.0,0.0));self.canvas.configure(cursor="fleur")

    def _pan_motion(self,event):
        if not self.pan_drag:return
        x,y,origin=self.pan_drag;new=(origin[0]+event.x-x,origin[1]+event.y-y);old=self.pan or new;dx=new[0]-old[0];dy=new[1]-old[1];self.pan=new
        if self._image_item is not None:self.canvas.coords(self._image_item,*new)
        self.canvas.move("structure_overlay",dx,dy)

    def _pan_end(self,_event=None):
        self.pan_drag=None;self.canvas.configure(cursor="crosshair")

    def _wheel(self,event):
        if self.crop_image is None:return
        old_scale=self._fit_scale();pan=self.pan or (0.0,0.0)
        before=((event.x-pan[0])/old_scale,(event.y-pan[1])/old_scale)
        self.zoom=max(0.2,min(8.0,self.zoom*(1.15 if event.delta>0 else 1/1.15)))
        new_scale=self._fit_scale();self.pan=(event.x-before[0]*new_scale,event.y-before[1]*new_scale);self._ensure_raster();self._draw_overlays()

    def delete_selected(self,_event=None):
        if self.selected_annotation_id:
            self.project.delete_annotation(self.selected_annotation_id);self.selected_annotation_id=None;self._after_edit()
        return "break"

    def open_display_settings(self):
        structures=list(self.project.scheme.get("structures") or ());current=load_xray_structure_display(self.project,structures)
        dialog=tk.Toplevel(self.root);dialog.title("X-ray marker display");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1)
        ttk.Label(frame,text="X-ray marker display",style="SectionTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(frame,text="High-contrast defaults stay visible on black, white and gray radiographs.",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(2,10))
        size=tk.IntVar(master=dialog,value=current["size"]);label_size=tk.IntVar(master=dialog,value=current["label_size"])
        common=ttk.LabelFrame(frame,text="Common size",padding=(10,8));common.grid(row=2,column=0,sticky="ew")
        ttk.Label(common,text="Marker size").grid(row=0,column=0,sticky="w");ttk.Spinbox(common,from_=4,to=18,textvariable=size,width=5).grid(row=0,column=1,sticky="w",padx=(8,18))
        ttk.Label(common,text="Number size").grid(row=0,column=2,sticky="w");ttk.Spinbox(common,from_=8,to=24,textvariable=label_size,width=5).grid(row=0,column=3,sticky="w",padx=(8,0))
        types=ttk.LabelFrame(frame,text="Marker icons and colors",padding=(10,8));types.grid(row=3,column=0,sticky="ew",pady=(8,0));types.columnconfigure(1,weight=1)
        color_vars={};symbol_vars={};previews={}
        def paint(ident):
            canvas=previews[ident];canvas.delete("all");canvas.create_rectangle(1,1,31,19,fill=color_vars[ident].get(),outline="#333333")
        for row,structure in enumerate(structures):
            ident=structure["id"];color_vars[ident]=tk.StringVar(master=dialog,value=current["colors"][ident]);symbol_vars[ident]=tk.StringVar(master=dialog,value=SYMBOL_NAMES.get(current["symbols"][ident],"Circle"))
            ttk.Label(types,text=structure["name"]).grid(row=row,column=0,sticky="w",pady=3)
            preview=tk.Canvas(types,width=32,height=20,highlightthickness=0);preview.grid(row=row,column=1,sticky="w",padx=(10,6));previews[ident]=preview;paint(ident)
            def choose(sid=ident,name=structure["name"]):
                value=colorchooser.askcolor(color=color_vars[sid].get(),parent=dialog,title=name)[1]
                if value:color_vars[sid].set(value);paint(sid)
            ttk.Button(types,text="Color…",command=choose).grid(row=row,column=2,sticky="w",padx=(0,6))
            ttk.Combobox(types,textvariable=symbol_vars[ident],values=tuple(SYMBOL_LABELS),state="readonly",width=15).grid(row=row,column=3,sticky="w")
        status=tk.StringVar(master=dialog,value="");ttk.Label(frame,textvariable=status,style="Muted.TLabel").grid(row=4,column=0,sticky="w",pady=(8,0))
        actions=ttk.Frame(frame);actions.grid(row=5,column=0,sticky="e",pady=(10,0))
        def reset():
            defaults=normalize_xray_structure_display({},structures);size.set(DEFAULT_SIZE);label_size.set(DEFAULT_LABEL_SIZE)
            for structure in structures:
                ident=structure["id"];color_vars[ident].set(defaults["colors"][ident]);symbol_vars[ident].set(SYMBOL_NAMES.get(defaults["symbols"][ident],"Circle"));paint(ident)
            status.set("Bright high-contrast defaults loaded. Click Apply.")
        def apply():
            save_xray_structure_display(self.project,{
                "size":size.get(),"label_size":label_size.get(),
                "colors":{sid:var.get() for sid,var in color_vars.items()},
                "symbols":{sid:SYMBOL_LABELS.get(var.get(),"circle") for sid,var in symbol_vars.items()},
            },structures)
            self.display_settings=load_xray_structure_display(self.project,structures);self._build_marker_buttons();self._draw_overlays();status.set("Applied.")
        ttk.Button(actions,text="Reset",command=reset).pack(side="left")
        ttk.Button(actions,text="Close",command=dialog.destroy).pack(side="left",padx=(6,0))
        ttk.Button(actions,text="Apply",command=apply,style="Primary.TButton").pack(side="left",padx=(6,0))

    def start_batch(self):
        active=self.project.structure_batch(self.pass_no.get())
        if active:
            target=active["ids"][int(active.get("position",0) or 0)];self._load_specimen(target);return
        state=self.project.start_structure_batch(self.batch_size.get(),self.pass_no.get(),self.selected_specimen_id)
        ids=list(state.get("ids") or ())
        if not ids:messagebox.showinfo("Structure annotation batch","No unfinished eligible specimens remain.",parent=self.root);self._refresh_workflow();return
        self._load_specimen(ids[0])

    def next_unfinished(self):
        rows=self.project.structure_specimens(self.pass_no.get());unfinished=[row["specimen_id"] for row in rows if str(row.get("annotation_status") or "")!="verified"]
        if not unfinished:messagebox.showinfo("Structures","All eligible specimens are verified.",parent=self.root);return
        if self.selected_specimen_id in unfinished:
            pos=unfinished.index(self.selected_specimen_id);target=unfinished[(pos+1)%len(unfinished)]
        else:target=unfinished[0]
        self._load_specimen(target)

    def _switch_pass(self,number):
        number=int(number)
        if number==2 and not self.project.annotation_summary(2)["eligible"]:
            messagebox.showinfo("Repeatability","Verify pass 1 specimens before starting pass 2.",parent=self.root);return
        self.pass_no.set(number);self.pass_box.current(1 if number==2 else 0);self.specimen_list.pass_no=number;self.selected_specimen_id="";self.refresh()

    def _pass_changed(self,_event=None):self._switch_pass(2 if self.pass_box.current()==1 else 1)

    def _navigate(self,step):
        batch=self.project.structure_batch(self.pass_no.get())
        if batch and self.selected_specimen_id in batch.get("ids",()):
            result=self.project.move_structure_batch(self.selected_specimen_id,step,self.pass_no.get())
            if result.get("specimen_id"):self._load_specimen(result["specimen_id"])
            return
        ids=self.specimen_list.visible_ids()
        if not ids:return
        try:index=ids.index(self.selected_specimen_id)
        except ValueError:index=0
        target=ids[max(0,min(len(ids)-1,index+int(step)))];self._load_specimen(target)

    def verify_next(self):
        if not self.selected_specimen_id:return
        current=self.selected_specimen_id
        try:self.project.verify_annotations(current,self.pass_no.get())
        except ValueError as exc:messagebox.showwarning("Structures incomplete",str(exc),parent=self.root);return
        except Exception as exc:messagebox.showerror("Verify structures",str(exc),parent=self.root);return
        self._after_edit("Verified")
        batch=self.project.structure_batch(self.pass_no.get())
        if batch and current in batch.get("ids",()):
            result=self.project.move_structure_batch(current,1,self.pass_no.get())
            if result.get("finished"):
                messagebox.showinfo("Structure annotation batch","Batch complete.",parent=self.root);self._refresh_workflow();return
            if result.get("specimen_id"):self._load_specimen(result["specimen_id"]);return
        rows=self.specimen_list.rows();ids=[row["specimen_id"] for row in rows];status={row["specimen_id"]:row.get("annotation_status") for row in rows}
        if current in ids:
            pos=ids.index(current);ordered=ids[pos+1:]+ids[:pos];next_id=next((sid for sid in ordered if status.get(sid)!="verified"),None)
            if next_id:self._load_specimen(next_id)
