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
from app.ui.icons import CONTROL_ICON_SIZE, WORKFLOW_ICON_SIZE, tk_icon
from app.ui.design import ElidedLabel, FlowRow, action_icon, structure_prediction_text, sidebar_width_for_window, dialog_width_for_columns
from app.ui.workflow import WorkflowDock, add_command_separator
from types import SimpleNamespace
from app.ui.photo_list_panel import DEFAULT_SHOW_EXCLUDED, filtered_photo_indices
from app.ui.tooltips import Tooltip
from .xray_crop import oriented_crop
from .xray_icons import VISIBILITY_ICON_SIZE, tk_visibility_icon, tk_xray_icon
from .xray_structure_ai import (
    compare_structure_model_to_human, export_structure_model_package, import_structure_model_package,
    predict_structures, train_structure_model,
)
from .xray_schema import compatible_reference_roles, spatial_series_order
from .xray_structure_display import (
    DEFAULT_LABEL_SIZE, DEFAULT_SIZE, SYMBOL_LABELS, SYMBOL_NAMES,
    draw_xray_marker, draw_xray_role_badges, load_xray_structure_display, marker_style, role_color,
    normalize_xray_structure_display, save_xray_structure_display,
)
from .xray_result_qc import (
    clear_result_review_queue, complete_result_review_item,
    move_result_review_queue, remove_result_review_image, remove_result_review_specimen, result_review_queue,
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
    """Keep counted series first and start/stop markers after them."""
    indexed=list(enumerate(structures or ()))
    def key(item):
        index,structure=item;hotkey=str(structure.get("hotkey") or "").strip()
        numeric=int(hotkey) if hotkey.isdigit() else 999
        return (0 if bool(structure.get("repeated")) else 1,numeric,index)
    return [structure for _index,structure in sorted(indexed,key=key)]


def _structure_shortcuts(structures):
    """Legacy default schemes get consecutive shortcuts in the visible role order."""
    structures=list(structures or ());ordered=_structure_button_order(structures)
    stored=[str(item.get("hotkey") or "").strip() for item in structures]
    default_numeric=(
        len(structures)<=9 and all(key.isdigit() for key in stored)
        and set(stored)=={str(number) for number in range(1,len(structures)+1)}
    )
    if default_numeric:return {str(item["id"]):str(index+1) for index,item in enumerate(ordered)}
    return {str(item["id"]):str(item.get("hotkey") or "").strip() for item in structures}


def _first_structure_id(structures):
    ordered=_structure_button_order(structures)
    return ordered[0]["id"] if ordered else None


def _current_prediction_allowed(project,specimen_id,model,pass_no):
    """Current-only AI follows the specimen currently open for manual work.

    Batch prediction is deliberately stricter; this helper only controls the
    explicit one-specimen action. Any selected confirmed crop in any annotation
    pass may use AI as a starting point, then becomes human-verified only after Apply.
    """
    return bool(specimen_id and model)


_VISIBILITY_LABELS={
    "complete":"Complete",
    "partial":"Partial",
    "not_visible":"Not visible",
    "absent":"Absent",
}
_VISIBILITY_VALUES={label:value for value,label in _VISIBILITY_LABELS.items()}
_VISIBILITY_SYMBOLS={
    "complete":"✓",
    "partial":"◐",
    "not_visible":"⊘",
    "absent":"∅",
}
_VISIBILITY_HELP=(
    "Visibility for the selected marker type. Complete = every visible instance is marked; "
    "Partial = only some visible instances can be marked; Not visible = this structure cannot "
    "be judged on this X-ray; Absent = the structure is truly absent."
)


def _repeatability_diagram(parent):
    """Generic two-pass visual; deliberately not tied to fish or any other taxon."""
    canvas=tk.Canvas(parent,width=430,height=96,bg="#fbfcfd",highlightthickness=1,highlightbackground="#d8dde3")
    def specimen(cx,cy,dots):
        canvas.create_rectangle(cx-68,cy-26,cx+68,cy+26,fill="#f1f4f6",outline="#a5afb7",width=2)
        canvas.create_line(cx-48,cy+9,cx-22,cy-10,cx+4,cy+4,cx+28,cy-15,cx+49,cy+8,fill="#b3bdc5",width=2,smooth=True)
        for x,y in dots:canvas.create_oval(cx+x-4,cy+y-4,cx+x+4,cy+y+4,fill="#256d9e",outline="white",width=1)
    specimen(105,51,[(-42,8),(-20,-8),(4,5),(27,-12),(48,7)])
    specimen(325,51,[(-40,7),(-19,-7),(5,4),(29,-11),(47,8)])
    canvas.create_line(184,51,246,51,fill="#8b98a3",width=2,arrow="last")
    for cx,label in ((104,"1"),(324,"2")):
        canvas.create_oval(cx-12,7,cx+12,31,fill="#ffffff",outline="#c6cdd3")
        canvas.create_text(cx,19,text=label,fill="#27313a",font=("Segoe UI",9,"bold"))
    return canvas


class XRaySpecimenListPanel(ttk.Frame):
    """Compact searchable specimen list matching Crop/Landmarks visual language."""

    def __init__(self,parent,project,on_select,tooltip,on_exclusion=None):
        super().__init__(parent,padding=(7,5))
        self.project=project;self.on_select=on_select;self.tooltip=tooltip;self.on_exclusion=on_exclusion
        self.sample_query=tk.StringVar(master=self);self.specimen_query=tk.StringVar(master=self)
        self.show_excluded=tk.BooleanVar(master=self,value=DEFAULT_SHOW_EXCLUDED)
        self.selected_specimen_id=None;self.pass_no=1;self._rows=[];self.visible_indices=[];self._cache=();self._icons={}

        search=ttk.Frame(self,padding=(0,0,0,4));search.pack(fill="x");search.columnconfigure(0,weight=1);search.columnconfigure(1,weight=1)
        ttk.Label(search,text="Sample",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(search,text="Specimen",style="Muted.TLabel").grid(row=0,column=1,sticky="w",padx=(6,0))
        self.sample_entry=ttk.Entry(search,textvariable=self.sample_query,width=12);self.sample_entry.grid(row=1,column=0,sticky="ew",pady=(2,0))
        self.specimen_entry=ttk.Entry(search,textvariable=self.specimen_query,width=12);self.specimen_entry.grid(row=1,column=1,sticky="ew",padx=(6,0),pady=(2,0))
        tooltip.bind(self.sample_entry,"Find specimens by locality / source subfolder.")
        tooltip.bind(self.specimen_entry,"Find a specimen by plate filename or specimen label.")

        legend=ttk.Frame(self);legend.pack(fill="x",pady=(0,4))
        for color,text in (("#d93025"," not started"),("#e6a700"," draft"),("#188038"," verified")):
            square=tk.Canvas(legend,width=13,height=13,highlightthickness=0,bd=0)
            square.create_rectangle(2,2,10,10,fill="white",outline=color,width=3);square.pack(side="left")
            ttk.Label(legend,text=text,style="Muted.TLabel").pack(side="left",padx=(0,7))
        options=ttk.Frame(self);options.pack(fill="x",pady=(0,3))
        show=ttk.Checkbutton(options,text="Show excluded",variable=self.show_excluded);show.pack(side="left")
        ttk.Label(options,text="× excluded",style="Muted.TLabel").pack(side="right")
        tooltip.bind(show,"Show excluded specimens so they can be inspected or restored.")

        host=ttk.Frame(self);host.pack(fill="both",expand=True)
        self.canvas=PhotoListCanvas(host,height=24,bg="white",status_shape="square")
        scroll=ttk.Scrollbar(host,orient="vertical",command=self.canvas.yview);self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        self.canvas.bind("<<ListboxSelect>>",self._selected)
        action=ttk.Frame(self,padding=(0,5,0,0));action.pack(fill="x")
        self.exclude_button=ttk.Button(
            action,text="Exclude",image=self._action_icon("exclude"),compound="left",
            style="Icon.TButton",command=self.exclude_or_restore,
        )
        self.exclude_button.pack(side="left")
        tooltip.bind(
            self.exclude_button,
            "Exclude only this specimen from active Structure, AI and export workflows without deleting its crop, annotations or history. Select an excluded row and use Restore to bring it back.",
        )
        for variable in (self.sample_query,self.specimen_query,self.show_excluded):variable.trace_add("write",lambda *_:self.refresh(preserve_scroll=True))

    def _action_icon(self,name):
        key=(name,CONTROL_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_icon(self,name,CONTROL_ICON_SIZE)
        return self._icons[key]

    @staticmethod
    def _sample(relative_path):
        parent=Path(str(relative_path)).parent.as_posix()
        return "Root" if parent in {"",".","/"} else parent

    def _catalog(self):
        rows=[]
        allowed=None
        if int(self.pass_no)>1:
            repeat=self.project.structure_repeatability()
            repeat_passes=set()
            if repeat:
                repeat_passes={int(repeat.get("annotation1_pass_no") or 0),int(repeat.get("annotation2_pass_no") or 0)}
            if repeat and repeat.get("schema_current") and int(self.pass_no) in repeat_passes:
                allowed=set(repeat.get("ids") or ())
        for row in self.project.structure_specimens(self.pass_no,include_excluded=True):
            if allowed is not None and row["specimen_id"] not in allowed:continue
            status=str(row.get("annotation_status") or "")
            rows.append({
                **row,"sample_id":self._sample(row["relative_path"]),"source_relpath":row["relative_path"],
                "status_color":"green" if status=="verified" else "yellow" if status else "red",
            })
        return rows

    def _row_data(self,index,row):
        path=Path(str(row["relative_path"]));status=str(row.get("annotation_status") or "");excluded=bool(row.get("excluded"))
        tip="Excluded specimen — scientific data kept; use Restore below." if excluded else ("Verified structures" if status=="verified" else "Crop changed — annotate this specimen again" if status.startswith("stale") else "Saved draft — review required" if status else "Not started")
        return {
            "number":str(int(row.get("workflow_no") or index+1)),"cal":"","has_crop":True,"excluded":excluded,
            "text":f"{row['sample_id']} | {path.name} | specimen {int(row.get('ordinal') or 0)}",
            "status":row["status_color"],"tooltip":tip,"review_warning":False,
        }

    def refresh(self,preserve_scroll=False,reveal=False):
        self._rows=self._catalog()
        self._cache=tuple(
            (str(row["sample_id"]).casefold(),(str(row.get("label") or "")+" "+Path(str(row["relative_path"])).name).casefold())
            for row in self._rows
        )
        yview=self.canvas.yview()[0] if preserve_scroll and self.canvas.rows else None
        self.visible_indices=filtered_photo_indices(
            self._rows,self._cache,self.specimen_query.get(),self.sample_query.get(),show_excluded=self.show_excluded.get()
        )
        self.canvas.set_rows([self._row_data(i,self._rows[i]) for i in self.visible_indices])
        selected_index=next((i for i,row in enumerate(self._rows) if row["specimen_id"]==self.selected_specimen_id),None)
        if selected_index in self.visible_indices:
            visible=self.visible_indices.index(selected_index);self.canvas.selection_set(visible)
            if reveal:self.canvas.see(visible,align_top=True)
        if yview is not None and not reveal:self.canvas.yview_moveto(yview)
        selected_row=self._rows[selected_index] if selected_index is not None and 0<=selected_index<len(self._rows) else None
        excluded=bool((selected_row or {}).get("excluded"))
        self.exclude_button.configure(
            text="Restore" if excluded else "Exclude",
            image=self._action_icon("restore" if excluded else "exclude"),
            state="normal" if selected_row else "disabled",
        )

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

    def exclude_or_restore(self):
        row=next((item for item in self._rows if item["specimen_id"]==self.selected_specimen_id),None)
        if not row:return False
        specimen_id=str(row["specimen_id"]);excluded=bool(row.get("excluded"))
        if excluded:
            if not messagebox.askyesno(
                "Restore specimen","Restore this specimen to active X-ray workflows? Existing crop, annotations and history are unchanged.",
                parent=self,
            ):return False
            self.project.set_specimen_excluded(specimen_id,False)
        else:
            if not messagebox.askyesno(
                "Exclude specimen","Exclude only this specimen from Structure, AI and export workflows? Its crop, annotations and history will be kept.",
                parent=self,default="no",
            ):return False
            self.project.set_specimen_excluded(specimen_id,True)
        if self.on_exclusion:self.on_exclusion(specimen_id)
        else:self.refresh(preserve_scroll=True)
        return True


class XRayStructureWorkspace:
    """Landmarks-style X-ray marker workspace with cached zoom/pan and finite batches."""

    def __init__(
        self,parent,project,on_changed=None,initial_image_id=None,initial_specimen_id=None,
        on_selection=None,on_open_results=None,on_check_results=None,
    ):
        self.parent=parent;self.root=parent.winfo_toplevel();self.project=project;self.on_changed=on_changed or (lambda:None)
        self.on_selection=on_selection or (lambda _image_id,_specimen_id:None);self.on_open_results=on_open_results or (lambda:None)
        self.on_check_results=on_check_results or (lambda:None)
        self.tip=Tooltip(self.root);self.pass_no=tk.IntVar(value=1);self.batch_size=tk.IntVar(value=24)
        self.prediction_batch_size=tk.IntVar(value=24);self._busy=False
        self.selected_specimen_id=str(initial_specimen_id or "");self.preferred_image_id=str(initial_image_id or "")
        self.active_structure_id=None;self.selected_annotation_id=None
        self.crop_image=None;self.photo=None;self.zoom=1.0;self.pan=None;self.pan_drag=None;self._raster_key=None;self._image_item=None;self.current_specimen_excluded=False
        self.annotations=[];self.roles=[];self._drag_annotation=None;self._drag_last_screen=None;self._marker_buttons={};self._icons={}
        self._right_gesture=None;self._menu_icons=[];self._clear_menu_icons=[];self._updating_visibility=False
        self.display_settings=load_xray_structure_display(self.project,self.project.scheme.get("structures",()))
        self._source_cache_id="";self._source_cache=None
        self._key_bind_id=None
        self._build();self._bind_keys();self.refresh()

    def _icon(self,master,name,size=CONTROL_ICON_SIZE):
        key=("core",name,size)
        if key not in self._icons:self._icons[key]=tk_icon(master,name,size)
        return self._icons[key]

    def _xray_icon(self,master,name):
        key=("xray",name,CONTROL_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_xray_icon(master,name,CONTROL_ICON_SIZE)
        return self._icons[key]

    def _marker_button_icon(self,master,structure,style,size=32):
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

    def _visibility_icon(self,master,state,size=VISIBILITY_ICON_SIZE):
        key=("visibility",str(state),int(size))
        if key not in self._icons:self._icons[key]=tk_visibility_icon(master,state,size)
        return self._icons[key]

    def _button(self,parent,text,command,help_text="",icon=None,style="P.TButton"):
        icon=icon or action_icon(text)
        button=ttk.Button(parent,text=text,command=command,style=style,
                          image=self._icon(parent,icon) if icon else "",compound="left")
        if help_text:self.tip.bind(button,help_text)
        return button

    def _build(self):
        outer=ttk.Frame(self.parent);outer.pack(fill="both",expand=True);self.outer=outer
        outer.bind("<Destroy>",self._destroy,add="+")
        panes=ttk.Panedwindow(outer,orient="horizontal");panes.pack(fill="both",expand=True)
        left=ttk.Frame(panes,width=320,height=400);left.pack_propagate(False);main=ttk.Frame(panes);panes.add(left,weight=0);panes.add(main,weight=1);self.panes=panes
        main.grid_propagate(False)
        main.columnconfigure(0,weight=1);main.rowconfigure(3,weight=1)
        self.specimen_list=XRaySpecimenListPanel(left,self.project,self._list_selected,self.tip,self._specimen_exclusion_changed);self.specimen_list.pack(fill="both",expand=True)
        panes.bind("<Configure>",self._set_initial_sash,add="+")
        self.root.after_idle(self._set_initial_sash)

        context=ttk.Frame(main,padding=(6,2));context.grid(row=0,column=0,sticky="ew");context.columnconfigure(0,weight=1)
        context_fields=ttk.Frame(context);context_fields.grid(row=0,column=0,sticky="ew",padx=(0,8));context_fields.columnconfigure(3,weight=1)
        ttk.Label(context_fields,text="Sample:",style="ContextKey.TLabel").grid(row=0,column=0,sticky="w")
        self.locality_value=ttk.Label(context_fields,text="—",style="ContextValue.TLabel");self.locality_value.grid(row=0,column=1,sticky="w",padx=(4,14))
        ttk.Label(context_fields,text="Plate:",style="ContextKey.TLabel").grid(row=0,column=2,sticky="w")
        self.context_label=ElidedLabel(context_fields,text="—",style="ContextValue.TLabel",anchor="w");self.context_label.grid(row=0,column=3,sticky="ew",padx=(4,14))
        ttk.Label(context_fields,text="Specimen №:",style="ContextKey.TLabel").grid(row=0,column=4,sticky="w")
        self.specimen_value=ttk.Label(context_fields,text="—",style="ContextValue.TLabel");self.specimen_value.grid(row=0,column=5,sticky="w",padx=(4,0))
        self.tip.bind(self.context_label,lambda:self.context_label.full_text)
        status_host=ttk.Frame(context);status_host.grid(row=0,column=1,sticky="e")
        self.summary_labels={}
        for key,title in (("verified","Verified"),("draft","Draft"),("unstarted","Not started")):
            label=ttk.Label(status_host,text=f"{title}: 0",style="StatusChip.TLabel")
            label.pack(side="left",padx=(0,2));self.summary_labels[key]=label
        self.save_label=ttk.Label(status_host,text="Current: Not started",style="StatusChip.TLabel");self.save_label.pack(side="left",padx=(3,0))

        header=FlowRow(main,style="Toolbar.TFrame");header.grid(row=1,column=0,sticky="ew",pady=(0,3))
        ttk.Label(header,text="Marker actions:",style="SectionTitle.TLabel").pack(side="left",padx=(0,6))
        self.clear_type_button=ttk.Menubutton(header,text="Clear type…",image=self._icon(header,"clear_type"),compound="left",style="P.TButton")
        self.clear_type_button.pack(side="left",padx=2);self.tip.bind(self.clear_type_button,"Clear one marker type on this specimen.")
        self.clear_all_button=self._button(header,"Clear all…",self.clear_all_markers,"Clear all markers on this specimen.",icon="clear");self.clear_all_button.pack(side="left",padx=2)
        self.apply_separator=ttk.Separator(header,orient="vertical");self.apply_separator.pack(side="left",fill="y",padx=(6,4),pady=3)
        self.apply_button=self._button(header,"Verify specimen",self.verify_current,"Confirm this marker set after human review. In result review, this also advances the existing review queue.",icon="verify")
        self.apply_button.pack(side="left",padx=2)
        self.display_button=self._button(header,"Display…",self.open_display_settings,"Marker colors, shapes, size and labels.",icon="display")
        self.display_button.pack(side="right",padx=(8,2))

        header.relayout()
        self.queue_host=ttk.Frame(main);self.queue_host.grid(row=2,column=0,sticky="ew",pady=(0,3))
        self.review_queue_banner=ttk.Frame(self.queue_host,style="Attention.TFrame",padding=(6,4))
        self.review_queue_label=ElidedLabel(self.review_queue_banner,text="",style="AttentionTitle.TLabel",anchor="w")
        self.review_queue_label.pack(side="left",fill="x",expand=True)
        self.tip.bind(self.review_queue_label,lambda:self.review_queue_label.full_text)
        self._button(self.review_queue_banner,"Previous",lambda:self._move_result_review(-1),"Previous result in this review queue.",icon="previous",style="Nav.TButton").pack(side="left",padx=(6,2))
        self._button(self.review_queue_banner,"Next",lambda:self._move_result_review(1),"Inspect the next result without verifying this one.",icon="next",style="Nav.TButton").pack(side="left",padx=2)
        self._button(self.review_queue_banner,"Close queue",self._close_result_review,"Close this result review queue; all saved annotations and results are kept.",icon="close").pack(side="right",padx=(4,0))
        self.annotation_queue_banner=ttk.Frame(self.queue_host,style="Attention.TFrame",padding=(6,4))
        self.annotation_queue_label=ElidedLabel(self.annotation_queue_banner,text="",style="AttentionTitle.TLabel",anchor="w")
        self.annotation_queue_label.pack(side="left",fill="x",expand=True)
        self._button(self.annotation_queue_banner,"Previous",lambda:self._navigate(-1),"Previous specimen in this annotation batch.",icon="previous",style="Nav.TButton").pack(side="left",padx=(6,2))
        self._button(self.annotation_queue_banner,"Verify & Next",self.verify_next,"Verify this marker set and move to the next specimen in this batch.",icon="verify",style="NavPrimary.TButton").pack(side="left",padx=2)
        self._button(self.annotation_queue_banner,"Close queue",self._close_annotation_batch,"Close navigation through this batch; keep all saved annotations and repeatability passes.",icon="close").pack(side="right",padx=(4,0))

        canvas_host=ttk.Frame(main);canvas_host.grid(row=3,column=0,sticky="nsew");canvas_host.pack_propagate(False)
        self.canvas=tk.Canvas(canvas_host,background="#202020",highlightthickness=0,takefocus=True,cursor="crosshair");self.canvas.pack(fill="both",expand=True)
        for event,handler in (
            ("<Configure>",lambda _e:self._draw()),
            ("<Button-1>",self._canvas_down),("<B1-Motion>",self._canvas_drag),("<ButtonRelease-1>",self._canvas_up),
            ("<Button-3>",self._right_start),("<B3-Motion>",self._right_motion),("<ButtonRelease-3>",self._right_end),
            ("<Button-2>",self._pan_start),("<B2-Motion>",self._pan_motion),("<ButtonRelease-2>",self._pan_end),
            ("<MouseWheel>",self._wheel),
        ):self.canvas.bind(event,handler)
        self.canvas.bind("<Delete>",self.delete_selected);self.canvas.bind("<BackSpace>",self.delete_selected)
        self.prediction_label=ElidedLabel(context,text="",style="Prediction.TLabel",anchor="w")
        self.prediction_text=""
        self.tip.bind(self.prediction_label,lambda:self.prediction_label.full_text)

        marker_dock=ttk.Frame(main,style="WorkflowDock.TFrame",padding=(6,3));marker_dock.grid(row=4,column=0,sticky="ew",pady=(2,0));marker_dock.columnconfigure(1,weight=1)
        ttk.Label(marker_dock,text="Markers:",style="SectionTitle.TLabel").grid(row=0,column=0,sticky="w",padx=(0,6))
        self.marker_host=FlowRow(marker_dock,style="WorkflowDock.TFrame");self.marker_host.grid(row=0,column=1,sticky="ew")

        adapter=SimpleNamespace(ui_icon=lambda name,size:self._icon(main,name,size),tip=self.tip)
        workflow=WorkflowDock(main,adapter,help_factory=lambda host:self._button(host,"Help",self._show_help,"Open the Structures guide."))
        workflow.grid(row=5,column=0,sticky="ew",pady=(2,0));self.workflow_dock=workflow
        one=workflow.add_card("1. Human Repeatability",icon="landmark_repeat",help_text="Measure the same control specimens twice in independent annotation passes.")
        self.repeat_pool_label=ttk.Label(one,text="",style="Muted.TLabel");self.repeat_pool_label.grid(row=0,column=0,sticky="w")
        self.repeat_pass_label=ttk.Label(one,text="",style="Muted.TLabel");self.repeat_pass_label.grid(row=0,column=1,sticky="e",padx=(8,0));one.columnconfigure(1,weight=1)
        self.repeat_button=self._button(one,"Human Repeatability…",self.open_repeatability,"Open the complete human repeatability workflow.");self.repeat_button.grid(row=1,column=0,columnspan=2,sticky="w",pady=(5,0))

        two=workflow.add_card("2. Training data",icon="landmark_training",help_text="Annotation batch: human-verify the main specimen pass for training.")
        self.batch_summary=ttk.Label(two,text="",style="Muted.TLabel");self.batch_summary.grid(row=0,column=0,sticky="w")
        batch_actions=ttk.Frame(two);batch_actions.grid(row=1,column=0,sticky="w",pady=(4,0))
        ttk.Label(batch_actions,text="Batch").pack(side="left")
        ttk.Spinbox(batch_actions,from_=1,to=500,textvariable=self.batch_size,width=5).pack(side="left",padx=(4,0))
        add_command_separator(batch_actions)
        self.batch_button=self._button(batch_actions,"Start batch",self.start_batch,"Start or continue the existing finite annotation batch.");self.batch_button.pack(side="left")

        three=workflow.add_card("3. Train model",icon="landmark_train",help_text="Train from human-verified pass 1. Human Repeatability passes are excluded.")
        model_row=ttk.Frame(three);model_row.grid(row=0,column=0,sticky="ew");three.columnconfigure(0,weight=1)
        self.structure_model_label=ElidedLabel(model_row,text="Active: none",style="StatusChip.TLabel",anchor="w",width=24);self.structure_model_label.pack(side="left")
        add_command_separator(model_row)
        ttk.Label(model_row,text="From").pack(side="left")
        self.training_parent_choice=tk.StringVar(master=three,value="ImageNet ResNet18")
        self.training_parent_box=ttk.Combobox(model_row,textvariable=self.training_parent_choice,values=("ImageNet ResNet18",),width=22,state="readonly")
        self.training_parent_box.pack(side="left",padx=(4,0))
        self.training_summary=ttk.Label(model_row,text="",style="Muted.TLabel");self.training_summary.pack(side="right",padx=(10,0))
        train_actions=ttk.Frame(three);train_actions.grid(row=1,column=0,sticky="w",pady=(3,0))
        self.structure_train_button=self._button(train_actions,"Train",self.train_structure_ai,"Train Structure AI from existing eligible annotations.",style="Primary.TButton");self.structure_train_button.pack(side="left")
        add_command_separator(train_actions)
        self._button(train_actions,"Models…",self.manage_structure_models,"Compare and select saved Structure models.").pack(side="left")

        four=workflow.add_card("4. Predict & review",icon="landmark_apply",help_text="Predict unverified crops, inspect AI drafts, and check calculated trait values.")
        batch_row=ttk.Frame(four);batch_row.grid(row=0,column=0,sticky="w")
        ttk.Label(batch_row,text="Next batch").pack(side="left");ttk.Spinbox(batch_row,from_=1,to=500,textvariable=self.prediction_batch_size,width=4).pack(side="left",padx=(4,0));ttk.Label(batch_row,text="specimens",style="Muted.TLabel").pack(side="left",padx=(4,0))
        predict_actions=ttk.Frame(four);predict_actions.grid(row=1,column=0,sticky="w",pady=(4,0))
        self.predict_current_button=self._button(predict_actions,"Predict current",self.predict_current_structure,"Refresh AI suggestions for this specimen using the existing protection and confirmation rules.");self.predict_current_button.pack(side="left")
        add_command_separator(predict_actions)
        self.structure_predict_next_button=self._button(predict_actions,"Predict next batch",lambda:self.predict_structure_batch(self.prediction_batch_size.get()),"Predict the next eligible specimen crops.",style="Primary.TButton");self.structure_predict_next_button.pack(side="left")
        self.structure_predict_all_button=self._button(predict_actions,"Predict all",lambda:self.predict_structure_batch(None),"Predict all eligible unverified crops; preserve verified annotations.");self.structure_predict_all_button.pack(side="left",padx=(4,0))
        add_command_separator(predict_actions)
        self.structure_review_button=self._button(predict_actions,"Review AI",self.review_structure_ai,"Inspect saved AI drafts before verification.",style="ReviewAction.TButton");self.structure_review_button.pack(side="left")
        self.check_results_button=self._button(predict_actions,"Check results…",self.on_check_results,"Review suspicious calculated trait values.",style="ReviewAction.TButton");self.check_results_button.pack(side="left",padx=(4,0))
        add_command_separator(predict_actions)
        self._button(predict_actions,"Next unfinished",self.next_unfinished,"Open the next unfinished specimen.").pack(side="left")

    def _show_help(self):
        messagebox.showinfo("Structures — quick guide",
            "Place markers on the selected specimen. Click to place; drag to correct; Delete removes a selected marker.\n\n"
            "Use marker visibility to record partial, absent or invisible structures. Right-click a counted marker to assign a compatible reference role.\n\n"
            "Verify specimen confirms the current annotation. In an annotation batch, Verify & Next also advances. Close queue leaves all saved annotations intact.\n\n"
            "Human Repeatability uses separate annotation passes. Train uses the existing eligible main annotations; Review AI opens the saved drafts. Check results reviews calculated trait values.",parent=self.root)

    def continue_annotation_queue(self):
        state=self.project.get_ui_state("xray_structure_active_batch",{}) or {}
        ids=[str(value) for value in state.get("ids") or ()]
        if not ids:return False
        pass_no=max(1,int(state.get("pass_no") or 1));position=max(0,min(len(ids)-1,int(state.get("position") or 0)))
        self.pass_no.set(pass_no);self.specimen_list.pass_no=pass_no
        self._load_specimen(ids[position]);self._refresh_workflow();return True

    def continue_result_review_queue(self):
        state=result_review_queue(self.project)
        if not state:return False
        items=list(state.get("items") or ());position=max(0,min(len(items)-1,int(state.get("position") or 0)))
        specimen_id=str(items[position].get("specimen_id") or "")
        if not specimen_id:return False
        self.pass_no.set(1);self.specimen_list.pass_no=1;self._load_specimen(specimen_id);self._refresh_workflow();return True

    def _close_annotation_batch(self):
        self.project.set_ui_state("xray_structure_active_batch",{})
        self._refresh_workflow()

    def _refresh_prediction_info(self):
        self.prediction_text=structure_prediction_text(self.project,self.selected_specimen_id,self.pass_no.get())
        self.prediction_label.configure(text=self.prediction_text)
        if self.crop_image is not None:self._draw_overlays()

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
            structures=list(self.project.scheme.get("structures",()));shortcuts=_structure_shortcuts(structures)
            structure=next((item for item in structures if shortcuts.get(str(item["id"]))==key),None)
            if structure:
                self._choose_structure(structure["id"]);return "break"

    def _set_initial_sash(self,_event=None):
        try:
            if self.panes.winfo_width()<=1 or getattr(self,"_initial_sash_done",False):return
            width=max(900,self.panes.winfo_width());self.panes.sashpos(0,sidebar_width_for_window(width,self.specimen_list.winfo_reqwidth()))
            self._initial_sash_done=True
        except Exception:pass

    def _sample(self,relative_path):return XRaySpecimenListPanel._sample(relative_path)

    def _set_context(self,item=None):
        values={"locality":"—","plate":"—","specimen":"—"}
        if item is not None:
            image=self.project.source_image(item["image_id"]);path=Path(image["relative_path"])
            workflow_no=self.project.structure_workflow_number(item["specimen_id"])
            values={
                "locality":self._sample(image["relative_path"]),
                "plate":path.name,
                "specimen":str(workflow_no) if workflow_no else f"plate {int(item.get('ordinal') or 0)}",
            }
        self.locality_value.configure(text=values["locality"]);self.context_label.configure(text=values["plate"]);self.specimen_value.configure(text=values["specimen"])

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
        counts={};states={}
        if self.selected_specimen_id:
            for row in self.project.effective_annotations(self.selected_specimen_id,self.pass_no.get()):
                counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
            states=self.project.structure_visibility_states(self.selected_specimen_id,self.pass_no.get(),"human")
        self._marker_buttons={};self._marker_visibility_buttons={};self._marker_visibility_vars={};shortcuts=_structure_shortcuts(structures)
        # Marker and visibility controls share a 32 px pictorial floor. This keeps
        # native Windows button heights identical and makes the four states readable at a glance.
        self._visibility_menu_icons=[]
        for structure in _structure_button_order(structures):
            sid=str(structure["id"]);index=structures.index(structure);style=marker_style(settings,structure,index)
            hotkey=shortcuts.get(sid,"");count=counts.get(sid,0);icon=self._marker_button_icon(self.marker_host,structure,style)
            text=f"{hotkey} · {structure['name']}  {count}" if hotkey else f"{structure['name']}  {count}"
            group=ttk.Frame(self.marker_host,style="WorkflowDock.TFrame");group.pack(side="left",padx=(0,7))
            button=ttk.Button(
                group,text=text,image=icon,compound="left",
                style="MarkerActive.TButton" if sid==self.active_structure_id else "Marker.TButton",
                state="normal" if self.selected_specimen_id and not self.current_specimen_excluded else "disabled",
                command=lambda value=sid:self._choose_structure(value),
            )
            button.pack(side="left");self._marker_buttons[sid]=button
            help_text=(structure.get("description") or structure["name"])+(f" · shortcut {hotkey}" if hotkey else "")
            self.tip.bind(button,help_text)
            current=str(states.get(sid) or "complete")
            visibility_icon=self._visibility_icon(group,current)
            visibility=ttk.Button(
                group,text="",image=visibility_icon,compound="left",
                width=2,style="MarkerStatus.TButton",
                state="normal" if self.selected_specimen_id and not self.current_specimen_excluded else "disabled",
            )
            visibility.pack(side="left",padx=(2,0));self._marker_visibility_buttons[sid]=visibility
            menu=tk.Menu(visibility,tearoff=False)
            state_var=tk.StringVar(master=visibility,value=current);self._marker_visibility_vars[sid]=state_var
            for value,label in _VISIBILITY_LABELS.items():
                menu_icon=self._visibility_icon(menu,value);self._visibility_menu_icons.append(menu_icon)
                menu.add_radiobutton(
                    label=label,image=menu_icon,compound="left",
                    value=value,variable=state_var,
                    command=lambda structure_id=sid,var=state_var:self._set_structure_visibility(
                        structure_id,var.get()
                    ),
                )
            visibility.configure(command=lambda widget=visibility,popup=menu:self._post_marker_visibility_menu(widget,popup))
            self.tip.bind(
                visibility,
                f"{structure['name']} visibility: {_VISIBILITY_LABELS.get(current,'Complete')}. "
                "Complete = all visible instances marked; Partial = only some can be marked; "
                "Not visible = cannot be judged; Absent = truly absent.",
            )
        if not structures:ttk.Label(self.marker_host,text="No structures configured",style="Muted.TLabel").pack(side="left")
        self._refresh_clear_menu(structures,settings,counts)
        self.marker_host.relayout()

    @staticmethod
    def _post_marker_visibility_menu(button,menu):
        """Open the compact visibility menu from a native-height button."""
        try:menu.tk_popup(button.winfo_rootx(),button.winfo_rooty()+button.winfo_height())
        finally:menu.grab_release()

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
        editable=bool(self.selected_specimen_id and not self.current_specimen_excluded)
        self.clear_type_button.configure(menu=menu,state="normal" if editable and any(counts.values()) else "disabled")
        self.clear_all_button.configure(state="normal" if editable and (self.annotations or self.roles) else "disabled")

    def _choose_structure(self,structure_id):
        self.active_structure_id=structure_id;self.selected_annotation_id=None;self._build_marker_buttons();self._draw_overlays();self.canvas.focus_set()

    def _set_structure_visibility(self,structure_id,visibility):
        if not self.selected_specimen_id or self.current_specimen_excluded:return
        structure_id=str(structure_id);visibility=str(visibility)
        if visibility not in _VISIBILITY_LABELS:return
        current=self.project.structure_visibility(
            self.selected_specimen_id,structure_id,self.pass_no.get(),"human",
        )
        if visibility==current:return
        structure=self._structure(structure_id);name=(structure or {}).get("name") or structure_id
        if visibility in {"not_visible","absent"}:
            count=sum(
                1 for row in self.project.effective_annotations(self.selected_specimen_id,self.pass_no.get())
                if row["structure_id"]==structure_id
            )
            if count and not messagebox.askyesno(
                "Structure visibility",
                f"‘{name}’ already has {count} marker(s).\n\n"
                f"Set it to {_VISIBILITY_LABELS[visibility]} and clear those markers?",
                parent=self.root,default="no",
            ):
                self._build_marker_buttons()
                return
            if count:self.project.clear_annotations(self.selected_specimen_id,self.pass_no.get(),structure_id=structure_id)
        self.active_structure_id=structure_id
        self.project.set_structure_visibility(
            self.selected_specimen_id,structure_id,visibility,self.pass_no.get(),"human",
        )
        self._after_edit(f"{name}: {_VISIBILITY_LABELS[visibility]}")

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
        item=self.project.specimen(specimen_id);self.current_specimen_excluded=bool(item.get("excluded"))
        self.preferred_image_id=item["image_id"];self._set_context(item)
        try:
            source=self._source_for(item["image_id"])
            crop=oriented_crop(source,item["crop"],self.project.orientation_policy)
            self.crop_image=_display_ready(crop)
        except Exception as exc:
            messagebox.showerror("Structures",f"Could not open specimen crop:\n{exc}",parent=self.root);self.crop_image=None
        self.annotations=self.project.annotations(specimen_id,self.pass_no.get());self.roles=self.project.annotation_roles(specimen_id,self.pass_no.get())
        self.zoom=1.0;self.pan=None;self.pan_drag=None;self._raster_key=None;self._image_item=None;self.photo=None;self.canvas.delete("all")
        self.specimen_list.select(specimen_id,reveal=False);self._build_marker_buttons();self._update_counts();self._refresh_summary();self._refresh_workflow();self._refresh_prediction_info();self._draw();self._notify_selection();self.canvas.focus_set()

    def _clear(self):
        self.selected_specimen_id="";self.crop_image=self.photo=None;self.annotations=[];self.roles=[];self.current_specimen_excluded=False
        self._image_item=None;self._raster_key=None;self.pan=None;self.canvas.delete("all")
        if self.preferred_image_id:
            try:
                image=self.project.source_image(self.preferred_image_id);path=Path(image["relative_path"])
                values={"locality":self._sample(image["relative_path"]),"plate":path.name,"specimen":"—"}
                text=f"{values['locality']} · {values['plate']} · No confirmed specimen"
                self.context_label.configure(text=text)
            except Exception:self._set_context(None)
            self.canvas.create_text(
                18,18,anchor="nw",fill="white",
                text="No confirmed specimen crop is available on this plate.\nReturn to Crops and apply the crop before Structure annotation.",
                font=("Segoe UI",10,"bold"),
            )
        else:self._set_context(None)
        self._build_marker_buttons();self._update_counts();self._refresh_prediction_info()

    def _refresh_summary(self):
        summary=self.project.annotation_summary(self.pass_no.get())
        labels={"verified":"Verified","draft":"Draft","unstarted":"Not started"}
        for key,label in self.summary_labels.items():label.configure(text=f"{labels[key]}: {summary[key]}")
        state="normal" if self.selected_specimen_id and not self.current_specimen_excluded else "disabled";self.apply_button.configure(state=state)
        model=self.project.active_structure_model()
        can_predict=(not self.current_specimen_excluded) and _current_prediction_allowed(self.project,self.selected_specimen_id,model,self.pass_no.get())
        self.predict_current_button.configure(state="normal" if can_predict else "disabled")

    def _refresh_result_review_banner(self):
        value=result_review_queue(self.project)
        if value is None:
            self.review_queue_banner.pack_forget();return
        items=value["items"];position=int(value["position"]);item=items[position]
        priority="High priority" if item.get("severity")=="high" else "Review"
        checks=int(item.get("issue_count") or 0)
        workflow_no=self.project.structure_workflow_number(item["specimen_id"])
        detail=item.get("top_reason") or "Inspect this specimen and verify when the markers are correct."
        self.review_queue_label.configure(
            text=f"Result review · {position+1} / {len(items)} · {priority} · {checks} check{'s' if checks!=1 else ''} · specimen #{workflow_no or '?'} · {item['sample']} · {item['plate']}"
        )
        self.tip.bind(self.review_queue_label,lambda value=str(detail):value)
        self.review_queue_banner.pack(fill="x")

    def _move_result_review(self,step):
        value,_finished=move_result_review_queue(self.project,step)
        if value is None:return
        current=result_review_queue(self.project)
        if current:
            item=current["items"][int(current["position"])]
            self.pass_no.set(1);self.specimen_list.pass_no=1;self._load_specimen(item["specimen_id"])
        self._refresh_result_review_banner()

    def _close_result_review(self):
        clear_result_review_queue(self.project);self._refresh_result_review_banner()

    def _refresh_workflow(self):
        self._refresh_result_review_banner()
        p1=self.project.annotation_summary(1);current_summary=self.project.annotation_summary(self.pass_no.get());batch=self.project.structure_batch(self.pass_no.get())
        self.batch_summary.configure(text=f"{current_summary['verified']} verified · {current_summary['draft']} draft · {current_summary['unstarted']} not started")
        self.batch_button.configure(text="Continue batch" if batch else "Start batch")
        repeat=self.project.structure_repeatability()
        if repeat:
            self.repeat_pool_label.configure(text=f"{repeat['total']} specimens")
            self.repeat_pass_label.configure(text=f"A1 {repeat['annotation1_verified']}/{repeat['total']} · A2 {repeat['annotation2_verified']}/{repeat['total']}")
        else:
            self.repeat_pool_label.configure(text=f"{p1['verified']} eligible")
            self.repeat_pass_label.configure(text="A1 — · A2 —")
        self.repeat_button.configure(state="normal" if p1["verified"] else "disabled")
        model=self.project.active_structure_model();candidates=len(self.project.structure_prediction_candidate_ids());review=len(self.project.structure_ai_review_ids())
        self.training_summary.configure(text=f"Ready: {p1['verified']} human-verified")
        active_id=(model or {}).get("model_id") or "none"
        self.structure_model_label.configure(text=f"Active: {active_id}")
        parent_values=("ImageNet ResNet18",)+tuple(item["model_id"] for item in self.project.structure_models())
        current_parent=self.training_parent_choice.get()
        preferred_parent=(model or {}).get("model_id") or "ImageNet ResNet18"
        if current_parent not in parent_values:self.training_parent_choice.set(preferred_parent)
        self.training_parent_box.configure(values=parent_values)
        state="normal" if model and self.pass_no.get()==1 else "disabled"
        self.structure_predict_next_button.configure(state=state);self.structure_predict_all_button.configure(state=state)
        self.structure_review_button.configure(state="normal" if review else "disabled")
        current=self.selected_specimen_id;ids=list(batch.get("ids") or ())
        result_queue=result_review_queue(self.project)
        if ids and current in ids and result_queue is None:
            pos=ids.index(current)+1
            self.annotation_queue_label.configure(text=f"Annotation batch · {pos} / {len(ids)}")
            self.annotation_queue_banner.pack(fill="x")
        else:self.annotation_queue_banner.pack_forget()


    def _update_counts(self):
        counts={}
        if self.selected_specimen_id:
            for row in self.project.effective_annotations(self.selected_specimen_id,self.pass_no.get()):
                counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        run=self.project.annotation_run(self.selected_specimen_id,self.pass_no.get(),create=False) if self.selected_specimen_id else None
        current="Verified" if run and run.get("status")=="verified" else "Draft" if run else "Not started"
        self.save_label.configure(text=f"Current: {current}")

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
            index,structure=pair
            rows=spatial_series_order(rows) if structure.get("repeated") else sorted(rows,key=lambda row:(row["sort_order"],row["annotation_id"]))
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
        if self.prediction_text:
            self.canvas.create_text(13,13,anchor="nw",text=self.prediction_text,fill="#202020",font=("Segoe UI",10,"bold"),tags=("structure_hint","prediction_shadow"))
            self.canvas.create_text(12,12,anchor="nw",text=self.prediction_text,fill="#ffdf80",font=("Segoe UI",10,"bold"),tags=("structure_hint","prediction"))

    def _nearest(self,event):
        size=int(self.display_settings.get("size",DEFAULT_SIZE));best=None;limit=max(14,size+8)
        for row in self.annotations:
            sx,sy=self._screen(row["x"],row["y"]);distance=math.hypot(event.x-sx,event.y-sy)
            if distance<=limit and (best is None or distance<best[0]):best=(distance,row)
        return best[1] if best else None

    def _after_edit(self,text="Saved · draft"):
        self.annotations=self.project.annotations(self.selected_specimen_id,self.pass_no.get());self.roles=self.project.annotation_roles(self.selected_specimen_id,self.pass_no.get())
        self.save_label.configure(text=text);self.specimen_list.refresh(preserve_scroll=True);self._build_marker_buttons();self._update_counts();self._refresh_summary();self._refresh_workflow();self._draw_overlays();self._refresh_prediction_info();self.on_changed()

    def _canvas_down(self,event):
        if self.crop_image is None or not self.selected_specimen_id or self.current_specimen_excluded:return
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
        if not self.current_specimen_excluded and gesture["near"] is not None:self._show_role_menu(event,gesture["near"])
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
        if self.current_specimen_excluded:return "break"
        if self.selected_annotation_id:
            self.project.delete_annotation(self.selected_annotation_id);self.selected_annotation_id=None;self._after_edit()
        return "break"

    def clear_marker_category(self,structure_id,name):
        if not self.selected_specimen_id or self.current_specimen_excluded:return
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
        if not self.selected_specimen_id or self.current_specimen_excluded or not (self.annotations or self.roles):return
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
        selected_parent=self.training_parent_choice.get()
        parent_model_id="" if selected_parent=="ImageNet ResNet18" else selected_parent
        def worker():
            try:events.put(("done",train_structure_model(self.project,progress=progress,parent_model_id=parent_model_id)))
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
                        result=event[1];self.training_parent_choice.set(result["model_id"]);metrics=result.get("metrics") or {}
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

    def export_active_structure_ai(self):
        model=self.project.active_structure_model()
        if not model:
            messagebox.showinfo("Export trained AI","Train or import a Structure AI model first.",parent=self.root);return
        target=filedialog.asksaveasfilename(
            parent=self.root,title="Export trained Structure AI",defaultextension=".zip",
            initialfile=f"{model['model_id']}.zip",
            filetypes=(("MorphoLabel trained AI","*.zip"),("ZIP files","*.zip")),
        )
        if not target:return
        try:export_structure_model_package(self.project,target,model["model_id"])
        except Exception as exc:messagebox.showerror("Export trained AI",str(exc),parent=self.root);return
        messagebox.showinfo(
            "Export trained AI",
            "Saved as one portable file containing the trained weights and model metadata. Source X-rays are not included.",
            parent=self.root,
        )

    def import_structure_ai_file(self):
        source=filedialog.askopenfilename(
            parent=self.root,title="Import trained Structure AI",
            filetypes=(("MorphoLabel trained AI","*.zip"),("ZIP files","*.zip")),
        )
        if not source:return
        try:
            model_id=import_structure_model_package(self.project,source)
            self.project.activate_structure_model(model_id)
        except Exception as exc:messagebox.showerror("Import trained AI",str(exc),parent=self.root);return
        self._refresh_workflow();self._refresh_summary()
        messagebox.showinfo(
            "Import trained AI",
            f"Imported and activated {model_id}. The file contained the trained model only; project X-rays were not changed.",
            parent=self.root,
        )

    def manage_structure_models(self):
        dialog=tk.Toplevel(self.root);dialog.title("X-ray structure models");dialog.transient(self.root)
        frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1);frame.rowconfigure(1,weight=1)
        ttk.Label(
            frame,text="Portable Structure AI models · import/export contains weights and model metadata, never source X-rays.",
            style="PageSubtitle.TLabel",
        ).grid(row=0,column=0,sticky="w",pady=(0,8))
        columns=("model","date","source","training","quality","active")
        headers=(
            ("model","Model",205),("date","Created",135),("source","Started from",180),
            ("training","Train / validation",150),("quality","Validation",170),("active","Status",90),
        )
        model_width=dialog_width_for_columns((item[2] for item in headers),dialog.winfo_screenwidth(),chrome=105)
        dialog.geometry(f"{model_width}x420");dialog.minsize(min(model_width,900),300)
        tree=ttk.Treeview(frame,columns=columns,show="headings",selectmode="browse")
        for key,title,width in headers:
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
        def compare_human():
            model_id=selected()
            if not model_id:
                messagebox.showinfo("Compare with human","Select a model first.",parent=dialog);return
            if self._busy:return
            self._busy=True;events=queue.Queue()
            progress_dialog,progress_label,progress_bar=self._structure_ai_dialog(
                "Compare with human","Running the selected model on its validation holdout…",None
            )
            def progress(done,total,specimen_id):
                events.put(("progress",int(done),int(total),str(specimen_id)))
            def worker():
                try:events.put(("done",compare_structure_model_to_human(self.project,model_id,split="val",progress=progress)))
                except Exception as exc:events.put(("error",exc))
            threading.Thread(target=worker,daemon=True,name="xray-structure-human-comparison").start()
            def poll():
                try:
                    while True:
                        event=events.get_nowait()
                        if event[0]=="progress":
                            progress_label.configure(text=f"Validation holdout: {event[1]} / {event[2]} specimens")
                        elif event[0]=="error":
                            self._busy=False
                            try:progress_bar.stop();progress_dialog.destroy()
                            except tk.TclError:pass
                            messagebox.showerror("Compare with human",str(event[1]),parent=dialog);return
                        elif event[0]=="done":
                            self._busy=False
                            try:progress_bar.stop();progress_dialog.destroy()
                            except tk.TclError:pass
                            self._show_structure_model_comparison(event[1],parent=dialog);return
                except queue.Empty:pass
                if progress_dialog.winfo_exists():progress_dialog.after(120,poll)
            progress_dialog.after(120,poll)

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
        ttk.Button(actions,text="Compare with human…",command=compare_human).pack(side="left",padx=(5,0))
        ttk.Button(actions,text="Delete…",command=delete).pack(side="left",padx=(5,0))
        ttk.Button(actions,text="Close",command=dialog.destroy).pack(side="right")
        reload((self.project.active_structure_model() or {}).get("model_id"))

    def _show_structure_model_comparison(self,report,parent=None):
        summary=dict(report.get("summary") or {});traits=list(report.get("traits") or ());structures=list(report.get("structures") or ())
        dialog=tk.Toplevel(parent or self.root);dialog.title("Structure AI vs human");dialog.transient(parent or self.root);dialog.geometry("1120x650");dialog.minsize(900,520)
        outer=ttk.Frame(dialog,padding=12);outer.pack(fill="both",expand=True);outer.columnconfigure(0,weight=1);outer.rowconfigure(3,weight=1)
        ttk.Label(outer,text="Structure AI vs human",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(
            outer,text=f"{summary.get('model_id','')} · validation holdout only · {summary.get('specimens_compared',0)} current human-verified specimens compared. Project data are not changed.",
            style="PageSubtitle.TLabel",wraplength=1060,
        ).grid(row=1,column=0,sticky="w",pady=(2,8))
        def pct(value):
            return "—" if value is None else f"{100*float(value):.1f}%"
        def num(value,digits=3):
            return "—" if value is None else f"{float(value):.{digits}f}"
        exact=f"{int(summary.get('exact_traits') or 0)} / {int(summary.get('exact_traits_total') or 0)} ({pct(summary.get('exact_trait_accuracy'))})"
        all_correct=f"{int(summary.get('all_traits_correct_specimens') or 0)} / {int(summary.get('all_traits_evaluable_specimens') or 0)}"
        role=f"{int(summary.get('reference_role_exact') or 0)} / {int(summary.get('reference_role_total') or 0)} ({pct(summary.get('reference_role_accuracy'))})"
        summary_text=(
            f"Exact trait values: {exact}    ·    All evaluated traits correct: {all_correct}\n"
            f"Repeated count MAE: {num(summary.get('repeated_count_mae'))}    ·    Count bias: {num(summary.get('repeated_count_bias'))}    ·    "
            f"Reference role accuracy: {role}\n"
            f"Marker localization: median {pct(summary.get('localization_median_diag'))} of crop diagonal · p95 {pct(summary.get('localization_p95_diag'))}    ·    "
            f"Macro F1: {num(summary.get('macro_f1'))}"
        )
        ttk.Label(outer,text=summary_text,justify="left",wraplength=1060).grid(row=2,column=0,sticky="w",pady=(0,10))
        notebook=ttk.Notebook(outer);notebook.grid(row=3,column=0,sticky="nsew")
        trait_tab=ttk.Frame(notebook,padding=8);structure_tab=ttk.Frame(notebook,padding=8)
        notebook.add(trait_tab,text="Traits");notebook.add(structure_tab,text="Structures")
        trait_tab.columnconfigure(0,weight=1);trait_tab.rowconfigure(0,weight=1)
        trait_columns=("trait","method","n","accuracy","correct","mae","median","p95")
        trait_tree=ttk.Treeview(trait_tab,columns=trait_columns,show="headings")
        for key,title,width in (
            ("trait","Trait",230),("method","Method",105),("n","Compared",75),("accuracy","Accuracy",95),
            ("correct","Correct / evaluated",135),("mae","MAE",80),("median","Median |error|",105),("p95","P95 |error|",105),
        ):
            trait_tree.heading(key,text=title);trait_tree.column(key,width=width,anchor="w",stretch=key=="trait")
        trait_tree.grid(row=0,column=0,sticky="nsew")
        trait_scroll=ttk.Scrollbar(trait_tab,orient="vertical",command=trait_tree.yview);trait_tree.configure(yscrollcommand=trait_scroll.set);trait_scroll.grid(row=0,column=1,sticky="ns")
        for row in traits:
            accuracy=row.get("accuracy");correct=row.get("correct");evaluated=row.get("evaluated")
            correct_text="—" if correct is None else f"{int(correct)} / {int(evaluated or 0)}"
            trait_tree.insert("","end",values=(
                row.get("abbr") or row.get("name"),row.get("method"),row.get("n",0),pct(accuracy),correct_text,
                num(row.get("mae")),num(row.get("median_abs_error")),num(row.get("p95_abs_error")),
            ))
        structure_tab.columnconfigure(0,weight=1);structure_tab.rowconfigure(0,weight=1)
        structure_columns=("structure","n","prf","count","bias","role","localization")
        structure_tree=ttk.Treeview(structure_tab,columns=structure_columns,show="headings")
        for key,title,width in (
            ("structure","Structure",220),("n","N",55),("prf","Precision / Recall / F1",210),
            ("count","Exact count / MAE",165),("bias","Count bias",90),("role","Role accuracy / MAE",170),
            ("localization","Localization median / p95",180),
        ):
            structure_tree.heading(key,text=title);structure_tree.column(key,width=width,anchor="w",stretch=key=="structure")
        structure_tree.grid(row=0,column=0,sticky="nsew")
        structure_scroll=ttk.Scrollbar(structure_tab,orient="vertical",command=structure_tree.yview);structure_tree.configure(yscrollcommand=structure_scroll.set);structure_scroll.grid(row=0,column=1,sticky="ns")
        for row in structures:
            count_text="—" if row.get("exact_count_accuracy") is None else f"{pct(row.get('exact_count_accuracy'))} / {num(row.get('count_mae'))}"
            role_text="—" if row.get("role_accuracy") is None else f"{pct(row.get('role_accuracy'))} / {num(row.get('role_ordinal_mae'))}"
            loc_text="—" if row.get("localization_median_diag") is None else f"{pct(row.get('localization_median_diag'))} / {pct(row.get('localization_p95_diag'))}"
            structure_tree.insert("","end",values=(
                row.get("name"),row.get("n",0),
                f"{pct(row.get('precision'))} / {pct(row.get('recall'))} / {pct(row.get('f1'))}",
                count_text,num(row.get("count_bias")),role_text,loc_text,
            ))
        note=(
            "Accuracy is shown separately for every discrete or derived trait. For continuous traits it is the share within the scheme's explicit tolerance; without a tolerance, MAE/median/p95 are reported instead of inventing a pass/fail threshold. "
            "Count bias is AI count minus human count. Localization is normalized to the crop diagonal."
        )
        ttk.Label(outer,text=note,style="Muted.TLabel",wraplength=1060).grid(row=4,column=0,sticky="w",pady=(8,0))
        ttk.Button(outer,text="Close",command=dialog.destroy).grid(row=5,column=0,sticky="e",pady=(8,0))

    def _open_structure_review_batch(self,ids):
        ids=[str(value) for value in ids if str(value)]
        if not ids:return False
        self.pass_no.set(1);self.specimen_list.pass_no=1
        state={"pass_no":1,"ids":ids,"position":0}
        self.project.set_ui_state("xray_structure_active_batch",state)
        self._load_specimen(ids[0]);self._refresh_workflow()
        return True

    def _specimen_exclusion_changed(self,specimen_id):
        """Reversible specimen-level exclusion; crop, annotations and provenance stay intact."""
        specimen_id=str(specimen_id);item=self.project.specimen(specimen_id);excluded=bool(item.get("excluded"))
        if excluded:
            remove_result_review_specimen(self.project,specimen_id)
            repeat=self.project.structure_repeatability()
            if repeat and str(repeat.get("status") or "")=="in_progress" and specimen_id in {str(value) for value in repeat.get("ids") or ()}:
                self.project.retire_structure_repeatability(repeat["run_id"])
                self.pass_no.set(1);self.specimen_list.pass_no=1
        self.specimen_list.pass_no=self.pass_no.get()
        self.specimen_list.selected_specimen_id=specimen_id
        self.specimen_list.refresh(preserve_scroll=True,reveal=True)
        available={row["specimen_id"] for row in self.project.structure_specimens(self.pass_no.get(),include_excluded=True)}
        if specimen_id in available:self._load_specimen(specimen_id)
        else:self.refresh()
        self._refresh_workflow()
        return True

    def predict_current_structure(self):
        if self._busy or not self.selected_specimen_id or self.current_specimen_excluded:return
        model=self.project.active_structure_model()
        if not model:
            messagebox.showinfo("Predict current","Train or import a Structure AI model first.",parent=self.root);return
        specimen_id=str(self.selected_specimen_id)
        pass_no=int(self.pass_no.get())
        run=self.project.annotation_run(specimen_id,pass_no,"human",False)
        replacing_verified=bool(run and str(run.get("status") or "")=="verified")
        if replacing_verified and not messagebox.askyesno(
            "Predict current",
            "This annotation is already verified.\n\n"
            "Replace its markers with new AI suggestions? The current verified annotation will be archived first. "
            "After correcting the AI suggestions, press Apply to verify the result again.",
            parent=self.root,default="no",
        ):return
        self._busy=True;events=queue.Queue()
        dialog,label,bar=self._structure_ai_dialog("Predict current","Placing AI marker suggestions on this specimen…",1)
        def worker():
            try:events.put(("done",predict_structures(
                self.project,[specimen_id],model=model,pass_no=pass_no,allow_verified=True
            )))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-structure-predict-current").start()
        def poll():
            try:
                event=events.get_nowait()
            except queue.Empty:
                if dialog.winfo_exists():dialog.after(100,poll)
                return
            self._busy=False
            try:dialog.destroy()
            except tk.TclError:pass
            if event[0]=="error":
                messagebox.showerror("Predict current",str(event[1]),parent=self.root);return
            result=event[1];success=list(result.get("success") or ())
            if not success:
                failures=list(result.get("failures") or ())
                detail=str(failures[0].get("reason")) if failures else "No prediction was produced."
                messagebox.showwarning("Predict current",detail,parent=self.root);return
            self._load_specimen(specimen_id);self._refresh_workflow()
        dialog.after(100,poll)

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
        if self.pass_no.get()>1:
            self.open_repeatability();return
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
        if number>1:
            self.open_repeatability();return
        self.pass_no.set(1);self.specimen_list.pass_no=1;self.selected_specimen_id="";self.refresh()

    def _open_repeatability_pass(self,run,number,launcher=None):
        number=int(number)
        pass_no=int(run["annotation1_pass_no"] if number==1 else run["annotation2_pass_no"])
        if number==2 and int(run.get("annotation1_verified") or 0)<int(run.get("total") or 0):
            messagebox.showinfo(
                "Human repeatability","Finish Annotation 1 for the whole control sample before starting Annotation 2.",
                parent=launcher or self.root,
            );return False
        ids=list(run.get("ids") or ())
        if not ids:return False
        remaining=[]
        for specimen_id in ids:
            current=self.project.annotation_run(specimen_id,pass_no,"human",False)
            if not current or str(current.get("status") or "")!="verified":remaining.append(specimen_id)
        browse=remaining or ids
        self.pass_no.set(pass_no);self.specimen_list.pass_no=pass_no
        self.project.set_ui_state("xray_structure_active_batch",{"pass_no":pass_no,"ids":browse,"position":0})
        self.selected_specimen_id="";self.refresh()
        if browse:self._load_specimen(browse[0])
        if launcher is not None:
            try:launcher.destroy()
            except tk.TclError:pass
        return True

    def open_repeatability(self):
        run=self.project.structure_repeatability()
        if run and not run.get("schema_current"):
            messagebox.showwarning(
                "Human repeatability",
                "The trait scheme changed after this repeatability sample was created. The saved run is kept for audit; start a new sample under the current trait scheme.",
                parent=self.root,
            )
        dialog=tk.Toplevel(self.root);dialog.title("Human repeatability");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1)
        ttk.Label(frame,text="Human repeatability",font=("Segoe UI",11,"bold")).grid(row=0,column=0,sticky="w")
        _repeatability_diagram(frame).grid(row=1,column=0,sticky="ew",pady=(8,8))
        ttk.Label(
            frame,text="Annotate the same randomly selected specimens twice independently. This estimates your own counting and marker-placement error.",
            justify="left",wraplength=600,
        ).grid(row=2,column=0,sticky="w",pady=(0,2))
        ttk.Label(
            frame,text="Annotation 2 never shows Annotation 1. Both control annotations are separate from the main training annotation.",
            justify="left",wraplength=600,style="Muted.TLabel",
        ).grid(row=3,column=0,sticky="w",pady=(0,10))

        eligible=int(self.project.annotation_summary(1)["verified"]);default=min(10,eligible);count=tk.IntVar(master=dialog,value=default or 0)
        sample=ttk.LabelFrame(frame,text="Sample size",padding=(10,8));sample.grid(row=4,column=0,sticky="ew");sample.columnconfigure(3,weight=1)
        ttk.Label(sample,text="Specimens").grid(row=0,column=0,sticky="w")
        spin=ttk.Spinbox(sample,from_=1,to=max(1,eligible),textvariable=count,width=5);spin.grid(row=0,column=1,sticky="w",padx=(8,10))
        sample_note=ttk.Label(sample,text="",style="Muted.TLabel");sample_note.grid(row=1,column=0,columnspan=4,sticky="w",pady=(5,0))
        new_sample=ttk.Button(sample,text="Start new sample");new_sample.grid(row=0,column=2,sticky="w");new_sample.grid_remove()

        passes=ttk.Frame(frame);passes.grid(row=5,column=0,sticky="ew",pady=(10,0));passes.columnconfigure(0,weight=1);passes.columnconfigure(1,weight=1)
        one_box=ttk.LabelFrame(passes,text="Annotation 1",padding=(10,8));one_box.grid(row=0,column=0,sticky="nsew",padx=(0,5))
        two_box=ttk.LabelFrame(passes,text="Annotation 2",padding=(10,8));two_box.grid(row=0,column=1,sticky="nsew",padx=(5,0))
        one_status=ttk.Label(one_box,text="",style="Muted.TLabel");one_status.pack(anchor="w")
        two_status=ttk.Label(two_box,text="",style="Muted.TLabel");two_status.pack(anchor="w")
        one_open=ttk.Button(one_box,text="Start Annotation 1");one_open.pack(anchor="w",pady=(8,0))
        two_open=ttk.Button(two_box,text="Start Annotation 2");two_open.pack(anchor="w",pady=(8,0))
        actions=ttk.Frame(frame);actions.grid(row=6,column=0,sticky="ew",pady=(12,0))
        results=ttk.Button(actions,text="Results…",command=lambda:self.show_repeatability_results((run or {}).get("run_id")))
        results.pack(side="left");ttk.Button(actions,text="Close",command=dialog.destroy).pack(side="right")

        def clamp_count():
            try:value=int(count.get())
            except (TypeError,ValueError):value=default or 1
            value=max(1,min(max(1,eligible),value)) if eligible else 0
            count.set(value);return value

        def refresh():
            nonlocal run
            if run:run=self.project.structure_repeatability(run["run_id"])
            if run and run.get("status")=="retired":run=None
            if run:
                total=int(run["total"]);count.set(total);new_sample.grid()
                sample_note.configure(text=f"Current run: {total} specimens · recommended default: 10 · eligible: {eligible}. Start new sample keeps this run in audit history.")
                a1=int(run.get("annotation1_verified") or 0);a2=int(run.get("annotation2_verified") or 0)
                one_status.configure(text=f"{a1} / {total} specimens complete")
                two_status.configure(text=f"{a2} / {total} specimens complete")
                one_open.configure(text="Review Annotation 1" if a1>=total else "Continue Annotation 1" if a1 else "Start Annotation 1",state="normal")
                two_open.configure(text="Review Annotation 2" if a2>=total else "Continue Annotation 2" if a2 else "Start Annotation 2",state="normal" if a1>=total else "disabled")
                results.configure(state="normal" if a1 and a2 else "disabled")
            else:
                clamp_count();new_sample.grid_remove()
                sample_note.configure(text=f"Recommended default: 10 · eligible human-verified specimens: {eligible}. Choose the sample size before Annotation 1.")
                one_status.configure(text="Not started");two_status.configure(text="Not started")
                one_open.configure(text="Start Annotation 1",state="normal" if eligible else "disabled")
                two_open.configure(text="Start Annotation 2",state="disabled");results.configure(state="disabled")

        def ensure_run():
            nonlocal run
            if run and run.get("schema_current"):return run
            if not eligible:return None
            try:run=self.project.start_structure_repeatability(clamp_count(),seed=42)
            except Exception as exc:
                messagebox.showerror("Human repeatability",str(exc),parent=dialog);return None
            refresh();self._refresh_workflow();return run

        def open_pass(number):
            current=ensure_run()
            if current:self._open_repeatability_pass(current,number,launcher=dialog)

        def start_new():
            nonlocal run
            if run and run.get("status")=="in_progress":
                if not messagebox.askyesno(
                    "Start new sample",
                    "Start a new repeatability sample?\n\nThe current run will be retired from active use but kept in the audit history.",
                    parent=dialog,default="no",
                ):return
            if run:
                try:self.project.retire_structure_repeatability(run["run_id"])
                except Exception as exc:messagebox.showerror("Human repeatability",str(exc),parent=dialog);return
            run=None
            try:run=self.project.start_structure_repeatability(clamp_count(),seed=42)
            except Exception as exc:messagebox.showerror("Human repeatability",str(exc),parent=dialog);return
            refresh();self._refresh_workflow()

        one_open.configure(command=lambda:open_pass(1));two_open.configure(command=lambda:open_pass(2));new_sample.configure(command=start_new)
        refresh();dialog.grab_set()

    def show_repeatability_results(self,run_id=None):
        metrics=self.project.structure_repeatability_metrics(run_id)
        run=metrics.get("run")
        if not run:
            messagebox.showinfo("Human repeatability","No repeatability sample has been started.",parent=self.root);return
        dialog=tk.Toplevel(self.root);dialog.title("Human repeatability");dialog.transient(self.root);dialog.geometry("850x440")
        frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1);frame.rowconfigure(2,weight=1)
        ttk.Label(frame,text="Human repeatability",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(
            frame,text=(
                f"Annotation 1: {run['annotation1_verified']} / {run['total']} · Annotation 2: {run['annotation2_verified']} / {run['total']}. "
                "Counts compare two blind manual annotations; reference-role agreement compares the selected element position within its series."
            ),
            style="PageSubtitle.TLabel",wraplength=810,
        ).grid(row=1,column=0,sticky="w",pady=(2,9))
        columns=("structure","n","exact","mae","position","role")
        tree=ttk.Treeview(frame,columns=columns,show="headings")
        for key,title,width in (
            ("structure","Structure",220),("n","Compared",80),("exact","Exact count",105),
            ("mae","Count MAE",95),("position","Mean marker difference",150),("role","Same role position",130),
        ):
            tree.heading(key,text=title);tree.column(key,width=width,anchor="w",stretch=key=="structure")
        tree.grid(row=2,column=0,sticky="nsew")
        for row in metrics.get("structures") or ():
            exact=row.get("exact_count_accuracy");mae=row.get("count_mae");distance=row.get("mean_marker_difference");role=row.get("role_same_ordinal_accuracy")
            tree.insert("","end",values=(
                row["name"],row["specimens"],
                "—" if exact is None else f"{100*exact:.1f}%",
                "—" if mae is None else f"{mae:.3f}",
                "—" if distance is None else f"{distance:.4f}",
                "—" if role is None else f"{100*role:.1f}%",
            ))
        ttk.Button(frame,text="Close",command=dialog.destroy).grid(row=3,column=0,sticky="e",pady=(9,0))

    def _navigate(self,step):
        batch=self.project.structure_batch(self.pass_no.get())
        if not batch or self.selected_specimen_id not in batch.get("ids",()):return
        result=self.project.move_structure_batch(self.selected_specimen_id,step,self.pass_no.get())
        if result.get("specimen_id"):self._load_specimen(result["specimen_id"])

    def verify_current(self):
        if not self.selected_specimen_id or self.current_specimen_excluded:return False
        try:self.project.verify_annotations(self.selected_specimen_id,self.pass_no.get())
        except ValueError as exc:messagebox.showwarning("Structures incomplete",str(exc),parent=self.root);return False
        except Exception as exc:messagebox.showerror("Verify structures",str(exc),parent=self.root);return False
        self._after_edit("Verified")
        current=result_review_queue(self.project)
        if self.pass_no.get()==1 and current and str(current["items"][int(current["position"])].get("specimen_id"))==str(self.selected_specimen_id):
            value,_finished=complete_result_review_item(self.project)
            next_queue=result_review_queue(self.project)
            if next_queue:
                next_item=next_queue["items"][int(next_queue["position"])];self._refresh_result_review_banner();self._load_specimen(next_item["specimen_id"])
            else:self._refresh_result_review_banner()
        return True

    def verify_next(self):
        if not self.selected_specimen_id:return
        current=self.selected_specimen_id;batch=self.project.structure_batch(self.pass_no.get())
        if not batch or current not in batch.get("ids",()):return
        if not self.verify_current():return
        result=self.project.move_structure_batch(current,1,self.pass_no.get())
        if result.get("finished"):
            messagebox.showinfo("Structure annotation batch","Batch complete.",parent=self.root);self._refresh_workflow();self._refresh_summary();return
        if result.get("specimen_id"):self._load_specimen(result["specimen_id"])
