"""Interactive X-ray structure annotation workspace."""
from __future__ import annotations

import math
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from app.ui.tooltips import Tooltip
from .xray_crop import oriented_crop


def _display_ready(image):
    arr=np.asarray(image)
    if arr.ndim==3:
        if arr.shape[-1]>=3:
            arr=(0.299*arr[...,0]+0.587*arr[...,1]+0.114*arr[...,2])
        else:arr=arr[...,0]
    arr=np.asarray(arr,dtype=np.float32)
    finite=arr[np.isfinite(arr)]
    if not finite.size:return Image.new("L",image.size,0)
    lo=float(np.percentile(finite,0.5));hi=float(np.percentile(finite,99.5))
    if hi<=lo:hi=lo+1.0
    arr=np.clip((arr-lo)*255.0/(hi-lo),0,255).astype(np.uint8)
    return Image.fromarray(arr,"L")


def _shape_symbol(structure):
    return {"circle":"●","triangle":"▲","diamond":"◆","square":"■","cross":"✚","ring":"○"}.get(structure.get("shape"),"●")


class XRayStructureWorkspace:
    def __init__(self,parent,project,on_changed=None):
        self.parent=parent;self.root=parent.winfo_toplevel();self.project=project;self.on_changed=on_changed or (lambda:None)
        self.tip=Tooltip(self.root);self.pass_no=tk.IntVar(value=1)
        self.specimen_query=tk.StringVar();self.sample_query=tk.StringVar()
        self.selected_specimen_id=None;self.active_structure_id=None;self.selected_annotation_id=None
        self.crop_image=None;self.photo=None;self.display_scale=1.0;self.offset=(0,0);self._photo_key=None
        self.annotations=[];self._drag_annotation=None;self._structure_buttons={}
        self._build();self.refresh()

    def _build(self):
        outer=ttk.Frame(self.parent);outer.pack(fill="both",expand=True)
        outer.columnconfigure(1,weight=1);outer.rowconfigure(1,weight=1)

        toolbar=ttk.Frame(outer,style="Toolbar.TFrame");toolbar.grid(row=0,column=0,columnspan=3,sticky="ew",pady=(0,5))
        ttk.Label(toolbar,text="Manual pass").pack(side="left")
        self.pass_box=ttk.Combobox(toolbar,state="readonly",width=16,values=("1 · primary","2 · repeatability"))
        self.pass_box.current(0);self.pass_box.pack(side="left",padx=(5,12));self.pass_box.bind("<<ComboboxSelected>>",self._pass_changed)
        self.previous_button=ttk.Button(toolbar,text="‹ Previous",style="Nav.TButton",command=lambda:self._navigate(-1));self.previous_button.pack(side="right")
        self.verify_button=ttk.Button(toolbar,text="Verify & Next ›",style="NavPrimary.TButton",command=self.verify_next);self.verify_button.pack(side="right",padx=(5,0))
        self.summary_label=ttk.Label(toolbar,text="",style="Muted.TLabel");self.summary_label.pack(side="right",padx=(0,10))
        self.save_label=ttk.Label(toolbar,text="",style="Muted.TLabel");self.save_label.pack(side="left",padx=(8,0))

        left=ttk.LabelFrame(outer,text="Specimens",padding=6);left.grid(row=1,column=0,rowspan=2,sticky="nsew",padx=(0,5))
        left.columnconfigure(0,weight=1);left.rowconfigure(2,weight=1)
        search=ttk.Frame(left);search.grid(row=0,column=0,sticky="ew",pady=(0,5));search.columnconfigure(0,weight=1);search.columnconfigure(1,weight=1)
        ttk.Label(search,text="Sample",style="Muted.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(search,text="Specimen",style="Muted.TLabel").grid(row=0,column=1,sticky="w",padx=(6,0))
        ttk.Entry(search,textvariable=self.sample_query).grid(row=1,column=0,sticky="ew",pady=(2,0))
        ttk.Entry(search,textvariable=self.specimen_query).grid(row=1,column=1,sticky="ew",padx=(6,0),pady=(2,0))
        legend=ttk.Frame(left);legend.grid(row=1,column=0,sticky="ew",pady=(0,4))
        for color,text in (("#d93025"," not started"),("#e6a700"," draft"),("#188038"," verified")):
            sw=tk.Canvas(legend,width=13,height=13,highlightthickness=0,bd=0)
            sw.create_rectangle(2,2,10,10,fill="white",outline=color,width=3);sw.pack(side="left")
            ttk.Label(legend,text=text,style="Muted.TLabel").pack(side="left",padx=(0,6))
        self.listbox=tk.Listbox(left,activestyle="none",exportselection=False,width=40)
        scroll=ttk.Scrollbar(left,orient="vertical",command=self.listbox.yview);self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.grid(row=2,column=0,sticky="nsew");scroll.grid(row=2,column=1,sticky="ns")
        self.listbox.bind("<<ListboxSelect>>",self._list_selected)
        self.sample_query.trace_add("write",lambda *_:self._refresh_list())
        self.specimen_query.trace_add("write",lambda *_:self._refresh_list())

        center=ttk.LabelFrame(outer,text="Specimen crop",padding=4);center.grid(row=1,column=1,sticky="nsew")
        center.columnconfigure(0,weight=1);center.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(center,background="#202020",highlightthickness=0,takefocus=True,cursor="crosshair")
        self.canvas.grid(row=0,column=0,sticky="nsew")
        self.canvas.bind("<Configure>",lambda _e:self._draw())
        self.canvas.bind("<Button-1>",self._canvas_down);self.canvas.bind("<B1-Motion>",self._canvas_drag);self.canvas.bind("<ButtonRelease-1>",self._canvas_up)
        self.canvas.bind("<Delete>",self.delete_selected);self.canvas.bind("<BackSpace>",self.delete_selected)

        right=ttk.LabelFrame(outer,text="Structures to mark",padding=8);right.grid(row=1,column=2,rowspan=2,sticky="nsew",padx=(5,0))
        ttk.Label(right,text="Choose a structure, then click the anatomy. Number keys switch tools.",style="Muted.TLabel",wraplength=290,justify="left").pack(anchor="w",pady=(0,7))
        self.active_label=ttk.Label(right,text="",style="SectionTitle.TLabel");self.active_label.pack(anchor="w",pady=(0,5))
        self.structure_host=ttk.Frame(right);self.structure_host.pack(fill="x")
        ttk.Separator(right,orient="horizontal").pack(fill="x",pady=8)
        ttk.Label(right,text="Editing",style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(right,text="Click a marker to select it. Drag to move. Delete removes the selected marker. Repeated structures are numbered in click order.",style="Muted.TLabel",wraplength=290,justify="left").pack(anchor="w",pady=(3,0))

        bottom=ttk.Frame(outer);bottom.grid(row=2,column=1,sticky="ew",pady=(4,0))
        self.counts_label=ttk.Label(bottom,text="",style="Muted.TLabel");self.counts_label.pack(side="left")
        self.status_label=ttk.Label(bottom,text="",style="Muted.TLabel");self.status_label.pack(side="right")

    def refresh(self):
        self._build_structure_buttons()
        rows=self.project.structure_specimens(self.pass_no.get())
        ids=[row["specimen_id"] for row in rows]
        if self.selected_specimen_id not in ids:self.selected_specimen_id=ids[0] if ids else None
        self._refresh_list(rows)
        if self.selected_specimen_id:self._load_specimen(self.selected_specimen_id)
        else:self._clear()
        self._refresh_summary()

    def _build_structure_buttons(self):
        for child in self.structure_host.winfo_children():child.destroy()
        self._structure_buttons={}
        structures=self.project.scheme.get("structures",[])
        if self.active_structure_id not in {s["id"] for s in structures}:self.active_structure_id=structures[0]["id"] if structures else None
        for structure in structures:
            row=ttk.Frame(self.structure_host);row.pack(fill="x",pady=2)
            marker=tk.Label(row,text=_shape_symbol(structure),foreground=structure.get("color","#1976e9"),font=("Segoe UI Symbol",14,"bold"),width=2)
            marker.pack(side="left")
            button=ttk.Button(row,text=structure["name"],command=lambda sid=structure["id"]:self._choose_structure(sid),style="Primary.TButton" if structure["id"]==self.active_structure_id else "P.TButton")
            button.pack(side="left",fill="x",expand=True);self._structure_buttons[structure["id"]]=button
            hotkey=str(structure.get("hotkey") or "")
            ttk.Label(row,text=hotkey or "—",style="SectionTitle.TLabel",width=3,anchor="center").pack(side="right")
            if hotkey:self.canvas.bind(hotkey,lambda _e,sid=structure["id"]:self._choose_structure(sid))
            self.tip.bind(button,structure.get("description") or structure["name"])
        self._update_active_structure()

    def _choose_structure(self,structure_id):
        self.active_structure_id=structure_id;self.selected_annotation_id=None
        for sid,button in self._structure_buttons.items():button.configure(style="Primary.TButton" if sid==structure_id else "P.TButton")
        self._update_active_structure();self._draw()

    def _structure(self,structure_id=None):
        structure_id=structure_id or self.active_structure_id
        return next((item for item in self.project.scheme.get("structures",[]) if item["id"]==structure_id),None)

    def _update_active_structure(self):
        structure=self._structure()
        if structure is None:self.active_label.configure(text="No structures");return
        role="Repeated series" if structure.get("repeated") else "Single reference"
        self.active_label.configure(text=f"{_shape_symbol(structure)}  {structure['name']} · {role}")

    @staticmethod
    def _sample_name(relative_path):
        parent=Path(str(relative_path)).parent.as_posix()
        return "Root" if parent in {"",".","/"} else parent

    def _filtered_rows(self,rows):
        sq=self.sample_query.get().strip().casefold();iq=self.specimen_query.get().strip().casefold()
        result=[]
        for row in rows:
            sample=self._sample_name(row["relative_path"]);label=str(row.get("label") or "")
            if sq and sq not in sample.casefold():continue
            if iq and iq not in label.casefold() and iq not in Path(row["relative_path"]).name.casefold():continue
            result.append(row)
        return result

    def _refresh_list(self,rows=None):
        rows=rows if rows is not None else self.project.structure_specimens(self.pass_no.get())
        self._visible_rows=self._filtered_rows(rows)
        self.listbox.delete(0,"end")
        for index,row in enumerate(self._visible_rows):
            status=str(row.get("annotation_status") or "")
            symbol="■" if status=="verified" else "□"
            prefix="✓" if status=="verified" else "•" if status=="draft" else " "
            sample=self._sample_name(row["relative_path"]);label=str(row.get("label") or "")
            self.listbox.insert("end",f"{prefix} {symbol} {sample} | {label}")
            color="#188038" if status=="verified" else "#b87900" if status=="draft" else "#8b1d18"
            self.listbox.itemconfig(index,foreground=color)
            if row["specimen_id"]==self.selected_specimen_id:self.listbox.selection_set(index);self.listbox.see(index)

    def _list_selected(self,_event=None):
        sel=self.listbox.curselection()
        if not sel:return
        row=self._visible_rows[sel[0]]
        if row["specimen_id"]!=self.selected_specimen_id:self._load_specimen(row["specimen_id"])

    def _load_specimen(self,specimen_id):
        self.selected_specimen_id=specimen_id;self.selected_annotation_id=None
        item=self.project.specimen(specimen_id)
        try:
            with Image.open(self.project.source_image_path(item["image_id"])) as source:
                source.load();crop=oriented_crop(source,item["crop"])
            self.crop_image=_display_ready(crop)
        except Exception as exc:
            messagebox.showerror("Structures",f"Could not open specimen crop:\n{exc}",parent=self.root);self.crop_image=None
        self.annotations=self.project.annotations(specimen_id,self.pass_no.get())
        self._photo_key=None;self._update_counts();self._draw()
        self._refresh_list();self._refresh_summary()

    def _clear(self):
        self.selected_specimen_id=None;self.crop_image=self.photo=None;self.annotations=[];self.canvas.delete("all");self._update_counts()

    def _refresh_summary(self):
        summary=self.project.annotation_summary(self.pass_no.get())
        self.summary_label.configure(text=f"{summary['verified']} verified · {summary['draft']} draft · {summary['unstarted']} not started")
        self.verify_button.configure(state="normal" if self.selected_specimen_id else "disabled")
        self.previous_button.configure(state="normal" if self.selected_specimen_id else "disabled")

    def _update_counts(self):
        counts={}
        for row in self.annotations:counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        pieces=[]
        for structure in self.project.scheme.get("structures",[]):
            count=counts.get(structure["id"],0)
            pieces.append(f"{structure.get('hotkey') or ''} {structure['name']}: {count}")
        self.counts_label.configure(text="   ·   ".join(pieces))
        run=self.project.annotation_run(self.selected_specimen_id,self.pass_no.get(),create=False) if self.selected_specimen_id else None
        self.status_label.configure(text="Verified" if run and run.get("status")=="verified" else "Draft autosaved" if run else "Not started")

    def _fit(self):
        if self.crop_image is None:return None
        cw=max(2,self.canvas.winfo_width());ch=max(2,self.canvas.winfo_height())
        scale=min(max(1,cw-24)/self.crop_image.width,max(1,ch-24)/self.crop_image.height,1.0)
        w=max(1,round(self.crop_image.width*scale));h=max(1,round(self.crop_image.height*scale));ox=(cw-w)//2;oy=(ch-h)//2
        self.display_scale=w/self.crop_image.width;self.offset=(ox,oy);key=(id(self.crop_image),w,h)
        if key!=self._photo_key:
            fitted=self.crop_image if (w,h)==self.crop_image.size else self.crop_image.resize((w,h),Image.Resampling.LANCZOS)
            self.photo=ImageTk.PhotoImage(fitted,master=self.canvas);self._photo_key=key
        return self.photo

    def _screen(self,x,y):
        return self.offset[0]+float(x)*self.crop_image.width*self.display_scale,self.offset[1]+float(y)*self.crop_image.height*self.display_scale

    def _normal(self,x,y):
        px=(float(x)-self.offset[0])/max(1e-9,self.display_scale);py=(float(y)-self.offset[1])/max(1e-9,self.display_scale)
        return max(0.0,min(1.0,px/max(1,self.crop_image.width))),max(0.0,min(1.0,py/max(1,self.crop_image.height)))

    def _draw(self):
        self.canvas.delete("all");photo=self._fit()
        if photo is None:return
        self.canvas.create_image(self.offset[0],self.offset[1],anchor="nw",image=photo)
        grouped={}
        for row in self.annotations:grouped.setdefault(row["structure_id"],[]).append(row)
        structures={s["id"]:s for s in self.project.scheme.get("structures",[])}
        for sid,rows in grouped.items():
            structure=structures.get(sid)
            if structure is None:continue
            rows=sorted(rows,key=lambda row:(row["sort_order"],row["annotation_id"]))
            for seq,row in enumerate(rows,1):
                sx,sy=self._screen(row["x"],row["y"]);selected=row["annotation_id"]==self.selected_annotation_id
                self._draw_marker(sx,sy,structure,selected)
                if structure.get("repeated"):
                    self.canvas.create_text(sx+9,sy-9,text=str(seq),fill=structure.get("color","#1976e9"),font=("Segoe UI",8,"bold"))
        if self.selected_annotation_id:
            self.canvas.create_text(12,12,anchor="nw",text="Selected marker · drag to move · Delete to remove",fill="white")
        else:self.canvas.create_text(12,12,anchor="nw",text="Click anatomy to place the active structure",fill="white")

    def _draw_marker(self,x,y,structure,selected=False):
        color=structure.get("color","#1976e9");r=7 if selected else 5;shape=structure.get("shape","circle")
        width=3 if selected else 2
        if shape in {"circle","ring"}:self.canvas.create_oval(x-r,y-r,x+r,y+r,outline=color,width=width,fill="" if shape=="ring" else color)
        elif shape=="square":self.canvas.create_rectangle(x-r,y-r,x+r,y+r,outline=color,width=width,fill=color)
        elif shape=="triangle":self.canvas.create_polygon(x,y-r,x-r,y+r,x+r,y+r,outline=color,width=width,fill=color)
        elif shape=="diamond":self.canvas.create_polygon(x,y-r,x-r,y,x,y+r,x+r,y,outline=color,width=width,fill=color)
        else:
            self.canvas.create_line(x-r,y,x+r,y,fill=color,width=width);self.canvas.create_line(x,y-r,x,y+r,fill=color,width=width)
        if selected:self.canvas.create_oval(x-r-4,y-r-4,x+r+4,y+r+4,outline="white",width=1)

    def _nearest(self,event,max_pixels=13):
        best=None
        for row in self.annotations:
            sx,sy=self._screen(row["x"],row["y"]);distance=math.hypot(event.x-sx,event.y-sy)
            if distance<=max_pixels and (best is None or distance<best[0]):best=(distance,row)
        return best[1] if best else None

    def _canvas_down(self,event):
        if self.crop_image is None or self.selected_specimen_id is None:return
        self.canvas.focus_set();near=self._nearest(event)
        if near is not None:
            self.selected_annotation_id=near["annotation_id"];self._drag_annotation=near["annotation_id"];self._draw();return
        structure=self._structure()
        if structure is None:return
        nx,ny=self._normal(event.x,event.y)
        annotation_id=self.project.add_annotation(
            self.selected_specimen_id,structure["id"],nx,ny,self.pass_no.get(),
            replace_single=not bool(structure.get("repeated")),
        )
        self.selected_annotation_id=annotation_id;self.annotations=self.project.annotations(self.selected_specimen_id,self.pass_no.get())
        self.save_label.configure(text="Saved");self._update_counts();self._refresh_list();self._draw();self.on_changed()

    def _canvas_drag(self,event):
        if self._drag_annotation is None or self.crop_image is None:return
        nx,ny=self._normal(event.x,event.y)
        for row in self.annotations:
            if row["annotation_id"]==self._drag_annotation:
                row["x"]=nx;row["y"]=ny;break
        self._draw()

    def _canvas_up(self,event):
        if self._drag_annotation is None:return
        annotation_id=self._drag_annotation;self._drag_annotation=None;nx,ny=self._normal(event.x,event.y)
        try:self.project.move_annotation(annotation_id,nx,ny)
        except Exception as exc:messagebox.showerror("Structures",str(exc),parent=self.root)
        self.annotations=self.project.annotations(self.selected_specimen_id,self.pass_no.get());self.save_label.configure(text="Saved")
        self._update_counts();self._refresh_list();self._draw();self.on_changed()

    def delete_selected(self,_event=None):
        if not self.selected_annotation_id:return "break"
        self.project.delete_annotation(self.selected_annotation_id);self.selected_annotation_id=None
        self.annotations=self.project.annotations(self.selected_specimen_id,self.pass_no.get());self.save_label.configure(text="Saved")
        self._update_counts();self._refresh_list();self._draw();self.on_changed();return "break"

    def _pass_changed(self,_event=None):
        self.pass_no.set(2 if self.pass_box.current()==1 else 1);self.selected_specimen_id=None;self.refresh()

    def _navigate(self,step):
        rows=self._filtered_rows(self.project.structure_specimens(self.pass_no.get()))
        ids=[row["specimen_id"] for row in rows]
        if not ids:return
        try:index=ids.index(self.selected_specimen_id)
        except ValueError:index=0
        target=ids[max(0,min(len(ids)-1,index+int(step)))]
        self._load_specimen(target);self._refresh_list(rows)

    def verify_next(self):
        if not self.selected_specimen_id:return
        try:self.project.verify_annotations(self.selected_specimen_id,self.pass_no.get())
        except ValueError as exc:
            messagebox.showwarning("Structures incomplete",str(exc),parent=self.root);return
        except Exception as exc:
            messagebox.showerror("Verify structures",str(exc),parent=self.root);return
        rows=self._filtered_rows(self.project.structure_specimens(self.pass_no.get()));ids=[row["specimen_id"] for row in rows]
        current=self.selected_specimen_id
        next_id=None
        if current in ids:
            pos=ids.index(current)
            candidates=ids[pos+1:]+ids[:pos]
            status={row["specimen_id"]:row.get("annotation_status") for row in rows}
            next_id=next((sid for sid in candidates if status.get(sid)!="verified"),None)
        self._refresh_list(rows);self._refresh_summary();self.save_label.configure(text="Verified")
        if next_id:self._load_specimen(next_id)
        else:self._load_specimen(current)
        self.on_changed()
