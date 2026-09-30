"""Tk workspace for the X-ray plate-to-specimen crop workflow."""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from .xray_crop import crop_from_geometry, detect_specimens, display_preview
from .xray_detector import predict_plates, train_detector


class XRayCropWorkspace:
    """Training-first plate workflow mirroring the production Landmark Crop UX."""

    def __init__(self,parent,project,on_changed=None):
        self.parent=parent;self.project=project;self.on_changed=on_changed or (lambda:None)
        self.selected_image_id=None;self.selected_specimen_id=None
        self.preview=self.photo=None;self.preview_original_size=(1,1);self.display_scale=1.0;self.offset=(0,0)
        self._busy=False;self._add_mode=False;self._add_start=None
        self.training_batch_size=tk.IntVar(value=6);self.prediction_batch_size=tk.IntVar(value=6)
        self._build();self.refresh()

    def _build(self):
        outer=ttk.Frame(self.parent);outer.pack(fill="both",expand=True)

        toolbar=ttk.Frame(outer);toolbar.pack(fill="x",pady=(0,6))
        self.previous_button=ttk.Button(toolbar,text="Previous",command=lambda:self._move_batch(-1))
        self.previous_button.pack(side="left")
        self.confirm_button=ttk.Button(toolbar,text="Confirm plate & Next",style="Primary.TButton",command=self.confirm_plate_next)
        self.confirm_button.pack(side="left",padx=(6,0))
        ttk.Label(toolbar,text="Correct the proposed specimen frames; a plate becomes training truth only after confirmation.",style="Muted.TLabel").pack(side="left",padx=10)
        self.batch_status=ttk.Label(toolbar,text="",style="Muted.TLabel");self.batch_status.pack(side="right")

        workflow=ttk.Frame(outer);workflow.pack(fill="x",pady=(0,7))
        for column in range(3):workflow.columnconfigure(column,weight=1)

        one=ttk.LabelFrame(workflow,text="1. Training batch",padding=8);one.grid(row=0,column=0,sticky="nsew",padx=(0,4))
        ttk.Label(one,text="Human-confirmed plates teach the detector.",style="Muted.TLabel").grid(row=0,column=0,columnspan=3,sticky="w")
        ttk.Label(one,text="Plates").grid(row=1,column=0,sticky="w",pady=(5,0))
        ttk.Spinbox(one,from_=1,to=100,textvariable=self.training_batch_size,width=5).grid(row=1,column=1,sticky="w",padx=4,pady=(5,0))
        ttk.Label(one,text="Recommended 6–10",style="Muted.TLabel").grid(row=1,column=2,sticky="w",pady=(5,0))
        self.training_button=ttk.Button(one,text="Start first batch",command=self.start_training_batch)
        self.training_button.grid(row=2,column=0,columnspan=3,sticky="w",pady=(7,0))

        two=ttk.LabelFrame(workflow,text="2. Train",padding=8);two.grid(row=0,column=1,sticky="nsew",padx=4)
        self.model_label=ttk.Label(two,text="Active: none",style="Muted.TLabel");self.model_label.grid(row=0,column=0,sticky="w")
        self.training_count_label=ttk.Label(two,text="Train-ready: 0 plates · 0 specimens");self.training_count_label.grid(row=1,column=0,sticky="w",pady=(5,0))
        self.train_button=ttk.Button(two,text="Train X-ray crop model",style="Primary.TButton",command=self.train_model)
        self.train_button.grid(row=2,column=0,sticky="w",pady=(7,0))

        three=ttk.LabelFrame(workflow,text="3. Predict & review",padding=8);three.grid(row=0,column=2,sticky="nsew",padx=(4,0))
        self.predict_count_label=ttk.Label(three,text="",style="Muted.TLabel");self.predict_count_label.grid(row=0,column=0,columnspan=3,sticky="w")
        ttk.Label(three,text="Next").grid(row=1,column=0,sticky="w",pady=(5,0))
        ttk.Spinbox(three,from_=1,to=500,textvariable=self.prediction_batch_size,width=5).grid(row=1,column=1,sticky="w",padx=4,pady=(5,0))
        ttk.Label(three,text="plates",style="Muted.TLabel").grid(row=1,column=2,sticky="w",pady=(5,0))
        actions=ttk.Frame(three);actions.grid(row=2,column=0,columnspan=3,sticky="w",pady=(7,0))
        self.predict_next_button=ttk.Button(actions,text="Predict next",command=lambda:self.predict_batch(self.prediction_batch_size.get()))
        self.predict_next_button.pack(side="left")
        self.predict_all_button=ttk.Button(actions,text="Predict all remaining",command=lambda:self.predict_batch(None))
        self.predict_all_button.pack(side="left",padx=4)
        self.review_button=ttk.Button(actions,text="Review AI crops",command=self.review_ai)
        self.review_button.pack(side="left")

        body=ttk.Panedwindow(outer,orient="horizontal");body.pack(fill="both",expand=True)
        left=ttk.LabelFrame(body,text="Source X-rays",padding=6);center=ttk.Frame(body);right=ttk.LabelFrame(body,text="Selected specimen",padding=8)
        body.add(left,weight=1);body.add(center,weight=5);body.add(right,weight=2)

        self.plates=ttk.Treeview(left,columns=("status","count"),show="tree headings",selectmode="browse",height=18)
        self.plates.heading("#0",text="Plate");self.plates.column("#0",width=190,stretch=True)
        self.plates.heading("status",text="Status");self.plates.column("status",width=86,anchor="center",stretch=False)
        self.plates.heading("count",text="Fish");self.plates.column("count",width=44,anchor="center",stretch=False)
        plate_scroll=ttk.Scrollbar(left,orient="vertical",command=self.plates.yview);self.plates.configure(yscrollcommand=plate_scroll.set)
        self.plates.pack(side="left",fill="both",expand=True);plate_scroll.pack(side="right",fill="y")
        self.plates.bind("<<TreeviewSelect>>",self._plate_selected)

        self.canvas=tk.Canvas(center,background="#202020",highlightthickness=0,cursor="crosshair")
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",lambda _e:self._draw())
        self.canvas.bind("<Button-1>",self._canvas_down)
        self.canvas.bind("<ButtonRelease-1>",self._canvas_up)

        self.name_var=tk.StringVar(value="No specimen selected")
        ttk.Label(right,textvariable=self.name_var,style="SectionTitle.TLabel",wraplength=260).pack(anchor="w")
        self.meta_var=tk.StringVar(value="")
        ttk.Label(right,textvariable=self.meta_var,style="Muted.TLabel",wraplength=260,justify="left").pack(anchor="w",pady=(3,9))
        self.edit_button=ttk.Button(right,text="Edit crop…",command=self.edit_selected);self.edit_button.pack(fill="x",pady=2)
        self.reject_button=ttk.Button(right,text="False detection — remove",command=self.reject_selected);self.reject_button.pack(fill="x",pady=2)
        self.add_button=ttk.Button(right,text="Add missed specimen",command=self.start_add);self.add_button.pack(fill="x",pady=(10,2))
        ttk.Label(right,text="Do not confirm objects one by one. Correct the whole plate, then use Confirm plate & Next. That confirmed plate becomes training truth.",style="Muted.TLabel",wraplength=260,justify="left").pack(anchor="w",pady=(12,0))

    def _batch(self):
        return self.project.get_ui_state("xray_crop_active_batch",{})

    def _set_batch(self,ids,batch_type,model_id=""):
        ids=list(dict.fromkeys(ids))
        state={"batch_type":str(batch_type),"ids":ids,"position":0,"model_id":str(model_id or "")}
        self.project.set_ui_state("xray_crop_active_batch",state)
        if ids:self._select_plate(ids[0])
        self.refresh()
        return bool(ids)

    def refresh(self,preserve_plate=True):
        previous=self.selected_image_id if preserve_plate else None
        rows=self.project.source_images();specimens=self.project.specimens();batch=self._batch();batch_ids=set(batch.get("ids") or [])
        by_image={}
        for item in specimens:
            if item["excluded"]:continue
            by_image.setdefault(item["image_id"],[]).append(item)
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
        summary=self.project.crop_summary();model=self.project.active_crop_model();training=self.project.training_plates()
        self.training_button.configure(text="Start first batch" if not training else "Add next batch")
        self.model_label.configure(text=f"Active: {(model or {}).get('model_id') or 'none'}")
        self.training_count_label.configure(text=f"Train-ready: {len(training)} plates · {summary['training_specimens']} specimens")
        self.predict_count_label.configure(text=f"Uncropped {summary['uncropped_plates']} · AI review {summary['ai_pending_plates']} · Verified {summary['verified_plates']}")
        model_state="normal" if model else "disabled"
        self.predict_next_button.configure(state=model_state);self.predict_all_button.configure(state=model_state)
        self.review_button.configure(state="normal" if summary["ai_pending_plates"] else "disabled")
        ids=list(batch.get("ids") or []);active=bool(ids and self.selected_image_id in ids)
        self.confirm_button.configure(state="normal" if active else "disabled");self.previous_button.configure(state="normal" if active else "disabled")
        if active:
            pos=ids.index(self.selected_image_id)+1
            label="AI review" if batch.get("batch_type")=="prediction_review" else "Training batch"
            self.batch_status.configure(text=f"{label} {pos}/{len(ids)}")
        else:self.batch_status.configure(text="")
        plate_ids=self.plates.get_children()
        target=previous if previous and self.plates.exists(previous) else (ids[0] if ids and self.plates.exists(ids[0]) else (plate_ids[0] if plate_ids else None))
        if target:
            self.plates.selection_set(target);self.plates.focus(target);self.plates.see(target);self._load_plate(target)
        else:self._clear_canvas()
        self.on_changed()

    def _select_plate(self,image_id):
        if self.plates.exists(image_id):
            self.plates.selection_set(image_id);self.plates.focus(image_id);self.plates.see(image_id)
        self._load_plate(image_id)

    def _plate_selected(self,_event=None):
        selected=self.plates.selection()
        if selected:self._load_plate(selected[0])

    def _load_plate(self,image_id):
        self.selected_image_id=image_id;self.selected_specimen_id=None
        try:preview,_scale,original_size=display_preview(self.project.source_image_path(image_id),1400)
        except Exception as exc:messagebox.showerror("X-ray Crops",str(exc),parent=self.parent);return
        self.preview=preview;self.preview_original_size=original_size;self._update_selected_panel();self._draw()

    def _clear_canvas(self):
        self.canvas.delete("all");self.preview=self.photo=None;self.selected_image_id=self.selected_specimen_id=None;self._update_selected_panel()

    def _fit(self):
        if self.preview is None:return None
        cw=max(2,self.canvas.winfo_width());ch=max(2,self.canvas.winfo_height())
        scale=min(cw/self.preview.width,ch/self.preview.height,1.0)
        width=max(1,round(self.preview.width*scale));height=max(1,round(self.preview.height*scale))
        image=self.preview if scale==1 else self.preview.resize((width,height),Image.Resampling.LANCZOS)
        ox=(cw-width)//2;oy=(ch-height)//2
        self.display_scale=(width/self.preview_original_size[0]) if self.preview_original_size[0] else 1.0;self.offset=(ox,oy)
        return image

    def _screen(self,x,y):return self.offset[0]+float(x)*self.display_scale,self.offset[1]+float(y)*self.display_scale
    def _original(self,x,y):return (float(x)-self.offset[0])/max(1e-9,self.display_scale),(float(y)-self.offset[1])/max(1e-9,self.display_scale)

    def _draw(self):
        self.canvas.delete("all");fitted=self._fit()
        if fitted is None:return
        self.photo=ImageTk.PhotoImage(fitted);self.canvas.create_image(self.offset[0],self.offset[1],anchor="nw",image=self.photo,tags="plate")
        if not self.selected_image_id:return
        for item in self.project.specimens(self.selected_image_id):
            if item["excluded"]:continue
            crop=item.get("crop") or {};corners=crop.get("corners") or []
            if len(corners)!=4:continue
            pts=[]
            for x,y in corners:pts.extend(self._screen(x,y))
            selected=item["specimen_id"]==self.selected_specimen_id
            color="#35d07f" if item["crop_status"]=="confirmed" else "#ffcc00";width=4 if selected else 2
            tag=f"specimen:{item['specimen_id']}"
            self.canvas.create_polygon(*pts,outline=color,fill="",width=width,tags=("crop",tag))
            cx,cy=self._screen(crop.get("center_x",0),crop.get("center_y",0))
            self.canvas.create_text(cx,cy,text=str(item.get("ordinal") or ""),fill="white",font=("Segoe UI",10,"bold"),tags=("crop",tag))
            self.canvas.tag_bind(tag,"<Button-1>",lambda _e,sid=item["specimen_id"]:self._select_specimen(sid))
        if self._add_mode:self.canvas.create_text(15,15,anchor="nw",text="Drag a box around the missed specimen",fill="#ffcc00",font=("Segoe UI",11,"bold"),tags="add_hint")

    def _select_specimen(self,specimen_id):
        self.selected_specimen_id=specimen_id;self._update_selected_panel();self._draw()

    def _update_selected_panel(self):
        if not self.selected_specimen_id:
            self.name_var.set("No specimen selected");self.meta_var.set("")
            self.edit_button.configure(state="disabled");self.reject_button.configure(state="disabled");return
        try:item=self.project.specimen(self.selected_specimen_id)
        except KeyError:self.selected_specimen_id=None;self._update_selected_panel();return
        crop=item.get("crop") or {};qc=item.get("crop_qc") or crop.get("qc") or []
        self.name_var.set(item["label"]);status="Confirmed" if item["crop_status"]=="confirmed" else "Proposed"
        model=f" · {item['model_id']}" if item.get("model_id") else ""
        self.meta_var.set(f"{status} · {item['crop_source'] or 'unknown'}{model}\nAngle {float(crop.get('angle_degrees',0)):.1f}°"+(f"\nQC: {', '.join(qc)}" if qc else ""))
        self.edit_button.configure(state="normal");self.reject_button.configure(state="normal")

    def start_training_batch(self):
        if self._busy:return
        count=max(1,int(self.training_batch_size.get()));candidates=self.project.training_candidate_ids()
        batch_ids=[image_id for image_id in candidates if not self.project.source_image(image_id)["crop_reviewed"]][:count]
        if not batch_ids:
            messagebox.showinfo("X-ray training batch","No unverified plates are available.",parent=self.parent);return
        self._busy=True;events=queue.Queue()
        dialog=tk.Toplevel(self.parent);dialog.title("Prepare X-ray training batch");dialog.transient(self.parent)
        frame=ttk.Frame(dialog,padding=14);frame.pack();label=ttk.Label(frame,text="Preparing initial specimen proposals…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="determinate",maximum=len(batch_ids));bar.pack(fill="x",pady=(8,0))
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
                    if event[0]=="progress":bar.configure(value=event[1]);label.configure(text=f"Preparing plate {event[1]} of {event[2]}…")
                    elif event[0]=="error":
                        self._busy=False;dialog.destroy();messagebox.showerror("X-ray training batch",str(event[1]),parent=self.parent);return
                    else:
                        self._busy=False;dialog.destroy();self._set_batch(batch_ids,"training")
                        messagebox.showinfo("X-ray training batch",f"Prepared {len(batch_ids)} plate(s).\n\nCorrect every specimen on each plate, then use Confirm plate & Next.",parent=self.parent);return
            except queue.Empty:self.parent.after(100,poll)
        poll()

    def confirm_plate_next(self):
        if not self.selected_image_id:return
        try:self.project.confirm_plate(self.selected_image_id,"human")
        except Exception as exc:messagebox.showerror("Confirm X-ray plate",str(exc),parent=self.parent);return
        self._move_batch(1)

    def _move_batch(self,step):
        state=self._batch();ids=list(state.get("ids") or [])
        if not ids or self.selected_image_id not in ids:return
        pos=ids.index(self.selected_image_id)+int(step)
        if pos<0:pos=0
        if pos>=len(ids):
            finished_type=state.get("batch_type");self.project.set_ui_state("xray_crop_active_batch",{"batch_type":finished_type,"ids":[],"finished":True})
            self.refresh()
            if finished_type=="training":
                messagebox.showinfo("X-ray training batch","Batch complete. These confirmed plates are now training truth and are ready for model training.",parent=self.parent)
            else:messagebox.showinfo("X-ray crop review","Prediction review batch complete.",parent=self.parent)
            return
        state["position"]=pos;self.project.set_ui_state("xray_crop_active_batch",state);self.selected_image_id=ids[pos];self.refresh()

    def train_model(self):
        if self._busy:return
        if len(self.project.training_plates())<3:
            messagebox.showinfo("Train X-ray crop model","Confirm at least 3 plates first. A first batch of 6–10 diverse plates is recommended.",parent=self.parent);return
        self._busy=True;events=queue.Queue()
        dialog=tk.Toplevel(self.parent);dialog.title("Train X-ray crop model");dialog.transient(self.parent)
        frame=ttk.Frame(dialog,padding=14);frame.pack();label=ttk.Label(frame,text="Preparing detector training…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="indeterminate");bar.pack(fill="x",pady=(8,0));bar.start()
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
                        self._busy=False;dialog.destroy();messagebox.showerror("X-ray crop training",str(event[1]),parent=self.parent);return
                    else:
                        self._busy=False;dialog.destroy();result=event[1];self.refresh()
                        messagebox.showinfo("X-ray crop training",f"Model ready: {result['model_id']}\nTraining plates: {result['training_plates']}\nTraining specimens: {result['training_specimens']}",parent=self.parent);return
            except queue.Empty:self.parent.after(150,poll)
        poll()

    def predict_batch(self,count):
        if self._busy:return
        model=self.project.active_crop_model()
        if not model:
            messagebox.showinfo("Predict X-ray crops","Train an X-ray crop model first.",parent=self.parent);return
        candidates=self.project.prediction_candidate_ids()
        ids=candidates if count is None else candidates[:max(1,int(count))]
        if not ids:
            messagebox.showinfo("Predict X-ray crops","No remaining eligible plates need prediction.",parent=self.parent);return
        self._busy=True;events=queue.Queue();cancel=threading.Event()
        dialog=tk.Toplevel(self.parent);dialog.title("Predict X-ray crops");dialog.transient(self.parent)
        frame=ttk.Frame(dialog,padding=14);frame.pack();label=ttk.Label(frame,text=f"Predicting {len(ids)} plate(s)…");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="determinate",maximum=len(ids));bar.pack(fill="x",pady=(8,0))
        ttk.Button(frame,text="Cancel",command=cancel.set).pack(anchor="e",pady=(8,0))
        def worker():
            try:events.put(("done",predict_plates(self.project,ids,cancel=cancel,progress=lambda done,total,image_id:events.put(("progress",done,total,image_id))))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-detector-predict").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait()
                    if event[0]=="progress":bar.configure(value=event[1]);label.configure(text=f"Predicting plate {event[1]} of {event[2]}…")
                    elif event[0]=="error":
                        self._busy=False;dialog.destroy();messagebox.showerror("Predict X-ray crops",str(event[1]),parent=self.parent);return
                    else:
                        self._busy=False;dialog.destroy();result=event[1];self.refresh()
                        summary=f"Predicted: {result['success']} plate(s)."
                        if result.get("failures"):summary+=f"\nNeeds attention: {len(result['failures'])}."
                        success=list(result.get("successful_ids") or [])
                        if success and messagebox.askyesno("Predict X-ray crops",summary+"\n\nReview this batch now?",parent=self.parent,default=messagebox.YES):
                            self._set_batch(success,"prediction_review",result.get("model_id"));return
                        messagebox.showinfo("Predict X-ray crops",summary,parent=self.parent);return
            except queue.Empty:self.parent.after(100,poll)
        poll()

    def review_ai(self):
        ids=self.project.ai_review_plate_ids()
        if not ids:
            messagebox.showinfo("Review AI crops","No AI-predicted plates require review.",parent=self.parent);return
        self._set_batch(ids,"prediction_review",(self.project.active_crop_model() or {}).get("model_id",""))

    def reject_selected(self):
        if not self.selected_specimen_id:return
        if not messagebox.askyesno("Remove false detection","Remove this proposed specimen from the plate?",parent=self.parent):return
        self.project.reject_specimen(self.selected_specimen_id);self.selected_specimen_id=None;self.refresh()

    def edit_selected(self):
        if not self.selected_specimen_id:return
        item=self.project.specimen(self.selected_specimen_id)
        dialog=XRayCropEditor(self.parent,self.project.source_image_path(item["image_id"]),item["crop"])
        self.parent.wait_window(dialog)
        if dialog.result:self.project.update_specimen_crop(item["specimen_id"],dialog.result);self.refresh()

    def start_add(self):
        if not self.selected_image_id:return
        self._add_mode=True;self._add_start=None;self._draw()

    def _canvas_down(self,event):
        if self._add_mode:self._add_start=(event.x,event.y)

    def _canvas_up(self,event):
        if not self._add_mode or not self._add_start:return
        x0,y0=self._original(*self._add_start);x1,y1=self._original(event.x,event.y)
        self._add_mode=False;self._add_start=None
        left,right=sorted((x0,x1));top,bottom=sorted((y0,y1))
        if right-left<20 or bottom-top<20:self._draw();return
        crop=crop_from_geometry((left+right)/2,(top+bottom)/2,right-left,bottom-top,0,self.preview_original_size,algorithm="manual")
        specimen_id=self.project.add_manual_specimen(self.selected_image_id,crop)
        self.refresh();self._select_specimen(specimen_id)
        messagebox.showinfo("Missed specimen","Specimen added. If it is tilted, use Edit crop to rotate the frame. Confirm the plate only after every specimen is correct.",parent=self.parent)


class XRayCropEditor(tk.Toplevel):
    """Rare-case editor for one oriented rectangle."""

    def __init__(self,parent,image_path,crop):
        super().__init__(parent);self.title("Edit X-ray crop");self.transient(parent);self.result=None
        self.image_path=image_path;self.crop=dict(crop);self.photo=None;self.mode=None;self.anchor=None;self.initial=None
        preview,_scale,original_size=display_preview(image_path,1300)
        self.preview=preview;self.original_size=original_size
        outer=ttk.Frame(self,padding=8);outer.pack(fill="both",expand=True)
        self.canvas=tk.Canvas(outer,background="#202020",width=min(1100,preview.width),height=min(760,preview.height),highlightthickness=0)
        self.canvas.pack(fill="both",expand=True)
        actions=ttk.Frame(outer);actions.pack(fill="x",pady=(7,0))
        ttk.Label(actions,text="Drag inside to move · drag a corner to resize · yellow handle rotates",style="Muted.TLabel").pack(side="left")
        ttk.Button(actions,text="Cancel",command=self.destroy).pack(side="right")
        ttk.Button(actions,text="Save",style="Primary.TButton",command=self._save).pack(side="right",padx=(0,6))
        self.canvas.bind("<Configure>",lambda _e:self._draw())
        self.canvas.bind("<Button-1>",self._down);self.canvas.bind("<B1-Motion>",self._drag);self.canvas.bind("<ButtonRelease-1>",self._up)
        self.grab_set()

    def _fit(self):
        cw=max(2,self.canvas.winfo_width());ch=max(2,self.canvas.winfo_height())
        scale=min(cw/self.preview.width,ch/self.preview.height,1.0)
        w=max(1,round(self.preview.width*scale));h=max(1,round(self.preview.height*scale))
        img=self.preview if scale==1 else self.preview.resize((w,h),Image.Resampling.LANCZOS)
        self.scale=w/self.original_size[0];self.offset=((cw-w)//2,(ch-h)//2)
        return img

    def _screen(self,x,y):return self.offset[0]+x*self.scale,self.offset[1]+y*self.scale
    def _original(self,x,y):return ((x-self.offset[0])/self.scale,(y-self.offset[1])/self.scale)

    def _geometry(self):
        return (float(self.crop["center_x"]),float(self.crop["center_y"]),float(self.crop["length"]),float(self.crop["width"]),float(self.crop["angle_degrees"]))

    def _corners(self):
        cx,cy,length,width,angle=self._geometry();a=math.radians(angle);u=(math.cos(a),math.sin(a));v=(-u[1],u[0])
        return [
            (cx-length/2*u[0]-width/2*v[0],cy-length/2*u[1]-width/2*v[1]),
            (cx+length/2*u[0]-width/2*v[0],cy+length/2*u[1]-width/2*v[1]),
            (cx+length/2*u[0]+width/2*v[0],cy+length/2*u[1]+width/2*v[1]),
            (cx-length/2*u[0]+width/2*v[0],cy-length/2*u[1]+width/2*v[1]),
        ]

    def _draw(self):
        self.canvas.delete("all");img=self._fit();self.photo=ImageTk.PhotoImage(img);self.canvas.create_image(*self.offset,anchor="nw",image=self.photo)
        corners=self._corners();pts=[]
        for point in corners:pts.extend(self._screen(*point))
        self.canvas.create_polygon(*pts,outline="#35d07f",fill="",width=3)
        for point in corners:
            x,y=self._screen(*point);self.canvas.create_rectangle(x-6,y-6,x+6,y+6,fill="#35d07f",outline="white")
        cx,cy,length,width,angle=self._geometry();a=math.radians(angle);u=(math.cos(a),math.sin(a))
        hx,hy=cx+(length/2+35/max(self.scale,1e-6))*u[0],cy+(length/2+35/max(self.scale,1e-6))*u[1]
        sx,sy=self._screen(hx,hy);ex,ey=self._screen(cx+length/2*u[0],cy+length/2*u[1])
        self.canvas.create_line(ex,ey,sx,sy,fill="#ffcc00",width=2);self.canvas.create_oval(sx-7,sy-7,sx+7,sy+7,fill="#ffcc00",outline="white")

    @staticmethod
    def _inside(point,polygon):
        x,y=point;inside=False;j=len(polygon)-1
        for i,(xi,yi) in enumerate(polygon):
            xj,yj=polygon[j]
            if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/(yj-yi+1e-12)+xi:inside=not inside
            j=i
        return inside

    def _hit(self,x,y):
        ox,oy=self._original(x,y);corners=self._corners();tol=14/max(self.scale,1e-6)
        for i,(cx,cy) in enumerate(corners):
            if (ox-cx)**2+(oy-cy)**2<=tol**2:return ("corner",i)
        cx,cy,length,width,angle=self._geometry();a=math.radians(angle);u=(math.cos(a),math.sin(a))
        hx,hy=cx+(length/2+35/max(self.scale,1e-6))*u[0],cy+(length/2+35/max(self.scale,1e-6))*u[1]
        if (ox-hx)**2+(oy-hy)**2<=tol**2:return ("rotate",0)
        if self._inside((ox,oy),corners):return ("move",0)
        return None

    def _down(self,event):
        self.mode=self._hit(event.x,event.y);self.anchor=self._original(event.x,event.y);self.initial=self._geometry()

    def _drag(self,event):
        if not self.mode:return
        x,y=self._original(event.x,event.y);cx,cy,length,width,angle=self.initial
        if self.mode[0]=="move":
            ax,ay=self.anchor;self.crop["center_x"]=cx+x-ax;self.crop["center_y"]=cy+y-ay
        elif self.mode[0]=="rotate":
            self.crop["angle_degrees"]=math.degrees(math.atan2(y-cy,x-cx))
        else:
            a=math.radians(angle);u=(math.cos(a),math.sin(a));v=(-u[1],u[0]);dx=x-cx;dy=y-cy
            self.crop["length"]=max(20.0,2*abs(dx*u[0]+dy*u[1]));self.crop["width"]=max(20.0,2*abs(dx*v[0]+dy*v[1]))
        self._draw()

    def _up(self,_event):self.mode=self.anchor=self.initial=None

    def _save(self):
        cx,cy,length,width,angle=self._geometry()
        self.result=crop_from_geometry(cx,cy,length,width,angle,self.original_size,algorithm="manual")
        self.destroy()
