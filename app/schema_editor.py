"""Small standalone landmark schema CSV editor."""
import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from .profile import read_schema_csv
from .identity import apply_window_identity
from .ui.tk_lifecycle import trace_for_widget

LEGEND=("# ROLE LEGEND:","# BOTH = used for linear measurements and geometric morphometrics","# GM = geometric morphometrics only","# CLASSICAL = used for linear measurements (legacy role code)","# Lines beginning with # are comments and are ignored by MorphoLabel.")
ROLE_CODES={"BT":"BOTH","GM":"GM","CL":"CLASSICAL"}
ROLE_NAMES={"BT":"Both","GM":"Geometric morphometrics","CL":"Linear measurements"}
ROLE_FROM_NAME={v:k for k,v in ROLE_NAMES.items()}

class SchemaEditor(tk.Toplevel):
 def __init__(self,parent,path=None,*,project=None,on_apply=None):
  super().__init__(parent);apply_window_identity(self,short=True);self.geometry("900x520");self.minsize(680,420);self.path=Path(path) if path else None;self.rows=[];self.delimiter=";";self.dirty=False;self._editor=None;self._editor_row=None;self._editor_key=None
  namebar=ttk.Frame(self,padding=5);namebar.pack(fill="x")
  ttk.Label(namebar,text="Scheme name:").pack(side="left")
  self.scheme_name=tk.StringVar();ttk.Entry(namebar,textvariable=self.scheme_name,width=44).pack(side="left",padx=6);trace_for_widget(self,self.scheme_name,"write",lambda *_: setattr(self,"dirty",True))
  bar=ttk.Frame(self,padding=5);bar.pack(fill="x")
  self.project=project;self.on_apply=on_apply
  self.apply_button=ttk.Button(bar,text="Apply to this project",command=self.apply_to_project) if project is not None else None
  for text,cmd in (("New",self.new_schema),("Open...",self.open_schema),("Save",self.save),("Save As...",self.save_as)) : ttk.Button(bar,text=text,command=cmd).pack(side="left",padx=2)
  frame=ttk.Frame(self,padding=5);frame.pack(fill="both",expand=True)
  self.table=ttk.Treeview(frame,columns=("id","role","abbr","name"),show="headings",selectmode="browse")
  for c,h,w,st in (("id","#",45,False),("role","Use",190,False),("abbr","Abbr",100,False),("name","Name",400,True)):
   self.table.heading(c,text=h);self.table.column(c,width=w,minwidth=w,stretch=st,anchor="w")
  frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
  scroll=ttk.Scrollbar(frame,orient="vertical",command=self.table.yview)
  def scroll_x(*args):self.close_editor();self.table.xview(*args)
  horizontal=ttk.Scrollbar(frame,orient="horizontal",command=scroll_x)
  self.table.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
  self.table.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns");horizontal.grid(row=1,column=0,sticky="ew")
  self.table.bind("<Double-1>",self.edit_cell);self.table.bind("<ButtonPress-1>",self.table_press);self.table.bind("<B1-Motion>",self.drag_motion);self.table.bind("<ButtonRelease-1>",self.drag_end);self.table.bind("<MouseWheel>",lambda e:self.close_editor())
  controls=ttk.Frame(self,padding=5);controls.pack(fill="x")
  for text,cmd in (("+ Add landmark",self.add_row),("Delete",self.delete_row),("↑",lambda:self.move(-1)),("↓",lambda:self.move(1))):ttk.Button(controls,text=text,command=cmd).pack(side="left",padx=2)
  self.protocol("WM_DELETE_WINDOW",self.close);self.new_schema() if self.path is None else self.load_path(self.path)
 def renumber(self):
  for i,row in enumerate(self.rows,1):row["id"]=i
 def redraw(self):
  self.renumber();self.table.delete(*self.table.get_children())
  for row in self.rows:self.table.insert("","end",iid=str(row["id"]),values=(row["id"],ROLE_NAMES.get(row["role"],row["role"]),row["abbr"],row["name"]))
 def new_schema(self):
  if self.dirty and not self.confirm_discard():return
  self.close_editor();self.path=None;self.rows=[{"id":1,"role":"BT","abbr":"","name":""}];self.delimiter=";";self._stored_scheme_name=None;self._initial_scheme_name="";self.scheme_name.set("New landmark schema");self.dirty=True;self.redraw()
  self._update_apply_button()
 def load_path(self,path):
  try:
   from .project_storage import load_schema
   load_schema(path)
   self.close_editor();delim,_,raw=read_schema_csv(path);text=Path(path).read_text(encoding="utf-8-sig");name=next((line.strip()[13:] for line in text.splitlines() if line.lstrip().startswith("# SCHEMA_NAME=")),Path(path).stem);self.rows=[{"id":i+1,"role":({"BOTH":"BT","GM":"GM","CLASSICAL":"CL"}.get(r.get("role","BOTH").upper(),"BT")),"abbr":r.get("abbr","").strip(),"name":r.get("name","").strip()} for i,r in enumerate(raw)] or [{"id":1,"role":"BT","abbr":"","name":""}];self.delimiter=delim;self.path=Path(path);self.scheme_name.set(name);self.dirty=False;self.redraw()
   for row,source in zip(self.rows,raw):row["category"]=(source.get("category") or "").strip()
   self._stored_scheme_name=next((line for line in text.splitlines() if line.lstrip().startswith("# SCHEMA_NAME=")),None);self._initial_scheme_name=name
   self._update_apply_button()
  except Exception as exc:messagebox.showerror("Open schema",str(exc),parent=self)
 def _update_apply_button(self):
  if self.apply_button is None:return
  meaningful=self.path is None or self.path.resolve()!=self.project.schema_path.resolve()
  if meaningful:self.apply_button.pack(side="left",padx=(12,2))
  else:self.apply_button.pack_forget()
 def apply_to_project(self):
  if self.project is None:return False
  self.close_editor()
  try:self.validate()
  except ValueError as exc:messagebox.showerror("Invalid schema",str(exc),parent=self);return False
  import tempfile
  with tempfile.TemporaryDirectory(prefix="morpholabel_scheme_") as scratch:
   target=Path(scratch)/"scheme.csv"
   fields=("id","abbr","name","role","category") if any(row.get("category") for row in self.rows) else ("id","abbr","name","role")
   with target.open("w",newline="",encoding="utf-8") as stream:
    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
    for i,row in enumerate(self.rows,1):writer.writerow({key:({"id":i,"abbr":row["abbr"].strip(),"name":row["name"].strip(),"role":ROLE_CODES[row["role"]],"category":row.get("category","")})[key] for key in fields})
   if self.project.count("landmarks") and not messagebox.askyesno("Apply landmark scheme","Apply this scheme to the current project?\n\nExisting points stay attached to their abbreviations. Removed landmarks remain in history; new landmarks need annotation. Changed scientific definitions require review. A backup preserves the previous scheme and data.",parent=self,default=messagebox.NO):return False
   try:self.project.apply_landmark_schema(self.path if self.path is not None and not self.dirty else target)
   except Exception as exc:messagebox.showerror("Apply landmark scheme",str(exc),parent=self);return False
  self.path=self.project.schema_path;self.dirty=False;self._update_apply_button()
  if self.on_apply:self.on_apply()
  return True
 def open_schema(self):
  if self.dirty and not self.confirm_discard():return
  path=filedialog.askopenfilename(parent=self,filetypes=[("CSV","*.csv"),("All files","*.*")])
  if path:self.load_path(path)
 def validate(self):
  seen=set()
  for i,row in enumerate(self.rows,1):
   if not row["abbr"].strip():raise ValueError(f"Row {i}: abbreviation is empty")
   if not row["name"].strip():raise ValueError(f"Row {i}: name is empty")
   if row["abbr"].strip() in seen:raise ValueError(f"Duplicate abbreviation: {row['abbr'].strip()}")
   if row["role"] not in ROLE_CODES:raise ValueError(f"Row {i}: invalid role")
   seen.add(row["abbr"].strip())
 def save(self):
  self.close_editor()
  if not self.path:return self.save_as()
  try:self.validate()
  except ValueError as exc:messagebox.showerror("Invalid schema",str(exc),parent=self);return False
  self.renumber();d=self.delimiter if self.delimiter in ",;\t|" else ","
  import io
  out=io.StringIO(newline="")
  if self._stored_scheme_name is not None or self.scheme_name.get()!=self._initial_scheme_name:out.write("# SCHEMA_NAME="+self.scheme_name.get().replace("\n"," ").replace("\r"," ")+"\n")
  fields=("id","abbr","name","role","category") if any(row.get("category") for row in self.rows) else ("id","abbr","name","role")
  writer=csv.DictWriter(out,fieldnames=fields,delimiter=d,lineterminator="\n");writer.writeheader()
  for row in self.rows:writer.writerow({key:({"id":row["id"],"abbr":row["abbr"].strip(),"name":row["name"].strip(),"role":ROLE_CODES[row["role"]],"category":row.get("category","")})[key] for key in fields})
  from .measurements import _atomic
  _atomic(self.path,out.getvalue());self.dirty=False;self._update_apply_button();return True
 def save_as(self):
  safe="".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in self.scheme_name.get()).strip().replace(" ","_") or "landmark_schema"
  path=filedialog.asksaveasfilename(parent=self,defaultextension=".csv",initialfile=safe+".csv",filetypes=[("CSV","*.csv")])
  if not path:return False
  previous_path,previous_delimiter=self.path,self.delimiter
  self.path=Path(path);self.delimiter=";"
  try:
   if self.save():return True
  except Exception:
   self.path,self.delimiter=previous_path,previous_delimiter;raise
  self.path,self.delimiter=previous_path,previous_delimiter;return False
 def add_row(self):
  self.close_editor();sel=self.table.selection();idx=self.table.index(sel[0])+1 if sel else len(self.rows);self.rows.insert(idx,{"id":0,"role":"BT","abbr":"","name":""});self.dirty=True;self.redraw();self.table.selection_set(str(idx+1))
 def delete_row(self):
  self.close_editor();sel=self.table.selection()
  if not sel:return
  row=self.rows[self.table.index(sel[0])]
  if (row["abbr"] or row["name"]) and not messagebox.askyesno("Delete landmark","Delete selected landmark?",parent=self):return
  self.rows.pop(self.table.index(sel[0]));self.dirty=True;self.redraw()
 def move(self,delta):
  self.close_editor();sel=self.table.selection()
  if not sel:return
  i=self.table.index(sel[0]);j=i+delta
  if 0<=j<len(self.rows):self.rows[i],self.rows[j]=self.rows[j],self.rows[i];self.dirty=True;self.redraw();self.table.selection_set(str(j+1));self.table.see(str(j+1))
 def close_editor(self,commit=True):
  w=self._editor
  if w is None:return
  if commit and self._editor_row is not None:
   value=w.get()
   if self.rows[self._editor_row][self._editor_key]!=value:self.dirty=True
   self.rows[self._editor_row][self._editor_key]=value
   rowid=str(self._editor_row+1)
   if self.table.exists(rowid):self.table.set(rowid,self._editor_key,value)
  try:w.destroy()
  except tk.TclError:pass
  self._editor=None;self._editor_row=None;self._editor_key=None
 def _set_role(self,index,rowid,code):
  if code not in ROLE_CODES:return
  self.rows[index]["role"]=code;self.dirty=True;self.redraw();self.table.selection_set(rowid);self.table.focus(rowid)
 def table_press(self,event):
  self.close_editor()
  rowid=self.table.identify_row(event.y);col=self.table.identify_column(event.x)
  if rowid and col=="#2":
   i=self.table.index(rowid);self.table.selection_set(rowid);self.table.focus(rowid)
   menu=tk.Menu(self,tearoff=False);current=self.rows[i]["role"]
   for code,label in ROLE_NAMES.items():
    menu.add_command(label=("✓  " if code==current else "    ")+label,command=lambda value=code:self._set_role(i,rowid,value))
   self._role_menu=menu
   try:menu.tk_popup(event.x_root,event.y_root)
   finally:menu.grab_release()
   return "break"
  self.drag_start(event)
 def edit_cell(self,event):
  self.close_editor()
  rowid=self.table.identify_row(event.y);col=self.table.identify_column(event.x)
  if not rowid or col in {"#1","#2"}:return
  i=self.table.index(rowid);key={"#3":"abbr","#4":"name"}.get(col)
  if not key:return
  bbox=self.table.bbox(rowid,col);var=tk.StringVar(value=self.rows[i][key]);w=ttk.Entry(self.table,textvariable=var)
  x=max(0,bbox[0]);width=max(24,min(bbox[2],self.table.winfo_width()-x-2))
  w.place(x=x,y=bbox[1],width=width,height=bbox[3]);w.focus_set();w.xview_moveto(1);self._editor=w;self._editor_row=i;self._editor_key=key
  def finish(_=None):
   self.rows[i][key]=var.get();self.dirty=True;self.close_editor(False);self.redraw();self.table.selection_set(rowid)
  def cancel(_=None):self.close_editor(False);self.redraw()
  w.bind("<Return>",finish);w.bind("<FocusOut>",finish);w.bind("<Escape>",cancel)
 def drag_start(self,event):self._drag_row=self.table.identify_row(event.y)
 def drag_motion(self,event):pass
 def drag_end(self,event):
  if not getattr(self,"_drag_row",None):return
  target=self.table.identify_row(event.y);src=self._drag_row;self._drag_row=None
  if target and target!=src:
   a,b=self.table.index(src),self.table.index(target);row=self.rows.pop(a);self.rows.insert(b,row);self.dirty=True;self.redraw();self.table.selection_set(str(b+1))
 def confirm_discard(self):return messagebox.askyesno("Unsaved changes","Discard unsaved changes?",parent=self)
 def close(self):
  self.close_editor()
  if self.dirty and not self.confirm_discard():return
  self.destroy()
