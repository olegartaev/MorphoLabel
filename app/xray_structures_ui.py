"""Interactive X-ray structure annotation workspace."""
from __future__ import annotations

import math
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from app.photo_list import PhotoListCanvas
from app.ui.icons import CONTROL_ICON_SIZE, tk_icon
from app.ui.photo_list_panel import filtered_photo_indices
from app.ui.tooltips import Tooltip
from .xray_crop import oriented_crop


def _display_ready(image):
    arr=np.asarray(image)
    if arr.ndim==3:
        arr=(0.299*arr[...,0]+0.587*arr[...,1]+0.114*arr[...,2]) if arr.shape[-1]>=3 else arr[...,0]
    arr=np.asarray(arr,dtype=np.float32);finite=arr[np.isfinite(arr)]
    if not finite.size:return Image.new("L",image.size,0)
    lo=float(np.percentile(finite,0.5));hi=float(np.percentile(finite,99.5))
    if hi<=lo:hi=lo+1.0
    return Image.fromarray(np.clip((arr-lo)*255.0/(hi-lo),0,255).astype(np.uint8),"L")


def _shape_symbol(structure):
    return {"circle":"●","triangle":"▲","diamond":"◆","square":"■","cross":"✚","ring":"○"}.get(structure.get("shape"),"●")


class XRaySpecimenListPanel(ttk.Frame):
    """The same compact searchable list language used by Crop/Landmarks."""

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
                **row,
                "sample_id":self._sample(row["relative_path"]),
                "source_relpath":row["relative_path"],
                "status_color":"green" if status=="verified" else "yellow" if status in {"draft","stale"} else "red",
            })
        return rows

    def _row_data(self,index,row):
        path=Path(str(row["relative_path"]));status=str(row.get("annotation_status") or "")
        tip="Verified structures" if status=="verified" else "Saved draft — review required" if status else "Not started"
        return {
            "number":str(index+1),"cal":"","has_crop":True,"excluded":False,
            "text":f"{row['sample_id']} | {path.name} · Fish №{int(row.get('ordinal') or 0)}",
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
            self._rows,self._cache,self.specimen_query.get(),self.sample_query.get(),show_excluded=True,
        )
        self.canvas.set_rows([self._row_data(i,self._rows[i]) for i in self.visible_indices])
        selected_index=next((i for i,row in enumerate(self._rows) if row["specimen_id"]==self.selected_specimen_id),None)
        if selected_index in self.visible_indices:
            visible=self.visible_indices.index(selected_index);self.canvas.selection_set(visible)
            if reveal:self.canvas.see(visible)
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
    """Landmarks-style marker workspace for one oriented specimen Crop."""

    def __init__(self,parent,project,on_changed=None,initial_image_id=None,initial_specimen_id=None,on_selection=None):
        self.parent=parent;self.root=parent.winfo_toplevel();self.project=project;self.on_changed=on_changed or (lambda:None)
        self.on_selection=on_selection or (lambda _image_id,_specimen_id:None);self.tip=Tooltip(self.root)
        self.pass_no=tk.IntVar(value=1);self.selected_specimen_id=str(initial_specimen_id or "");self.preferred_image_id=str(initial_image_id or "")
        self.active_structure_id=None;self.selected_annotation_id=None;self.crop_image=None;self.photo=None;self.display_scale=1.0;self.offset=(0,0);self._photo_key=None
        self.annotations=[];self._drag_annotation=None;self._marker_buttons={};self._icons={}
        self._build();self.refresh()

    def _icon(self,master,name):
        key=(name,CONTROL_ICON_SIZE)
        if key not in self._icons:self._icons[key]=tk_icon(master,name,CONTROL_ICON_SIZE)
        return self._icons[key]

    def _build(self):
        outer=ttk.Frame(self.parent,padding=(0,0));outer.pack(fill="both",expand=True)
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
        self.canvas.bind("<Configure>",lambda _e:self._draw());self.canvas.bind("<Button-1>",self._canvas_down);self.canvas.bind("<B1-Motion>",self._canvas_drag);self.canvas.bind("<ButtonRelease-1>",self._canvas_up)
        self.canvas.bind("<Delete>",self.delete_selected);self.canvas.bind("<BackSpace>",self.delete_selected)

        dock=ttk.Frame(main,style="WorkflowDock.TFrame",padding=(6,5));dock.grid(row=2,column=0,sticky="ew",pady=(4,0));dock.columnconfigure(1,weight=1)
        ttk.Label(dock,text="Marker actions:",style="SectionTitle.TLabel").grid(row=0,column=0,sticky="w",padx=(0,6))
        self.marker_host=ttk.Frame(dock,style="WorkflowDock.TFrame");self.marker_host.grid(row=0,column=1,sticky="ew")
        actions=ttk.Frame(dock,style="WorkflowDock.TFrame");actions.grid(row=0,column=2,sticky="e")
        self.delete_button=ttk.Button(actions,text="Delete",image=self._icon(actions,"delete"),compound="left",style="Icon.TButton",command=self.delete_selected)
        self.delete_button.pack(side="left",padx=(6,2))
        self.tip.bind(self.delete_button,"Delete the selected structure marker.")
        ttk.Label(actions,text="Click = place · drag = correct",style="Muted.TLabel").pack(side="left",padx=(8,0))
        self.counts_label=ttk.Label(dock,text="",style="Muted.TLabel");self.counts_label.grid(row=1,column=0,columnspan=3,sticky="w",pady=(4,0))
        self.save_label=ttk.Label(dock,text="",style="Muted.TLabel");self.save_label.grid(row=1,column=2,sticky="e",pady=(4,0))

    def _set_initial_sash(self):
        try:
            width=max(900,self.panes.winfo_width());self.panes.sashpos(0,max(300,min(400,int(width*.21))))
        except Exception:pass

    def _sample(self,relative_path):
        return XRaySpecimenListPanel._sample(relative_path)

    def _context(self,item):
        image=self.project.source_image(item["image_id"]);path=Path(image["relative_path"])
        return f"Locality: {self._sample(image['relative_path'])}  ·  Plate: {path.name}  ·  Fish №{int(item.get('ordinal') or 0)}"

    def _notify_selection(self):
        if not self.selected_specimen_id:return
        item=self.project.specimen(self.selected_specimen_id);self.on_selection(item["image_id"],self.selected_specimen_id)

    def _build_marker_buttons(self):
        for child in self.marker_host.winfo_children():child.destroy()
        structures=list(self.project.scheme.get("structures") or ())
        ids={item["id"] for item in structures}
        if self.active_structure_id not in ids:self.active_structure_id=structures[0]["id"] if structures else None
        counts={}
        for row in self.annotations:counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        self._marker_buttons={}
        ordered=[item for item in structures if item.get("repeated")]+[item for item in structures if not item.get("repeated")]
        saw_reference=False
        for structure in ordered:
            if not structure.get("repeated") and not saw_reference:
                ttk.Separator(self.marker_host,orient="vertical").pack(side="left",fill="y",padx=5,pady=2);saw_reference=True
            hotkey=str(structure.get("hotkey") or "");count=counts.get(structure["id"],0);symbol=_shape_symbol(structure)
            text=f"{hotkey+' ' if hotkey else ''}{symbol} {structure['name']} ({count})"
            button=ttk.Button(self.marker_host,text=text,style="Primary.TButton" if structure["id"]==self.active_structure_id else "P.TButton",command=lambda sid=structure["id"]:self._choose_structure(sid))
            button.pack(side="left",padx=2);self._marker_buttons[structure["id"]]=button
            self.tip.bind(button,structure.get("description") or structure["name"])
            if hotkey:self.canvas.bind(hotkey,lambda _e,sid=structure["id"]:self._choose_structure(sid))
        if not structures:
            ttk.Label(self.marker_host,text="No structures configured",style="Muted.TLabel").pack(side="left")

    def _choose_structure(self,structure_id):
        self.active_structure_id=structure_id;self.selected_annotation_id=None;self._build_marker_buttons();self._draw();self.canvas.focus_set()

    def _structure(self,structure_id=None):
        structure_id=structure_id or self.active_structure_id
        return next((item for item in self.project.scheme.get("structures",()) if item["id"]==structure_id),None)

    def refresh(self):
        self.specimen_list.pass_no=self.pass_no.get();rows=self.project.structure_specimens(self.pass_no.get());ids=[row["specimen_id"] for row in rows]
        target=self.selected_specimen_id if self.selected_specimen_id in ids else next((row["specimen_id"] for row in rows if row["image_id"]==self.preferred_image_id),None)
        self.selected_specimen_id=target or (ids[0] if ids else "")
        self.specimen_list.selected_specimen_id=self.selected_specimen_id;self.specimen_list.refresh(reveal=True)
        if self.selected_specimen_id:self._load_specimen(self.selected_specimen_id)
        else:self._clear()
        self._refresh_summary()

    def _list_selected(self,specimen_id):
        if specimen_id!=self.selected_specimen_id:self._load_specimen(specimen_id)

    def _load_specimen(self,specimen_id):
        self.selected_specimen_id=specimen_id;self.selected_annotation_id=None;item=self.project.specimen(specimen_id)
        self.preferred_image_id=item["image_id"];self.context_label.configure(text=self._context(item))
        try:
            with Image.open(self.project.source_image_path(item["image_id"])) as source:
                source.load();crop=oriented_crop(source,item["crop"])
            self.crop_image=_display_ready(crop)
        except Exception as exc:
            messagebox.showerror("Structures",f"Could not open specimen crop:\n{exc}",parent=self.root);self.crop_image=None
        self.annotations=self.project.annotations(specimen_id,self.pass_no.get());self._photo_key=None
        self.specimen_list.select(specimen_id,reveal=True);self._build_marker_buttons();self._update_counts();self._draw();self._refresh_summary();self._notify_selection()

    def _clear(self):
        self.selected_specimen_id="";self.crop_image=self.photo=None;self.annotations=[];self.context_label.configure(text="No eligible specimen")
        self.canvas.delete("all");self._build_marker_buttons();self._update_counts()

    def _refresh_summary(self):
        summary=self.project.annotation_summary(self.pass_no.get())
        self.summary_label.configure(text=f"{summary['verified']} verified · {summary['draft']} draft · {summary['unstarted']} not started")
        state="normal" if self.selected_specimen_id else "disabled";self.verify_button.configure(state=state);self.previous_button.configure(state=state)

    def _update_counts(self):
        counts={}
        for row in self.annotations:counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        structures=list(self.project.scheme.get("structures") or ())
        self.counts_label.configure(text="   ·   ".join(f"{item['name']}: {counts.get(item['id'],0)}" for item in structures))
        run=self.project.annotation_run(self.selected_specimen_id,self.pass_no.get(),create=False) if self.selected_specimen_id else None
        self.save_label.configure(text="Verified" if run and run.get("status")=="verified" else "Saved · draft" if run else "Not started")

    def _fit(self):
        if self.crop_image is None:return None
        cw=max(2,self.canvas.winfo_width());ch=max(2,self.canvas.winfo_height());scale=min(max(1,cw-24)/self.crop_image.width,max(1,ch-24)/self.crop_image.height,1.0)
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
        structures={item["id"]:item for item in self.project.scheme.get("structures",())}
        for sid,rows in grouped.items():
            structure=structures.get(sid)
            if structure is None:continue
            rows=sorted(rows,key=lambda row:(row["sort_order"],row["annotation_id"]))
            for seq,row in enumerate(rows,1):
                sx,sy=self._screen(row["x"],row["y"]);selected=row["annotation_id"]==self.selected_annotation_id
                self._draw_marker(sx,sy,structure,selected)
                if structure.get("repeated"):self.canvas.create_text(sx+9,sy-9,text=str(seq),fill=structure.get("color","#1976e9"),font=("Segoe UI",8,"bold"))
        hint="Selected marker · drag to move · Delete to remove" if self.selected_annotation_id else "Choose a marker below, then click the anatomy"
        self.canvas.create_text(12,12,anchor="nw",text=hint,fill="white")

    def _draw_marker(self,x,y,structure,selected=False):
        color=structure.get("color","#1976e9");r=7 if selected else 5;shape=structure.get("shape","circle");width=3 if selected else 2
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

    def _after_edit(self,text="Saved · draft"):
        self.annotations=self.project.annotations(self.selected_specimen_id,self.pass_no.get())
        self.save_label.configure(text=text);self.specimen_list.refresh(preserve_scroll=True);self._build_marker_buttons();self._update_counts();self._refresh_summary();self._draw();self.on_changed()

    def _canvas_down(self,event):
        if self.crop_image is None or not self.selected_specimen_id:return
        self.canvas.focus_set();near=self._nearest(event)
        if near is not None:
            self.selected_annotation_id=near["annotation_id"];self._drag_annotation=near["annotation_id"];self._draw();return
        structure=self._structure()
        if structure is None:return
        nx,ny=self._normal(event.x,event.y)
        self.selected_annotation_id=self.project.add_annotation(
            self.selected_specimen_id,structure["id"],nx,ny,self.pass_no.get(),replace_single=not bool(structure.get("repeated")),
        )
        self._after_edit()

    def _canvas_drag(self,event):
        if self._drag_annotation is None or self.crop_image is None:return
        nx,ny=self._normal(event.x,event.y)
        for row in self.annotations:
            if row["annotation_id"]==self._drag_annotation:row["x"]=nx;row["y"]=ny;break
        self._draw()

    def _canvas_up(self,event):
        if self._drag_annotation is None:return
        annotation_id=self._drag_annotation;self._drag_annotation=None;nx,ny=self._normal(event.x,event.y)
        try:self.project.move_annotation(annotation_id,nx,ny)
        except Exception as exc:messagebox.showerror("Structures",str(exc),parent=self.root);return
        self._after_edit()

    def delete_selected(self,_event=None):
        if self.selected_annotation_id:
            self.project.delete_annotation(self.selected_annotation_id);self.selected_annotation_id=None;self._after_edit()
        return "break"

    def _pass_changed(self,_event=None):
        self.pass_no.set(2 if self.pass_box.current()==1 else 1);self.specimen_list.pass_no=self.pass_no.get();self.refresh()

    def _navigate(self,step):
        ids=self.specimen_list.visible_ids()
        if not ids:return
        try:index=ids.index(self.selected_specimen_id)
        except ValueError:index=0
        target=ids[max(0,min(len(ids)-1,index+int(step)))]
        self._load_specimen(target)

    def verify_next(self):
        if not self.selected_specimen_id:return
        try:self.project.verify_annotations(self.selected_specimen_id,self.pass_no.get())
        except ValueError as exc:messagebox.showwarning("Structures incomplete",str(exc),parent=self.root);return
        except Exception as exc:messagebox.showerror("Verify structures",str(exc),parent=self.root);return
        self._after_edit("Verified")
        rows=self.specimen_list.rows();ids=[row["specimen_id"] for row in rows];current=self.selected_specimen_id;next_id=None
        if current in ids:
            pos=ids.index(current);ordered=ids[pos+1:]+ids[:pos];status={row["specimen_id"]:row.get("annotation_status") for row in rows}
            next_id=next((sid for sid in ordered if status.get(sid)!="verified"),None)
        if next_id:self._load_specimen(next_id)
