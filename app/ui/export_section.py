"""Project-level exports backed by canonical production services."""
import tkinter as tk
import json
from datetime import datetime, timezone
from pathlib import Path
import uuid
from tkinter import ttk, messagebox, filedialog
from app.export_formats import available_groups, selected_groups, export_landmark_tps, export_landmark_csv_long, export_landmark_wide, export_morphoj_text
from app.measurements import export_measurements
from app.analysis_export import export_analysis_bundle, SCOPE_VERIFIED, SCOPE_ALL
from .icons import WORKFLOW_ICON_SIZE
from .section_base import SectionView
from .tk_lifecycle import trace_for_widget

class ExportSection(SectionView):
 def render(self):
  panel=self.frame(padding=18);panel.pack(fill='both',expand=True);cfg=self.context.project.config
  header=ttk.Frame(panel);header.pack(fill='x',pady=(0,14));header.columnconfigure(0,weight=1)
  ttk.Label(header,text='Export',style='PageTitle.TLabel').grid(row=0,column=0,sticky='w')
  ttk.Label(header,text=f"{cfg.get('name',self.context.project.root.name)} · {len(self.context.rows)} images",style='PageSubtitle.TLabel').grid(row=1,column=0,sticky='w',pady=(2,0))
  guide='Save reviewed results for statistics or figures.\n\nLandmark coordinates\nChoose TPS, CSV or a MorphoJ-compatible format for shape analysis.\n\nMeasurements\nSave the distances you defined in Measurements as a table.'
  self.what_to_do(header,'Export — quick guide',guide).grid(row=0,column=1,rowspan=2,sticky='ne')

  cards=ttk.Frame(panel);cards.pack(fill='x');cards.columnconfigure(0,weight=1);cards.columnconfigure(1,weight=1)
  def card_header(icon,text):
   header=ttk.Frame(cards)
   ttk.Label(header,image=self.shell.ui_icon(icon,WORKFLOW_ICON_SIZE)).pack(side='left',padx=(0,6))
   ttk.Label(header,text=text,style='WorkflowCardTitle.TLabel').pack(side='left')
   return header

  land=ttk.LabelFrame(cards,labelwidget=card_header('export_landmarks','Landmark coordinates'),padding=14);land.grid(row=0,column=0,sticky='nsew',padx=(0,5))
  ttk.Label(land,text='Export landmark positions for geometric morphometrics or other coordinate-based analyses.',style='Muted.TLabel',wraplength=430,justify='left').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,10))
  mode=tk.StringVar(value='all');groups=available_groups(self.context.project);chosen={name:tk.BooleanVar(value=True) for name in groups};checks=[]
  ttk.Label(land,text='Landmarks to include',style='SectionTitle.TLabel').grid(row=1,column=0,columnspan=3,sticky='w')
  all_choice=ttk.Radiobutton(land,text='All landmarks',variable=mode,value='all');all_choice.grid(row=2,column=0,sticky='w',pady=(4,0))
  selected_choice=ttk.Radiobutton(land,text='Choose groups',variable=mode,value='groups');selected_choice.grid(row=2,column=1,sticky='w',padx=(10,0),pady=(4,0))
  self.shell.tip.bind(all_choice,'Export every landmark in the active project scheme.');self.shell.tip.bind(selected_choice,'Export only the groups selected below.')
  line=ttk.Frame(land);line.grid(row=3,column=0,columnspan=3,sticky='ew',pady=(6,2));line.columnconfigure(0,weight=1);line.columnconfigure(1,weight=1)
  if groups:
   for index,(name,var) in enumerate(chosen.items()):
    check=ttk.Checkbutton(line,text=name,variable=var);check.grid(row=index//2,column=index%2,sticky='w',padx=(0,12),pady=(2,2));checks.append(check)
  else:
   ttk.Label(line,text='No landmark groups are defined; use All landmarks.',style='Muted.TLabel').pack(anchor='w')
  def update(*_):
   for check in checks:check.state(['!disabled'] if mode.get()=='groups' else ['disabled'])
  trace_for_widget(panel,mode,'write',update);update()
  self.button(land,'Export landmark coordinates…',lambda:self.landmarks(mode.get(),selected_groups(tuple(chosen),{name:var.get() for name,var in chosen.items()})),'Choose an output format and destination.',style='Primary.TButton').grid(row=4,column=0,columnspan=3,sticky='w',pady=(12,0))
  self.button(land,'Export analysis dataset…',self.analysis_dataset,'Create a traceable analysis bundle.',style='Primary.TButton').grid(row=5,column=0,columnspan=3,sticky='w',pady=(7,0))

  measurement=ttk.LabelFrame(cards,labelwidget=card_header('export_measurements','Measurements'),padding=14);measurement.grid(row=0,column=1,sticky='nsew',padx=(5,0))
  ttk.Label(measurement,text='Export the active named distances as a table for statistical analysis.',style='Muted.TLabel',wraplength=430,justify='left').pack(anchor='w',pady=(0,10))
  ttk.Label(measurement,text='Output contains the project measurement definitions and their values for eligible images.',wraplength=430,justify='left').pack(anchor='w')
  self.button(measurement,'Export measurements…',self.measurements,'Choose CSV or tab-delimited text and a destination.',style='Primary.TButton').pack(anchor='w',pady=(12,0))
 def _save_as(self,title,initial,filetypes):
  kind=tk.StringVar(master=self.shell,value=filetypes[0][0]);target=filedialog.asksaveasfilename(parent=self.shell,title=title,initialfile=initial,filetypes=filetypes,typevariable=kind)
  return target,kind.get()
 def _format_target(self,target,kind):
  """Keep the filename extension consistent with the format selected in the dialog."""
  if not target:return target
  label=str(kind or '').casefold();suffix='.tps' if 'tps' in label else '.txt' if 'morphoj' in label or 'tab-delimited' in label or '.txt' in label else '.csv'
  path=Path(target)
  return str(path if path.suffix.lower()==suffix else path.with_suffix(suffix))
 def landmarks(self,mode,groups):
  selected=groups if mode=='groups' else ()
  if mode=='groups' and not selected:messagebox.showwarning('Export landmark coordinates','Select at least one landmark group.',parent=self.shell);return
  types=[('TPS (*.tps)','*.tps'),('CSV wide (*.csv)','*.csv'),('CSV long (*.csv)','*.csv'),('MorphoJ row/column text (*.txt)','*.txt')];target,kind=self._save_as('Export landmark coordinates','landmarks.tps',types)
  if not target:return
  target=self._format_target(target,kind)
  project=self.context.project
  def worker(progress):
   progress('Exporting landmark coordinates…')
   if kind.startswith('CSV wide'):return export_landmark_wide(project,selected,target=target)
   if kind.startswith('CSV long'):return export_landmark_csv_long(project,selected,target=target)
   if kind.startswith('MorphoJ'):return export_morphoj_text(project,selected,target=target)
   return export_landmark_tps(project,selected,target=target)
  self.shell._run_background_task('Export landmark coordinates','Exporting landmark coordinates…',worker,lambda path:messagebox.showinfo('Export landmark coordinates',f'Created: {path}',parent=self.shell))

 def measurements(self):
  types=[('CSV (*.csv)','*.csv'),('Tab-delimited text (*.txt)','*.txt')];target,kind=self._save_as('Export measurements','measurements.csv',types)
  if not target:return
  target=self._format_target(target,kind)
  project=self.context.project;delimiter='\t' if kind.startswith('Tab-delimited') else ','
  def worker(progress):
   progress('Calculating and exporting measurements…')
   return export_measurements(project,target=target,delimiter=delimiter)
  self.shell._run_background_task('Export measurements','Calculating and exporting measurements…',worker,lambda result:messagebox.showinfo('Export measurements',f"Rows: {result['rows']}\nFile: {result['path']}",parent=self.shell))


 def analysis_dataset(self):
  dialog=tk.Toplevel(self.shell);dialog.title('Export analysis dataset');dialog.transient(self.shell);dialog.resizable(False,False)
  body=ttk.Frame(dialog,padding=16);body.pack(fill='both',expand=True)
  scope=tk.StringVar(master=dialog,value=SCOPE_VERIFIED);verify=tk.BooleanVar(master=dialog,value=False);destination=tk.StringVar(master=dialog,value='')
  ttk.Label(body,text='Data scope').grid(row=0,column=0,columnspan=3,sticky='w')
  ttk.Radiobutton(body,text='Verified only (default)',variable=scope,value=SCOPE_VERIFIED).grid(row=1,column=0,columnspan=3,sticky='w')
  ttk.Radiobutton(body,text='All (may include unchecked or unfinished records)',variable=scope,value=SCOPE_ALL).grid(row=2,column=0,columnspan=3,sticky='w')
  ttk.Checkbutton(body,text='Verify source files (SHA256; may take a long time)',variable=verify).grid(row=3,column=0,columnspan=3,sticky='w',pady=(6,8))
  ttk.Label(body,text='Destination parent folder').grid(row=4,column=0,columnspan=3,sticky='w')
  entry=ttk.Entry(body,textvariable=destination,width=52);entry.grid(row=5,column=0,columnspan=2,sticky='ew',pady=(3,8))
  def choose():
   value=filedialog.askdirectory(parent=dialog,title='Choose analysis bundle destination')
   if value: destination.set(value)
  ttk.Button(body,text='Browse…',command=choose).grid(row=5,column=2,sticky='e',padx=(7,0))
  def start():
   parent=destination.get().strip()
   if not parent:
    messagebox.showwarning('Export analysis dataset','Choose a destination folder.',parent=dialog);return
   stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
   target=Path(parent)/('MorphoLabel_Analysis_'+stamp+'_'+uuid.uuid4().hex[:8])
   project=self.context.project;chosen_scope=scope.get();check_sources=verify.get();dialog.destroy()
   def worker(progress):
    progress('Taking a consistent SQLite snapshot and building the analysis bundle…')
    return export_analysis_bundle(project,target,scope=chosen_scope,verify_sources=check_sources)
   def complete(result):
    counts=result['counts'];morpho=counts['MorphoJ_omitted']
    messagebox.showinfo('Analysis dataset exported',
     f"Active: {counts['active_specimens']}  Selected: {counts['selected_for_scope']}\n"
     f"Drafts: {counts['drafts']}  Excluded: {counts['excluded']}\n"
     f"MorphoJ omitted by group: {json.dumps(morpho,ensure_ascii=False,sort_keys=True)}\n"
     f"Destination: {result['path']}",parent=self.shell)
   self.shell._run_background_task('Export analysis dataset','Creating a consistent analysis bundle…',worker,complete)
  controls=ttk.Frame(body);controls.grid(row=6,column=0,columnspan=3,sticky='e',pady=(6,0))
  ttk.Button(controls,text='Cancel',command=dialog.destroy).pack(side='right')
  ttk.Button(controls,text='Export',command=start).pack(side='right',padx=(0,7))
  entry.focus_set()
