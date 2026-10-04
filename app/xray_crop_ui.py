"""Tk workspace for the X-ray plate-to-specimen crop workflow."""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import uuid
from pathlib import Path

from PIL import Image, ImageTk

from app.photo_list import PhotoListCanvas
from app.ui.dialogs import center
from app.ui.icons import CONTROL_ICON_SIZE, WORKFLOW_ICON_SIZE, tk_icon
from app.ui.photo_list_panel import filtered_photo_indices, photo_search_cache
from app.ui.tooltips import Tooltip
from app.ui.design import ElidedLabel, FlowRow, action_icon, build_context_row, prediction_stamp, sidebar_width_for_window, dialog_width_for_columns
from app.ui.workflow import WorkflowDock, add_command_separator
from types import SimpleNamespace
from .xray_crop import crop_corners, crop_from_geometry, detect_specimens, display_preview
from .xray_detector import predict_plates, train_detector
from .xray_icons import tk_xray_icon


def crop_flip_button_state(crop_selected):
    """The flip controls depend only on whether a crop is selected."""
    return "normal" if crop_selected else "disabled"


class PlateCropEditSession:
    """In-memory edits for one plate; persistence happens only on explicit confirmation."""

    def __init__(self, specimens=(), selected_id=None):
        self.load(specimens, selected_id=selected_id)

    def load(self, specimens, selected_id=None):
        self.items={}
        for raw in specimens:
            item=dict(raw);item["crop"]=dict(raw.get("crop") or {})
            self.items[item["specimen_id"]]=item
        self.new_ids=set();self.dirty_ids=set();self.deleted_ids=set()
        self.selected_id=selected_id if selected_id in self.items else None

    def active_items(self):
        return sorted(
            (item for specimen_id,item in self.items.items() if specimen_id not in self.deleted_ids),
            key=lambda item:(int(item.get("ordinal") or 0),str(item.get("label") or "")),
        )

    def item(self, specimen_id=None):
        specimen_id=specimen_id or self.selected_id
        if specimen_id in self.deleted_ids:return None
        return self.items.get(specimen_id)

    def select(self, specimen_id):
        self.selected_id=specimen_id if specimen_id in self.items and specimen_id not in self.deleted_ids else None
        return self.selected_id

    def add(self, crop):
        specimen_id=f"draft:{uuid.uuid4()}"
        ordinal=1+max((int(item.get("ordinal") or 0) for item in self.active_items()),default=0)
        self.items[specimen_id]={
            "specimen_id":specimen_id,"label":f"New {ordinal}","ordinal":ordinal,
            "crop":dict(crop),"crop_source":"manual","crop_status":"proposed","model_id":"","excluded":0,
        }
        self.new_ids.add(specimen_id);self.selected_id=specimen_id
        return specimen_id

    def update_selected(self, crop):
        item=self.item()
        if item is None:return False
        previous=dict(item.get("crop") or {});updated=dict(crop)
        for key in ("head_side","bottom_side","orientation_source","orientation_model_id"):
            if key in previous:updated[key]=previous[key]
        updated["orientation_verified"]=False
        item["crop"]=updated
        if self.selected_id not in self.new_ids:self.dirty_ids.add(self.selected_id)
        return True

    def _flip(self,axis):
        item=self.item()
        if item is None:return False
        crop=dict(item.get("crop") or {})
        if axis=="horizontal":crop["head_side"]="right" if crop.get("head_side","left")=="left" else "left"
        elif axis=="vertical":crop["bottom_side"]="top" if crop.get("bottom_side","bottom")=="bottom" else "bottom"
        else:return False
        crop["orientation_source"]="human";crop["orientation_verified"]=False
        crop.pop("orientation_confidence",None);item["crop"]=crop
        if self.selected_id not in self.new_ids:self.dirty_ids.add(self.selected_id)
        return True

    def flip_horizontal(self):return self._flip("horizontal")
    def flip_vertical(self):return self._flip("vertical")

    def delete_selected(self):
        specimen_id=self.selected_id
        if specimen_id is None:return False
        if specimen_id in self.new_ids:
            self.new_ids.remove(specimen_id);self.items.pop(specimen_id,None)
        else:
            self.deleted_ids.add(specimen_id);self.dirty_ids.discard(specimen_id)
        self.selected_id=None
        return True

    @property
    def dirty(self):
        return bool(self.new_ids or self.dirty_ids or self.deleted_ids)

    def changes(self):
        return {
            "edits":[
                {"specimen_id":specimen_id,"crop":dict(self.items[specimen_id]["crop"])}
                for specimen_id in sorted(self.dirty_ids)
                if specimen_id in self.items and specimen_id not in self.deleted_ids
            ],
            "new_crops":[
                {"client_id":specimen_id,"crop":dict(self.items[specimen_id]["crop"])}
                for specimen_id in sorted(self.new_ids)
                if specimen_id in self.items
            ],
            "removed_ids":sorted(self.deleted_ids),
        }


def apply_and_confirm_plate(project,image_id,session):
    """Persist the current plate exactly once, then make it human training truth."""
    selected=session.selected_id;result={"id_map":{}}
    if session.dirty:
        changes=session.changes()
        result=project.apply_plate_crop_edits(
            image_id,edits=changes["edits"],new_crops=changes["new_crops"],removed_ids=changes["removed_ids"],
        )
        selected=result.get("id_map",{}).get(selected,selected)
    project.confirm_plate(image_id,"human")
    return selected


class XRayPlateListPanel(ttk.Frame):
    """Landmarks-style searchable plate sidebar backed by XRayProject."""

    def __init__(self,parent,project,on_select,tooltip,on_exclusion=None):
        super().__init__(parent,padding=(7,5))
        self.project=project;self.on_select=on_select;self.tooltip=tooltip;self.on_exclusion=on_exclusion
        self.sample_query=tk.StringVar(master=self);self.image_query=tk.StringVar(master=self);self.show_excluded=tk.BooleanVar(master=self,value=True)
        self.selected_image_id=None;self.visible_indices=[];self._rows=[];self._cache=();self._icons={}

        search=ttk.Frame(self,padding=(0,0,0,4));search.pack(fill="x");search.columnconfigure(0,weight=1);search.columnconfigure(1,weight=1)
        ttk.Label(search,text="Sample",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(search,text="Plate",style="Muted.TLabel").grid(row=0,column=1,sticky="w",padx=(6,0))
        self.sample_entry=ttk.Entry(search,textvariable=self.sample_query,width=12);self.sample_entry.grid(row=1,column=0,sticky="ew",pady=(2,0))
        self.image_entry=ttk.Entry(search,textvariable=self.image_query,width=12);self.image_entry.grid(row=1,column=1,sticky="ew",padx=(6,0),pady=(2,0))
        tooltip.bind(self.sample_entry,"Find X-rays by source subfolder / sample.")
        tooltip.bind(self.image_entry,"Find an X-ray by filename.")

        legend=ttk.Frame(self);legend.pack(fill="x",pady=(0,4))
        states=ttk.Frame(legend);states.pack(fill="x")
        for color,text in (("#d93025"," unresolved"),("#e6a700"," review"),("#188038"," verified")):
            square=tk.Canvas(states,width=13,height=13,highlightthickness=0,bd=0)
            square.create_rectangle(2,2,10,10,fill="white",outline=color,width=3);square.pack(side="left")
            ttk.Label(states,text=text,style="Muted.TLabel").pack(side="left",padx=(0,7))
        options=ttk.Frame(legend);options.pack(fill="x",pady=(2,0))
        show=ttk.Checkbutton(options,text="Show excluded",variable=self.show_excluded);show.pack(side="left")
        tooltip.bind(show,"Include excluded X-rays in the list.")

        list_host=ttk.Frame(self);list_host.pack(fill="both",expand=True)
        self.canvas=PhotoListCanvas(list_host,height=24,bg="white",status_shape="square")
        self.scrollbar=ttk.Scrollbar(list_host,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left",fill="both",expand=True);self.scrollbar.pack(side="right",fill="y")
        self.canvas.bind("<<ListboxSelect>>",self._selected)

        action=ttk.Frame(self,padding=(0,5,0,0));action.pack(fill="x")
        self.exclude_button=ttk.Button(action,text="Exclude",image=self._action_icon("exclude"),compound="left",style="Icon.TButton",command=self.exclude_or_restore)
        self.exclude_button.pack(side="left")
        tooltip.bind(self.exclude_button,"Exclude this plate from active X-ray workflows without deleting crops, models or provenance.")

        for variable in (self.sample_query,self.image_query,self.show_excluded):
            variable.trace_add("write",lambda *_:self.refresh(preserve_scroll=True))

    def _action_icon(self,name):
        key=(name,CONTROL_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_icon(self,name,CONTROL_ICON_SIZE)
        return self._icons[key]

    @staticmethod
    def _sample(relative_path):
        parent=Path(str(relative_path)).parent.as_posix()
        return "Root" if parent in {"",".","/"} else parent

    def _catalog_rows(self):
        images=self.project.source_images();specimens=self.project.specimens()
        by_image={}
        for item in specimens:
            if item.get("excluded"):continue
            by_image.setdefault(item["image_id"],[]).append(item)
        totals={}
        for row in images:totals[self._sample(row["relative_path"])]=totals.get(self._sample(row["relative_path"]),0)+1
        positions={}
        result=[]
        for row in images:
            sample=self._sample(row["relative_path"]);positions[sample]=positions.get(sample,0)+1
            items=by_image.get(row["image_id"],[])
            status="green" if row.get("crop_reviewed") else "yellow" if items else "red"
            tooltip=("Excluded" if row.get("excluded") else "Verified X-ray crops" if status=="green" else "Crop review required" if status=="yellow" else "No specimen crops yet")
            result.append({
                **row,"sample_id":sample,"source_relpath":row["relative_path"],"status_color":status,
                "has_crop":bool(items),"specimen_count":len(items),"index_in_sample":positions[sample],"total_in_sample":totals[sample],
                "tooltip":tooltip,
            })
        return result

    def _row_data(self,index,row):
        path=Path(str(row["relative_path"]));sample=row["sample_id"];excluded=bool(row.get("excluded"))
        return {
            "number":str(index+1),"cal":"","has_crop":bool(row.get("has_crop")),"excluded":excluded,
            "text":f"{sample} | {path.name} ({row['index_in_sample']} | {row['total_in_sample']}) · {row['specimen_count']}",
            "status":row.get("status_color","red"),"tooltip":row.get("tooltip",""),"review_warning":False,
        }

    def refresh(self,preserve_scroll=False,reveal=False):
        self._rows=self._catalog_rows()
        self._cache=photo_search_cache(self._rows)
        yview=self.canvas.yview()[0] if preserve_scroll and self.canvas.rows else None
        self.visible_indices=filtered_photo_indices(
            self._rows,self._cache,self.image_query.get(),self.sample_query.get(),show_excluded=self.show_excluded.get(),
        )
        self.canvas.set_rows([self._row_data(i,self._rows[i]) for i in self.visible_indices])
        selected_index=next((i for i,row in enumerate(self._rows) if row["image_id"]==self.selected_image_id),None)
        if selected_index in self.visible_indices:
            visible=self.visible_indices.index(selected_index);self.canvas.selection_set(visible)
            if reveal:self.canvas.see(visible)
        if yview is not None and not reveal:self.canvas.yview_moveto(yview)
        row=next((row for row in self._rows if row["image_id"]==self.selected_image_id),None)
        excluded=bool((row or {}).get("excluded"))
        self.exclude_button.configure(
            text="Restore" if excluded else "Exclude",image=self._action_icon("restore" if excluded else "exclude"),
            state="normal" if row else "disabled",
        )

    def select(self,image_id,reveal=True):
        self.selected_image_id=str(image_id) if image_id else None
        selected_index=next((i for i,row in enumerate(self._rows) if row["image_id"]==self.selected_image_id),None)
        if selected_index not in self.visible_indices:
            self.refresh(preserve_scroll=True,reveal=False);return
        visible=self.visible_indices.index(selected_index);self.canvas.selection_set(visible)
        if reveal:self.canvas.see(visible)
        row=self._rows[selected_index];excluded=bool(row.get("excluded"))
        self.exclude_button.configure(
            text="Restore" if excluded else "Exclude",image=self._action_icon("restore" if excluded else "exclude"),
            state="normal",
        )

    def visible_ids(self):
        return [self._rows[index]["image_id"] for index in self.visible_indices]

    def _selected(self,_event=None):
        selection=self.canvas.curselection()
        if not selection:return
        visible=selection[0]
        if not 0<=visible<len(self.visible_indices):return
        row=self._rows[self.visible_indices[visible]]
        # Match the Landmarks list: excluded rows stay inspectable/selectable
        # so the same Exclude button can become Restore. Workflow navigation
        # still skips excluded plates.
        self.selected_image_id=row["image_id"];excluded=bool(row.get("excluded"))
        self.exclude_button.configure(
            text="Restore" if excluded else "Exclude",image=self._action_icon("restore" if excluded else "exclude"),
            state="normal",
        )
        self.on_select(row["image_id"])

    def navigate(self,step):
        ids=self.visible_ids()
        if not ids:return False
        current=self.selected_image_id
        try:position=ids.index(current)
        except ValueError:position=-1 if int(step)>0 else 0
        direction=1 if int(step)>=0 else -1
        for offset in range(1,len(ids)+1):
            candidate=ids[(position+direction*offset)%len(ids)]
            row=next((item for item in self._rows if item["image_id"]==candidate),None)
            if row and not row.get("excluded"):
                self.selected_image_id=candidate;self.on_select(candidate);self.select(candidate,reveal=True);return True
        return False

    def exclude_or_restore(self):
        row=next((item for item in self._rows if item["image_id"]==self.selected_image_id),None)
        if not row:return
        excluded=bool(row.get("excluded"))
        if excluded:
            if not messagebox.askyesno("Restore X-ray","Restore this plate to active X-ray workflows? Existing scientific data are unchanged.",parent=self):return
            self.project.set_source_excluded(row["image_id"],False)
        else:self.project.set_source_excluded(row["image_id"],True)
        if self.on_exclusion:self.on_exclusion(row["image_id"],not excluded)
        self.refresh(preserve_scroll=True,reveal=True)


class XRayCropWorkspace:
    """Landmarks-style Crop workspace with multiple specimens on one X-ray plate."""

    def __init__(self,parent,project,on_changed=None,initial_image_id=None,initial_specimen_id=None,on_selection=None):
        self.parent=parent;self.root=parent.winfo_toplevel();self.project=project;self.on_changed=on_changed or (lambda:None)
        self.on_selection=on_selection or (lambda _image_id,_specimen_id:None)
        self.selected_image_id=None;self.session=PlateCropEditSession()
        self._preferred_image_id=str(initial_image_id or "");self._preferred_specimen_id=str(initial_specimen_id or "")
        self.preview=self.photo=None;self.preview_original_size=(1,1);self.display_scale=1.0;self.offset=(0,0);self._photo_key=None
        self.zoom=1.0;self.pan=None;self.pan_drag=None
        self._busy=False;self._queue_active=False;self._drag_mode=None;self._drag_anchor=None;self._drag_initial=None;self._drag_changed=False;self._drawing_crop=None
        self._icons={};self.training_batch_size=tk.IntVar(value=6);self.prediction_batch_size=tk.IntVar(value=6);self._tip=Tooltip(self.root)
        self._build();self.refresh(preserve_plate=False)
        self.root.bind("<Return>",self._enter_batch,add="+")

    @property
    def selected_specimen_id(self):return self.session.selected_id

    def _button(self,parent,text,command,help_text="",style=None,icon=None):
        icon=icon or action_icon(text)
        image=(self._xray_icon(parent,icon,CONTROL_ICON_SIZE) if icon in {"flip_horizontal","flip_vertical"} else self._icon(parent,icon,CONTROL_ICON_SIZE)) if icon else ""
        button=ttk.Button(parent,text=text,command=command,style=style or "P.TButton",image=image,compound="left" if icon else "none")
        if help_text:self._tip.bind(button,help_text)
        return button

    def _icon(self,master,name,size=WORKFLOW_ICON_SIZE):
        key=("core",name,size)
        if key not in self._icons:self._icons[key]=tk_icon(master,name,size)
        return self._icons[key]

    def _xray_icon(self,master,name,size=CONTROL_ICON_SIZE):
        key=("xray",name,size)
        if key not in self._icons:self._icons[key]=tk_xray_icon(master,name,size)
        return self._icons[key]

    def _tool_icon_button(self,parent,name,command,help_text):
        button=ttk.Button(parent,text="",image=self._xray_icon(parent,name),style="Icon.TButton",command=command,width=3)
        self._tip.bind(button,help_text);return button

    def _build(self):
        outer=ttk.Frame(self.parent,padding=(0,0));outer.pack(fill="both",expand=True)
        panes=ttk.Panedwindow(outer,orient="horizontal");panes.pack(fill="both",expand=True)
        sidebar_host=ttk.Frame(panes,width=320,height=400);sidebar_host.pack_propagate(False);main=ttk.Frame(panes)
        main.grid_propagate(False)
        panes.add(sidebar_host,weight=0);panes.add(main,weight=1)
        self.panes=panes;main.columnconfigure(0,weight=1);main.rowconfigure(2,weight=1)

        self.plate_list=XRayPlateListPanel(sidebar_host,self.project,self._list_selected,self._tip,self._source_exclusion_changed)
        self.plate_list.pack(fill="both",expand=True)
        panes.bind("<Configure>",self._set_initial_sash,add="+")
        self.root.after_idle(lambda:self._set_initial_sash())

        header=ttk.Frame(main);header.grid(row=0,column=0,sticky="ew",pady=(0,3));header.columnconfigure(0,weight=1)
        context_fields,context_values=build_context_row(header,("Sample","Plate","Specimen №"));context_fields.grid(row=0,column=0,sticky="w",padx=6,pady=(1,3))
        self.sample_value=context_values["Sample"];self.context_label=context_values["Plate"];self.specimen_value=context_values["Specimen №"];self.crop_value=self.specimen_value
        self.prediction_text=""
        status_host=ttk.Frame(header);status_host.grid(row=0,column=1,sticky="e",padx=(10,6))
        self.predict_status_labels={}
        for key,title in (("unresolved","Unresolved"),("review","Review"),("verified","Verified")):
            label=ttk.Label(status_host,text=f"{title}: 0",style="StatusChip.TLabel")
            label.pack(side="left",padx=(0,3));self.predict_status_labels[key]=label
        actions=FlowRow(header,style="Toolbar.TFrame");actions.grid(row=1,column=0,sticky="ew");self.actions=actions
        self.left_actions=actions
        ttk.Label(actions,text="Crop actions:",style="SectionTitle.TLabel").pack(side="left",padx=(0,6))
        self.crop_actions=ttk.Frame(actions);self.crop_actions.pack(side="left")
        self.delete_crop_button=self._button(self.crop_actions,"Delete",self.delete_selected,"Delete the selected crop only.",icon="delete");self.delete_crop_button.pack(side="left",padx=2)
        self.clear_plate_button=self._button(self.crop_actions,"Clear all…",self.clear_plate_crops,"Clear all crops on this plate.",icon="clear");self.clear_plate_button.pack(side="left",padx=2)
        self.selection_separator=ttk.Separator(actions,orient="vertical");self.selection_separator.pack(side="left",fill="y",padx=(6,4),pady=3)
        self.orientation_actions=ttk.Frame(actions);self.orientation_actions.pack(side="left")
        self.flip_h_button=self._button(self.orientation_actions,"Flip ↔",self.flip_selected_horizontal,"Flip the selected crop left to right.",icon="flip_horizontal");self.flip_h_button.pack(side="left",padx=2)
        self.flip_v_button=self._button(self.orientation_actions,"Flip ↕",self.flip_selected_vertical,"Flip the selected crop top to bottom.",icon="flip_vertical");self.flip_v_button.pack(side="left",padx=2)
        self.apply_separator=ttk.Separator(actions,orient="vertical");self.apply_separator.pack(side="left",fill="y",padx=(6,4),pady=3)
        self.apply_group=ttk.Frame(actions);self.apply_group.pack(side="left")
        self.apply_button=self._button(self.apply_group,"Apply crops",self.apply_current,"Accept the specimen crops on this plate and stay on it.",style="CropApply.TButton",icon="verify");self.apply_button.pack(side="left")
        self.save_status=ttk.Label(self.apply_group,text="",style="Muted.TLabel");self.save_status.pack(side="left",padx=(6,0))
        actions.relayout()

        self.queue_banner=ttk.Frame(main,style="Attention.TFrame",padding=(6,4))
        self.queue_banner_title=ElidedLabel(self.queue_banner,text="",style="AttentionTitle.TLabel",anchor="w")
        self.queue_banner_title.pack(side="left",fill="x",expand=True)
        self.batch_actions=ttk.Frame(self.queue_banner,style="Attention.TFrame");self.batch_actions.pack(side="right")
        self.status_previous=self._button(self.batch_actions,"Previous",lambda:self._move_batch(-1),"Previous plate in this finite batch.",style="Nav.TButton",icon="previous");self.status_previous.pack(side="left",padx=(6,2))
        self.confirm_button=self._button(self.batch_actions,"Confirm & Next",self.confirm_plate_next,"Apply the crops, confirm this plate, and continue.",style="NavPrimary.TButton",icon="verify");self.confirm_button.pack(side="left",padx=2)
        self.continue_queue_button=self._button(self.batch_actions,"Continue",self.continue_batch,"Continue this saved Crop queue.",style="Primary.TButton",icon="next");self.continue_queue_button.pack(side="left",padx=2)
        self.close_queue_button=self._button(self.batch_actions,"Close queue",self.dismiss_batch,"Close this Crop queue; keep saved crops, predictions and provenance.",icon="close");self.close_queue_button.pack(side="left",padx=(4,0))

        canvas_frame=ttk.Frame(main);canvas_frame.grid(row=2,column=0,sticky="nsew");canvas_frame.pack_propagate(False)
        self.canvas=tk.Canvas(canvas_frame,background="#202020",highlightthickness=0,cursor="crosshair",takefocus=True)
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",lambda _e:self._draw())
        self.canvas.bind("<Button-1>",self._canvas_down);self.canvas.bind("<B1-Motion>",self._canvas_drag);self.canvas.bind("<ButtonRelease-1>",self._canvas_up)
        self.canvas.bind("<MouseWheel>",self._wheel)
        for button in (2,3):
            self.canvas.bind(f"<ButtonPress-{button}>",self._pan_start)
            self.canvas.bind(f"<B{button}-Motion>",self._pan_motion)
            self.canvas.bind(f"<ButtonRelease-{button}>",self._pan_end)
        self.canvas.bind("<Delete>",self.delete_selected);self.canvas.bind("<BackSpace>",self.delete_selected)

        adapter=SimpleNamespace(ui_icon=lambda name,size:self._icon(main,name,size),tip=self._tip)
        workflow=WorkflowDock(main,adapter,help_factory=lambda host:self._button(host,"Help",self._show_help,"Open the X-ray Crop guide."))
        workflow.grid(row=3,column=0,sticky="ew",pady=(2,0));self.workflow_dock=workflow
        one=workflow.add_card("1. Training data",icon="crop_training",help_text="Start examples are the initial diverse human-confirmed plates used to establish Crop detection and head / ventral orientation.")
        batch_actions=ttk.Frame(one);batch_actions.grid(row=0,column=0,sticky="w")
        ttk.Label(batch_actions,text="Batch").pack(side="left")
        ttk.Spinbox(batch_actions,from_=1,to=100,textvariable=self.training_batch_size,width=4).pack(side="left",padx=(4,0))
        ttk.Label(batch_actions,text="6–10 recommended",style="Muted.TLabel").pack(side="left",padx=(5,0))
        add_command_separator(batch_actions)
        self.training_button=self._button(batch_actions,"Start first batch",self.start_training_batch,"Prepare diverse plates for manual crop and orientation correction.");self.training_button.pack(side="left")
        two=workflow.add_card("2. Train model",icon="crop_train",help_text="Train crop detection and head / ventral orientation from verified examples.")
        model_row=ttk.Frame(two);model_row.grid(row=0,column=0,sticky="ew");two.columnconfigure(0,weight=1)
        self.model_label=ElidedLabel(model_row,text="Active: none",style="StatusChip.TLabel",anchor="w",width=23);self.model_label.pack(side="left")
        add_command_separator(model_row)
        ttk.Label(model_row,text="From").pack(side="left")
        self.training_parent_choice=tk.StringVar(master=two,value="RTMDet pretrained")
        self.training_parent_box=ttk.Combobox(model_row,textvariable=self.training_parent_choice,values=("RTMDet pretrained",),width=22,state="readonly")
        self.training_parent_box.pack(side="left",padx=(4,0))
        self._training_parent_touched=False
        self.training_parent_box.bind("<<ComboboxSelected>>",lambda _e:setattr(self,"_training_parent_touched",True))
        self.training_count_label=ttk.Label(model_row,text="Ready: 0",style="Muted.TLabel");self.training_count_label.pack(side="right",padx=(10,0))
        train_actions=ttk.Frame(two);train_actions.grid(row=1,column=0,sticky="w",pady=(3,0))
        self.train_button=self._button(train_actions,"Train",self.train_model,"Train crop detection and orientation using existing eligible examples.",style="Primary.TButton");self.train_button.pack(side="left")
        add_command_separator(train_actions)
        self.models_button=self._button(train_actions,"Models…",self.manage_models,"Compare and select saved Crop models.");self.models_button.pack(side="left")

        three=workflow.add_card("3. Predict & review",icon="crop_apply",help_text="Predict eligible plates, then human-review the crops and orientation.")
        batch_row=ttk.Frame(three);batch_row.grid(row=0,column=0,sticky="w")
        ttk.Label(batch_row,text="Next batch").pack(side="left");ttk.Spinbox(batch_row,from_=1,to=500,textvariable=self.prediction_batch_size,width=4).pack(side="left",padx=(4,0))
        ttk.Label(batch_row,text="plates",style="Muted.TLabel").pack(side="left",padx=(4,0))
        add_command_separator(batch_row)
        ttk.Label(batch_row,text="Model").pack(side="left")
        self.prediction_model_choice=tk.StringVar(master=three,value="")
        self.prediction_model_box=ttk.Combobox(batch_row,textvariable=self.prediction_model_choice,width=21,state="disabled")
        self.prediction_model_box.pack(side="left",padx=(4,0));self.prediction_model_box.bind("<<ComboboxSelected>>",self._activate_prediction_model)
        self._tip.bind(self.prediction_model_box,"Active Crop AI model used by all prediction actions. Choosing a model makes it active immediately.")
        predict_actions=ttk.Frame(three);predict_actions.grid(row=1,column=0,sticky="w",pady=(4,0))
        self.predict_current_button=self._button(predict_actions,"Predict current",self.predict_current_plate,"Apply Crop AI to the selected plate. Human-reviewed plates are protected and are never overwritten.");self.predict_current_button.pack(side="left")
        add_command_separator(predict_actions)
        self.predict_next_button=self._button(predict_actions,"Predict next batch",lambda:self.predict_batch(self.prediction_batch_size.get()),"Predict the next eligible plates.",style="Primary.TButton");self.predict_next_button.pack(side="left")
        self.predict_all_button=self._button(predict_actions,"Predict all",lambda:self.predict_batch(None),"Predict every remaining eligible plate.");self.predict_all_button.pack(side="left",padx=(4,0))
        add_command_separator(predict_actions)
        self.review_button=self._button(predict_actions,"Review AI",self.review_ai,"Review model-proposed crops and orientation before human confirmation.",style="ReviewAction.TButton",icon="review_worst");self.review_button.pack(side="left")

    def _set_initial_sash(self,_event=None):
        try:
            if self.panes.winfo_width()<=1 or getattr(self,"_initial_sash_done",False):return
            width=max(900,self.panes.winfo_width());self.panes.sashpos(0,sidebar_width_for_window(width,self.plate_list.winfo_reqwidth()))
            self._initial_sash_done=True
        except Exception:pass

    def _workflow_card(self,parent,column,title,icon,help_text):
        label=ttk.Frame(parent);ttk.Label(label,image=self._icon(label,icon)).pack(side="left",padx=(0,6))
        ttk.Label(label,text=title,style="WorkflowCardTitle.TLabel").pack(side="left")
        card=ttk.LabelFrame(parent,labelwidget=label,padding=(6,3),style="WorkflowCard.TLabelframe")
        card.grid(row=0,column=column,sticky="nsew",padx=(0 if column==0 else 4,0));self._tip.bind(card,help_text);self._tip.bind(label,help_text)
        return card

    def _show_help(self):
        dialog=tk.Toplevel(self.root);dialog.title("X-ray Crop — quick guide");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="X-ray Crop — quick guide",font=("Segoe UI",11,"bold")).pack(anchor="w")
        ttk.Label(frame,text=(
            "1. Adjust crops and orientation\nWheel zooms and right-drag pans like Landmarks. Select a crop, then use the two flip icons when head or ventral side is wrong. Blue marks the head edge; orange marks the ventral edge. Drag empty image space to add a missed specimen; Delete removes the selected crop.\n\n"
            "2. Apply crop\nOutside a finite batch, Apply crop saves and human-confirms the whole current plate.\n\n"
            "3. Training / review batch\nInside a batch, the same operation is Confirm & Next; Previous never silently confirms.\n\n"
            "4. Train and predict\nCrop detection learns from confirmed plates. Head / ventral orientation learns from the orientation you confirm, then is proposed automatically on later crops."
        ),justify="left",wraplength=600).pack(anchor="w",pady=(8,0))
        self._button(frame,"Close",dialog.destroy,"Close this guide.").pack(anchor="e",pady=(14,0));center(self.root,dialog)

    def _notify_selection(self):
        specimen_id=str(self.session.selected_id or "")
        if specimen_id.startswith("draft:"):specimen_id=""
        self._preferred_image_id=str(self.selected_image_id or "");self._preferred_specimen_id=specimen_id
        self.on_selection(self._preferred_image_id,specimen_id)

    def _batch(self):return self.project.get_ui_state("xray_crop_active_batch",{})

    @staticmethod
    def _batch_current_id(state):
        ids=list((state or {}).get("ids") or [])
        if not ids:return ""
        position=max(0,min(len(ids)-1,int((state or {}).get("position",0) or 0)))
        return str(ids[position])

    def _active_batch(self):
        state=self._batch()
        return state if self._queue_active and self.selected_image_id==self._batch_current_id(state) else None

    def _set_batch(self,ids,batch_type,model_id=""):
        ids=list(dict.fromkeys(str(value) for value in ids))
        state={"batch_type":str(batch_type),"ids":ids,"position":0,"model_id":str(model_id or "")}
        self.project.set_ui_state("xray_crop_active_batch",state);self._queue_active=bool(ids)
        if ids:self.selected_image_id=ids[0]
        self.refresh(preserve_plate=bool(ids));return bool(ids)

    def continue_batch(self):
        state=self._batch();current=self._batch_current_id(state)
        if not current:
            self._queue_active=False;self._refresh_batch_banner();self._update_batch_controls();return False
        self._queue_active=True
        if current!=self.selected_image_id:self._load_plate(current)
        self.plate_list.select(current,reveal=False);self._refresh_batch_banner();self._update_batch_controls()
        return True

    def dismiss_batch(self):
        self.project.set_ui_state("xray_crop_active_batch",{})
        self._queue_active=False;self._refresh_batch_banner();self._update_batch_controls()
        return True

    def _enter_batch(self,event):
        if event.widget.winfo_class() in {"Entry","TEntry","TCombobox","Text","Spinbox","TSpinbox"}:return
        if self._active_batch():self.confirm_plate_next();return "break"

    def _list_selected(self,image_id):
        if image_id==self.selected_image_id:return
        try:self.flush_pending_edits()
        except Exception as exc:
            messagebox.showerror("X-ray Crops",f"Could not save the current Crop edits:\n{exc}",parent=self.root);return
        self._load_plate(image_id);self.on_changed()

    def _source_exclusion_changed(self,image_id,excluded):
        state=self._batch();ids=list(state.get("ids") or [])
        if excluded and image_id in ids:
            ids.remove(image_id);state["ids"]=ids;state["position"]=min(int(state.get("position",0) or 0),max(0,len(ids)-1))
            self.project.set_ui_state("xray_crop_active_batch",state)
        if excluded and image_id==self.selected_image_id:
            candidates=[row["image_id"] for row in self.project.source_images() if not row["excluded"]]
            self.selected_image_id=candidates[0] if candidates else None
        self.refresh(preserve_plate=bool(self.selected_image_id))

    def _refresh_controls(self):
        status=self.project.crop_workspace_status();model=self.project.active_crop_model()
        self.training_button.configure(text="Start first batch" if not status["training_plates"] else "Add next batch")
        model_metrics=(model or {}).get("metrics") or {};orientation_mark=" · orientation ✓" if model_metrics.get("orientation/enabled") else ""
        active_id=(model or {}).get("model_id") or "none"
        self.model_label.configure(text=f"Active: {active_id}{orientation_mark}")
        prediction_values=tuple(item["model_id"] for item in self.project.crop_models())
        self.prediction_model_box.configure(values=prediction_values,state="readonly" if prediction_values else "disabled")
        self.prediction_model_choice.set(active_id if model else "")
        parent_values=("RTMDet pretrained",)+prediction_values
        current_parent=self.training_parent_choice.get()
        preferred_parent=(model or {}).get("model_id") or "RTMDet pretrained"
        if not getattr(self,"_training_parent_touched",False) or current_parent not in parent_values:
            self.training_parent_choice.set(preferred_parent)
        self.training_parent_box.configure(values=parent_values)
        self.training_count_label.configure(text=f"Ready: {status['training_plates']} plates · {status['training_specimens']} crops · orientation {status['orientation_training']}")
        self.predict_status_labels["unresolved"].configure(text=f"Unresolved: {status['prediction_candidates']}")
        self.predict_status_labels["review"].configure(text=f"Review: {status['ai_pending_plates']}")
        self.predict_status_labels["verified"].configure(text=f"Verified: {status['verified_plates']}")
        next_state="normal" if model and status["prediction_candidates"] else "disabled"
        all_state="normal" if model and status["prediction_candidates"] else "disabled"
        self.predict_next_button.configure(state=next_state);self.predict_all_button.configure(state=all_state)
        self._refresh_predict_current_state(model)
        self.review_button.configure(state="normal" if status["ai_pending_plates"] else "disabled")
        self._refresh_apply_state()
        self._refresh_flip_controls();self._refresh_batch_banner();self._update_batch_controls()

    def _activate_prediction_model(self,_event=None):
        model_id=str(self.prediction_model_choice.get() or "")
        if not model_id:return
        try:self.project.activate_crop_model(model_id)
        except Exception as exc:
            messagebox.showerror("X-ray Crop model",str(exc),parent=self.root);return
        self._refresh_controls();self.on_changed()

    def _current_apply_needed(self):
        if not self.selected_image_id:return False
        try:image=self.project.source_image(self.selected_image_id)
        except KeyError:return False
        if bool(image.get("excluded")):return False
        items=list(self.session.active_items())
        if not items:return False
        if self.session.dirty:return True
        if not bool(image.get("crop_reviewed")):return True
        return any(
            str(item.get("crop_status") or "")!="confirmed"
            or not bool((item.get("crop") or {}).get("orientation_verified"))
            for item in items
        )

    def _refresh_apply_state(self):
        needed=self._current_apply_needed()
        button=getattr(self,"apply_button",None)
        if button is not None and button.winfo_exists():
            button.configure(state="normal" if needed else "disabled")
        return needed

    def _refresh_predict_current_state(self,model=None):
        model=model or self.project.active_crop_model()
        current_ok=False
        if model and self.selected_image_id:
            try:
                image=self.project.source_image(self.selected_image_id)
                current_ok=not bool(image.get("excluded"))
            except KeyError:
                current_ok=False
        self.predict_current_button.configure(state="normal" if current_ok else "disabled")
        return current_ok

    def _refresh_batch_banner(self):
        state=self._batch();ids=list(state.get("ids") or [])
        if not ids:
            self.queue_banner.grid_remove();return
        position=max(0,min(len(ids)-1,int(state.get("position",0) or 0)))
        label="AI review" if state.get("batch_type")=="prediction_review" else "Training batch"
        suffix="" if self._active_batch() else " · saved"
        self.queue_banner_title.configure(text=f"{label} · {position+1}/{len(ids)}{suffix}")
        self.queue_banner.grid(row=1,column=0,sticky="ew",pady=(0,4))

    def _refresh_flip_controls(self):
        state=crop_flip_button_state(bool(self.session.selected_id))
        self.delete_crop_button.configure(state=state)
        self.flip_h_button.configure(state=state);self.flip_v_button.configure(state=state)

    def refresh(self,preserve_plate=True):
        previous=self.selected_image_id if preserve_plate else None
        images=[row for row in self.project.source_images() if not row.get("excluded")];available={row["image_id"] for row in images}
        batch=self._batch();ids=list(batch.get("ids") or []);position=max(0,min(len(ids)-1,int(batch.get("position",0) or 0))) if ids else 0
        preferred=self._preferred_image_id if self._preferred_image_id in available else ""
        target=previous if previous in available else (preferred or (images[0]["image_id"] if images else None))
        self.plate_list.selected_image_id=target;self.plate_list.refresh(preserve_scroll=preserve_plate,reveal=not preserve_plate)
        if target:self._load_plate(target)
        else:self._clear_canvas()
        self._refresh_controls();self.on_changed()

    def _update_batch_controls(self):
        active=self._active_batch()
        if active is None:
            self.status_previous.pack_forget();self.confirm_button.pack_forget()
            if not self.continue_queue_button.winfo_ismapped():self.continue_queue_button.pack(side="left",padx=2)
            self.apply_group._flow_hidden=False;self.actions.relayout()
            return
        self.apply_group._flow_hidden=True;self.actions.relayout();self.continue_queue_button.pack_forget()
        if not self.status_previous.winfo_ismapped():self.status_previous.pack(side="left",padx=(6,2),before=self.close_queue_button)
        if not self.confirm_button.winfo_ismapped():self.confirm_button.pack(side="left",padx=2,before=self.close_queue_button)
        ids=list(active.get("ids") or []);pos=max(0,min(len(ids)-1,int(active.get("position",0) or 0)))
        self.status_previous.configure(state="normal" if pos>0 else "disabled")

    def _load_plate(self,image_id):
        items=self.project.specimens(image_id)
        selected=self._preferred_specimen_id if any(item["specimen_id"]==self._preferred_specimen_id for item in items) else (items[0]["specimen_id"] if items else None)
        self.selected_image_id=image_id;self.session.load(items,selected_id=selected)
        self._drag_mode=self._drag_anchor=self._drag_initial=None;self._drawing_crop=None;self._drag_changed=False
        self.zoom=1.0;self.pan=None;self.pan_drag=None
        try:preview,_scale,original_size=display_preview(self.project.source_image_path(image_id),1400)
        except Exception as exc:messagebox.showerror("X-ray Crops",str(exc),parent=self.root);return
        self.preview=preview;self.preview_original_size=original_size;self._photo_key=None;self._set_save_status();self._draw();self._refresh_flip_controls();self._refresh_batch_banner();self._update_batch_controls();self._notify_selection();self._refresh_plate_context();self._refresh_predict_current_state()

    def _refresh_plate_context(self):
        if not self.selected_image_id:return
        image=self.project.source_image(self.selected_image_id);path=Path(image["relative_path"])
        self.sample_value.configure(text=self.plate_list._sample(image["relative_path"]))
        self.context_label.configure(text=path.name)
        selected=self.session.item();self.crop_value.configure(text=str(selected.get("ordinal") or "—") if selected else "—")
        models={}
        for item in self.session.active_items():
            if str(item.get("specimen_id") or "").startswith("draft:"):continue
            for event in reversed(self.project.crop_events(item["specimen_id"])):
                if event.get("action")=="detect" and (event.get("payload") or {}).get("model_id"):
                    model=(event.get("payload") or {})["model_id"]
                    models[model]=max(models.get(model,""),str(event.get("created_at") or ""));break
        self.prediction_text="; ".join(prediction_stamp(model,when) for model,when in sorted(models.items()))
        self._draw()

    def _clear_canvas(self):
        self.canvas.delete("all");self.preview=self.photo=None;self._photo_key=None;self.selected_image_id=None;self.session.load(())
        self.zoom=1.0;self.pan=None;self.pan_drag=None
        self._set_save_status();self._update_batch_controls();self.sample_value.configure(text="—");self.context_label.configure(text="—");self.crop_value.configure(text="—");self.prediction_text=""

    def _set_save_status(self,text=None):
        if text is None:text="Unsaved changes" if self.session.dirty else ""
        self.save_status.configure(text=text)
        self._refresh_apply_state()

    def flush_pending_edits(self):
        """Persist the current local Crop delta before leaving this plate/stage."""
        if not self.selected_image_id or not self.session.dirty:return self.session.selected_id
        selected=self.session.selected_id;changes=self.session.changes()
        list_changed=bool(changes["new_crops"] or changes["removed_ids"])
        result=self.project.apply_plate_crop_edits(
            self.selected_image_id,
            edits=changes["edits"],new_crops=changes["new_crops"],removed_ids=changes["removed_ids"],
        )
        selected=result.get("id_map",{}).get(selected,selected)
        self.session.load(self.project.specimens(self.selected_image_id),selected_id=selected)
        self._preferred_specimen_id=str(selected or "")
        if selected:self._notify_selection()
        else:
            self._preferred_image_id=str(self.selected_image_id or "")
            self.on_selection(self._preferred_image_id,"")
        if list_changed:self.plate_list.refresh(preserve_scroll=True,reveal=False)
        self._set_save_status("Saved · Apply to verify");self._refresh_flip_controls();self.on_changed()
        return selected

    def _fit(self):
        if self.preview is None:return None
        cw=max(2,self.canvas.winfo_width());ch=max(2,self.canvas.winfo_height())
        base=min(max(1,cw-28)/self.preview.width,max(1,ch-28)/self.preview.height,1.0)
        scale=max(0.01,base*self.zoom)
        width=max(1,round(self.preview.width*scale));height=max(1,round(self.preview.height*scale))
        if self.pan is None:self.pan=((cw-width)/2,(ch-height)/2)
        self.offset=(float(self.pan[0]),float(self.pan[1]))
        self.display_scale=(width/self.preview_original_size[0]) if self.preview_original_size[0] else 1.0
        key=(id(self.preview),width,height)
        if key!=self._photo_key:
            fitted=self.preview if (width,height)==self.preview.size else self.preview.resize((width,height),Image.Resampling.LANCZOS)
            self.photo=ImageTk.PhotoImage(fitted,master=self.canvas);self._photo_key=key
        return self.photo

    def _screen(self,x,y):return self.offset[0]+float(x)*self.display_scale,self.offset[1]+float(y)*self.display_scale
    def _original(self,x,y):return (float(x)-self.offset[0])/max(1e-9,self.display_scale),(float(y)-self.offset[1])/max(1e-9,self.display_scale)

    def _wheel(self,event):
        if self.preview is None:return "break"
        self._fit();old_zoom=self.zoom;old_scale=max(1e-9,self.display_scale)
        source_x=(float(event.x)-self.offset[0])/old_scale;source_y=(float(event.y)-self.offset[1])/old_scale
        new_zoom=max(0.25,min(8.0,old_zoom*(1.15 if event.delta>0 else 1/1.15)))
        if abs(new_zoom-old_zoom)<1e-12:return "break"
        new_scale=old_scale*(new_zoom/old_zoom);self.zoom=new_zoom
        self.pan=(float(event.x)-source_x*new_scale,float(event.y)-source_y*new_scale)
        self._draw();return "break"

    def _pan_start(self,event):
        if self.preview is None:return "break"
        self._fit();self.pan_drag=(event.x,event.y,self.offset);self.canvas.configure(cursor="fleur");return "break"

    def _pan_motion(self,event):
        if not self.pan_drag:return "break"
        x,y,origin=self.pan_drag;self.pan=(origin[0]+event.x-x,origin[1]+event.y-y);self._draw();return "break"

    def _pan_end(self,_event=None):
        self.pan_drag=None;self.canvas.configure(cursor="crosshair");return "break"

    def _draw(self):
        self.canvas.delete("all");photo=self._fit()
        if photo is None:return
        self.canvas.create_image(self.offset[0],self.offset[1],anchor="nw",image=photo,tags="plate")
        for item in self.session.active_items():
            crop=item.get("crop") or {};corners=crop.get("corners") or []
            if len(corners)!=4:continue
            selected=item["specimen_id"]==self.session.selected_id
            color="#58c8c4" if item.get("crop_status")=="confirmed" else "#ff7f6e"
            if selected:self._draw_crop_frame(corners,"#26e6b3",selected=True)
            else:self._draw_crop_frame(corners,color,selected=False)
            cx,cy=self._screen(crop.get("center_x",0),crop.get("center_y",0))
            self.canvas.create_oval(cx-9,cy-9,cx+9,cy+9,fill="#071521",outline="",tags="crop")
            self.canvas.create_text(cx,cy,text=str(item.get("ordinal") or ""),fill="white",font=("Segoe UI",9,"bold"),tags="crop")
            self._draw_orientation_markers(crop,selected)
            if selected:self._draw_handles(crop)
        if self._drawing_crop is not None:
            pts=[]
            for x,y in self._drawing_crop.get("corners") or ():pts.extend(self._screen(x,y))
            if len(pts)==8:self.canvas.create_polygon(*pts,outline="#35d07f",fill="",width=2,dash=(5,3),tags="crop")
        if self.prediction_text:
            self.canvas.create_text(13,13,anchor="nw",fill="#202020",text=self.prediction_text,font=("Segoe UI",10,"bold"),tags="crop_prediction_shadow")
            self.canvas.create_text(12,12,anchor="nw",fill="#ffdf80",text=self.prediction_text,font=("Segoe UI",10,"bold"),tags="crop_prediction")

    def _draw_crop_frame(self,corners,color,selected=False):
        """Rounded double-stroke boundary: clear on X-rays without a pile of corner bars."""
        screen=[self._screen(*point) for point in corners]
        if len(screen)!=4:return
        closed=screen+[screen[0]]
        points=[coordinate for point in closed for coordinate in point]
        halo_width=8 if selected else 5
        line_width=4.2 if selected else 2.6
        self.canvas.create_line(
            *points,fill="#10222b",width=halo_width,capstyle="round",joinstyle="round",tags="crop"
        )
        self.canvas.create_line(
            *points,fill=color,width=line_width,capstyle="round",joinstyle="round",tags="crop"
        )

    def _draw_crop_brackets(self,corners,color):
        """Compatibility wrapper for older callers/tests."""
        self._draw_crop_frame(corners,color,selected=False)

    @staticmethod
    def _orientation_geometry(crop):
        corners=crop.get("corners") or []
        if len(corners)!=4:return None
        c0,c1,c2,c3=[tuple(map(float,point)) for point in corners]
        head_edge=(c0,c3) if crop.get("head_side")!="right" else (c1,c2)
        bottom_edge=(c0,c1) if crop.get("bottom_side")=="top" else (c3,c2)
        midpoint=lambda a,b:((a[0]+b[0])/2,(a[1]+b[1])/2)
        return {
            "head":midpoint(*head_edge),"head_edge":head_edge,
            "bottom":midpoint(*bottom_edge),"bottom_edge":bottom_edge,
            "center":(float(crop.get("center_x",0)),float(crop.get("center_y",0))),
        }

    def _draw_orientation_markers(self,crop,selected):
        """Show head and ventral orientation on selected and unselected frames."""
        geometry=self._orientation_geometry(crop)
        if geometry is None:return
        cx,cy=self._screen(*geometry["center"]);hx,hy=self._screen(*geometry["head"]);bx,by=self._screen(*geometry["bottom"])
        def outward_unit(mx,my):
            dx=mx-cx;dy=my-cy;length=max(1.0,math.hypot(dx,dy));return dx/length,dy/length
        def triangle(mx,my,size):
            ux,uy=outward_unit(mx,my);px,py=-uy,ux
            tip=(mx+ux*size,my+uy*size);base=(mx-ux*size*.45,my-uy*size*.45)
            return (tip[0],tip[1],base[0]+px*size*.62,base[1]+py*size*.62,base[0]-px*size*.62,base[1]-py*size*.62)

        head_size=18 if selected else 15
        head="#159cff";ventral="#ffb000"
        self.canvas.create_polygon(*triangle(hx,hy,head_size+2),fill="#071521",outline="white" if selected else "#071521",width=1,tags=("crop","orientation"))
        self.canvas.create_polygon(*triangle(hx,hy,head_size),fill=head,outline="white",width=1,tags=("crop","orientation"))
        edge=geometry["bottom_edge"];start=self._screen(*edge[0]);end=self._screen(*edge[1])
        dx=end[0]-start[0];dy=end[1]-start[1];length=max(1.0,math.hypot(dx,dy));ux,uy=dx/length,dy/length
        half=min(34.0,max(22.0,length*.24));cx,cy=bx,by
        stripe=(cx-ux*half,cy-uy*half,cx+ux*half,cy+uy*half)
        self.canvas.create_line(
            *stripe,fill="#10222b",width=11 if selected else 9,
            capstyle="round",tags=("crop","orientation")
        )
        self.canvas.create_line(
            *stripe,fill=ventral,width=7 if selected else 6,
            capstyle="round",tags=("crop","orientation")
        )

    def _draw_handles(self,crop):
        corners=crop.get("corners") or []
        for point in corners:
            hx,hy=self._screen(*point)
            self.canvas.create_oval(hx-7,hy-7,hx+7,hy+7,fill="#071521",outline="white",width=1,tags="crop_handle")
            self.canvas.create_oval(hx-4,hy-4,hx+4,hy+4,fill="#54f0aa",outline="#071521",width=1,tags="crop_handle")
        angle=math.radians(float(crop.get("angle_degrees",0)));major=(math.cos(angle),math.sin(angle))
        reach=float(crop.get("length",0))/2+35/max(self.display_scale,1e-6)
        rx=float(crop.get("center_x",0))+reach*major[0];ry=float(crop.get("center_y",0))+reach*major[1]
        ex=float(crop.get("center_x",0))+float(crop.get("length",0))/2*major[0];ey=float(crop.get("center_y",0))+float(crop.get("length",0))/2*major[1]
        sx,sy=self._screen(rx,ry);tx,ty=self._screen(ex,ey)
        self.canvas.create_line(tx,ty,sx,sy,fill="#071521",width=5,tags="crop_handle")
        self.canvas.create_line(tx,ty,sx,sy,fill="#ffd34e",width=2.5,tags="crop_handle")
        self.canvas.create_oval(sx-9,sy-9,sx+9,sy+9,fill="#071521",outline="white",width=1,tags="crop_handle")
        self.canvas.create_oval(sx-5,sy-5,sx+5,sy+5,fill="#ffd34e",outline="#071521",width=1,tags="crop_handle")

    @staticmethod
    def _inside(point,polygon):
        x,y=point;inside=False;j=len(polygon)-1
        for i,(xi,yi) in enumerate(polygon):
            xj,yj=polygon[j]
            if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/(yj-yi+1e-12)+xi:inside=not inside
            j=i
        return inside

    def _hit_crop(self,x,y,item):
        crop=item.get("crop") or {};corners=crop.get("corners") or []
        if len(corners)!=4:return None
        tol=12/max(self.display_scale,1e-6)
        for index,(cx,cy) in enumerate(corners):
            if (x-cx)**2+(y-cy)**2<=tol**2:return ("corner",index)
        angle=math.radians(float(crop.get("angle_degrees",0)));major=(math.cos(angle),math.sin(angle))
        reach=float(crop.get("length",0))/2+35/max(self.display_scale,1e-6)
        rx=float(crop.get("center_x",0))+reach*major[0];ry=float(crop.get("center_y",0))+reach*major[1]
        if (x-rx)**2+(y-ry)**2<=tol**2:return ("rotate",0)
        if self._inside((x,y),corners):return ("move",0)
        return None

    def _canvas_down(self,event):
        if not self.selected_image_id or self.preview is None:return
        self.canvas.focus_set();x,y=self._original(event.x,event.y);selected=self.session.item()
        ordered=([selected] if selected else [])+[item for item in reversed(self.session.active_items()) if selected is None or item["specimen_id"]!=selected["specimen_id"]]
        for item in ordered:
            if item is None:continue
            hit=self._hit_crop(x,y,item)
            if hit is None:continue
            self.session.select(item["specimen_id"]);self._preferred_specimen_id=item["specimen_id"];self._notify_selection();self._refresh_flip_controls()
            crop=item.get("crop") or {};self._drag_mode=hit;self._drag_anchor=(x,y);self._drag_changed=False
            self._drag_initial=(float(crop.get("center_x",0)),float(crop.get("center_y",0)),float(crop.get("length",0)),float(crop.get("width",0)),float(crop.get("angle_degrees",0)))
            self._drawing_crop=None;self._draw();return
        self.session.select(None);self._refresh_flip_controls()
        self._drag_mode=("draw",0);self._drag_anchor=(x,y);self._drag_initial=None;self._drag_changed=False;self._drawing_crop=None;self._draw()

    def _canvas_drag(self,event):
        if self._drag_mode is None or not self.selected_image_id:return
        x,y=self._original(event.x,event.y);ax,ay=self._drag_anchor
        if abs(x-ax)+abs(y-ay)>1.0:self._drag_changed=True
        if self._drag_mode[0]=="draw":
            left,right=sorted((ax,x));top,bottom=sorted((ay,y))
            if right-left>=2 and bottom-top>=2:self._drawing_crop=crop_from_geometry((left+right)/2,(top+bottom)/2,right-left,bottom-top,0,self.preview_original_size,algorithm="manual",orientation_policy=self.project.orientation_policy)
            self._draw();return
        if not self._drag_changed:return
        cx,cy,length,width,angle=self._drag_initial
        if self._drag_mode[0]=="move":cx+=x-ax;cy+=y-ay
        elif self._drag_mode[0]=="rotate":angle=math.degrees(math.atan2(y-cy,x-cx))
        else:
            a=math.radians(angle);major=(math.cos(a),math.sin(a));minor=(-major[1],major[0]);initial_corners=crop_corners(cx,cy,length,width,angle)
            opposite=initial_corners[(int(self._drag_mode[1])+2)%4];dx=x-opposite[0];dy=y-opposite[1]
            cx=(x+opposite[0])/2;cy=(y+opposite[1])/2;length=max(20.0,abs(dx*major[0]+dy*major[1]));width=max(20.0,abs(dx*minor[0]+dy*minor[1]))
        self.session.update_selected(crop_from_geometry(cx,cy,length,width,angle,self.preview_original_size,confidence="high",algorithm="manual",orientation_policy=self.project.orientation_policy))
        self._set_save_status();self._draw()

    def _canvas_up(self,_event):
        if self._drag_mode is None:return
        if self._drag_mode[0]=="draw":
            crop=self._drawing_crop;self._drag_mode=self._drag_anchor=self._drag_initial=None;self._drawing_crop=None
            if crop is not None and float(crop.get("length",0))>=20 and float(crop.get("width",0))>=20:
                self.session.add(crop);self._set_save_status();self._refresh_flip_controls()
            self._draw();return
        changed=self._drag_changed
        self._drag_mode=self._drag_anchor=self._drag_initial=None;self._drag_changed=False
        if changed:self._set_save_status()
        self._draw()

    def delete_selected(self,_event=None):
        if self.session.delete_selected():self._set_save_status();self._draw();self._refresh_flip_controls()
        return "break"

    def flip_selected_horizontal(self):
        if self.session.flip_horizontal():
            self._set_save_status("Flipped left ↔ right · saved when you leave or Apply");self._draw();self._refresh_flip_controls()

    def flip_selected_vertical(self):
        if self.session.flip_vertical():
            self._set_save_status("Flipped top ↕ bottom · saved when you leave or Apply");self._draw();self._refresh_flip_controls()

    def clear_plate_crops(self):
        if not self.selected_image_id:return
        count=len(self.session.active_items())
        if not count:
            messagebox.showinfo("Clear plate crops","This plate has no current crops.",parent=self.root);return
        if not messagebox.askyesno("Clear all crops on this plate",f"Retire all {count} current crop(s) on this plate?\n\nCoordinate annotations will be archived, not discarded. You can then create and confirm new crops.",parent=self.root,default="no"):return
        try:removed=self.project.remove_all_plate_crops(self.selected_image_id)
        except Exception as exc:messagebox.showerror("Clear plate crops",str(exc),parent=self.root);return
        self.session.load(());self._preferred_specimen_id="";self._notify_selection();self.plate_list.refresh(preserve_scroll=True,reveal=False);self._refresh_controls();self._set_save_status(f"Cleared {removed} crop(s)");self._draw();self.on_changed()

    def apply_current(self,silent=False):
        if not self.selected_image_id:return "FAILED"
        selected=self.session.selected_id
        try:selected=apply_and_confirm_plate(self.project,self.selected_image_id,self.session)
        except Exception as exc:
            if not silent:messagebox.showerror("Apply crop",str(exc),parent=self.root)
            return "FAILED"
        self.session.load(self.project.specimens(self.selected_image_id),selected_id=selected)
        self._preferred_specimen_id=str(selected or "");self._notify_selection()
        self.plate_list.refresh(preserve_scroll=True,reveal=False);self.plate_list.select(self.selected_image_id,reveal=False);self._refresh_controls();self._set_save_status("Crop applied · verified");self._draw();self.on_changed()
        return "SAVED"

    def start_training_batch(self):
        if self._busy:return
        count=max(1,int(self.training_batch_size.get()));batch_ids=self.project.select_training_plate_ids(count)
        if not batch_ids:messagebox.showinfo("Crop training batch","No unverified plates are available.",parent=self.root);return
        self._busy=True;events=queue.Queue();dialog=tk.Toplevel(self.root);dialog.title("Prepare crop training batch");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True);label=ttk.Label(frame,text="Selecting training plates…",justify="left");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="determinate",maximum=len(batch_ids));bar.pack(fill="x",pady=(8,0));center(self.root,dialog)
        def worker():
            try:
                for index,image_id in enumerate(batch_ids,1):
                    if not self.project.specimens(image_id):
                        proposals=detect_specimens(self.project.source_image_path(image_id));self.project.replace_auto_proposals(image_id,proposals,"xray-otsu-pca-v1")
                    events.put(("progress",index,len(batch_ids)))
                events.put(("done",))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-training-batch-prepare").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait()
                    if event[0]=="progress":bar.configure(value=event[1]);label.configure(text=f"Preparing {event[1]} of {event[2]} plates…")
                    elif event[0]=="error":
                        self._busy=False;dialog.destroy();messagebox.showerror("Crop training batch",str(event[1]),parent=self.root);return
                    else:
                        self._busy=False;dialog.destroy();self._set_batch(batch_ids,"training")
                        messagebox.showinfo("Crop training batch",f"Prepared {len(batch_ids)} plate(s). Correct every crop, then use Confirm & Next.",parent=self.root);return
            except queue.Empty:self.root.after(100,poll)
        poll()

    def confirm_plate_next(self):
        if not self.selected_image_id:return
        if self.apply_current(silent=False)!="SAVED":return
        self._move_batch(1)

    def _move_batch(self,step):
        state=self._batch();ids=list(state.get("ids") or [])
        if not ids or self.selected_image_id not in ids:return False
        pos=ids.index(self.selected_image_id)+int(step)
        if pos<0:pos=0
        if pos>=len(ids):
            batch_type=state.get("batch_type");self.project.set_ui_state("xray_crop_active_batch",{"batch_type":batch_type,"ids":[],"finished":True})
            self._refresh_controls();self.plate_list.refresh(preserve_scroll=True)
            messagebox.showinfo("Crop review batch" if batch_type=="prediction_review" else "Crop training batch","Batch complete.",parent=self.root);return True
        state["position"]=pos;self.project.set_ui_state("xray_crop_active_batch",state);self._load_plate(ids[pos]);self.plate_list.select(ids[pos],reveal=False);self._refresh_batch_banner();self.on_changed();return True

    def train_model(self):
        if self._busy:return
        if len(self.project.training_plates())<3:
            messagebox.showinfo("Train crop model","Confirm at least 3 plates first. A first batch of 6–10 diverse plates is recommended.",parent=self.root);return
        self._busy=True;events=queue.Queue();dialog=tk.Toplevel(self.root);dialog.title("Train crop model");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack();label=ttk.Label(frame,text="Training X-ray crop model…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="indeterminate");bar.pack(fill="x",pady=(8,0));bar.start();center(self.root,dialog)
        def progress(stage,detail):events.put(("stage",stage,detail))
        selected_parent=self.training_parent_choice.get()
        parent_model_id="" if selected_parent=="RTMDet pretrained" else selected_parent
        def worker():
            try:events.put(("done",train_detector(self.project,progress=progress,parent_model_id=parent_model_id)))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-detector-training").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait()
                    if event[0]=="stage":label.configure(text=f"{event[1]}: {event[2]}")
                    elif event[0]=="error":
                        self._busy=False;dialog.destroy();messagebox.showerror("Crop training",str(event[1]),parent=self.root);return
                    else:
                        self._busy=False;dialog.destroy();result=event[1];self._training_parent_touched=False;self.training_parent_choice.set(result["model_id"]);self._refresh_controls();metrics=result.get("metrics") or {}
                        detail=f"Model ready: {result['model_id']}\nTraining plates: {result['training_plates']}\nTraining crops: {result['training_specimens']}"
                        if metrics.get("orientation/enabled"):
                            head=metrics.get("orientation/head_accuracy");bottom=metrics.get("orientation/bottom_accuracy");parts=[]
                            if isinstance(head,(int,float)):parts.append(f"head {head*100:.0f}%")
                            if isinstance(bottom,(int,float)):parts.append(f"ventral {bottom*100:.0f}%")
                            detail+="\nOrientation: "+(" · ".join(parts) if parts else "trained")
                        else:detail+="\nOrientation: not trained yet — confirm more crop orientations."
                        messagebox.showinfo("Crop training",detail,parent=self.root);return
            except queue.Empty:self.root.after(150,poll)
        poll()

    def manage_models(self):
        dialog=tk.Toplevel(self.root);dialog.title("X-ray crop models");dialog.transient(self.root)
        frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1);frame.rowconfigure(1,weight=1)
        ttk.Label(frame,text="Registered models · quality values are shown only when recorded",style="PageSubtitle.TLabel").grid(row=0,column=0,sticky="w",pady=(0,8))
        columns=("model","date","source","training","crop_quality","orientation_quality","active")
        tree=ttk.Treeview(frame,columns=columns,show="headings",selectmode="browse")
        headers=(("model","Model",165),("date","Trained",130),("source","Started from",165),("training","Plates / crops",130),("crop_quality","Crop validation",150),("orientation_quality","Orientation",170),("active","Status",80))
        model_width=dialog_width_for_columns((item[2] for item in headers),dialog.winfo_screenwidth(),chrome=105)
        dialog.geometry(f"{model_width}x420");dialog.minsize(min(model_width,920),300)
        for key,label,width in headers:tree.heading(key,text=label);tree.column(key,width=width,anchor="w")
        tree.grid(row=1,column=0,sticky="nsew");scroll=ttk.Scrollbar(frame,orient="vertical",command=tree.yview);scroll.grid(row=1,column=1,sticky="ns");tree.configure(yscrollcommand=scroll.set)
        def refresh():
            tree.delete(*tree.get_children())
            for model in self.project.crop_models():
                metrics=model.get("metrics") or {};stamp=str(model.get("created_at") or "").replace("T"," ")[:16]
                source=str(metrics.get("initialization") or model.get("parent_model_id") or "Pretrained RTMDet")
                quality=[]
                for key,label in (("coco/bbox_mAP","mAP"),("coco/bbox_mAP_50","AP50"),("coco/bbox_mAP_75","AP75"),("mAP","mAP")):
                    value=metrics.get(key)
                    if isinstance(value,(int,float)) and not any(part.startswith(label+" ") for part in quality):quality.append(f"{label} {value:.3f}")
                orientation=[]
                for key,label in (("orientation/head_accuracy","Head"),("orientation/bottom_accuracy","Ventral"),("orientation/joint_accuracy","Joint")):
                    value=metrics.get(key)
                    if isinstance(value,(int,float)):orientation.append(f"{label} {value*100:.0f}%")
                if not metrics.get("orientation/enabled"):orientation=["Not trained"]
                tree.insert("","end",iid=model["model_id"],values=(
                    model["model_id"],stamp,source,f"{model.get('training_plate_count',0)} / {model.get('training_specimen_count',0)}",
                    " · ".join(quality) or "Not recorded"," · ".join(orientation),"Active" if model.get("active") else "Available",
                ))
        def selected_model():
            selected=tree.selection();return selected[0] if selected else None
        actions=ttk.Frame(frame);actions.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(10,0))
        def activate():
            model_id=selected_model()
            if not model_id:return
            try:self.project.activate_crop_model(model_id)
            except Exception as exc:messagebox.showerror("X-ray models",str(exc),parent=dialog);return
            self._training_parent_touched=False;refresh();self._refresh_controls()
        def delete():
            model_id=selected_model()
            if not model_id:return
            if not messagebox.askyesno("Delete X-ray model",f"Delete {model_id} and its managed model files? This cannot be undone.",parent=dialog,default="no"):return
            try:self.project.delete_crop_model(model_id)
            except Exception as exc:messagebox.showerror("X-ray models",str(exc),parent=dialog);return
            refresh();self._refresh_controls()
        self._button(actions,"Make selected active",activate,"Use this registered model for future predictions.").pack(side="left")
        self._button(actions,"Delete model…",delete,"Delete the selected model and its managed files; models with dependent descendants are protected.").pack(side="left",padx=(6,0))
        self._button(actions,"Close",dialog.destroy).pack(side="right")
        refresh();center(self.root,dialog)

    def predict_current_plate(self):
        """Apply the active Crop AI model to only the selected, unreviewed plate."""
        if self._busy or not self.selected_image_id:return
        model=self.project.active_crop_model()
        if not model:
            messagebox.showinfo("Predict current","Train or activate a Crop AI model first.",parent=self.root);return
        image_id=str(self.selected_image_id);image=self.project.source_image(image_id)
        if image.get("excluded"):
            messagebox.showinfo("Predict current","Restore this X-ray plate before applying Crop AI.",parent=self.root);return
        if image.get("crop_reviewed"):
            messagebox.showinfo(
                "Predict current",
                "This plate is already human-reviewed, so Crop AI will not overwrite its confirmed crops. "
                "Use direct crop editing if a confirmed crop needs correction.",
                parent=self.root,
            );return
        try:self.flush_pending_edits()
        except Exception as exc:
            messagebox.showerror("Predict current",f"Could not save the current crop edits:\n{exc}",parent=self.root);return
        self._busy=True;events=queue.Queue()
        dialog=tk.Toplevel(self.root);dialog.title("Predict current");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
        label=ttk.Label(frame,text="Applying Crop AI to the current X-ray…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="indeterminate",length=340);bar.pack(fill="x",pady=(8,0));bar.start(12);center(self.root,dialog)
        def worker():
            try:events.put(("done",predict_plates(self.project,[image_id],model=model)))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-detector-predict-current").start()
        def poll():
            try:event=events.get_nowait()
            except queue.Empty:
                if dialog.winfo_exists():dialog.after(100,poll)
                return
            self._busy=False
            try:bar.stop();dialog.destroy()
            except tk.TclError:pass
            if event[0]=="error":
                messagebox.showerror("Predict current",str(event[1]),parent=self.root);self._refresh_controls();return
            result=event[1]
            if not result.get("success"):
                failures=list(result.get("failures") or ())
                detail=str(failures[0].get("reason")) if failures else "No crop prediction was produced."
                messagebox.showwarning("Predict current",detail,parent=self.root);self._refresh_controls();return
            self.plate_list.refresh(preserve_scroll=True);self._load_plate(image_id);self._refresh_controls()
        dialog.after(100,poll)

    def predict_batch(self,count):
        if self._busy:return
        model=self.project.active_crop_model()
        if not model:messagebox.showinfo("Predict Crop","Train an X-ray crop model first.",parent=self.root);return
        candidates=self.project.prediction_candidate_ids();ids=self.project.select_prediction_plate_ids(len(candidates) if count is None else max(1,int(count)))
        if not ids:messagebox.showinfo("Predict Crop","No remaining eligible plates need prediction.",parent=self.root);return
        self._busy=True;events=queue.Queue();cancel=threading.Event();dialog=tk.Toplevel(self.root);dialog.title("Predict Crop");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack();label=ttk.Label(frame,text=f"Preparing crop predictions for {len(ids)} plate(s)…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="determinate",maximum=len(ids));bar.pack(fill="x",pady=(8,0));self._button(frame,"Cancel",cancel.set,"Stop after the current prediction.").pack(anchor="e",pady=(8,0));center(self.root,dialog)
        def worker():
            try:events.put(("done",predict_plates(self.project,ids,cancel=cancel,progress=lambda done,total,image_id:events.put(("progress",done,total,image_id)))))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-detector-predict").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait()
                    if event[0]=="progress":bar.configure(value=event[1]);label.configure(text=f"Predicting Crop: {event[1]} / {event[2]}")
                    elif event[0]=="error":
                        self._busy=False;dialog.destroy();messagebox.showerror("Predict Crop",str(event[1]),parent=self.root);return
                    else:
                        self._busy=False;dialog.destroy();result=event[1];self.plate_list.refresh(preserve_scroll=True);self._refresh_controls()
                        summary=f"Predicted: {result['success']} plate(s)."
                        if result.get("failures"):summary+=f"\nNeeds attention: {len(result['failures'])}."
                        success=list(result.get("successful_ids") or [])
                        if success and messagebox.askyesno("Predict Crop",summary+"\n\nReview this batch now?",parent=self.root,default=messagebox.YES):
                            self._set_batch(success,"prediction_review",result.get("model_id"));return
                        messagebox.showinfo("Predict Crop",summary,parent=self.root);return
            except queue.Empty:self.root.after(100,poll)
        poll()

    def review_ai(self):
        ids=self.project.select_ai_review_plate_ids()
        if not ids:messagebox.showinfo("Review AI crops","No AI crop proposals require review.",parent=self.root);return
        self._set_batch(ids,"prediction_review",(self.project.active_crop_model() or {}).get("model_id",""))
