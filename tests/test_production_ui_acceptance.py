"""Deterministic smoke checks for the real modular production UI (disposable data only)."""
import tempfile, unittest, hashlib, time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from PIL import Image
from app.project_storage import Project
from app.ui.context import UIContext
from app.ui.section_registry import visible_sections

class ProductionUISmoke(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name); source=root/'source'; (source/'sample_a').mkdir(parents=True); (source/'sample_b').mkdir()
  from app.ui import preferences
  self._preferences=preferences;self._preference_path=preferences._PATH;preferences._PATH=root/'ui_preferences.json'
  Image.new('RGB',(30,20),'white').save(source/'sample_a'/'a.jpg'); Image.new('RGB',(30,20),'black').save(source/'sample_b'/'b.jpg')
  schema=root/'schema.csv';schema.write_text('id,abbr,name,role,category\n1,A,Anterior,BOTH,Head\n2,P,Posterior,BOTH,Tail\n',encoding='utf-8')
  self.source=source;self.project=Project.create('smoke',source,root,schema,source_layout='direct');self.source_hashes={path.relative_to(source).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in source.rglob('*') if path.is_file()}
 def tearDown(self):
  self._preferences._PATH=self._preference_path
  # Background cache preparation is intentionally non-blocking; let a disposable worker release files before cleanup.
  for _ in range(50):
   try:self.tmp.cleanup();return
   except PermissionError:time.sleep(.1)
  self.tmp.cleanup()
 def test_context_navigation_search_and_crop_visibility(self):
  ui=UIContext(self.project);ui.refresh();self.assertEqual(2,len(ui.rows));self.assertEqual('a.jpg',ui.current()['original_name']);self.assertEqual(['b.jpg'],[r['original_name'] for r in ui.search('sample_b')]);ui.navigate(1);self.assertEqual('b.jpg',ui.current()['original_name']);self.assertIn('crop',[s.key for s in visible_sections(ui.crop_enabled())]);ui.set_crop_enabled(False);self.assertNotIn('crop',[s.key for s in visible_sections(ui.crop_enabled())]);self.assertEqual(0,self.project.count('landmarks'))
 def test_standardized_canvas_storage_path(self):
  row=self.project.catalog_rows()[0]; standardized=self.project.cache_root/'standardized'/f"{row['image_id']}.png";standardized.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(30,20),'white').save(standardized)
  self.project.save_crop(row['image_id'],{'standardized_relpath':standardized.relative_to(self.project.data_root).as_posix(),'transform':{'original_width':30,'original_height':20,'output_width':30,'output_height':20,'crop_x':0,'crop_y':0,'scale_x':1,'scale_y':1,'rotation_degrees':0}},'manual')
  self.project.save_landmark(row['image_id'],1,10,8,'manual','manual');opened=Project.open(self.project.root);point=opened.load_landmarks(row['image_id'])[1]
  self.assertEqual((point['x_standardized'],point['y_standardized'],point['provenance']),(10.0,8.0,'manual'))
 def test_real_export_services_on_disposable_project(self):
  from app.results_export import export_project_results
  from app.measurements import export_measurements
  results=export_project_results(self.project);self.assertTrue(results['tps'].is_file());self.assertTrue(results['specimens'].is_file());measured=export_measurements(self.project);self.assertTrue(measured['path'].is_file())
 def test_ui_actions_leave_source_photos_unchanged(self):
  ui=UIContext(self.project);ui.refresh();ui.set_crop_enabled(False);ui.set_crop_enabled(True);self.project.scan_originals()
  actual={path.relative_to(self.source).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in self.source.rglob('*') if path.is_file()};self.assertEqual(self.source_hashes,actual)
 def test_same_shell_project_attach_and_populated_schema_editor_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   from app.schema_editor import SchemaEditor
   shell=ProductionShell();shell.withdraw();shell._attach_project(self.project);shell.update_idletasks()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   self.assertIs(shell.context.project,self.project);self.assertEqual('project',shell.context.section)
   editor=SchemaEditor(shell,self.project.schema_path);editor.update_idletasks()
   trees=[]
   def walk(widget):
    if isinstance(widget,ttk.Treeview):trees.append(widget)
    for child in widget.winfo_children():walk(child)
   walk(editor);self.assertTrue(trees);self.assertGreaterEqual(len(trees[0].get_children()),2)
   editor.destroy()
  finally:shell.destroy()
 def test_normal_shell_startup_and_stage_navigation_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell();shell.withdraw();shell.update_idletasks()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   nav=shell.root.winfo_children()[0];labels=[child.cget('text') for child in nav.winfo_children() if child.winfo_class()=='TButton']
   self.assertEqual(['Project','Crop','Landmarks','Measurements','Export'],labels)
   self.assertFalse(any('SIMM |' in str(child.cget('text')) for child in shell.root.winfo_children() if child.winfo_class()=='TLabel'))
   widgets=[]
   def walk(widget):
    widgets.extend(widget.winfo_children())
    for child in widget.winfo_children():walk(child)
   walk(shell);self.assertTrue(any('text' in child.keys() and child.cget('text')=='New Project...' for child in widgets))
  finally:shell.destroy()

 def test_shared_photo_list_virtualizes_large_catalog_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell(self.project);shell.withdraw();shell.select('landmarks');shell.update_idletasks()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   shell.context.rows=[{'image_id':str(i),'original_name':f'fish_{i:04d}.jpg','relative_path':f'Sample_{i%100:03d}/fish_{i:04d}.jpg','locality':f'Sample_{i%100:03d}','sample_id':f'Sample_{i%100:03d}','index_in_locality':1,'total_in_locality':15,'status_color':'green','calibrated':False,'has_crop':False} for i in range(1500)]
   panel=shell.photo_panel;panel.refresh();panel.on_select=lambda:None;shell.update_idletasks();self.assertEqual(1500,len(panel.canvas.rows))
   shell.deiconify();shell.update();panel.canvas.focus_force();shell.update();panel.canvas.event_generate('<End>',when='now');shell.update();self.assertEqual((1499,),panel.canvas.curselection());shell.withdraw()
   panel.image_query.set('fish_1499');shell.update_idletasks();self.assertEqual(1,len(panel.canvas.rows))
   panel.image_query.set('');panel.locality_query.set('sample_042');shell.update_idletasks();self.assertEqual(15,len(panel.canvas.rows))
  finally:shell.destroy()
 def test_shell_layout_photo_panel_and_active_stage_style_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell(self.project);shell.withdraw()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   for width,height in ((1366,768),(1920,1080)):
    shell.geometry(f'{width}x{height}');shell.select('crop');shell.update_idletasks()
    nav=shell.root.winfo_children()[0];buttons=[child for child in nav.winfo_children() if child.winfo_class()=='TButton']
    active=[button for button in buttons if button.cget('text')=='Crop'][0]
    self.assertEqual('StageActive.TButton',active.cget('style'))
    self.assertIsNotNone(shell.photo_panel);self.assertEqual('PhotoListCanvas',type(shell.photo_panel.canvas).__name__)
    bars=[child for child in shell.section_host.winfo_children()[0].winfo_children() if child.winfo_class()=='TFrame']
    workflow=bars[-1]; self.assertLessEqual(workflow.winfo_rooty()+workflow.winfo_height(),shell.winfo_rooty()+shell.winfo_height())
   shell.context.set_crop_enabled(False);shell.render();shell.update_idletasks()
   nav=shell.root.winfo_children()[0];self.assertNotIn('Crop',[child.cget('text') for child in nav.winfo_children() if child.winfo_class()=='TButton'])
  finally:shell.destroy()
 def test_skip_crop_landmarks_and_calibration_load_real_project_cache_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   from app.calibration_workflow import CalibrationWorkflow
   shell=ProductionShell(self.project);shell.withdraw();shell.context.set_crop_enabled(False);shell.select('landmarks')
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   widgets=[]
   def walk(widget):
    widgets.extend(widget.winfo_children())
    for child in widget.winfo_children():walk(child)
   walk(shell);canvas=next(w for w in widgets if isinstance(w,tk.Canvas) and w.cget('background')=='#202020')
   for _ in range(50):
    shell.update();shell.update_idletasks();time.sleep(.05)
    if any(canvas.type(item)=='image' for item in canvas.find_all()):break
   self.assertTrue(any(canvas.type(item)=='image' for item in canvas.find_all()),'Skip crop must show the developed full image')
   self.assertFalse(self.project.crop_exists(self.project.catalog_rows()[0]['image_id']))
   dialog=CalibrationWorkflow(shell,self.project)
   for _ in range(50):
    shell.update();shell.update_idletasks();time.sleep(.05)
    if dialog.image is not None:break
   self.assertIsNotNone(dialog.image,'Calibration must display the active project developed image')
   dialog.points=[(2.0,2.0),(12.0,2.0)];dialog.mm.set('10');self.assertTrue(dialog._save_current())
   self.assertTrue(self.project.locality_calibration(dialog.locality()));dialog.destroy()
  finally:shell.destroy()
 def test_shell_constructs_and_renders_sections_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell(self.project);shell.withdraw();shell.update_idletasks()
  except Exception as exc:
   self.skipTest(f'Tk display unavailable: {exc}')
  try:
   shell.select('crop');time.sleep(.6);shell.update();shell.update_idletasks();self.assertIsNotNone(shell.photo_panel); self.assertTrue(hasattr(shell.photo_panel,'canvas'))
   for section in ('landmarks','measurements','export'):
    shell.select(section);shell.update_idletasks()
   shell.context.set_crop_enabled(False);shell.render()
   self.assertNotIn('Crop',[child.cget('text') for child in shell.root.winfo_children()[0].winfo_children()])
   shell.context.set_crop_enabled(True);shell.render();shell.show_model_transfer();shell.update_idletasks()
   dialogs=[w for w in shell.winfo_children() if w.winfo_class()=='Toplevel'];[w.destroy() for w in dialogs]
  finally: shell.destroy()
 def test_crop_models_dialog_keeps_table_scrollbar_and_bottom_right_actions_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   for model_id in ('crop_model_v001','crop_model_v002','crop_model_v003'):
    folder=self.project.data_root/'ai'/'models'/model_id;folder.mkdir(parents=True,exist_ok=True)
    self.project.register_model(model_id,'crop',path=f'ai/models/{model_id}',metrics={'training_examples':5},active=model_id=='crop_model_v001')
   shell=ProductionShell(self.project);shell.withdraw();shell.show_models('crop');shell.update_idletasks()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   dialog=next(w for w in shell.winfo_children() if isinstance(w,tk.Toplevel));shell.deiconify();dialog.deiconify();shell.update_idletasks();tree=next(w for w in dialog.winfo_children()[0].winfo_children()[0].winfo_children() if isinstance(w,ttk.Treeview))
   scroll=next(w for w in dialog.winfo_children()[0].winfo_children()[0].winfo_children() if isinstance(w,ttk.Scrollbar));buttons=[]
   def walk(widget):
    if isinstance(widget,ttk.Button):buttons.append(widget)
    for child in widget.winfo_children():walk(child)
   walk(dialog);use=next(b for b in buttons if b.cget('text')=='Use selected');close=next(b for b in buttons if b.cget('text')=='Close')
   self.assertEqual(3,len(tree.get_children()));self.assertEqual('grid',scroll.winfo_manager());self.assertEqual('right',use.pack_info()['side']);self.assertEqual('right',close.pack_info()['side']);self.assertIs(use.master,close.master)
   target=next(item for item in tree.get_children() if tree.item(item,'values')[1]=='crop_model_v002');tree.selection_set(target);tree.event_generate('<<TreeviewSelect>>');shell.update_idletasks();use.invoke();shell.update_idletasks();self.assertEqual('crop_model_v002',self.project.active_model('crop')['model_id']);self.assertTrue(dialog.winfo_exists())
  finally:shell.destroy()
 def test_warm_section_refresh_uses_cached_catalog(self):
  from unittest.mock import patch
  ui=UIContext(self.project);ui.refresh(force=True)
  with patch.object(self.project,'catalog_rows',side_effect=AssertionError('warm refresh must not rescan catalog')):
   started=time.perf_counter();ui.refresh();ui.section='landmarks';ui.refresh();elapsed=time.perf_counter()-started
  self.assertLess(elapsed,.25)
 def test_schema_role_groups_and_skip_crop_measurement_identity(self):
  from app.export_formats import available_groups,export_landmark_tps
  from app.measurements import save_measurements,values_for_image
  row=self.project.catalog_rows()[0];developed=self.project.cache_root/'developed'/f"{row['image_id']}.png";developed.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(30,20),'white').save(developed)
  self.project.save_landmark(row['image_id'],1,2,3,'manual','manual');self.project.save_landmark(row['image_id'],2,12,3,'manual','manual')
  self.project.set_locality_calibration(row['locality'],row['image_id'],2.0,'mm',{'mm_per_pixel':.5,'points_original':[[0,0],[2,0]]})
  save_measurements(self.project,[{'use':True,'abbr':'D','name':'Distance','point1':1,'point2':2}])
  values,mpp=values_for_image(self.project,row);self.assertEqual((values['D'],mpp),(5.0,.5))
  self.assertIn('Head',available_groups(self.project));self.assertTrue(export_landmark_tps(self.project,['Head']).is_file())
 def test_photo_click_preserves_scroll_position_when_tk_available(self):
  row=self.project.catalog_rows()[0];target=self.project.cache_root/'developed'/f"{row['image_id']}.png";target.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(30,20),'white').save(target)
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell(self.project);shell.withdraw();shell.update_idletasks()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   from app.ui.landmark_sidebar import LandmarkSidebar; host=ttk.Frame(shell.root);host.grid(row=2,column=0,sticky='nsew');panel=LandmarkSidebar(host,shell.context,lambda *_:None,shell.tip,lambda _ident:None);panel.pack(fill='both',expand=True);shell.context.rows=[{'image_id':str(i),'original_name':f'fish_{i:04d}.jpg','relative_path':f'Sample/fish_{i:04d}.jpg','locality':'Sample','sample_id':'Sample','index_in_locality':i+1,'total_in_locality':1303,'status_color':'green'} for i in range(1303)];panel.refresh();shell.update_idletasks();panel.canvas.yview_moveto(.55);before=panel.canvas.yview()[0];panel.canvas.event_generate('<Button-1>',x=12,y=40);shell.update_idletasks();after=panel.canvas.yview()[0];self.assertAlmostEqual(before,after,places=4)
  finally:shell.destroy()
 def test_explicit_export_targets_do_not_write_default_files(self):
  from app.export_formats import export_landmark_wide
  from app.measurements import export_measurements
  target=self.tmp.name and Path(self.tmp.name)/'chosen_landmarks.csv';measures=Path(self.tmp.name)/'chosen_measurements.txt'
  self.assertTrue(export_landmark_wide(self.project,target=target).is_file());self.assertEqual(target,export_landmark_wide(self.project,target=target));self.assertTrue(export_measurements(self.project,target=measures,delimiter='\t')['path'].is_file())
 def test_measurement_preview_real_image_when_tk_available(self):
  row=self.project.catalog_rows()[0];target=self.project.cache_root/'developed'/f"{row['image_id']}.png";target.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(30,20),'white').save(target)
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell(self.project);shell.withdraw();shell.select('measurements')
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   for _ in range(10):shell.update();shell.update_idletasks()
   canvases=[]
   def walk(widget):
    if isinstance(widget,tk.Canvas):canvases.append(widget)
    for child in widget.winfo_children():walk(child)
   walk(shell);self.assertTrue(any(any(canvas.type(item)=='image' for item in canvas.find_all()) for canvas in canvases))
  finally:shell.destroy()
 def test_last_project_reopens_in_the_same_shell_when_tk_available(self):
  try:
   from app.ui.shell import ProductionShell
   first=ProductionShell();first.withdraw();first._attach_project(self.project);first.update_idletasks();first.destroy()
   second=ProductionShell();second.withdraw();second.update_idletasks()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   self.assertIsNotNone(second.context.project);self.assertEqual(self.project.root.resolve(),second.context.project.root.resolve());self.assertEqual('project',second.context.section)
   labels=[child.cget('text') for child in second.root.winfo_children()[0].winfo_children() if child.winfo_class()=='TButton'];self.assertEqual(['Project','Crop','Landmarks','Measurements','Export'],labels)
  finally:second.destroy()
 def test_photo_click_paints_before_idle_and_keeps_scroll_when_tk_available(self):
  from unittest.mock import Mock
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell(self.project);shell.withdraw();shell.update_idletasks()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   from app.ui.photo_list_panel import PhotoListPanel;host=ttk.Frame(shell.root);host.grid(row=2,column=0,sticky='nsew');panel=PhotoListPanel(host,shell.context,lambda *_:None,shell.tip);panel.pack(fill='both',expand=True);shell.context.rows=[{'image_id':str(i),'original_name':f'fish_{i:04d}.jpg','relative_path':f'Sample/fish_{i:04d}.jpg','locality':'Sample','sample_id':'Sample','index_in_locality':i+1,'total_in_locality':1303,'status_color':'green'} for i in range(1303)];panel.refresh();shell.update_idletasks();panel.canvas.yview_moveto(.55);before=panel.canvas.yview()[0]
   view=Mock();shell.current_view=view;panel.on_select=shell._selected_image;panel.canvas._select(730,reveal=False);panel._selected();self.assertTrue(panel.canvas.curselection());self.assertAlmostEqual(before,panel.canvas.yview()[0],places=6);view.on_image_selected.assert_not_called()
   shell.update();view.on_image_selected.assert_called_once()
  finally:shell.destroy()
 def test_landmark_drag_is_vector_only_between_press_and_release_when_tk_available(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  row=self.project.catalog_rows()[0];target=self.project.cache_root/'developed'/f"{row['image_id']}.png";target.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(100,80),'white').save(target);self.project.save_landmark(row['image_id'],1,20,20,'manual','manual')
  try:
   from app.ui.shell import ProductionShell
   import app.ui.landmark_canvas as canvas_module
   shell=ProductionShell(self.project);shell.withdraw();shell.select('landmarks')
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   controller=shell.current_view.canvas
   for _ in range(80):
    shell.update();shell.update_idletasks();time.sleep(.02)
    if controller.image is not None:break
   self.assertIsNotNone(controller.image)
   x,y=controller._position(20,20);controller.place(SimpleNamespace(x=x,y=y));shell.update_idletasks()
   image_before=controller.stats['photo_creations'];reads_before=controller.stats['state_reads']
   with patch.object(canvas_module,'load_current_landmark_state',wraps=canvas_module.load_current_landmark_state) as state_read,patch.object(canvas_module.ImageTk,'PhotoImage',wraps=canvas_module.ImageTk.PhotoImage) as photo,patch.object(self.project,'save_landmark',wraps=self.project.save_landmark) as save:
    for offset in range(1,101):controller.drag(SimpleNamespace(x=x+offset*.1,y=y+offset*.1))
    self.assertEqual(0,state_read.call_count);self.assertEqual(0,photo.call_count);self.assertEqual(0,save.call_count);self.assertEqual(image_before,controller.stats['photo_creations']);self.assertEqual(reads_before,controller.stats['state_reads'])
    controller.release(SimpleNamespace(x=x+10,y=y+10));self.assertEqual(1,save.call_count);self.assertEqual(1,state_read.call_count);self.assertEqual(0,photo.call_count)
  finally:shell.destroy()
 def test_top_next_invokes_real_landmark_batch_path_when_tk_available(self):
  from app.landmark_ai_workflow import STATE_KEY,load_state
  for name in ('c.jpg','d.jpg'): Image.new('RGB',(30,20),'white').save(self.source/'sample_a'/name)
  self.project.scan_originals();ids=[row['image_id'] for row in self.project.catalog_rows()]
  for ident in ids:
   target=self.project.cache_root/'developed'/f"{ident}.png";target.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(30,20),'white').save(target)
   self.project.save_landmark(ident,1,4,4,'manual','manual');self.project.save_landmark(ident,2,14,4,'manual','manual');self.project.clear_checked(ident)
  [self.project.mark_checked(ident) for ident in ids[:2]];self.project.set_ui_state(STATE_KEY,{'stage':'INITIAL_TRAINING','control_image_ids':ids[:2],'initial_image_ids':ids[2:],'improvement_image_ids':[],'current_image_id':ids[2],'current_position':0})
  ids=ids[2:]
  try:
   from app.ui.shell import ProductionShell
   shell=ProductionShell(self.project);shell.withdraw();shell.select('landmarks');shell.context.selected=next(i for i,row in enumerate(shell.context.rows) if row['image_id']==ids[0]);shell._selected_image()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   controller=shell.current_view.canvas
   for _ in range(100):
    shell.update();shell.update_idletasks();time.sleep(.01)
    if controller.ready_for(ids[0]):break
   self.assertTrue(controller.ready_for(ids[0]))
   # Acceptance path is the actual top button, never a section navigation call.
   shell.status_next.invoke()
   for _ in range(100):
    shell.update();shell.update_idletasks();time.sleep(.01)
    if shell.context.current()['image_id']==ids[1] and controller.ready_for(ids[1]):break
   self.assertTrue(self.project.annotation_status(ids[0])['verified'], f'current={shell.context.current()} state={load_state(self.project)} canvas={controller.state}')
   self.assertEqual(ids[1],shell.context.current()['image_id'])
   self.assertEqual(1,load_state(self.project)['current_position'])
   self.assertTrue(controller.ready_for(ids[1]))
  finally:shell.destroy()
 def test_status_header_reserves_batch_navigation_through_sash_and_window_resize_when_tk_available(self):
  from app.ui.shell import ProductionShell
  from app.landmark_ai_workflow import STATE_KEY
  ids=[row['image_id'] for row in self.project.catalog_rows()]
  for image_id in ids:
   self.project.save_landmark(image_id,1,4,4,'manual','manual');self.project.save_landmark(image_id,2,14,4,'manual','manual')
  self.project.set_ui_state(STATE_KEY,{'stage':'INITIAL_TRAINING','initial_image_ids':ids,'improvement_image_ids':[],'current_image_id':ids[0],'current_position':0})
  try:
   shell=ProductionShell(self.project);shell.select('landmarks');shell.deiconify();shell.update()
  except Exception as exc:self.skipTest(f'Tk display unavailable: {exc}')
  try:
   for width,height in ((980,650),(1120,700),(1600,900)):
    shell.geometry(f'{width}x{height}');shell.update_idletasks();shell.update()
    pane=shell.workspace_panes;available=pane.winfo_width()
    for sash in (220,max(220,available-390)):
     pane.sashpos(0,sash);shell.update_idletasks();shell.update()
     previous,index,next_button=shell.status_previous,shell.status_index,shell.status_next
     self.assertTrue(all(widget.winfo_ismapped() for widget in (previous,index,next_button)))
     self.assertIn('Remaining',index.cget('text'))
     self.assertLessEqual(previous.winfo_rootx()+previous.winfo_width(),index.winfo_rootx())
     self.assertLessEqual(index.winfo_rootx()+index.winfo_width(),next_button.winfo_rootx())
     self.assertLessEqual(next_button.winfo_rootx()+next_button.winfo_width(),shell.status_bar.winfo_rootx()+shell.status_bar.winfo_width()+1)
     self.assertLessEqual(shell.status_left.winfo_rootx()+shell.status_left.winfo_width(),shell.status_navigation.winfo_rootx())
   self.project.set_ui_state(STATE_KEY,{'stage':'IDLE','initial_image_ids':[],'improvement_image_ids':[]});shell._update_status();self.assertRegex(shell.status_index.cget('text'),r'^1 / 2$')
  finally:shell.destroy()
if __name__=='__main__': unittest.main()



