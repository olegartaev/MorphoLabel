"""Friendly measurement definition manager."""
import tkinter as tk
from tkinter import ttk,messagebox,filedialog

from .measurements import load_measurements,save_measurements,validate_measurement
from .ui.dialogs import center,info


def transfer_measurement_definitions(parent,project,action,on_saved=None):
 from .measurements import export_measurement_definitions,import_measurement_definitions,schema_path
 if not project.schema:return False
 options={"parent":parent,"filetypes":[("Measurement definitions","*.csv")],"initialfile":"measurement_definitions.csv"}
 path=filedialog.askopenfilename(title="Import measurement definitions",**options) if action=="import" else filedialog.asksaveasfilename(title="Export measurement definitions",defaultextension=".csv",**options)
 if not path:return False
 if action=="import" and schema_path(project).is_file() and load_measurements(project):
  if not messagebox.askyesno("Import measurement definitions","Replace the current measurement definitions? A backup keeps the previous definitions. Landmark coordinates and calibration stay unchanged.",parent=parent,default=messagebox.NO):return False
 try:
  (import_measurement_definitions if action=="import" else export_measurement_definitions)(project,path)
 except Exception as exc:messagebox.showerror("Measurement definitions",str(exc),parent=parent);return False
 if action=="import" and on_saved:on_saved()
 return True


class MeasurementsWindow(tk.Toplevel):
 def __init__(self,parent,project,on_saved=None,on_selection=None):
  super().__init__(parent)
  self.parent=parent;self.project=project;self.on_saved=on_saved;self.on_selection=on_selection;self.rows=load_measurements(project,include_unresolved=True)
  self.title("Measurement definitions");self.geometry("860x520");self.minsize(680,420);self.resizable(True,True);self.transient(parent)

  root=ttk.Frame(self,padding=14);root.pack(fill="both",expand=True);root.rowconfigure(2,weight=1);root.columnconfigure(0,weight=1)
  header=ttk.Frame(root);header.grid(row=0,column=0,sticky="ew");header.columnconfigure(0,weight=1)
  ttk.Label(header,text="Measurement definitions",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
  ttk.Button(header,text="Help",command=self._help).grid(row=0,column=1,sticky="e")
  ttk.Label(root,text="Define each measurement as the straight-line distance between two landmarks.",style="PageSubtitle.TLabel").grid(row=1,column=0,sticky="w",pady=(2,10))

  table_host=ttk.Frame(root);table_host.grid(row=2,column=0,sticky="nsew");table_host.rowconfigure(0,weight=1);table_host.columnconfigure(0,weight=1)
  self.tree=ttk.Treeview(table_host,columns=("use","abbr","name","p1","p2"),show="headings",selectmode="browse")
  for col,text,width,stretch in (
   ("use","Use",58,False),
   ("abbr","Code",90,False),
   ("name","Measurement",220,True),
   ("p1","From landmark",190,True),
   ("p2","To landmark",190,True),
  ):
   self.tree.heading(col,text=text);self.tree.column(col,width=width,anchor="w",stretch=stretch)
  scroll=ttk.Scrollbar(table_host,orient="vertical",command=self.tree.yview);self.tree.configure(yscrollcommand=scroll.set)
  self.tree.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")
  horizontal=ttk.Scrollbar(table_host,orient="horizontal",command=self.tree.xview);horizontal.grid(row=1,column=0,sticky="ew");self.tree.configure(xscrollcommand=horizontal.set)
  self.tree.bind("<<TreeviewSelect>>",self._selected);self.tree.bind("<Double-1>",lambda _e:self.edit())

  actions=ttk.Frame(root);actions.grid(row=3,column=0,sticky="ew",pady=(10,0));actions.columnconfigure(3,weight=1)
  ttk.Button(actions,text="+ Add measurement",command=self.add).grid(row=0,column=0,sticky="w")
  self.edit_button=ttk.Button(actions,text="Edit selected",command=self.edit);self.edit_button.grid(row=0,column=1,sticky="w",padx=(6,0))
  self.delete_button=ttk.Button(actions,text="Delete",command=self.delete);self.delete_button.grid(row=0,column=2,sticky="w",padx=(6,0))
  ttk.Button(actions,text="Close",command=self.destroy).grid(row=0,column=4,sticky="e")
  from .ui.design import FlowRow
  transfer=FlowRow(root);transfer.grid(row=4,column=0,sticky="ew",pady=(8,0))
  ttk.Button(transfer,text="Import definitions…",command=lambda:self.transfer("import"),state="normal" if project.schema else "disabled").pack(side="left")
  ttk.Button(transfer,text="Export definitions…",command=lambda:self.transfer("export"),state="normal" if project.schema else "disabled").pack(side="left",padx=6)
  self.refresh();center(parent,self)

 def transfer(self,action):
  def saved():self.rows=load_measurements(self.project,include_unresolved=True);self.refresh();self._done()
  return transfer_measurement_definitions(self,self.project,action,saved)

 def _help(self):
  info(self,"Measurements — quick guide",
       "Why: measurements convert landmark positions into comparable quantitative traits for analysis.\n\n"
       "Add a measurement, give it a short code and name, then choose the two landmarks that define the distance.\n\n"
       "Only measurements marked Use are included in the active measurement set and export.")

 def _selected(self,_event=None):
  selected=self.tree.selection();state="normal" if selected else "disabled"
  self.edit_button.configure(state=state);self.delete_button.configure(state=state)
  if selected and self.on_selection:self.on_selection(self.rows[int(selected[0])])

 def _label(self,ident,abbr=None):
  if ident is None:return f"Unavailable: {abbr or 'removed landmark'}"
  row=next((x for x in self.project.schema if int(x.get("id",x.get("landmark_id")))==int(ident)),{})
  name=(row.get('name') or row.get('abbr') or 'Landmark').strip()
  abbr=(row.get('abbr') or '').strip()
  suffix=f" ({abbr})" if abbr and abbr != name else ""
  return f"{int(ident)} — {name}{suffix}"

 def refresh(self):
  self.tree.delete(*self.tree.get_children())
  for i,r in enumerate(self.rows):
   self.tree.insert("","end",iid=str(i),values=("!" if r.get('unresolved') else "✓" if r["use"] else "",r["abbr"],r["name"],self._label(r["point1"],r.get('point1_abbr')),self._label(r["point2"],r.get('point2_abbr'))))
  self._selected()

 def add(self):
  if len(self.project.schema)<2:
   messagebox.showwarning("Measurements","At least two landmarks are required before a measurement can be defined.",parent=self);return
  self._edit(None)

 def edit(self):
  selected=self.tree.selection()
  if selected:self._edit(int(selected[0]))

 def delete(self):
  selected=self.tree.selection()
  if not selected:return
  index=int(selected[0]);name=self.rows[index].get("name") or self.rows[index].get("abbr") or "this measurement"
  if not messagebox.askyesno("Delete measurement",f"Delete {name}?",parent=self):return
  del self.rows[index];save_measurements(self.project,self.rows,preserve_unresolved=False);self.refresh();self._done()

 def _edit(self,index):
  value=self.rows[index].copy() if index is not None else {"use":True,"abbr":"","name":"","point1":int(self.project.schema[0]["id"]),"point2":int(self.project.schema[1]["id"])}
  d=tk.Toplevel(self);d.title("Edit measurement" if index is not None else "Add measurement");d.transient(self);d.minsize(580,340);d.resizable(True,True)
  frame=ttk.Frame(d,padding=14);frame.pack(fill="both",expand=True);frame.columnconfigure(1,weight=1)
  ttk.Label(frame,text="Edit measurement" if index is not None else "Add measurement",style="SectionTitle.TLabel").grid(row=0,column=0,columnspan=2,sticky="w")
  ttk.Label(frame,text="A measurement is the distance between two landmarks.",style="Muted.TLabel").grid(row=1,column=0,columnspan=2,sticky="w",pady=(2,10))

  use=tk.BooleanVar(master=d,value=value["use"]);abbr=tk.StringVar(master=d,value=value["abbr"]);name=tk.StringVar(master=d,value=value["name"])
  choices=[self._label(x.get("id",x.get("landmark_id"))) for x in self.project.schema]
  bylabel={label:int(row.get("id",row.get("landmark_id"))) for label,row in zip(choices,self.project.schema)}
  p1=tk.StringVar(master=d,value=self._label(value["point1"],value.get('point1_abbr')));p2=tk.StringVar(master=d,value=self._label(value["point2"],value.get('point2_abbr')))

  ttk.Label(frame,text="Code").grid(row=2,column=0,sticky="w",pady=4);ttk.Entry(frame,textvariable=abbr,width=22).grid(row=2,column=1,sticky="ew",padx=(10,0),pady=4)
  ttk.Label(frame,text="Name").grid(row=3,column=0,sticky="w",pady=4);ttk.Entry(frame,textvariable=name,width=38).grid(row=3,column=1,sticky="ew",padx=(10,0),pady=4)
  ttk.Label(frame,text="From landmark").grid(row=4,column=0,sticky="w",pady=4);ttk.Combobox(frame,textvariable=p1,values=choices,state="readonly",width=38).grid(row=4,column=1,sticky="ew",padx=(10,0),pady=4)
  ttk.Label(frame,text="To landmark").grid(row=5,column=0,sticky="w",pady=4);ttk.Combobox(frame,textvariable=p2,values=choices,state="readonly",width=38).grid(row=5,column=1,sticky="ew",padx=(10,0),pady=4)
  ttk.Checkbutton(frame,text="Use this measurement",variable=use).grid(row=6,column=0,columnspan=2,sticky="w",pady=(8,2))

  actions=ttk.Frame(frame);actions.grid(row=7,column=0,columnspan=2,sticky="e",pady=(12,0))
  ttk.Button(actions,text="Cancel",command=d.destroy).pack(side="left")
  def save():
   try:new=validate_measurement({"use":use.get(),"abbr":abbr.get().strip(),"name":name.get().strip(),"point1":bylabel[p1.get()],"point2":bylabel[p2.get()]},self.project.schema,self.rows,index)
   except (ValueError,KeyError) as exc:messagebox.showerror("Measurement",str(exc),parent=d);return
   if index is None:self.rows.append(new)
   else:self.rows[index]=new
   save_measurements(self.project,self.rows,preserve_unresolved=False);d.destroy();self.refresh();self._done()
  ttk.Button(actions,text="Save measurement",command=save,style="Primary.TButton").pack(side="left",padx=(6,0))
  center(self,d)

 def _done(self):
  if self.on_saved:self.on_saved()
