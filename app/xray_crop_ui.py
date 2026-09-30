"""Tk workspace for the X-ray plate-to-specimen crop workflow."""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from .xray_crop import ALGORITHM_VERSION, crop_from_geometry, detect_specimens, display_preview


class XRayCropWorkspace:
    """Plate-level auto-crop UI: one bulk action, then review only exceptions."""

    def __init__(self,parent,project,on_changed=None):
        self.parent=parent;self.project=project;self.on_changed=on_changed or (lambda:None)
        self.selected_image_id=None;self.selected_specimen_id=None
        self.preview=self.photo=None;self.preview_original_size=(1,1);self.display_scale=1.0;self.offset=(0,0)
        self._detecting=False;self._add_mode=False;self._add_start=None
        self._build();self.refresh()

    def _build(self):
        outer=ttk.Frame(self.parent);outer.pack(fill="both",expand=True)
        toolbar=ttk.Frame(outer);toolbar.pack(fill="x",pady=(0,7))
        self.auto_button=ttk.Button(toolbar,text="Auto-crop all plates",style="Primary.TButton",command=self.auto_crop_all)
        self.auto_button.pack(side="left")
        self.review_button=ttk.Button(toolbar,text="Review exceptions",command=self.review_exceptions)
        self.review_button.pack(side="left",padx=(6,0))
        self.status=ttk.Label(toolbar,text="",style="Muted.TLabel");self.status.pack(side="left",padx=10)

        body=ttk.Panedwindow(outer,orient="horizontal");body.pack(fill="both",expand=True)
        left=ttk.LabelFrame(body,text="Source X-rays",padding=6);center=ttk.Frame(body);right=ttk.LabelFrame(body,text="Selected specimen",padding=8)
        body.add(left,weight=1);body.add(center,weight=5);body.add(right,weight=2)

        self.plates=ttk.Treeview(left,columns=("status","count"),show="tree headings",selectmode="browse",height=18)
        self.plates.heading("#0",text="Plate");self.plates.column("#0",width=180,stretch=True)
        self.plates.heading("status",text="Status");self.plates.column("status",width=80,anchor="center",stretch=False)
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
        self.accept_button=ttk.Button(right,text="Accept selected",style="Primary.TButton",command=self.accept_selected)
        self.accept_button.pack(fill="x",pady=2)
        self.edit_button=ttk.Button(right,text="Edit crop…",command=self.edit_selected);self.edit_button.pack(fill="x",pady=2)
        self.reject_button=ttk.Button(right,text="False detection — remove",command=self.reject_selected);self.reject_button.pack(fill="x",pady=2)
        self.add_button=ttk.Button(right,text="Add missed specimen",command=self.start_add);self.add_button.pack(fill="x",pady=(10,2))
        ttk.Label(right,text="Most plates need no specimen-by-specimen work. Auto-crop accepts clear cases and leaves only ambiguous crops here.",style="Muted.TLabel",wraplength=260,justify="left").pack(anchor="w",pady=(12,0))

    def refresh(self,preserve_plate=True):
        previous=self.selected_image_id if preserve_plate else None
        rows=self.project.source_images();specimens=self.project.specimens()
        by_image={}
        for item in specimens:
            if item["excluded"]:continue
            by_image.setdefault(item["image_id"],[]).append(item)
        self.plates.delete(*self.plates.get_children())
        for row in rows:
            items=by_image.get(row["image_id"],[])
            review=sum(x["crop_status"]=="proposed" for x in items)
            confirmed=sum(x["crop_status"]=="confirmed" for x in items)
            status="Review" if review else ("Ready" if confirmed else "Not run")
            self.plates.insert("","end",iid=row["image_id"],text=row["relative_path"],values=(status,len(items)))
        summary=self.project.crop_summary()
        self.status.configure(text=f"{summary['confirmed']} confirmed · {summary['review']} to review · {summary['plates_with_specimens']}/{summary['plates']} plates processed")
        review_state="normal" if summary["review"] else "disabled";self.review_button.configure(state=review_state)
        ids=self.plates.get_children()
        target=previous if previous and self.plates.exists(previous) else (ids[0] if ids else None)
        if target:
            self.plates.selection_set(target);self.plates.focus(target);self.plates.see(target)
            self._load_plate(target)
        else:self._clear_canvas()
        self.on_changed()

    def _plate_selected(self,_event=None):
        selected=self.plates.selection()
        if selected:self._load_plate(selected[0])

    def _load_plate(self,image_id):
        self.selected_image_id=image_id;self.selected_specimen_id=None
        try:
            preview,_scale,original_size=display_preview(self.project.source_image_path(image_id),1400)
        except Exception as exc:
            messagebox.showerror("X-ray Crops",str(exc),parent=self.parent);return
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
        original_scale=(width/self.preview_original_size[0]) if self.preview_original_size[0] else 1.0
        self.display_scale=original_scale;self.offset=(ox,oy)
        return image

    def _screen(self,x,y):
        return self.offset[0]+float(x)*self.display_scale,self.offset[1]+float(y)*self.display_scale

    def _original(self,x,y):
        return (float(x)-self.offset[0])/max(1e-9,self.display_scale),(float(y)-self.offset[1])/max(1e-9,self.display_scale)

    def _draw(self):
        self.canvas.delete("all")
        fitted=self._fit()
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
            color="#35d07f" if item["crop_status"]=="confirmed" else "#ffcc00"
            width=4 if selected else 2
            tag=f"specimen:{item['specimen_id']}"
            self.canvas.create_polygon(*pts,outline=color,fill="",width=width,tags=("crop",tag))
            cx,cy=self._screen(crop.get("center_x",0),crop.get("center_y",0))
            self.canvas.create_text(cx,cy,text=str(item.get("ordinal") or ""),fill="white",font=("Segoe UI",10,"bold"),tags=("crop",tag))
            self.canvas.tag_bind(tag,"<Button-1>",lambda _e,sid=item["specimen_id"]:self._select_specimen(sid))
        if self._add_mode:
            self.canvas.create_text(15,15,anchor="nw",text="Drag a box around the missed specimen",fill="#ffcc00",font=("Segoe UI",11,"bold"),tags="add_hint")

    def _select_specimen(self,specimen_id):
        self.selected_specimen_id=specimen_id;self._update_selected_panel();self._draw()

    def _update_selected_panel(self):
        if not self.selected_specimen_id:
            self.name_var.set("No specimen selected");self.meta_var.set("")
            for button in (self.accept_button,self.edit_button,self.reject_button):button.configure(state="disabled")
            return
        try:item=self.project.specimen(self.selected_specimen_id)
        except KeyError:
            self.selected_specimen_id=None;self._update_selected_panel();return
        crop=item.get("crop") or {};qc=item.get("crop_qc") or crop.get("qc") or []
        self.name_var.set(item["label"])
        status="Confirmed" if item["crop_status"]=="confirmed" else "Needs review"
        self.meta_var.set(f"{status} · {item['crop_source'] or 'unknown'}\nAngle {float(crop.get('angle_degrees',0)):.1f}°"+(f"\nQC: {', '.join(qc)}" if qc else ""))
        self.accept_button.configure(state="disabled" if item["crop_status"]=="confirmed" else "normal")
        self.edit_button.configure(state="normal");self.reject_button.configure(state="normal")

    def auto_crop_all(self):
        if self._detecting:return
        self._detecting=True;self.auto_button.configure(state="disabled");self.status.configure(text="Auto-cropping X-rays…")
        events=queue.Queue();rows=[row for row in self.project.source_images() if not row["excluded"]]
        def worker():
            total_high=total_review=total_protected=0
            try:
                for index,row in enumerate(rows,1):
                    proposals=detect_specimens(self.project.source_image_path(row["image_id"]))
                    result=self.project.replace_auto_proposals(row["image_id"],proposals,ALGORITHM_VERSION)
                    self.project.confirm_clear_proposals(row["image_id"])
                    total_high+=result["high"];total_review+=result["review"];total_protected+=result["protected"]
                    events.put(("progress",index,len(rows),row["relative_path"]))
                events.put(("done",total_high,total_review,total_protected))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="xray-auto-crop").start()
        def poll():
            try:
                while True:
                    event=events.get_nowait();kind=event[0]
                    if kind=="progress":
                        self.status.configure(text=f"Plate {event[1]}/{event[2]} · {event[3]}")
                    elif kind=="error":
                        self._detecting=False;self.auto_button.configure(state="normal")
                        messagebox.showerror("Auto-crop X-rays",str(event[1]),parent=self.parent);self.refresh();return
                    else:
                        self._detecting=False;self.auto_button.configure(state="normal");self.refresh()
                        messagebox.showinfo("Auto-crop X-rays",f"Clear crops accepted: {event[1]}\nExceptions to review: {event[2]}\nExisting confirmed crops protected: {event[3]}",parent=self.parent)
                        if event[2]:self.review_exceptions()
                        return
            except queue.Empty:self.parent.after(100,poll)
        poll()

    def review_exceptions(self):
        rows=self.project.crop_review_candidates()
        if not rows:return
        item=rows[0];image_id=item["image_id"]
        if self.plates.exists(image_id):
            self.plates.selection_set(image_id);self.plates.focus(image_id);self.plates.see(image_id)
            self._load_plate(image_id);self._select_specimen(item["specimen_id"])

    def accept_selected(self):
        if not self.selected_specimen_id:return
        self.project.confirm_specimen(self.selected_specimen_id);self.refresh()

    def reject_selected(self):
        if not self.selected_specimen_id:return
        if not messagebox.askyesno("Remove false detection","Remove this proposed specimen from the plate?",parent=self.parent):return
        self.project.reject_specimen(self.selected_specimen_id);self.selected_specimen_id=None;self.refresh()

    def edit_selected(self):
        if not self.selected_specimen_id:return
        item=self.project.specimen(self.selected_specimen_id)
        dialog=XRayCropEditor(self.parent,self.project.source_image_path(item["image_id"]),item["crop"])
        self.parent.wait_window(dialog)
        if dialog.result:
            self.project.update_specimen_crop(item["specimen_id"],dialog.result);self.refresh()

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
        messagebox.showinfo("Missed specimen","Specimen added. If it is tilted, use Edit crop to rotate the frame.",parent=self.parent)


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
