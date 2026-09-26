"""Project-level exports backed by canonical production services."""
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from app.export_formats import available_groups, export_landmark_tps, export_landmark_csv_long, export_landmark_wide, export_morphoj_text
from app.measurements import export_measurements
from .section_base import SectionView

class ExportSection(SectionView):
 def render(self):
  panel=self.frame(padding=18);panel.pack(fill='both',expand=True);cfg=self.context.project.config
  header=ttk.Frame(panel);header.pack(fill='x',pady=(0,14));header.columnconfigure(0,weight=1)
  ttk.Label(header,text='Export',style='PageTitle.TLabel').grid(row=0,column=0,sticky='w')
  ttk.Label(header,text=f"{cfg.get('name',self.context.project.root.name)} · {len(self.context.rows)} images",style='PageSubtitle.TLabel').grid(row=1,column=0,sticky='w',pady=(2,0))
  guide='Why: Export creates portable files for statistics, figures and reproducible downstream analysis.\n\nLandmark coordinates\nExport landmark positions when you need shape coordinates in TPS, CSV or MorphoJ-compatible form.\n\nMeasurements\nExport the named distances defined in Measurements as a simple table for statistical analysis.'
  self.what_to_do(header,'Export — quick guide',guide).grid(row=0,column=1,rowspan=2,sticky='ne')

  cards=ttk.Frame(panel);cards.pack(fill='x');cards.columnconfigure(0,weight=1);cards.columnconfigure(1,weight=1)

  land=ttk.LabelFrame(cards,text='📍  Landmark coordinates',padding=14);land.grid(row=0,column=0,sticky='nsew',padx=(0,5))
  ttk.Label(land,text='Export landmark positions for geometric morphometrics or other coordinate-based analyses.',style='Muted.TLabel',wraplength=430,justify='left').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,10))
  mode=tk.StringVar(value='all');groups=available_groups(self.context.project);chosen={name:tk.BooleanVar(value=True) for name in groups};checks=[]
  ttk.Label(land,text='Landmarks to include',style='SectionTitle.TLabel').grid(row=1,column=0,columnspan=3,sticky='w')
  all_choice=ttk.Radiobutton(land,text='All landmarks',variable=mode,value='all');all_choice.grid(row=2,column=0,sticky='w',pady=(4,0))
  selected_choice=ttk.Radiobutton(land,text='Selected groups',variable=mode,value='groups');selected_choice.grid(row=2,column=1,sticky='w',padx=(10,0),pady=(4,0))
  self.shell.tip.bind(all_choice,'Export every landmark in the active project scheme.');self.shell.tip.bind(selected_choice,'Export only the groups selected below.')
  line=ttk.Frame(land);line.grid(row=3,column=0,columnspan=3,sticky='w',pady=(6,2))
  if groups:
   for name,var in chosen.items():
    check=ttk.Checkbutton(line,text=name,variable=var);check.pack(side='left',padx=(0,8));checks.append(check)
  else:
   ttk.Label(line,text='No landmark groups are defined; use All landmarks.',style='Muted.TLabel').pack(anchor='w')
  def update(*_):
   for check in checks:check.state(['!disabled'] if mode.get()=='groups' else ['disabled'])
  mode.trace_add('write',update);update()
  self.button(land,'Export landmark coordinates…',lambda:self.landmarks(mode.get(),[name for name,var in chosen.items() if var.get()]),'Choose an output format and destination.',style='Primary.TButton').grid(row=4,column=0,columnspan=3,sticky='w',pady=(12,0))

  measurement=ttk.LabelFrame(cards,text='📏  Measurements',padding=14);measurement.grid(row=0,column=1,sticky='nsew',padx=(5,0))
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
  from pathlib import Path
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
