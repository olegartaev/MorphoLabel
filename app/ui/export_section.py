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

_LANDMARK_FORMATS={
 'Wide CSV':{'initial':'landmarks_wide.csv','filter':'CSV wide (*.csv)','pattern':'*.csv','extension':'.csv','description':'One specimen per row, with landmark coordinates, sample and source-file information. Suitable for R and Excel.'},
 'TPS':{'initial':'landmarks.tps','filter':'TPS (*.tps)','pattern':'*.tps','extension':'.tps','description':'Landmark coordinates in original-image pixels, for TPS-compatible morphometric software.'},
 'Long CSV':{'initial':'landmarks_long.csv','filter':'CSV long (*.csv)','pattern':'*.csv','extension':'.csv','description':'One landmark per row, including annotation state and provenance.'},
 'MorphoJ':{'initial':'landmarks_morphoj.txt','filter':'MorphoJ row/column text (*.txt)','pattern':'*.txt','extension':'.txt','description':'Numeric landmark coordinates for complete specimens. A companion CSV identifies samples and source files.'},
}

def _extension_for_kind(kind,filetypes,default):
 text=str(kind or '').casefold()
 for label,pattern in filetypes:
  if text==label.casefold() or text==pattern.casefold() or pattern.casefold() in text:
   return '.tps' if pattern.casefold().endswith('.tps') else '.txt' if pattern.casefold().endswith('.txt') else '.csv'
 return default

class ExportSection(SectionView):
 def render(self):
  panel=self.frame(padding=18);panel.pack(fill='both',expand=True);cfg=self.context.project.config
  header=ttk.Frame(panel);header.pack(fill='x',pady=(0,12));header.columnconfigure(0,weight=1)
  ttk.Label(header,text='Export',style='PageTitle.TLabel').grid(row=0,column=0,sticky='w')
  ttk.Label(header,text=f"{cfg.get('name',self.context.project.root.name)} · {len(self.context.rows)} images",style='PageSubtitle.TLabel').grid(row=1,column=0,sticky='w',pady=(2,0))
  self.project_folder_label=ttk.Label(header,text=f"Project folder: {self.context.project.root}",style='Muted.TLabel',wraplength=1000,justify='left');self.project_folder_label.grid(row=2,column=0,sticky='w',pady=(2,0))
  guide=("Export landmark coordinates and measurements for downstream analysis.\n\n"
   "For a final reviewed dataset, choose Export analysis dataset and keep Verified only (default).\n\n"
   "Direct landmark and measurement exports may also include eligible records that have not been human-verified.\n\n"
   "The analysis dataset includes specimen identities, project definitions and information about missing or omitted values.")
  self.what_to_do(header,'Export — quick guide',guide).grid(row=0,column=1,rowspan=3,sticky='ne')

  cards=ttk.Frame(panel);cards.pack(fill='both',expand=True);cards.columnconfigure(0,weight=1);cards.columnconfigure(1,weight=1)
  def card_header(icon,text):
   title=ttk.Frame(cards)
   ttk.Label(title,image=self.shell.ui_icon(icon,WORKFLOW_ICON_SIZE)).pack(side='left',padx=(0,6))
   ttk.Label(title,text=text,style='WorkflowCardTitle.TLabel').pack(side='left')
   return title

  land=ttk.LabelFrame(cards,labelwidget=card_header('export_landmarks','Landmark coordinates'),padding=14);self.landmark_panel=land
  land.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,8))
  ttk.Label(land,text='Export landmark coordinates as TPS, CSV or MorphoJ-compatible text. This direct export is not restricted to human-verified images.',style='Muted.TLabel',wraplength=1050,justify='left').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,8))
  mode=tk.StringVar(master=panel,value='all');self.landmark_mode=mode;groups=available_groups(self.context.project)
  chosen={name:tk.BooleanVar(master=panel,value=True) for name in groups};checks=[];self.group_checkboxes=checks
  ttk.Label(land,text='Landmarks to include',style='SectionTitle.TLabel').grid(row=1,column=0,columnspan=3,sticky='w')
  all_choice=ttk.Radiobutton(land,text='All landmarks',variable=mode,value='all');all_choice.grid(row=2,column=0,sticky='w',pady=(3,0))
  selected_choice=ttk.Radiobutton(land,text='Choose groups',variable=mode,value='groups');selected_choice.grid(row=2,column=1,sticky='w',padx=(10,0),pady=(3,0))
  self.shell.tip.bind(all_choice,'Export every landmark in the active project scheme.');self.shell.tip.bind(selected_choice,'Export only the groups selected below.')
  group_line=ttk.Frame(land);group_line.grid(row=3,column=0,columnspan=3,sticky='ew',pady=(4,2));group_line.columnconfigure(0,weight=1);group_line.columnconfigure(1,weight=1)
  if groups:
   for index,(name,var) in enumerate(chosen.items()):
    check=ttk.Checkbutton(group_line,text=name,variable=var);check.grid(row=index//2,column=index%2,sticky='w',padx=(0,12),pady=(2,2));checks.append(check)
  else:ttk.Label(group_line,text='No landmark groups are defined; use All landmarks.',style='Muted.TLabel').grid(row=0,column=0,sticky='w')
  def update(*_):
   for check in checks:check.state(['!disabled'] if mode.get()=='groups' else ['disabled'])
  trace_for_widget(panel,mode,'write',update);update()

  self.landmark_format=tk.StringVar(master=panel,value='Wide CSV')
  selector_row=ttk.Frame(land);selector_row.grid(row=4,column=0,columnspan=3,sticky='w',pady=(8,0))
  ttk.Label(selector_row,text='Format',style='SectionTitle.TLabel').pack(side='left',padx=(0,8))
  self.format_selector=ttk.Combobox(selector_row,textvariable=self.landmark_format,values=tuple(_LANDMARK_FORMATS),state='readonly',width=18)
  self.format_selector.pack(side='left')
  self.format_description_label=ttk.Label(land,text='',style='Muted.TLabel',wraplength=1050,justify='left')
  self.format_description_label.grid(row=5,column=0,columnspan=3,sticky='w',pady=(4,0))
  def describe_format(_event=None):self.format_description_label.configure(text=_LANDMARK_FORMATS.get(self.landmark_format.get(),_LANDMARK_FORMATS['Wide CSV'])['description'])
  self.format_selector.bind('<<ComboboxSelected>>',describe_format);describe_format()
  self.shell.tip.bind(self.format_selector,'Choose the format before selecting the output file.')
  self.landmark_export_button=self.button(land,'Export landmarks…',lambda:self.landmarks(mode.get(),selected_groups(tuple(chosen),{name:var.get() for name,var in chosen.items()}),self.landmark_format.get()),'Save landmark coordinates in the selected format.',style='Primary.TButton')
  self.landmark_export_button.grid(row=6,column=0,sticky='w',pady=(8,0))
  self.analysis_export_button=self.button(land,'Export analysis dataset…',self.analysis_dataset,'Create a traceable analysis bundle.')
  self.analysis_export_button.grid(row=7,column=0,sticky='w',pady=(4,0))

  measurement=ttk.LabelFrame(cards,labelwidget=card_header('export_measurements','Measurements'),padding=(12,8));self.measurement_panel=measurement
  measurement.grid(row=1,column=0,columnspan=2,sticky='ew')
  ttk.Label(measurement,text='Export named linear measurements as a table. This direct export may include eligible unverified images.',style='Muted.TLabel',wraplength=1050,justify='left').grid(row=0,column=0,sticky='w',pady=(0,4))
  ttk.Label(measurement,text='Output contains the project measurement definitions and their values for eligible images.',style='Muted.TLabel',wraplength=1050,justify='left').grid(row=1,column=0,sticky='w')
  self.measurements_export_button=self.button(measurement,'Export measurements…',self.measurements,'Choose CSV or tab-delimited text and a destination.')
  self.measurements_export_button.grid(row=2,column=0,sticky='w',pady=(7,0))

 def _save_as(self,title,initial,filetypes,default_extension,selected_kind=None):
  """Save through the native dialog; any corrected suffix is reconfirmed there."""
  choices=list(filetypes);kind=tk.StringVar(master=self.shell,value=selected_kind or choices[0][0])
  initialfile=initial;initialdir=None
  while True:
   target=filedialog.asksaveasfilename(parent=self.shell,title=title,initialfile=initialfile,initialdir=initialdir,
    filetypes=choices,defaultextension=default_extension,typevariable=kind)
   if not target:return '',kind.get()
   selected=kind.get();extension=_extension_for_kind(selected,choices,default_extension)
   path=Path(target)
   if path.suffix.casefold()==extension.casefold():return str(path),selected
   corrected=path.with_suffix(extension) if path.suffix else path.with_name(path.name+extension)
   messagebox.showinfo(title,f'The selected format uses {extension}. The Save dialog will reopen with “{corrected.name}”; confirm the final name and any overwrite there.',parent=self.shell)
   initialfile=corrected.name;initialdir=str(corrected.parent)
   match=next((item for item in choices if item[1].casefold()==f'*{extension}'.casefold()),None)
   if match:choices=[match];kind.set(match[0])

 def landmarks(self,mode,groups,format_name='Wide CSV'):
  selected=groups if mode=='groups' else ()
  if mode=='groups' and not selected:messagebox.showwarning('Export landmarks','Select at least one landmark group.',parent=self.shell);return
  fmt=_LANDMARK_FORMATS.get(format_name,_LANDMARK_FORMATS['Wide CSV'])
  target,kind=self._save_as('Export landmarks',fmt['initial'],[(fmt['filter'],fmt['pattern'])],fmt['extension'],fmt['filter'])
  if not target:return
  project=self.context.project
  exporters={'Wide CSV':export_landmark_wide,'TPS':export_landmark_tps,'Long CSV':export_landmark_csv_long,'MorphoJ':export_morphoj_text}
  exporter=exporters[format_name]
  def worker(progress):
   progress('Exporting landmarks…')
   return exporter(project,selected,target=target)
  def complete(path):
   companion=path.with_name(f'{path.stem}_specimens.csv') if format_name in {'TPS','MorphoJ'} else None
   message=f'Created: {path}'
   if companion is not None:message+=f'\nSpecimen crosswalk: {companion}'
   messagebox.showinfo('Export landmarks',message,parent=self.shell)
  self.shell._run_background_task('Export landmarks','Exporting landmarks…',worker,complete)

 def measurements(self):
  types=[('CSV (*.csv)','*.csv'),('Tab-delimited text (*.txt)','*.txt')]
  target,kind=self._save_as('Export measurements','measurements.csv',types,'.csv','CSV (*.csv)')
  if not target:return
  project=self.context.project;delimiter='\t' if 'tab-delimited' in kind.casefold() or '.txt' in kind.casefold() or kind.endswith('*.txt') else ','
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
