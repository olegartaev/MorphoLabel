"""Tk workspace for the X-ray plate-to-specimen crop workflow."""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import uuid

from PIL import Image, ImageTk

from app.ui.dialogs import center
from app.ui.icons import WORKFLOW_ICON_SIZE, tk_icon
from app.ui.tooltips import Tooltip
from .xray_crop import crop_corners, crop_from_geometry, detect_specimens, display_preview
from .xray_detector import predict_plates, train_detector


class PlateCropEditSession:
    """In-memory edits for one plate; persistence happens only through Apply crop."""

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
        item["crop"]=dict(crop)
        if self.selected_id not in self.new_ids:self.dirty_ids.add(self.selected_id)
        return True

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
        edits=[
            {"specimen_id":specimen_id,"crop":dict(self.items[specimen_id]["crop"])}
            for specimen_id in sorted(self.dirty_ids)
            if specimen_id in self.items and specimen_id not in self.deleted_ids
        ]
        new_crops=[
            {"client_id":specimen_id,"crop":dict(self.items[specimen_id]["crop"])}
            for specimen_id in sorted(self.new_ids)
            if specimen_id in self.items
        ]
        return {"edits":edits,"new_crops":new_crops,"removed_ids":sorted(self.deleted_ids)}


class XRayCropWorkspace:
    """Multi-specimen Crop workspace using the same interaction model as Landmark Crop."""

    def __init__(self,parent,project,on_changed=None):
        self.parent=parent;self.root=parent.winfo_toplevel();self.project=project;self.on_changed=on_changed or (lambda:None)
        self.selected_image_id=None;self.session=PlateCropEditSession()
        self.preview=self.photo=None;self.preview_original_size=(1,1);self.display_scale=1.0;self.offset=(0,0);self._photo_key=None
        self._busy=False;self._drag_mode=None;self._drag_anchor=None;self._drag_initial=None;self._drag_changed=False
        self._drawing_crop=None;self._icons={};self._refreshing_list=False
        self.training_batch_size=tk.IntVar(value=6);self.prediction_batch_size=tk.IntVar(value=6)
        self._tip=Tooltip(self.root)
        self._build();self.refresh(preserve_plate=False)

    @property
    def selected_specimen_id(self):
        return self.session.selected_id

    def _button(self,parent,text,command,help_text="",primary=False):
        button=ttk.Button(parent,text=text,command=command,style="Primary.TButton" if primary else "P.TButton")
        if help_text:self._tip.bind(button,help_text)
        return button

    def _icon(self,master,name):
        key=(name,WORKFLOW_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_icon(master,name,WORKFLOW_ICON_SIZE)
        return self._icons[key]

    def _build(self):
        outer=ttk.Frame(self.parent,padding=(6,4));outer.pack(fill="both",expand=True)
        outer.columnconfigure(0,weight=1);outer.rowconfigure(1,weight=1)

        header=ttk.Frame(outer);header.grid(row=0,column=0,sticky="ew",pady=(0,4))
        actions=ttk.Frame(header,style="Toolbar.TFrame");actions.pack(fill="x")
        self.apply_button=self._button(
            actions,"Apply crop",self.apply_current,
            "Save all crop edits on this plate and stay on the current plate.",True,
        );self.apply_button.pack(side="left")
        ttk.Label(
            actions,
            text="Click a crop to select it · drag inside/edges to adjust · drag empty space to add · Delete removes selected.",
            style="Muted.TLabel",
        ).pack(side="left",padx=10)
        self.save_status=ttk.Label(actions,text="",style="Muted.TLabel");self.save_status.pack(side="left",padx=(4,0))
        self.batch_actions=ttk.Frame(actions,style="Toolbar.TFrame")
        self.previous_button=self._button(self.batch_actions,"Previous",lambda:self._move_batch(-1),"Go to the previous plate in this batch.")
        self.previous_button.pack(side="left")
        self.confirm_button=self._button(
            self.batch_actions,"Confirm & Next",self.confirm_plate_next,
            "Apply the current crops, mark this whole plate as human-confirmed training truth, and continue.",True,
        );self.confirm_button.pack(side="left",padx=(5,0))
        self.batch_status=ttk.Label(self.batch_actions,text="",style="Muted.TLabel");self.batch_status.pack(side="left",padx=(8,0))

        body=ttk.Panedwindow(outer,orient="horizontal");body.grid(row=1,column=0,sticky="nsew")
        left=ttk.LabelFrame(body,text="Source X-rays",padding=6);center=ttk.Frame(body)
        body.add(left,weight=1);body.add(center,weight=6)
        self.plates=ttk.Treeview(left,columns=("status","count"),show="tree headings",selectmode="browse",height=18)
        self.plates.heading("#0",text="Plate");self.plates.column("#0",width=190,stretch=True)
        self.plates.heading("status",text="Status");self.plates.column("status",width=86,anchor="center",stretch=False)
        self.plates.heading("count",text="Specimens");self.plates.column("count",width=72,anchor="center",stretch=False)
        plate_scroll=ttk.Scrollbar(left,orient="vertical",command=self.plates.yview);self.plates.configure(yscrollcommand=plate_scroll.set)
        self.plates.pack(side="left",fill="both",expand=True);plate_scroll.pack(side="right",fill="y")
        self.plates.bind("<<TreeviewSelect>>",self._plate_selected)

        self.canvas=tk.Canvas(center,background="#202020",highlightthickness=0,cursor="crosshair",takefocus=True)
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",lambda _e:self._draw())
        self.canvas.bind("<Button-1>",self._canvas_down)
        self.canvas.bind("<B1-Motion>",self._canvas_drag)
        self.canvas.bind("<ButtonRelease-1>",self._canvas_up)
        self.canvas.bind("<Delete>",self.delete_selected)
        self.canvas.bind("<BackSpace>",self.delete_selected)

        workflow=ttk.Frame(outer,style="WorkflowDock.TFrame",padding=(0,2,0,0));workflow.grid(row=2,column=0,sticky="ew",pady=(4,0))
        workflow.columnconfigure(0,weight=1)
        workflow_header=ttk.Frame(workflow,style="WorkflowDock.TFrame");workflow_header.grid(row=0,column=0,sticky="ew",pady=(0,2))
        workflow_header.columnconfigure(0,weight=1)
        ttk.Label(workflow_header,text="Workflow",style="WorkflowDockTitle.TLabel").grid(row=0,column=0,sticky="w")
        self._button(workflow_header,"Help",self._show_help,"Open a short guide for X-ray cropping.").grid(row=0,column=1,sticky="e")
        cards=ttk.Frame(workflow,style="WorkflowDock.TFrame");cards.grid(row=1,column=0,sticky="ew")
        for column in range(3):cards.columnconfigure(column,weight=1,uniform="workflow")

        one=self._workflow_card(cards,0,"1. Training batch","crop_training","Create or continue human-corrected plate examples used for detector training.")
        ttk.Label(one,text="Manual corrected examples",style="Muted.TLabel").grid(row=0,column=0,columnspan=3,sticky="w")
        ttk.Label(one,text="Batch size").grid(row=1,column=0,sticky="w",pady=(5,0))
        ttk.Spinbox(one,from_=1,to=100,textvariable=self.training_batch_size,width=5).grid(row=1,column=1,sticky="w",padx=4,pady=(5,0))
        ttk.Label(one,text="Recommended 6–10",style="Muted.TLabel").grid(row=1,column=2,sticky="w",pady=(5,0))
        self.training_button=self._button(one,"Start first batch",self.start_training_batch,"Prepare diverse plates for manual crop correction.")
        self.training_button.grid(row=2,column=0,columnspan=3,sticky="w",pady=(7,0))

        two=self._workflow_card(cards,1,"2. Train","crop_train","Train a new X-ray Crop detector from all human-confirmed plates.")
        self.model_label=ttk.Label(two,text="Active: none",style="Muted.TLabel");self.model_label.grid(row=0,column=0,sticky="w")
        self.training_count_label=ttk.Label(two,text="Train-ready: 0 plates · 0 specimens");self.training_count_label.grid(row=1,column=0,sticky="w",pady=(4,0))
        self.train_button=self._button(two,"Train X-ray crop model",self.train_model,"Train from all verified X-ray crop examples.",True)
        self.train_button.grid(row=2,column=0,sticky="w",pady=(7,0))

        three=self._workflow_card(cards,2,"3. Predict & review","crop_apply","Predict only plates that do not already have protected human edits or pending model crops.")
        self.predict_count_label=ttk.Label(three,text="",style="Muted.TLabel");self.predict_count_label.grid(row=0,column=0,columnspan=3,sticky="w")
        batch_row=ttk.Frame(three);batch_row.grid(row=1,column=0,columnspan=3,sticky="w",pady=(5,0))
        ttk.Label(batch_row,text="Next").pack(side="left")
        ttk.Spinbox(batch_row,from_=1,to=500,textvariable=self.prediction_batch_size,width=5).pack(side="left",padx=4)
        ttk.Label(batch_row,text="remaining plates",style="Muted.TLabel").pack(side="left")
        predict_actions=ttk.Frame(three);predict_actions.grid(row=2,column=0,columnspan=3,sticky="w",pady=(7,0))
        self.predict_next_button=self._button(predict_actions,"Predict next",lambda:self.predict_batch(self.prediction_batch_size.get()),"Predict specimen crops for the next eligible plates.")
        self.predict_next_button.pack(side="left")
        self.predict_all_button=self._button(predict_actions,"Predict all remaining",lambda:self.predict_batch(None),"Predict specimen crops for every remaining eligible plate.")
        self.predict_all_button.pack(side="left",padx=4)
        self.review_button=self._button(predict_actions,"Review AI crops",self.review_ai,"Review all plates with pending AI crop proposals.")
        self.review_button.pack(side="left")

    def _workflow_card(self,parent,column,title,icon,help_text):
        label=ttk.Frame(parent)
        ttk.Label(label,image=self._icon(label,icon)).pack(side="left",padx=(0,6))
        ttk.Label(label,text=title,style="WorkflowCardTitle.TLabel").pack(side="left")
        card=ttk.LabelFrame(parent,labelwidget=label,padding=(7,5),style="WorkflowCard.TLabelframe")
        card.grid(row=0,column=column,sticky="nsew",padx=(0 if column==0 else 4,0))
        self._tip.bind(card,help_text);self._tip.bind(label,help_text)
        return card

    def _show_help(self):
        dialog=tk.Toplevel(self.root);dialog.title("X-ray Crop — quick guide");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="X-ray Crop — quick guide",font=("Segoe UI",11,"bold")).pack(anchor="w")
        text=(
            "1. Adjust crops\nClick a rectangle to select it. Drag it or its handles just like Landmark Crop. "
            "Drag on empty image space to create a missing crop; press Delete to remove the selected crop.\n\n"
            "2. Apply crop\nApply crop saves the current plate but does not make it training truth.\n\n"
            "3. Training batch\nCorrect every specimen on each plate, then Confirm & Next. Only a human-confirmed whole plate teaches the model.\n\n"
            "4. Train and predict\nTrain from confirmed plates, then predict the next batch or all remaining plates and review them."
        )
        ttk.Label(frame,text=text,justify="left",wraplength=600).pack(anchor="w",pady=(8,0))
        self._button(frame,"Close",dialog.destroy,"Close this guide.").pack(anchor="e",pady=(14,0))
        center(self.root,dialog)

    def _batch(self):
        return self.project.get_ui_state("xray_crop_active_batch",{})

    def _set_batch(self,ids,batch_type,model_id=""):
        ids=list(dict.fromkeys(ids))
        self.project.set_ui_state("xray_crop_active_batch",{"batch_type":str(batch_type),"ids":ids,"position":0,"model_id":str(model_id or "")})
        if ids:self.selected_image_id=ids[0]
        self.refresh(preserve_plate=bool(ids))
        return bool(ids)

    def _refresh_list(self,preserve_selection=True):
        previous=self.selected_image_id if preserve_selection else None
        rows=self.project.source_images();specimens=self.project.specimens();batch=self._batch();batch_ids=set(batch.get("ids") or [])
        by_image={}
        for item in specimens:
            if item["excluded"]:continue
            by_image.setdefault(item["image_id"],[]).append(item)
        self._refreshing_list=True
        try:
            self.plates.delete(*self.plates.get_children())
            for row in rows:
                items=by_image.get(row["image_id"],[])
                if row["crop_reviewed"]:status="Verified"
                elif row["image_id"] in batch_ids:
                    status="AI review" if batch.get("batch_type")=="prediction_review" else "Training"
                elif any(x["crop_source"]=="model" and x["crop_status"]=="proposed" for x in items):status="AI review"
                elif items:status="Proposed"
                else:status="Uncropped"
                self.plates.insert("","end",iid=row["image_id"],text=row["relative_path"],values=(status,len(items)))
            if previous and self.plates.exists(previous):
                self.plates.selection_set(previous);self.plates.focus(previous);self.plates.see(previous)
        finally:self._refreshing_list=False

        summary=self.project.crop_summary();model=self.project.active_crop_model();training=self.project.training_plates()
        self.training_button.configure(text="Start first batch" if not training else "Add next batch")
        self.model_label.configure(text=f"Active: {(model or {}).get('model_id') or 'none'}")
        self.training_count_label.configure(text=f"Train-ready: {len(training)} plates · {summary['training_specimens']} specimens")
        self.predict_count_label.configure(text=f"Remaining {len(self.project.prediction_candidate_ids())} · AI review {summary['ai_pending_plates']} · Verified {summary['verified_plates']}")
        model_state="normal" if model else "disabled"
        self.predict_next_button.configure(state=model_state);self.predict_all_button.configure(state=model_state)
        self.review_button.configure(state="normal" if summary["ai_pending_plates"] else "disabled")
        self._update_batch_controls()

    def refresh(self,preserve_plate=True):
        previous=self.selected_image_id if preserve_plate else None
        self._refresh_list(preserve_selection=preserve_plate)
        ids=list(self._batch().get("ids") or [])
        plate_ids=self.plates.get_children()
        target=previous if previous and self.plates.exists(previous) else (ids[0] if ids and self.plates.exists(ids[0]) else (plate_ids[0] if plate_ids else None))
        if target:
            self._refreshing_list=True
            try:self.plates.selection_set(target);self.plates.focus(target);self.plates.see(target)
            finally:self._refreshing_list=False
            self._load_plate(target)
        else:self._clear_canvas()
        self.on_changed()

    def _update_batch_controls(self):
        state=self._batch();ids=list(state.get("ids") or [])
        active=bool(ids and self.selected_image_id in ids)
        if not active:
            if self.batch_actions.winfo_manager():self.batch_actions.pack_forget()
            self.batch_status.configure(text="")
            return
        if not self.batch_actions.winfo_manager():self.batch_actions.pack(side="right")
        pos=ids.index(self.selected_image_id)
        self.previous_button.configure(state="normal" if pos>0 else "disabled")
        label="AI review" if state.get("batch_type")=="prediction_review" else "Training batch"
        self.batch_status.configure(text=f"{label} {pos+1}/{len(ids)}")

    def _plate_selected(self,_event=None):
        if self._refreshing_list:return
        selected=self.plates.selection()
        if selected and selected[0]!=self.selected_image_id:self._load_plate(selected[0])

    def _load_plate(self,image_id):
        self.selected_image_id=image_id;self.session.load(self.project.specimens(image_id))
        self._drag_mode=self._drag_anchor=self._drag_initial=None;self._drawing_crop=None;self._drag_changed=False
        try:preview,_scale,original_size=display_preview(self.project.source_image_path(image_id),1400)
        except Exception as exc:messagebox.showerror("X-ray Crops",str(exc),parent=self.root);return
        self.preview=preview;self.preview_original_size=original_size;self._photo_key=None
        self._set_save_status();self._update_batch_controls();self._draw()

    def _clear_canvas(self):
        self.canvas.delete("all");self.preview=self.photo=None;self._photo_key=None;self.selected_image_id=None;self.session.load(())
        self._set_save_status();self._update_batch_controls()

    def _set_save_status(self,text=None):
        if text is None:text="Unsaved changes" if self.session.dirty else ""
        self.save_status.configure(text=text)

    def _fit(self):
        if self.preview is None:return None
        cw=max(2,self.canvas.winfo_width());ch=max(2,self.canvas.winfo_height())
        scale=min(max(1,cw-28)/self.preview.width,max(1,ch-28)/self.preview.height,1.0)
        width=max(1,round(self.preview.width*scale));height=max(1,round(self.preview.height*scale))
        ox=(cw-width)//2;oy=(ch-height)//2
        self.display_scale=(width/self.preview_original_size[0]) if self.preview_original_size[0] else 1.0;self.offset=(ox,oy)
        key=(id(self.preview),width,height)
        if key!=self._photo_key:
            fitted=self.preview if (width,height)==self.preview.size else self.preview.resize((width,height),Image.Resampling.LANCZOS)
            self.photo=ImageTk.PhotoImage(fitted,master=self.canvas);self._photo_key=key
        return self.photo

    def _screen(self,x,y):return self.offset[0]+float(x)*self.display_scale,self.offset[1]+float(y)*self.display_scale
    def _original(self,x,y):return (float(x)-self.offset[0])/max(1e-9,self.display_scale),(float(y)-self.offset[1])/max(1e-9,self.display_scale)

    def _draw(self):
        self.canvas.delete("all");photo=self._fit()
        if photo is None:return
        self.canvas.create_image(self.offset[0],self.offset[1],anchor="nw",image=photo,tags="plate")
        for item in self.session.active_items():
            crop=item.get("crop") or {};corners=crop.get("corners") or []
            if len(corners)!=4:continue
            selected=item["specimen_id"]==self.session.selected_id
            pts=[]
            for x,y in corners:pts.extend(self._screen(x,y))
            if selected:color="#35d07f";width=3
            elif item.get("crop_status")=="confirmed":color="#6ba987";width=2
            else:color="#d3a63d";width=2
            self.canvas.create_polygon(*pts,outline=color,fill="",width=width,tags="crop")
            cx,cy=self._screen(crop.get("center_x",0),crop.get("center_y",0))
            self.canvas.create_text(cx,cy,text=str(item.get("ordinal") or ""),fill="white",font=("Segoe UI",9,"bold"),tags="crop")
            if selected:self._draw_handles(crop)
        if self._drawing_crop is not None:
            pts=[]
            for x,y in self._drawing_crop.get("corners") or ():pts.extend(self._screen(x,y))
            if len(pts)==8:self.canvas.create_polygon(*pts,outline="#35d07f",fill="",width=2,dash=(5,3),tags="crop")
        if self.session.selected_id:
            self.canvas.create_text(12,12,anchor="nw",fill="white",text="Selected crop · Delete removes it",tags="crop_hint")
        else:
            self.canvas.create_text(12,12,anchor="nw",fill="white",text="Drag empty space to draw a new crop",tags="crop_hint")

    def _draw_handles(self,crop):
        corners=crop.get("corners") or []
        for point in corners:
            hx,hy=self._screen(*point)
            self.canvas.create_rectangle(hx-5,hy-5,hx+5,hy+5,fill="#35d07f",outline="white",tags="crop_handle")
        angle=math.radians(float(crop.get("angle_degrees",0)));major=(math.cos(angle),math.sin(angle))
        reach=float(crop.get("length",0))/2+35/max(self.display_scale,1e-6)
        rx=float(crop.get("center_x",0))+reach*major[0];ry=float(crop.get("center_y",0))+reach*major[1]
        ex=float(crop.get("center_x",0))+float(crop.get("length",0))/2*major[0]
        ey=float(crop.get("center_y",0))+float(crop.get("length",0))/2*major[1]
        sx,sy=self._screen(rx,ry);tx,ty=self._screen(ex,ey)
        self.canvas.create_line(tx,ty,sx,sy,fill="#ffcc00",width=2,tags="crop_handle")
        self.canvas.create_oval(sx-7,sy-7,sx+7,sy+7,fill="#ffcc00",outline="white",tags="crop_handle")

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
        self.canvas.focus_set();x,y=self._original(event.x,event.y)
        selected=self.session.item()
        ordered=([selected] if selected else [])+[item for item in reversed(self.session.active_items()) if selected is None or item["specimen_id"]!=selected["specimen_id"]]
        for item in ordered:
            if item is None:continue
            hit=self._hit_crop(x,y,item)
            if hit is None:continue
            self.session.select(item["specimen_id"]);crop=item.get("crop") or {}
            self._drag_mode=hit;self._drag_anchor=(x,y);self._drag_changed=False
            self._drag_initial=(
                float(crop.get("center_x",0)),float(crop.get("center_y",0)),
                float(crop.get("length",0)),float(crop.get("width",0)),float(crop.get("angle_degrees",0)),
            )
            self._drawing_crop=None;self._draw();return
        self.session.select(None);self._drag_mode=("draw",0);self._drag_anchor=(x,y);self._drag_initial=None;self._drag_changed=False;self._drawing_crop=None
        self._draw()

    def _canvas_drag(self,event):
        if self._drag_mode is None or not self.selected_image_id:return
        x,y=self._original(event.x,event.y);ax,ay=self._drag_anchor
        if abs(x-ax)+abs(y-ay)>1.0:self._drag_changed=True
        if self._drag_mode[0]=="draw":
            left,right=sorted((ax,x));top,bottom=sorted((ay,y))
            if right-left>=2 and bottom-top>=2:
                self._drawing_crop=crop_from_geometry((left+right)/2,(top+bottom)/2,right-left,bottom-top,0,self.preview_original_size,algorithm="manual")
            self._draw();return
        if not self._drag_changed:return
        cx,cy,length,width,angle=self._drag_initial
        if self._drag_mode[0]=="move":
            cx+=x-ax;cy+=y-ay
        elif self._drag_mode[0]=="rotate":
            angle=math.degrees(math.atan2(y-cy,x-cx))
        else:
            a=math.radians(angle);major=(math.cos(a),math.sin(a));minor=(-major[1],major[0])
            initial_corners=crop_corners(cx,cy,length,width,angle)
            opposite=initial_corners[(int(self._drag_mode[1])+2)%4]
            dx=x-opposite[0];dy=y-opposite[1]
            cx=(x+opposite[0])/2;cy=(y+opposite[1])/2
            length=max(20.0,abs(dx*major[0]+dy*major[1]));width=max(20.0,abs(dx*minor[0]+dy*minor[1]))
        crop=crop_from_geometry(cx,cy,length,width,angle,self.preview_original_size,confidence="high",algorithm="manual")
        self.session.update_selected(crop);self._set_save_status();self._draw()

    def _canvas_up(self,_event):
        if self._drag_mode is None:return
        if self._drag_mode[0]=="draw":
            crop=self._drawing_crop
            self._drag_mode=self._drag_anchor=self._drag_initial=None;self._drawing_crop=None
            if crop is not None and float(crop.get("length",0))>=20 and float(crop.get("width",0))>=20:
                self.session.add(crop);self._set_save_status()
            self._draw();return
        self._drag_mode=self._drag_anchor=self._drag_initial=None;self._drag_changed=False
        self._draw()

    def delete_selected(self,_event=None):
        if not self.session.delete_selected():return "break"
        self._set_save_status();self._draw();return "break"

    def apply_current(self,silent=False):
        if not self.selected_image_id:return "FAILED"
        if not self.session.dirty:
            if not silent:self._set_save_status("No changes to apply")
            return "SAVED"
        changes=self.session.changes();selected=self.session.selected_id
        try:
            result=self.project.apply_plate_crop_edits(
                self.selected_image_id,
                edits=changes["edits"],new_crops=changes["new_crops"],removed_ids=changes["removed_ids"],
            )
        except Exception as exc:
            messagebox.showerror("Apply crop",str(exc),parent=self.root);return "FAILED"
        selected=result.get("id_map",{}).get(selected,selected)
        self.session.load(self.project.specimens(self.selected_image_id),selected_id=selected)
        self._refresh_list(preserve_selection=True);self._set_save_status("Crop saved");self._draw();self.on_changed()
        return "SAVED"

    def start_training_batch(self):
        if self._busy:return
        count=max(1,int(self.training_batch_size.get()));batch_ids=self.project.select_training_plate_ids(count)
        if not batch_ids:
            messagebox.showinfo("X-ray training batch","No unverified plates are available.",parent=self.root);return
        self._busy=True;events=queue.Queue()
        dialog=tk.Toplevel(self.root);dialog.title("Prepare crop training batch");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
        label=ttk.Label(frame,text="Selecting training plates…",justify="left");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="determinate",maximum=len(batch_ids));bar.pack(fill="x",pady=(8,0));center(self.root,dialog)
        def worker():
            try:
                for index,image_id in enumerate(batch_ids,1):
                    if not self.project.specimens(image_id):
                        proposals=detect_specimens(self.project.source_image_path(image_id))
                        self.project.replace_auto_proposals(image_id,proposals,"xray-otsu-pca-v1")
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
        if self.apply_current(silent=True)!="SAVED":return
        try:self.project.confirm_plate(self.selected_image_id,"human")
        except Exception as exc:messagebox.showerror("Confirm X-ray plate",str(exc),parent=self.root);return
        self._move_batch(1)

    def _move_batch(self,step):
        state=self._batch();ids=list(state.get("ids") or [])
        if not ids or self.selected_image_id not in ids:return
        pos=ids.index(self.selected_image_id)+int(step)
        if pos<0:pos=0
        if pos>=len(ids):
            finished_type=state.get("batch_type")
            self.project.set_ui_state("xray_crop_active_batch",{"batch_type":finished_type,"ids":[],"finished":True})
            self._refresh_list(preserve_selection=True);self._update_batch_controls()
            if finished_type=="training":
                messagebox.showinfo("Crop training batch","Batch complete. Human-confirmed plates are ready for training.",parent=self.root)
            else:messagebox.showinfo("Crop review batch","Batch review complete.",parent=self.root)
            return
        state["position"]=pos;self.project.set_ui_state("xray_crop_active_batch",state)
        self._refresh_list(preserve_selection=False)
        self._refreshing_list=True
        try:self.plates.selection_set(ids[pos]);self.plates.focus(ids[pos]);self.plates.see(ids[pos])
        finally:self._refreshing_list=False
        self._load_plate(ids[pos]);self.on_changed()

    def train_model(self):
        if self._busy:return
        if len(self.project.training_plates())<3:
            messagebox.showinfo("Train crop model","Confirm at least 3 plates first. A first batch of 6–10 diverse plates is recommended.",parent=self.root);return
        self._busy=True;events=queue.Queue()
        dialog=tk.Toplevel(self.root);dialog.title("Train crop model");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack();label=ttk.Label(frame,text="Training X-ray crop model…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="indeterminate");bar.pack(fill="x",pady=(8,0));bar.start();center(self.root,dialog)
        def progress(stage,detail):events.put(("stage",stage,detail))
        def worker():
            try:events.put(("done",train_detector(self.project,progress=progress)))
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
                        self._busy=False;dialog.destroy();result=event[1];self._refresh_list()
                        messagebox.showinfo("Crop training",f"Model ready: {result['model_id']}\nTraining plates: {result['training_plates']}\nTraining specimens: {result['training_specimens']}",parent=self.root);return
            except queue.Empty:self.root.after(150,poll)
        poll()

    def predict_batch(self,count):
        if self._busy:return
        if self.session.dirty and self.apply_current(silent=True)!="SAVED":return
        model=self.project.active_crop_model()
        if not model:
            messagebox.showinfo("Predict Crop","Train an X-ray crop model first.",parent=self.root);return
        candidates=self.project.prediction_candidate_ids()
        ids=candidates if count is None else self.project.select_prediction_plate_ids(max(1,int(count)))
        if not ids:
            messagebox.showinfo("Predict Crop","No remaining eligible plates need prediction.",parent=self.root);return
        self._busy=True;events=queue.Queue();cancel=threading.Event()
        dialog=tk.Toplevel(self.root);dialog.title("Predict Crop");dialog.transient(self.root);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=14);frame.pack()
        label=ttk.Label(frame,text=f"Preparing crop predictions for {len(ids)} plate(s)…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="determinate",maximum=len(ids));bar.pack(fill="x",pady=(8,0))
        self._button(frame,"Cancel",cancel.set,"Stop after the current crop prediction.").pack(anchor="e",pady=(8,0));center(self.root,dialog)
        def worker():
            try:
                result=predict_plates(self.project,ids,cancel=cancel,progress=lambda done,total,image_id:events.put(("progress",done,total,image_id)))
                events.put(("done",result))
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
                        self._busy=False;dialog.destroy();result=event[1];self._refresh_list()
                        summary=f"Predicted: {result['success']} plate(s)."
                        if result.get("failures"):summary+=f"\nNeeds attention: {len(result['failures'])}."
                        success=list(result.get("successful_ids") or [])
                        if success and messagebox.askyesno("Predict Crop",summary+"\n\nReview this batch now?",parent=self.root,default=messagebox.YES):
                            self._set_batch(success,"prediction_review",result.get("model_id"));return
                        messagebox.showinfo("Predict Crop",summary,parent=self.root);return
            except queue.Empty:self.root.after(100,poll)
        poll()

    def review_ai(self):
        ids=self.project.ai_review_plate_ids()
        if not ids:
            messagebox.showinfo("Review AI crops","No AI crop proposals require review.",parent=self.root);return
        self._set_batch(ids,"prediction_review",(self.project.active_crop_model() or {}).get("model_id",""))
