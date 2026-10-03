"""Interactive X-ray structure annotation workspace."""
from __future__ import annotations

import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from app.photo_list import PhotoListCanvas
from app.ui.icons import CONTROL_ICON_SIZE, tk_icon
from app.ui.photo_list_panel import filtered_photo_indices
from app.ui.tooltips import Tooltip
from .xray_crop import oriented_crop
from .xray_icons import tk_xray_icon
from .xray_structure_ai import (
    export_structure_model_package, import_structure_model_package,
    predict_structures, train_structure_model,
)
from .xray_schema import compatible_reference_roles
from .xray_structure_display import (
    DEFAULT_LABEL_SIZE, DEFAULT_SIZE, SYMBOL_LABELS, SYMBOL_NAMES,
    draw_xray_marker, draw_xray_role_badges, load_xray_structure_display, marker_style, role_color,
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


def _first_structure_id(structures):
    ordered=_structure_button_order(structures)
    return ordered[0]["id"] if ordered else None


_VISIBILITY_LABELS={
    "complete":"Complete",
    "partial":"Partial",
    "not_visible":"Not visible",
    "absent":"Absent",
}
_VISIBILITY_VALUES={label:value for value,label in _VISIBILITY_LABELS.items()}
_VISIBILITY_HELP=(
    "Visibility for the selected marker type. Complete = every visible instance is marked; "
    "Partial = only some visible instances can be marked; Not visible = this structure cannot "
    "be judged on this X-ray; Absent = the structure is truly absent."
)


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
        self.selected_specimen_id=str(specimen_id or "")
        selected_index=next((i for i,row in enumerate(self._rows) if row["specimen_id"]==self.selected_specimen_id),None)
        if selected_index not in self.visible_indices:
            self.refresh(preserve_scroll=True,reveal=False);return
        visible=self.visible_indices.index(selected_index);self.canvas.selection_set(visible)
        if reveal:self.canvas.see(visible,align_top=True)

    def rows(self):return list(self._rows)
    def visible_ids(self):return [self._rows[index]["specimen_id"] for index in self.visible_indices]

    def _selected(self,_event=None):
        selection=self.canvas.curselection()
        if not selection:return
        visible=selection[0]
        if not 0<=visible<len(self.visible_indices):return
        row=self._rows[self.visible_indices[visible]]
        self.selected_specimen_id=row["specimen_id"];self.on_select(row["specimen_id"])


class XRayStructureWorkspace:
    """Landmarks-style X-ray marker workspace with cached zoom/pan and finite batches."""

    def __init__(
        self,parent,project,on_changed=None,initial_image_id=None,initial_specimen_id=None,
        on_selection=None,on_open_results=None,
    ):
        self.parent=parent;self.root=parent.winfo_toplevel();self.project=project;self.on_changed=on_changed or (lambda:None)
        self.on_selection=on_selection or (lambda _image_id,_specimen_id:None);self.on_open_results=on_open_results or (lambda:None)
        self.tip=Tooltip(self.root);self.pass_no=tk.IntVar(value=1);self.batch_size=tk.IntVar(value=24)
        self.prediction_batch_size=tk.IntVar(value=24);self._busy=False
        self.selected_specimen_id=str(initial_specimen_id or "");self.preferred_image_id=str(initial_image_id or "")
        self.active_structure_id=None;self.selected_annotation_id=None
        self.crop_image=None;self.photo=None;self.zoom=1.0;self.pan=None;self.pan_drag=None;self._raster_key=None;self._image_item=None
        self.annotations=[];self.roles=[];self._drag_annotation=None;self._drag_last_screen=None;self._marker_buttons={};self._icons={}
        self._right_gesture=None;self._menu_icons=[];self._clear_menu_icons=[];self._updating_visibility=False
        self.display_settings=load_xray_structure_display(self.project,self.project.scheme.get("structures",()))
        self._source_cache_id="";self._source_cache=None
        self._key_bind_id=None
        self._build();self._bind_keys();self.refresh()

    def _icon(self,master,name):
        key=("core",name,CONTROL_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_icon(master,name,CONTROL_ICON_SIZE)
        return self._icons[key]

    def _xray_icon(self,master,name):
        key=("xray",name,CONTROL_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_xray_icon(master,name,CONTROL_ICON_SIZE)
        return self._icons[key]

    def _marker_button_icon(self,master,structure,style,size=24):
        key=("marker",structure["id"],style["color"],style["symbol"],int(size))
        if key in self._icons:return self._icons[key]
        aa=3;side=int(size)*aa;image=Image.new("RGBA",(side,side),(0,0,0,0));draw=ImageDraw.Draw(image)
        cx=cy=side/2;r=side*.27;color=style["color"];outline="#263746";width=max(2,int(side*.07))
        symbol=style["symbol"]
        if symbol=="triangle":
            draw.polygon([(cx,cy-r),(cx-r,cy+r),(cx+r,cy+r)],fill="#ffffff",outline=outline)
            draw.line([(cx,cy-r),(cx-r,cy+r),(cx+r,cy+r),(cx,cy-r)],fill=color,width=width,joint="curve")
        elif symbol=="diamond":
            draw.polygon([(cx,cy-r),(cx-r,cy),(cx,cy+r),(cx+r,cy)],fill="#ffffff",outline=outline)
            draw.line([(cx,cy-r),(cx-r,cy),(cx,cy+r),(cx+r,cy),(cx,cy-r)],fill=color,width=width,joint="curve")
        elif symbol=="square":
            draw.rectangle((cx-r,cy-r,cx+r,cy+r),fill="#ffffff",outline=outline,width=width)
            draw.rectangle((cx-r+width,cy-r+width,cx+r-width,cy+r-width),outline=color,width=width)
        elif symbol=="cross":
            draw.line((cx-r,cy-r,cx+r,cy+r),fill=outline,width=width+3)
            draw.line((cx-r,cy+r,cx+r,cy-r),fill=outline,width=width+3)
            draw.line((cx-r,cy-r,cx+r,cy+r),fill=color,width=width)
            draw.line((cx-r,cy+r,cx+r,cy-r),fill=color,width=width)
        else:
            draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill="#ffffff" if symbol!="filled_circle" else color,outline=outline,width=width)
            draw.ellipse((cx-r+width,cy-r+width,cx+r-width,cy+r-width),outline=color,width=width)
            if symbol=="target":draw.ellipse((cx-r*.32,cy-r*.32,cx+r*.32,cy+r*.32),fill=color)
        icon=ImageTk.PhotoImage(image.resize((int(size),int(size)),Image.Resampling.LANCZOS),master=master)
        self._icons[key]=icon;return icon

    def _build(self):
        outer=ttk.Frame(self.parent,padding=(0,0));outer.pack(fill="both",expand=True);self.outer=outer
        outer.bind("<Destroy>",self._destroy,add="+")
        panes=ttk.Panedwindow(outer,orient="horizontal");panes.pack(fill="both",expand=True)
        left=ttk.Frame(panes);main=ttk.Frame(panes);panes.add(left,weight=0);panes.add(main,weight=1);self.panes=panes
        main.columnconfigure(0,weight=1);main.rowconfigure(1,weight=1)

        self.specimen_list=XRaySpecimenListPanel(left,self.project,self._list_selected,self.tip);self.specimen_list.pack(fill="both",expand=True)
        self.root.after_idle(self._set_initial_sash)

        header=ttk.Frame(main,style="Toolbar.TFrame");header.grid(row=0,column=0,sticky="ew",pady=(0,4));header.columnconfigure(0,weight=1)
        meta=ttk.Frame(header,style="Toolbar.TFrame");meta.grid(row=0,column=0,sticky="w",padx=(2,8))
        self._context_values={}
        for column,(key,title) in enumerate((("locality","Locality:"),("plate","Plate:"),("specimen","Specimen:"))):
            offset=column*3
            ttk.Label(meta,text=title,style="SectionTitle.TLabel").grid(row=0,column=offset,sticky="w")
            value=ttk.Label(meta,text="—",anchor="w");value.grid(row=0,column=offset+1,sticky="w",padx=(4,8))
            self._context_values[key]=value
            if column<2:ttk.Label(meta,text="·",style="Muted.TLabel").grid(row=0,column=offset+2,sticky="w",padx=(0,8))
        status_host=ttk.Frame(header,style="Toolbar.TFrame");status_host.grid(row=0,column=1,sticky="e",padx=(6,4))
        self.summary_labels={}
        for key,title in (("verified","Verified"),("draft","Draft"),("unstarted","Not started")):
            label=ttk.Label(status_host,text=f"{title}: 0",style="StatusChip.TLabel")
            label.pack(side="left",padx=(0,2));self.summary_labels[key]=label
        self.save_label=ttk.Label(status_host,text="Current: Not started",style="StatusChip.TLabel");self.save_label.pack(side="left",padx=(3,0))
        nav=ttk.Frame(header,style="Toolbar.TFrame");nav.grid(row=0,column=2,sticky="e")
        tools=ttk.Frame(nav,style="Toolbar.TFrame");tools.grid(row=0,column=0,sticky="e")
        self.clear_type_button=ttk.Menubutton(
            tools,text="Clear type…",image=self._xray_icon(tools,"clear_marker_set"),compound="left",style="P.TButton",
        )
        self.clear_type_button.pack(side="left",padx=(0,2));self.tip.bind(self.clear_type_button,"Clear one marker type.")
        self.clear_all_button=ttk.Button(
            tools,text="Clear all markers",image=self._xray_icon(tools,"clear_all_markers"),compound="left",
            style="P.TButton",command=self.clear_all_markers,
        )
        self.clear_all_button.pack(side="left",padx=2);self.tip.bind(self.clear_all_button,"Clear all markers.")
        self.display_button=ttk.Button(
            tools,text="Display…",image=self._icon(tools,"display"),compound="left",style="P.TButton",command=self.open_display_settings,
        )
        self.display_button.pack(side="left",padx=(2,6));self.tip.bind(self.display_button,"Marker display.")
        self.apply_separator=ttk.Separator(nav,orient="vertical");self.apply_separator.grid(row=0,column=1,sticky="ns",padx=7,pady=2)
        self.apply_button=ttk.Button(nav,text="Apply",image=self._xray_icon(nav,"structure_apply"),compound="left",style="NavPrimary.TButton",command=self.verify_current)
        self.apply_button.grid(row=0,column=2,sticky="e")
        self.tip.bind(self.apply_button,"Verify without moving.")

        canvas_host=ttk.Frame(main);canvas_host.grid(row=1,column=0,sticky="nsew");canvas_host.pack_propagate(False)
        self.canvas=tk.Canvas(canvas_host,background="#202020",highlightthickness=0,takefocus=True,cursor="crosshair");self.canvas.pack(fill="both",expand=True)
        for event,handler in (
            ("<Configure>",lambda _e:self._draw()),
            ("<Button-1>",self._canvas_down),("<B1-Motion>",self._canvas_drag),("<ButtonRelease-1>",self._canvas_up),
            ("<Button-3>",self._right_start),("<B3-Motion>",self._right_motion),("<ButtonRelease-3>",self._right_end),
            ("<Button-2>",self._pan_start),("<B2-Motion>",self._pan_motion),("<ButtonRelease-2>",self._pan_end),
            ("<MouseWheel>",self._wheel),
        ):self.canvas.bind(event,handler)
        self.canvas.bind("<Delete>",self.delete_selected);self.canvas.bind("<BackSpace>",self.delete_selected)

        marker_dock=ttk.Frame(main,style="WorkflowDock.TFrame",padding=(6,4));marker_dock.grid(row=2,column=0,sticky="ew",pady=(4,0));marker_dock.columnconfigure(1,weight=1)
        ttk.Label(marker_dock,text="Markers:",style="SectionTitle.TLabel").grid(row=0,column=0,sticky="w",padx=(0,6))
        self.marker_host=ttk.Frame(marker_dock,style="WorkflowDock.TFrame");self.marker_host.grid(row=0,column=1,sticky="w")
        visibility=ttk.Frame(marker_dock,style="WorkflowDock.TFrame");visibility.grid(row=0,column=2,sticky="e",padx=(10,0))
        ttk.Label(visibility,text="Visibility:",style="Muted.TLabel").pack(side="left",padx=(0,4))
        self.visibility_var=tk.StringVar(master=self.root,value="Complete")
        self.visibility_box=ttk.Combobox(
            visibility,textvariable=self.visibility_var,values=tuple(_VISIBILITY_VALUES),state="readonly",width=11,
        )
        self.visibility_box.pack(side="left");self.visibility_box.bind("<<ComboboxSelected>>",self._visibility_changed)
        self.tip.bind(visibility,_VISIBILITY_HELP);self.tip.bind(self.visibility_box,_VISIBILITY_HELP)

        workflow=ttk.Frame(main,style="WorkflowDock.TFrame",padding=(0,4,0,0));workflow.grid(row=3,column=0,sticky="ew")
        workflow.columnconfigure(0,weight=1);workflow.columnconfigure(1,weight=1);workflow.columnconfigure(2,weight=1);workflow.columnconfigure(3,weight=1)
        one=self._workflow_card(workflow,0,"1. Annotation batch","Work through a finite saved set with batch-only previous / next controls.")
        self.batch_summary=ttk.Label(one,text="",style="Muted.TLabel");self.batch_summary.grid(row=0,column=0,columnspan=3,sticky="w")
        ttk.Label(one,text="Batch").grid(row=1,column=0,sticky="w",pady=(4,0))
        ttk.Spinbox(one,from_=1,to=500,textvariable=self.batch_size,width=5).grid(row=1,column=1,sticky="w",padx=4,pady=(4,0))
        self.batch_button=ttk.Button(one,text="Start batch",command=self.start_batch);self.batch_button.grid(row=2,column=0,columnspan=3,sticky="w",pady=(5,0))

        two=self._workflow_card(workflow,1,"2. Repeatability","Annotate the same verified specimens independently in pass 2.")
        self.repeat_summary=ttk.Label(two,text="",style="Muted.TLabel");self.repeat_summary.grid(row=0,column=0,columnspan=2,sticky="w")
        self.pass1_button=ttk.Button(two,text="Pass 1",command=lambda:self._switch_pass(1));self.pass1_button.grid(row=1,column=0,sticky="w",pady=(5,0))
        self.pass2_button=ttk.Button(two,text="Pass 2",command=lambda:self._switch_pass(2));self.pass2_button.grid(row=1,column=1,sticky="w",padx=(5,0),pady=(5,0))

        three=self._workflow_card(workflow,2,"3. Training data","Train only from human-verified pass 1 markers. AI output always returns as a draft for human review.")
        self.training_summary=ttk.Label(three,text="",style="Muted.TLabel");self.training_summary.grid(row=0,column=0,columnspan=4,sticky="w")
        self.structure_model_label=ttk.Label(three,text="Active AI: none",style="Muted.TLabel");self.structure_model_label.grid(row=1,column=0,columnspan=4,sticky="w",pady=(1,0))
        train_actions=ttk.Frame(three);train_actions.grid(row=2,column=0,columnspan=4,sticky="ew",pady=(5,0))
        self.structure_train_button=ttk.Button(train_actions,text="Train Structure AI",command=self.train_structure_ai)
        self.structure_train_button.pack(side="left")
        ttk.Button(train_actions,text="Models…",command=self.manage_structure_models).pack(side="left",padx=(5,0))
        predict_actions=ttk.Frame(three);predict_actions.grid(row=3,column=0,columnspan=4,sticky="ew",pady=(5,0))
        ttk.Label(predict_actions,text="Next").pack(side="left")
        ttk.Spinbox(predict_actions,from_=1,to=500,textvariable=self.prediction_batch_size,width=4).pack(side="left",padx=(3,5))
        self.structure_predict_next_button=ttk.Button(predict_actions,text="Predict next",command=lambda:self.predict_structure_batch(self.prediction_batch_size.get()))
        self.structure_predict_next_button.pack(side="left")
        self.structure_predict_all_button=ttk.Button(predict_actions,text="Predict all",command=lambda:self.predict_structure_batch(None))
        self.structure_predict_all_button.pack(side="left",padx=(4,0))
        review_actions=ttk.Frame(three);review_actions.grid(row=4,column=0,columnspan=4,sticky="ew",pady=(5,0))
        self.structure_review_button=ttk.Button(review_actions,text="Review AI",command=self.review_structure_ai)
        self.structure_review_button.pack(side="left")
        ttk.Button(review_actions,text="Next unfinished",command=self.next_unfinished).pack(side="left",padx=(5,0))

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
        key=str(event.keysym or "");batch=self.project.structure_batch(self.pass_no.get())
        in_batch=bool(batch and self.selected_specimen_id in batch.get("ids",()))
        if key in {"Left","KP_Left"} and in_batch:
            self._navigate(-1);return "break"
        if key in {"Right","KP_Right"} and in_batch:
            self.verify_next();return "break"
        if key=="space":
            self.verify_current();return "break"
        if key.isdigit():
            structure=next((item for item in self.project.scheme.get("structures",()) if str(item.get("hotkey") or "")==key),None)
            if structure:
                self._choose_structure(structure["id"]);return "break"

    def _set_initial_sash(self):
        try:
            width=max(900,self.panes.winfo_width());self.panes.sashpos(0,max(300,min(400,int(width*.21))))
        except Exception:pass

    def _sample(self,relative_path):return XRaySpecimenListPanel._sample(relative_path)

    def _set_context(self,item=None):
        values={"locality":"—","plate":"—","specimen":"—"}
        if item is not None:
            image=self.project.source_image(item["image_id"]);path=Path(image["relative_path"])
            values={
                "locality":self._sample(image["relative_path"]),
                "plate":path.name,
                "specimen":f"№{int(item.get('ordinal') or 0)}",
            }
        for key,label in self._context_values.items():label.configure(text=values[key])

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
        if self.selected_specimen_id:
            for row in self.project.effective_annotations(self.selected_specimen_id,self.pass_no.get()):
                counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        self._marker_buttons={}
        for structure in _structure_button_order(structures):
            index=structures.index(structure);style=marker_style(settings,structure,index)
            hotkey=str(structure.get("hotkey") or "");count=counts.get(structure["id"],0);icon=self._marker_button_icon(self.marker_host,structure,style)
            text=f"{hotkey} · {structure['name']}  {count}" if hotkey else f"{structure['name']}  {count}"
            button=ttk.Button(
                self.marker_host,text=text,image=icon,compound="left",
                style="Primary.TButton" if structure["id"]==self.active_structure_id else "P.TButton",
                command=lambda sid=structure["id"]:self._choose_structure(sid),
            )
            button.pack(side="left",padx=(0,4));self._marker_buttons[structure["id"]]=button
            self.tip.bind(button,(structure.get("description") or structure["name"])+f" · shortcut {hotkey}" if hotkey else structure.get("description") or structure["name"])
        if not structures:ttk.Label(self.marker_host,text="No structures configured",style="Muted.TLabel").pack(side="left")
        self._refresh_clear_menu(structures,settings,counts);self._refresh_visibility_control()

    def _refresh_clear_menu(self,structures,settings,counts):
        menu=tk.Menu(self.clear_type_button,tearoff=False);self._clear_menu_icons=[]
        for structure in _structure_button_order(structures):
            index=structures.index(structure);style=marker_style(settings,structure,index);count=int(counts.get(structure["id"],0) or 0)
            icon=self._marker_button_icon(self.clear_type_button,structure,style,18);self._clear_menu_icons.append(icon)
            menu.add_command(
                label=f"{structure['name']}  ({count})",image=icon,compound="left",
                state="normal" if count else "disabled",
                command=lambda sid=structure["id"],name=structure["name"]:self.clear_marker_category(sid,name),
            )
        self.clear_type_button.configure(menu=menu,state="normal" if any(counts.values()) else "disabled")
        self.clear_all_button.configure(state="normal" if (self.annotations or self.roles) else "disabled")

    def _choose_structure(self,structure_id):
        self.active_structure_id=structure_id;self.selected_annotation_id=None;self._build_marker_buttons();self._draw_overlays();self.canvas.focus_set()

    def _refresh_visibility_control(self):
        if not hasattr(self,"visibility_box"):return
        self._updating_visibility=True
        try:
            if not self.selected_specimen_id or not self.active_structure_id:
                self.visibility_var.set("Complete");self.visibility_box.configure(state="disabled");return
            value=self.project.structure_visibility(
                self.selected_specimen_id,self.active_structure_id,self.pass_no.get(),"human",
            )
            self.visibility_var.set(_VISIBILITY_LABELS.get(value,"Complete"));self.visibility_box.configure(state="readonly")
        finally:self._updating_visibility=False

    def _visibility_changed(self,_event=None):
        if self._updating_visibility or not self.selected_specimen_id or not self.active_structure_id:return
        visibility=_VISIBILITY_VALUES.get(self.visibility_var.get(),"complete")
        current=self.project.structure_visibility(self.selected_specimen_id,self.active_structure_id,self.pass_no.get(),"human")
        if visibility==current:return
        structure=self._structure(self.active_structure_id);name=(structure or {}).get("name") or self.active_structure_id
        if visibility in {"not_visible","absent"}:
            count=sum(
                1 for row in self.project.effective_annotations(self.selected_specimen_id,self.pass_no.get())
                if row["structure_id"]==self.active_structure_id
            )
            if count and not messagebox.askyesno(
                "Structure visibility",
                f"‘{name}’ already has {count} marker(s).\n\n"
                f"Set it to {_VISIBILITY_LABELS[visibility]} and clear those markers?",
                parent=self.root,default="no",
            ):
                self._refresh_visibility_control();return
            if count:self.project.clear_annotations(self.selected_specimen_id,self.pass_no.get(),structure_id=self.active_structure_id)
        self.project.set_structure_visibility(
            self.selected_specimen_id,self.active_structure_id,visibility,self.pass_no.get(),"human",
        )
        self._after_edit(f"Visibility · {_VISIBILITY_LABELS[visibility]}")

    def _ensure_structure_visible_for_marker(self,structure_id):
        state=self.project.structure_visibility(self.selected_specimen_id,structure_id,self.pass_no.get(),"human")
        if state in {"not_visible","absent"}:
            self.project.set_structure_visibility(self.selected_specimen_id,structure_id,"complete",self.pass_no.get(),"human")

    def _structure(self,structure_id=None):
        structure_id=structure_id or self.active_structure_id
        return next((item for item in self.project.scheme.get("structures",()) if item["id"]==structure_id),None)

    def refresh(self):
        self.specimen_list.pass_no=self.pass_no.get();rows=self.project.structure_specimens(self.pass_no.get());ids=[row["specimen_id"] for row in rows]
        batch=self.project.structure_batch(self.pass_no.get());batch_ids=list(batch.get("ids") or ())
        preferred_batch=batch_ids[int(batch.get("position",0) or 0)] if batch_ids else None
        preferred_plate=next((row["specimen_id"] for row in rows if row["image_id"]==self.preferred_image_id),None)
        if self.selected_specimen_id in ids:target=self.selected_specimen_id
        elif self.preferred_image_id:target=preferred_plate if preferred_plate in ids else None
        else:target=preferred_batch if preferred_batch in ids else (ids[0] if ids else None)
        self.selected_specimen_id=target or ""
        self.specimen_list.selected_specimen_id=self.selected_specimen_id;self.specimen_list.refresh(reveal=True)
        if self.selected_specimen_id:self._load_specimen(self.selected_specimen_id)
        else:self._clear()
        self._refresh_summary();self._refresh_workflow()

    def _list_selected(self,specimen_id):
        if specimen_id!=self.selected_specimen_id:self._load_specimen(specimen_id)

    def _load_specimen(self,specimen_id):
        self.selected_specimen_id=specimen_id;self.selected_annotation_id=None
        self.active_structure_id=_first_structure_id(self.project.scheme.get("structures",()))
        item=self.project.specimen(specimen_id)
        self.preferred_image_id=item["image_id"];self._set_context(item)
        try:
            source=self._source_for(item["image_id"])
            crop=oriented_crop(source,item["crop"],self.project.orientation_policy)
            self.crop_image=_display_ready(crop)
        except Exception as exc:
            messagebox.showerror("Structures",f"Could not open specimen crop:\n{exc}",parent=self.root);self.crop_image=None
        self.annotations=self.project.annotations(specimen_id,self.pass_no.get());self.roles=self.project.annotation_roles(specimen_id,self.pass_no.get())
        self.zoom=1.0;self.pan=None;self.pan_drag=None;self._raster_key=None;self._image_item=None;self.photo=None;self.canvas.delete("all")
        self.specimen_list.select(specimen_id,reveal=False);self._build_marker_buttons();self._update_counts();self._draw();self._notify_selection();self.canvas.focus_set()

    def _clear(self):
        self.selected_specimen_id="";self.crop_image=self.photo=None;self.annotations=[];self.roles=[]
        self._image_item=None;self._raster_key=None;self.pan=None;self.canvas.delete("all")
        if self.preferred_image_id:
            try:
                image=self.project.source_image(self.preferred_image_id);path=Path(image["relative_path"])
                values={"locality":self._sample(image["relative_path"]),"plate":path.name,"specimen":"—"}
                for key,label in self._context_values.items():label.configure(text=values[key])
            except Exception:self._set_context(None)
            self.canvas.create_text(
                18,18,anchor="nw",fill="white",
                text="No confirmed specimen crop is available on this plate.\nReturn to Crops and apply the crop before Structure annotation.",
                font=("Segoe UI",10,"bold"),
            )
        else:self._set_context(None)
        self._build_marker_buttons();self._update_counts()

    def _refresh_summary(self):
        summary=self.project.annotation_summary(self.pass_no.get())
        labels={"verified":"Verified","draft":"Draft","unstarted":"Not started"}
        for key,label in self.summary_labels.items():label.configure(text=f"{labels[key]}: {summary[key]}")
        state="normal" if self.selected_specimen_id else "disabled";self.apply_button.configure(state=state)

    def _refresh_workflow(self):
        p1=self.project.annotation_summary(1);p2=self.project.annotation_summary(2);batch=self.project.structure_batch(self.pass_no.get())
        self.batch_summary.configure(text=f"{p1['verified']} verified · {p1['draft']} draft · {p1['unstarted']} not started" if self.pass_no.get()==1 else f"{p2['verified']} verified · {p2['draft']} draft · {p2['unstarted']} not started")
        self.batch_button.configure(text="Continue batch" if batch else "Start batch")
        self.repeat_summary.configure(text=f"P1 {p1['verified']}/{p1['eligible']} · P2 {p2['verified']}/{p2['eligible']}")
        self.pass1_button.configure(style="Primary.TButton" if self.pass_no.get()==1 else "P.TButton")
        self.pass2_button.configure(style="Primary.TButton" if self.pass_no.get()==2 else "P.TButton",state="normal" if p2["eligible"] else "disabled")
        model=self.project.active_structure_model();candidates=len(self.project.structure_prediction_candidate_ids());review=len(self.project.structure_ai_review_ids())
        self.training_summary.configure(text=f"{p1['verified']} human-verified · {candidates} ready for AI · {review} to review")
        self.structure_model_label.configure(text=f"Active AI: {(model or {}).get('model_id') or 'none'}")
        state="normal" if model else "disabled"
        self.structure_predict_next_button.configure(state=state);self.structure_predict_all_button.configure(state=state)
        self.structure_review_button.configure(state="normal" if review else "disabled")
        self.results_summary.configure(text=f"{len(self.project.scheme.get('traits') or ())} live traits · updates on every edit")

    def _update_counts(self):
        counts={}
        if self.selected_specimen_id:
            for row in self.project.effective_annotations(self.selected_specimen_id,self.pass_no.get()):
                counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        run=self.project.annotation_run(self.selected_specimen_id,self.pass_no.get(),create=False) if self.selected_specimen_id else None
        current="Verified" if run and run.get("status")=="verified" else "Draft" if run else "Not started"
        self.save_label.configure(text=f"Current: {current}");self._refresh_visibility_control()

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
        grouped={};roles_by_annotation={}
        for row in self.annotations:grouped.setdefault(row["structure_id"],[]).append(row)
        for role in self.roles:roles_by_annotation.setdefault(int(role["annotation_id"]),[]).append(role)
        for sid,rows in grouped.items():
            pair=by_id.get(sid)
            if pair is None:continue
            index,structure=pair;rows=sorted(rows,key=lambda row:(row["sort_order"],row["annotation_id"]))
            for seq,row in enumerate(rows,1):
                selected=row["annotation_id"]==self.selected_annotation_id
                style=marker_style(settings,structure,index)
                sx,sy=self._screen(row["x"],row["y"]);label=str(seq) if structure.get("repeated") else ""
                draw_xray_marker(
                    self.canvas,sx,sy,color=style["color"],size=style["size"],symbol=style["symbol"],label=label,
                    label_size=style["label_size"],selected=selected,tags=(f"annotation:{row['annotation_id']}",),
                )
                role_colors=[]
                for role in roles_by_annotation.get(int(row["annotation_id"]),()):
                    role_pair=by_id.get(role["structure_id"])
                    if role_pair is None:continue
                    role_index,role_structure=role_pair;role_colors.append(role_color(settings,role_structure,role_index))
                draw_xray_role_badges(self.canvas,sx,sy,colors=role_colors,size=style["size"],tags=(f"annotation:{row['annotation_id']}",))
        if self.selected_annotation_id:
            attached=roles_by_annotation.get(int(self.selected_annotation_id),())
            role_names=[by_id[role["structure_id"]][1]["name"] for role in attached if role["structure_id"] in by_id]
            hint="Drag = move · Delete = remove"
            if role_names:hint+=" · also: "+", ".join(role_names)
        else:hint="Choose marker · click = place · right-click point = role"
        self.canvas.create_text(12,12,anchor="nw",text=hint,fill="white",font=("Segoe UI",9,"bold"),tags=("structure_hint",))

    def _nearest(self,event):
        size=int(self.display_settings.get("size",DEFAULT_SIZE));best=None;limit=max(14,size+8)
        for row in self.annotations:
            sx,sy=self._screen(row["x"],row["y"]);distance=math.hypot(event.x-sx,event.y-sy)
            if distance<=limit and (best is None or distance<best[0]):best=(distance,row)
        return best[1] if best else None

    def _after_edit(self,text="Saved · draft"):
        self.annotations=self.project.annotations(self.selected_specimen_id,self.pass_no.get());self.roles=self.project.annotation_roles(self.selected_specimen_id,self.pass_no.get())
        self.save_label.configure(text=text);self.specimen_list.refresh(preserve_scroll=True);self._build_marker_buttons();self._update_counts();self._refresh_summary();self._refresh_workflow();self._draw_overlays();self.on_changed()

    def _canvas_down(self,event):
        if self.crop_image is None or not self.selected_specimen_id:return
        self.canvas.focus_set();near=self._nearest(event);structure=self._structure()
        if near is not None:
            if structure is not None and not bool(structure.get("repeated")):
                compatible={item["id"] for item in compatible_reference_roles(self.project.scheme,near["structure_id"])}
                if structure["id"] in compatible:
                    try:
                        self._ensure_structure_visible_for_marker(structure["id"])
                        self.project.assign_annotation_role(near["annotation_id"],structure["id"])
                    except Exception as exc:messagebox.showerror("Structures",str(exc),parent=self.root);return
                    self.selected_annotation_id=near["annotation_id"];self._after_edit();return
            self.selected_annotation_id=near["annotation_id"];self.active_structure_id=near["structure_id"];self._drag_annotation=near["annotation_id"]
            self._drag_last_screen=self._screen(near["x"],near["y"]);self._build_marker_buttons();self._draw_overlays();return
        if structure is None:return
        self._ensure_structure_visible_for_marker(structure["id"])
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

    def _role_menu_icon(self,color):
        image=Image.new("RGBA",(16,16),(0,0,0,0));draw=ImageDraw.Draw(image)
        draw.ellipse((1,1,14,14),fill="#101418");draw.ellipse((3,3,12,12),fill=str(color))
        icon=ImageTk.PhotoImage(image,master=self.canvas);self._menu_icons.append(icon);return icon

    def _show_role_menu(self,event,row):
        structures,settings=self._styles();by_id={item["id"]:(index,item) for index,item in enumerate(structures)}
        compatible=compatible_reference_roles(self.project.scheme,row["structure_id"])
        assigned={role["structure_id"] for role in self.roles if int(role["annotation_id"])==int(row["annotation_id"])}
        menu=tk.Menu(self.canvas,tearoff=False);self._menu_icons=[]
        menu.add_command(label="Use this point as…",state="disabled")
        if compatible:
            for role in compatible:
                pair=by_id.get(role["id"]);index=pair[0] if pair else 0
                icon=self._role_menu_icon(role_color(settings,role,index));is_assigned=role["id"] in assigned
                def toggle(role_id=role["id"],attached=is_assigned,annotation_id=row["annotation_id"]):
                    try:
                        if attached:self.project.remove_annotation_role(annotation_id,role_id)
                        else:self.project.assign_annotation_role(annotation_id,role_id)
                    except Exception as exc:messagebox.showerror("Structures",str(exc),parent=self.root);return
                    self.selected_annotation_id=annotation_id;self._after_edit()
                menu.add_command(label=("✓  " if is_assigned else "    ")+role["name"],image=icon,compound="left",command=toggle)
        else:menu.add_command(label="No compatible start / stop roles",state="disabled")
        menu.add_separator();menu.add_command(label="Delete marker",command=self.delete_selected)
        self.selected_annotation_id=row["annotation_id"];self.active_structure_id=row["structure_id"];self._build_marker_buttons();self._draw_overlays()
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def _right_start(self,event):
        if self.crop_image is None:return "break"
        self._right_gesture={"x":event.x,"y":event.y,"pan":self.pan or (0.0,0.0),"near":self._nearest(event),"panning":False}
        return "break"

    def _right_motion(self,event):
        gesture=self._right_gesture
        if not gesture:return "break"
        dx=event.x-gesture["x"];dy=event.y-gesture["y"]
        if not gesture["panning"] and math.hypot(dx,dy)>=5:
            gesture["panning"]=True;self.canvas.configure(cursor="fleur")
        if gesture["panning"]:
            new=(gesture["pan"][0]+dx,gesture["pan"][1]+dy);old=self.pan or new;mx=new[0]-old[0];my=new[1]-old[1];self.pan=new
            if self._image_item is not None:self.canvas.coords(self._image_item,*new)
            self.canvas.move("structure_overlay",mx,my)
        return "break"

    def _right_end(self,event):
        gesture=self._right_gesture;self._right_gesture=None;self.canvas.configure(cursor="crosshair")
        if not gesture:return "break"
        if gesture["panning"]:return "break"
        if gesture["near"] is not None:self._show_role_menu(event,gesture["near"])
        return "break"

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

    def clear_marker_category(self,structure_id,name):
        if not self.selected_specimen_id:return
        count=sum(1 for row in self.project.effective_annotations(self.selected_specimen_id,self.pass_no.get()) if row["structure_id"]==structure_id)
        if not count:return
        structure=self._structure(structure_id);extra="\n\nAny start / stop roles attached to those points are removed with them." if structure and structure.get("repeated") else ""
        if not messagebox.askyesno(
            "Clear marker category",
            f"Remove all ‘{name}’ markers from this specimen?\n\nOther marker categories are kept.{extra}",
            parent=self.root,default="no",
        ):return
        self.project.clear_annotations(self.selected_specimen_id,self.pass_no.get(),structure_id=structure_id)
        self.selected_annotation_id=None;self._after_edit(f"Cleared {name}")

    def clear_all_markers(self):
        if not self.selected_specimen_id or not (self.annotations or self.roles):return
        if not messagebox.askyesno(
            "Clear all markers",
            "Remove every marker and start / stop role from this specimen?\n\nThe crop and source X-ray are not changed.",
            parent=self.root,default="no",
        ):return
        self.project.clear_annotations(self.selected_specimen_id,self.pass_no.get())
        self.selected_annotation_id=None;self._after_edit("All markers cleared")

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

    def _structure_ai_dialog(self,title,text,maximum=100):
        dialog=tk.Toplevel(self.root);dialog.title(title);dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
        label=ttk.Label(frame,text=text,justify="left",wraplength=520);label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="indeterminate" if maximum is None else "determinate",maximum=maximum or 100)
        bar.pack(fill="x",pady=(8,0))
        if maximum is None:bar.start(12)
        return dialog,label,bar

    def train_structure_ai(self):
        if self._busy:return
        p1=self.project.annotation_summary(1)
        if p1["verified"]<8:
            messagebox.showinfo(
                "Train Structure AI",
                "Verify at least 8 specimens from at least 3 source X-rays first. More diverse verified specimens usually give a more useful model.",
                parent=self.root,
            );return
        self._busy=True;events=queue.Queue()
        dialog,label,bar=self._structure_ai_dialog("Train Structure AI","Preparing verified X-ray structures…",None)
        def progress(stage,detail):
            events.put(("progress",str(stage),str(detail)))
        def worker():
            try:events.put(("done",train_structure_model(self.project,progress=progress)))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-structure-training").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait()
                    if event[0]=="progress":
                        label.configure(text=f"{event[1]}\n{event[2]}")
                    elif event[0]=="error":
                        self._busy=False
                        try:bar.stop();dialog.destroy()
                        except tk.TclError:pass
                        messagebox.showerror("Structure training",str(event[1]),parent=self.root);return
                    elif event[0]=="done":
                        self._busy=False
                        try:bar.stop();dialog.destroy()
                        except tk.TclError:pass
                        result=event[1];metrics=result.get("metrics") or {}
                        quality=metrics.get("structure/macro_f1")
                        detail=(
                            f"Model ready: {result['model_id']}\n"
                            f"Training: {result['training_specimens']} specimens on {result['training_plates']} plates\n"
                            f"Validation: {result['validation_specimens']} specimens on {result['validation_plates']} plates"
                        )
                        if isinstance(quality,(int,float)):detail+=f"\nValidation macro F1: {quality:.3f}"
                        self._refresh_workflow()
                        messagebox.showinfo("Structure training",detail,parent=self.root);return
            except queue.Empty:pass
            if dialog.winfo_exists():dialog.after(120,poll)
        dialog.after(120,poll)

    def manage_structure_models(self):
        dialog=tk.Toplevel(self.root);dialog.title("X-ray structure models");dialog.transient(self.root);dialog.geometry("1020x420")
        frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1);frame.rowconfigure(1,weight=1)
        ttk.Label(
            frame,text="Portable Structure AI models · import/export contains weights and model metadata, never source X-rays.",
            style="PageSubtitle.TLabel",
        ).grid(row=0,column=0,sticky="w",pady=(0,8))
        columns=("model","date","source","training","quality","active")
        tree=ttk.Treeview(frame,columns=columns,show="headings",selectmode="browse")
        for key,title,width in (
            ("model","Model",205),("date","Created",135),("source","Started from",180),
            ("training","Train / validation",150),("quality","Validation",170),("active","Status",90),
        ):
            tree.heading(key,text=title);tree.column(key,width=width,anchor="w",stretch=key in {"model","source","quality"})
        tree.grid(row=1,column=0,sticky="nsew")
        scroll=ttk.Scrollbar(frame,orient="vertical",command=tree.yview);tree.configure(yscrollcommand=scroll.set);scroll.grid(row=1,column=1,sticky="ns")
        def reload(select=None):
            for item in tree.get_children():tree.delete(item)
            for model in self.project.structure_models():
                metrics=model.get("metrics") or {};quality=metrics.get("structure/macro_f1")
                quality_text=f"macro F1 {quality:.3f}" if isinstance(quality,(int,float)) else "Not recorded"
                source=str(model.get("parent_model_id") or metrics.get("initialization") or metrics.get("original_model_id") or "ImageNet")
                tree.insert(
                    "","end",iid=model["model_id"],values=(
                        model["model_id"],str(model.get("created_at") or "").replace("T"," ")[:16],source,
                        f"{int(model.get('training_specimen_count') or 0)} / {int(model.get('validation_specimen_count') or 0)}",
                        quality_text,"Active" if model.get("active") else "Available",
                    ),
                )
            if select and tree.exists(select):tree.selection_set(select);tree.see(select)
        def selected():
            values=tree.selection();return str(values[0]) if values else ""
        def activate():
            model_id=selected()
            if not model_id:return
            try:self.project.activate_structure_model(model_id)
            except Exception as exc:messagebox.showerror("X-ray structure models",str(exc),parent=dialog);return
            reload(model_id);self._refresh_workflow()
        def export_model():
            model_id=selected()
            if not model_id:
                messagebox.showinfo("Export Structure AI","Select a model first.",parent=dialog);return
            target=filedialog.asksaveasfilename(
                parent=dialog,title="Export Structure AI",defaultextension=".zip",
                initialfile=f"{model_id}.zip",filetypes=(("MorphoLabel Structure AI","*.zip"),("ZIP files","*.zip")),
            )
            if not target:return
            try:export_structure_model_package(self.project,target,model_id)
            except Exception as exc:messagebox.showerror("Export Structure AI",str(exc),parent=dialog);return
            messagebox.showinfo("Export Structure AI","Portable model package saved. It can be imported on another computer with the same X-ray structure scheme.",parent=dialog)
        def import_model():
            source=filedialog.askopenfilename(
                parent=dialog,title="Import Structure AI",filetypes=(("MorphoLabel Structure AI","*.zip"),("ZIP files","*.zip")),
            )
            if not source:return
            try:model_id=import_structure_model_package(self.project,source)
            except Exception as exc:messagebox.showerror("Import Structure AI",str(exc),parent=dialog);return
            reload(model_id);self._refresh_workflow()
            messagebox.showinfo("Import Structure AI",f"Imported {model_id}. Select it and choose Make active before prediction or continued training.",parent=dialog)
        def delete():
            model_id=selected()
            if not model_id:return
            if not messagebox.askyesno(
                "Delete Structure AI",f"Delete {model_id} and its managed model files?\n\nModels used as a parent by later training are protected.",
                parent=dialog,default="no",
            ):return
            try:self.project.delete_structure_model(model_id)
            except Exception as exc:messagebox.showerror("Delete Structure AI",str(exc),parent=dialog);return
            reload();self._refresh_workflow()
        actions=ttk.Frame(frame);actions.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(9,0))
        ttk.Button(actions,text="Make active",command=activate).pack(side="left")
        ttk.Button(actions,text="Export…",command=export_model).pack(side="left",padx=(5,0))
        ttk.Button(actions,text="Import…",command=import_model).pack(side="left",padx=(5,0))
        ttk.Button(actions,text="Delete…",command=delete).pack(side="left",padx=(5,0))
        ttk.Button(actions,text="Close",command=dialog.destroy).pack(side="right")
        reload((self.project.active_structure_model() or {}).get("model_id"))

    def _open_structure_review_batch(self,ids):
        ids=[str(value) for value in ids if str(value)]
        if not ids:return False
        self.pass_no.set(1);self.specimen_list.pass_no=1
        state={"pass_no":1,"ids":ids,"position":0}
        self.project.set_ui_state("xray_structure_active_batch",state)
        self._load_specimen(ids[0]);self._refresh_workflow()
        return True

    def predict_structure_batch(self,count):
        if self._busy:return
        model=self.project.active_structure_model()
        if not model:
            messagebox.showinfo("Predict structures","Train or import a Structure AI model first.",parent=self.root);return
        candidates=self.project.structure_prediction_candidate_ids()
        ids=self.project.select_structure_prediction_ids(len(candidates) if count is None else max(1,int(count)))
        if not ids:
            messagebox.showinfo("Predict structures","No eligible unreviewed specimens remain.",parent=self.root);return
        self._busy=True;events=queue.Queue();cancel=threading.Event()
        dialog,label,bar=self._structure_ai_dialog("Predict structures",f"Preparing {len(ids)} specimen(s)…",len(ids))
        ttk.Button(dialog.winfo_children()[0],text="Cancel",command=cancel.set).pack(anchor="e",pady=(8,0))
        def progress(done,total,detail):
            events.put(("progress",int(done),int(total),str(detail)))
        def worker():
            try:events.put(("done",predict_structures(self.project,ids,cancel=cancel,progress=progress,model=model)))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-structure-predict").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait()
                    if event[0]=="progress":
                        bar.configure(value=event[1],maximum=max(1,event[2]));label.configure(text=f"Predicting structures: {event[1]} / {event[2]}")
                    elif event[0]=="error":
                        self._busy=False;dialog.destroy();messagebox.showerror("Predict structures",str(event[1]),parent=self.root);return
                    elif event[0]=="done":
                        self._busy=False;dialog.destroy();result=event[1]
                        success=[row["specimen_id"] for row in result.get("success") or ()]
                        failures=list(result.get("failures") or ())
                        self._refresh_workflow()
                        summary=f"Predicted {len(success)} specimen(s)."
                        if failures:summary+=f"\nFailed: {len(failures)}."
                        if success and messagebox.askyesno("Predict structures",summary+"\n\nReview this batch now?",parent=self.root,default="yes"):
                            self._open_structure_review_batch(success);return
                        messagebox.showinfo("Predict structures",summary,parent=self.root);return
            except queue.Empty:pass
            if dialog.winfo_exists():dialog.after(100,poll)
        dialog.after(100,poll)

    def review_structure_ai(self):
        ids=self.project.structure_ai_review_ids()
        if not ids:
            messagebox.showinfo("Review Structure AI","No AI marker drafts are waiting for review.",parent=self.root);return
        self._open_structure_review_batch(ids)

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
        self.pass_no.set(number);self.specimen_list.pass_no=number;self.selected_specimen_id="";self.refresh()

    def _navigate(self,step):
        batch=self.project.structure_batch(self.pass_no.get())
        if not batch or self.selected_specimen_id not in batch.get("ids",()):return
        result=self.project.move_structure_batch(self.selected_specimen_id,step,self.pass_no.get())
        if result.get("specimen_id"):self._load_specimen(result["specimen_id"])

    def verify_current(self):
        if not self.selected_specimen_id:return False
        try:self.project.verify_annotations(self.selected_specimen_id,self.pass_no.get())
        except ValueError as exc:messagebox.showwarning("Structures incomplete",str(exc),parent=self.root);return False
        except Exception as exc:messagebox.showerror("Verify structures",str(exc),parent=self.root);return False
        self._after_edit("Verified");return True

    def verify_next(self):
        if not self.selected_specimen_id:return
        current=self.selected_specimen_id;batch=self.project.structure_batch(self.pass_no.get())
        if not batch or current not in batch.get("ids",()):return
        if not self.verify_current():return
        result=self.project.move_structure_batch(current,1,self.pass_no.get())
        if result.get("finished"):
            messagebox.showinfo("Structure annotation batch","Batch complete.",parent=self.root);self._refresh_workflow();self._refresh_summary();return
        if result.get("specimen_id"):self._load_specimen(result["specimen_id"])
