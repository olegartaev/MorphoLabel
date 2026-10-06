"""Third-pass regressions through saved projects, portable models and actual Tk."""
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image
from app.project_storage import Project, load_schema
from app.ai_package import export_model_package, import_model_package
from app.measurements import save_measurements, load_measurements
from tests import test_final_functional_hardening as tk_fixtures


class ThirdWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.source=self.root/'source';self.source.mkdir();Image.new('RGB',(120,80),'white').save(self.source/'fish.png')
  self.schema=self.root/'schema.csv';self.schema.write_text('id,abbr,name,role,category\n1,A,Alpha,BOTH,head\n2,B,Beta,GM,tail\n',encoding='utf-8')
  self.project=Project.create('source_project',self.source,self.root,self.schema,source_layout='direct')
  path=self.project.models_root/'crop_model_v010';path.mkdir();weights=np.zeros((769,6));weights[0]=[.1,.2,.9,.8,math.sin(.4),math.cos(.4)]
  np.savez_compressed(path/'model.npz',weights=weights)
  (path/'model_manifest.json').write_text(json.dumps({'backend':'numpy_ridge_image_regression','output_schema':{'version':2}}),encoding='utf-8')
  self.project.register_model('crop_model_v010','crop',path='models/crop_model_v010',active=True)
  save_measurements(self.project,[{'use':False,'abbr':'AB','name':'Distance, "full"','point1':1,'point2':2}])

 def test_crop_package_applies_landmark_and_measurement_schemes_to_blank_project(self):
  archive=self.root/'crop.zip';export_model_package(self.project,'crop',archive)
  target=Project.create('blank',self.source,self.root,source_layout='direct')
  local=import_model_package(target,archive,'crop');target=Project.open(target.root)
  self.assertEqual(self.project.schema,target.schema);self.assertEqual(load_measurements(self.project),load_measurements(target))
  self.assertEqual(local,target.active_model('crop')['model_id'])
  self.assertTrue((target.data_root/target.active_model('crop')['path']/'model.npz').is_file())

 def test_model_export_names_begin_with_module(self):
  from app.model_transfer import model_package_filename
  self.assertEqual('landmarks_crop_model_v009.zip',model_package_filename({'model_id':'crop_model_v009'},'landmarks_crop_model'))
  self.assertEqual('xray_structure_test.zip',model_package_filename({'model_id':'structure_test'},'xray_structure_model'))
  self.assertEqual('xray_crop_model_v004.zip',model_package_filename({'model_id':'xray_crop_model_v004'},'xray_crop_model'))

 def test_bundle_registration_failure_rolls_back_schemes_history_and_models(self):
  archive=self.root/'crop.zip';export_model_package(self.project,'crop',archive)
  target=Project.create('target',self.source,self.root,self.schema,source_layout='direct')
  target.schema_path.write_text('id,abbr,name,role\n1,B,Beta,BOTH\n2,A,Alpha,BOTH\n',encoding='utf-8');target=Project.open(target.root)
  image=target.catalog_rows()[0]['image_id'];target.save_landmark(image,1,4,5,'manual','manual')
  save_measurements(target,[{'use':True,'abbr':'OLD','name':'Old definition','point1':1,'point2':2}])
  files={p:p.read_bytes() for p in (target.schema_path,target.config_path,target.root/'measurement_schema.csv')}
  with target.transaction() as c:
   rows=c.execute('SELECT * FROM landmarks').fetchall();c.execute("CREATE TRIGGER reject_import BEFORE INSERT ON models BEGIN SELECT RAISE(ABORT,'registry failure'); END")
  with self.assertRaisesRegex(Exception,'registry failure'):import_model_package(target,archive,'crop')
  self.assertEqual(files,{p:p.read_bytes() for p in files});self.assertEqual([],target.models('crop'))
  with target.transaction() as c:self.assertEqual(rows,c.execute('SELECT * FROM landmarks').fetchall())
  self.assertFalse((target.models_root/'crop'/'crop_model_v010').exists())
  with target.transaction() as c:c.execute('DROP TRIGGER reject_import')
  import_model_package(target,archive,'crop');target=Project.open(target.root)
  point=target.load_landmarks(image)[2];self.assertEqual((4,5),(point['x_standardized'],point['y_standardized']))
  self.assertEqual('AB',load_measurements(target)[0]['abbr'])

 def test_measurement_portability_rejects_malformed_duplicate_and_unknown_without_mutation(self):
  from app.measurements import measurement_definitions_csv, import_measurement_definitions
  original=(self.project.root/'measurement_schema.csv').read_bytes();text=measurement_definitions_csv(self.project)
  for content in (text.replace(',A,B',',A,UNKNOWN'),text+text.splitlines()[1]+'\n',text.replace('0,AB','maybe,AB'),text.replace('Point2Abbr','Point1Abbr'),text.replace(',A,B',',A,B,EXTRA')):
   path=self.root/'bad.csv';path.write_text(content,encoding='utf-8')
   with self.assertRaises(ValueError):import_measurement_definitions(self.project,path)
   self.assertEqual(original,(self.project.root/'measurement_schema.csv').read_bytes())
  path.write_text('\ufeff'+text.replace('\n','\r\n'),encoding='utf-8');import_measurement_definitions(self.project,path)
  self.assertEqual(original,(self.project.root/'measurement_schema.csv').read_bytes())

 def test_old_crop_weights_explicitly_report_rotation_unavailable_and_new_model_roundtrips(self):
  from app.crop_training import predict, rotation_supported
  model=self.project.active_model('crop');path=self.project.data_root/model['path']
  with Image.open(self.source/'fish.png') as image:expected,_=predict(image,project=self.project)
  package=self.root/'crop.zip';export_model_package(self.project,'crop',package)
  target=Project.create('angle_target',self.source,self.root,source_layout='direct');local=import_model_package(target,package,'crop')
  with Image.open(self.source/'fish.png') as image:actual,_=predict(image,project=Project.open(target.root))
  np.testing.assert_array_equal(expected['bounds'],actual['bounds']);self.assertEqual(expected['rotation_degrees'],actual['rotation_degrees']);self.assertTrue(actual['rotation_supported'])
  np.savez_compressed(path/'model.npz',weights=np.zeros((769,4)))
  self.assertFalse(rotation_supported(self.project))
  with Image.open(self.source/'fish.png') as image:output,_=predict(image,project=self.project)
  self.assertFalse(output['rotation_supported'])

 def test_new_crop_batches_keep_old_queues_through_reopen_and_explicit_close(self):
  from app.crop_queues import replace_batch, saved_batches, open_saved_batch, close_saved_batch
  image=self.project.catalog_rows()[0]['image_id'];first=replace_batch(self.project,'crop_active_batch',{'ids':[image],'position':0,'batch_type':'training'})
  second=replace_batch(self.project,'crop_active_batch',{'ids':[image],'position':0,'batch_type':'manual_review'})
  project=Project.open(self.project.root);saved=saved_batches(project,'crop_active_batch')[0];self.assertEqual(first,{k:v for k,v in saved.items() if k!='queue_id'});first=saved
  self.assertEqual(first,open_saved_batch(project,'crop_active_batch',first['queue_id']))
  saved=saved_batches(project,'crop_active_batch')[0];self.assertEqual(second,{k:v for k,v in saved.items() if k!='queue_id'});second=saved
  close_saved_batch(project,'crop_active_batch',second['queue_id']);self.assertEqual((),saved_batches(Project.open(project.root),'crop_active_batch'))

 def test_landmark_package_embeds_and_applies_both_schemes_to_blank_target(self):
  from app.project_storage import schema_hash
  directory=self.project.models_root/'rtmpose_test';directory.mkdir()
  (directory/'inference_config.py').write_text('model=dict(type="TopdownPoseEstimator")\n',encoding='utf-8')
  (directory/'best_engineering_validation.pth').write_bytes(b'controlled-checkpoint')
  (directory/'model.json').write_text(json.dumps({'backend':'rtmpose','schema_sha256':schema_hash(self.project.schema_path)}),encoding='utf-8')
  self.project.register_model('rtmpose_test','landmark',path='models/rtmpose_test',active=True)
  archive=self.root/'landmarks.zip';export_model_package(self.project,'landmark',archive)
  target=Project.create('empty_landmarks',self.source,self.root,source_layout='direct')
  local=import_model_package(target,archive,'landmark');target.set_active_model('landmark',local);target=Project.open(target.root)
  self.assertEqual(self.project.schema,target.schema);self.assertEqual(load_measurements(self.project),load_measurements(target))
  imported=target.data_root/target.active_model('landmark')['path'];self.assertEqual(b'controlled-checkpoint',(imported/'best_engineering_validation.pth').read_bytes())
  archive.unlink();self.assertTrue(imported.is_dir())

 def test_qc_queues_keep_old_members_and_do_not_end_by_jumping_to_last(self):
  from app.landmark_suspicious_review import start,move,state
  from app.crop_queues import saved_batches
  image=self.project.catalog_rows()[0]['image_id']
  issues=[{'image_id':image,'message':str(i),'landmark_ids':[1]} for i in range(3)]
  start(self.project,issues);start(self.project,issues)
  self.assertEqual(1,len(saved_batches(Project.open(self.project.root),'landmark_suspicious_review')))
  value=state(self.project);value['position']=2;self.project.set_ui_state('landmark_suspicious_review',value)
  _,finished=move(self.project,1);self.assertFalse(finished);self.assertTrue(state(Project.open(self.project.root))['active'])

 def test_corrupt_bundled_scheme_rejects_before_model_or_project_mutation(self):
  archive=self.root/'valid.zip';export_model_package(self.project,'crop',archive)
  target=Project.create('corrupt_target',self.source,self.root,source_layout='direct');before=target.schema_path.read_bytes()
  with zipfile.ZipFile(archive) as z:entries={name:z.read(name) for name in z.namelist()}
  manifest=json.loads(entries['manifest.json']);manifest['project_schemes']['landmarks']['csv']='corrupted';entries['manifest.json']=json.dumps(manifest).encode()
  bad=self.root/'bad.zip'
  with zipfile.ZipFile(bad,'w') as z:
   for name,data in entries.items():z.writestr(name,data)
  with self.assertRaisesRegex(ValueError,'checksum'):import_model_package(target,bad,'crop')
  self.assertEqual(before,target.schema_path.read_bytes());self.assertEqual([],target.models('crop'));self.assertFalse((target.root/'measurement_schema.csv').exists())

 def test_model_id_cannot_store_imported_artifacts_outside_project_model_folder(self):
  archive=self.root/'safe.zip';export_model_package(self.project,'crop',archive)
  with zipfile.ZipFile(archive) as z:entries={name:z.read(name) for name in z.namelist()}
  manifest=json.loads(entries['manifest.json']);manifest['model_id']='../../escaped_model';entries['manifest.json']=json.dumps(manifest).encode()
  bad=self.root/'bad_id.zip'
  with zipfile.ZipFile(bad,'w') as z:
   for name,data in entries.items():z.writestr(name,data)
  target=Project.create('local_only',self.source,self.root,source_layout='direct')
  with self.assertRaisesRegex(ValueError,'model ID'):import_model_package(target,bad,'crop')
  self.assertFalse((target.data_root/'escaped_model').exists());self.assertEqual([],target.models('crop'))

 def test_editing_active_measurements_cannot_silently_drop_unresolved_definitions(self):
  path=self.project.root/'measurement_schema.csv'
  original=path.read_text(encoding='utf-8');path.write_text(original+'1,HIST,Historical distance,1,99,A,REMOVED\n',encoding='utf-8')
  rows=load_measurements(self.project);rows[0]['name']='Edited active definition';save_measurements(self.project,rows)
  self.assertIn('Historical distance',path.read_text(encoding='utf-8'))
  self.assertIn('REMOVED',path.read_text(encoding='utf-8'))

 def test_new_ranked_review_does_not_finish_unreviewed_old_queue(self):
  from app.landmark_ai_review import create_review_session_for_ids, _load
  image=self.project.catalog_rows()[0]['image_id']
  create_review_session_for_ids(self.project,'first',[image],kind='review_worst_v2')
  create_review_session_for_ids(self.project,'second',[image],kind='review_worst_v2')
  old=next(x for x in _load(Project.open(self.project.root))['sessions'] if x['batch_id']=='first')
  self.assertFalse(old['complete']);self.assertFalse(old.get('closed',False))

 def test_empty_crop_scheme_preserves_target_definitions_and_import_collision_preserves_files(self):
  empty=Project.create('no_scheme_source',self.source,self.root,source_layout='direct')
  directory=empty.models_root/'crop_model_v010';directory.mkdir()
  source_model=self.project.data_root/self.project.active_model('crop')['path']
  for name in ('model.npz','model_manifest.json'):(directory/name).write_bytes((source_model/name).read_bytes())
  empty.register_model('crop_model_v010','crop',path='models/crop_model_v010',active=True)
  archive=self.root/'empty_scheme.zip';export_model_package(empty,'crop',archive)
  files={path:path.read_bytes() for path in (self.project.schema_path,self.project.root/'measurement_schema.csv')}
  occupied=self.project.models_root/'crop'/'crop_model_v010';occupied.mkdir(parents=True);(occupied/'retained.txt').write_text('keep',encoding='utf-8')
  local=import_model_package(self.project,archive,'crop')
  self.assertNotEqual('crop_model_v010',local);self.assertEqual('keep',(occupied/'retained.txt').read_text(encoding='utf-8'))
  self.assertEqual(files,{path:path.read_bytes() for path in files})
  archive.unlink();self.assertTrue((self.project.data_root/self.project.model_metadata(local)['path']/'model.npz').is_file())

 def test_qc_queue_finishes_only_after_all_members_are_completed(self):
  from app.landmark_suspicious_review import start,complete_current,active
  image=self.project.catalog_rows()[0]['image_id'];start(self.project,[{'image_id':image,'message':str(i)} for i in range(3)])
  for expected in (False,False,True):
   _,finished=complete_current(self.project);self.assertEqual(expected,finished)
  self.assertIsNone(active(Project.open(self.project.root)))

 def test_crop_queue_cannot_finish_by_jumping_to_last_member(self):
  from app.ui.crop_section import CropSection
  ids=[]
  for i in range(3):Image.new('RGB',(120,80),'white').save(self.source/f'{i}.png')
  self.project.scan_originals();rows=self.project.catalog_rows();ids=[r['image_id'] for r in rows]
  self.project.set_ui_state('crop_active_batch',{'ids':ids,'batch_type':'training','completed_ids':[]})
  context=SimpleNamespace(project=self.project,rows=rows,selected=len(rows)-1,current=lambda:rows[context.selected])
  shell=SimpleNamespace(_update_status=lambda:None,_sync_photo_panel_current=lambda **kw:None,_selected_image=lambda:None)
  view=SimpleNamespace(context=context,shell=shell,apply_current=lambda:'SAVED')
  with patch('app.ui.crop_section.messagebox.showinfo'):
   CropSection._move_batch(view,1)
  state=self.project.get_ui_state('crop_active_batch');self.assertFalse(state.get('finished',False));self.assertEqual(ids,state['ids'])

 def test_finished_training_flag_cannot_disable_a_new_unfinished_landmark_batch(self):
  from app.ui.landmarks_section import LandmarksSection
  image=self.project.catalog_rows()[0]['image_id'];messages=[]
  self.project.set_ui_state('landmark_ai_workflow',{'stage':'MODEL_IMPROVEMENT','improvement_image_ids':[image],'finite_editing_complete':True})
  view=SimpleNamespace(context=SimpleNamespace(project=self.project,current=lambda:{'image_id':image}),canvas=SimpleNamespace(state=SimpleNamespace(complete=False,unresolved_ids={1,2})),_inline_status=messages.append)
  self.assertTrue(LandmarksSection.navigate_training_batch(view,1))
  self.assertTrue(messages);self.assertFalse(self.project.get_ui_state('landmark_ai_workflow').get('finite_editing_complete',False))


class ThirdTkTests(unittest.TestCase):
 setUp=tk_fixtures.FinalTkHardeningTests.setUp
 make_shell=tk_fixtures.FinalTkHardeningTests.make_shell

 def widgets(self,parent):
  for child in parent.winfo_children():yield child;yield from self.widgets(child)

 def test_orientation_has_only_fish_and_no_reference_selector(self):
  from app.modules.xray_counts import OrientationSetupDialog
  shell,errors=self.make_shell();dialog=OrientationSetupDialog(shell);shell.update()
  texts=[str(w.cget('text')) for w in self.widgets(dialog) if 'text' in w.keys()]
  self.assertNotIn('Reference example:',texts);self.assertNotIn('Radial object',texts)
  self.assertEqual(1,len(dialog.preview.find_withtag('orientation_reference')));dialog.destroy()

 def test_schema_save_commits_current_input_and_preserves_quoted_names_categories(self):
  from app.schema_editor import SchemaEditor
  import tkinter as tk
  from tkinter import ttk
  shell,errors=self.make_shell();path=self.root/'entry_scheme.csv';path.write_text('id,abbr,name,role,category\n1,A,Alpha,BOTH,head\n',encoding='utf-8')
  editor=SchemaEditor(shell,path);shell.update();editor.rows[0]['name']='Name; with, "quotes"';editor.scheme_name.set('Named scheme')
  entry=ttk.Entry(editor.table);entry.insert(0,'Z');editor._editor=entry;editor._editor_row=0;editor._editor_key='abbr'
  editor.delimiter=';';self.assertTrue(editor.save());rows=load_schema(path)
  self.assertEqual('Z',rows[0]['abbr']);self.assertEqual('Name; with, "quotes"',rows[0]['name']);self.assertEqual('head',rows[0]['category'])
  self.assertTrue(path.read_text(encoding='utf-8').startswith('# SCHEMA_NAME=Named scheme\n'))
  editor.destroy()

 def test_scheme_and_measurement_tables_have_horizontal_scroll(self):
  from app.schema_editor import SchemaEditor
  from app.measurements_ui import MeasurementsWindow
  shell,errors=self.make_shell();editor=SchemaEditor(shell,self.landmark.schema_path);manager=MeasurementsWindow(shell,self.landmark);shell.update()
  for dialog in (editor,manager):
   horizontal=[w for w in self.widgets(dialog) if w.winfo_class()=='TScrollbar' and str(w.cget('orient'))=='horizontal']
   self.assertTrue(horizontal,dialog.title())
  editor.destroy();manager.destroy()

 def test_historical_measurements_remain_visible_in_manager(self):
  from app.measurements_ui import MeasurementsWindow
  from app.measurements import save_measurements
  shell,errors=self.make_shell();project=self.landmark
  save_measurements(project,[{'use':True,'abbr':'VISIBLE','name':'Visible','point1':1,'point2':2}])
  path=project.root/'measurement_schema.csv';path.write_text(path.read_text(encoding='utf-8')+'1,HIST,Retained history,1,99,A,REMOVED\n',encoding='utf-8')
  dialog=MeasurementsWindow(shell,project);shell.update();values=[dialog.tree.item(item,'values') for item in dialog.tree.get_children()]
  historical=next(row for row in values if row[1]=='HIST');self.assertIn('Unavailable',historical[4]);self.assertEqual('!',historical[0]);dialog.destroy()

 def test_project_model_cards_stay_visible_with_an_incompatible_saved_landmark_model(self):
  from app.project_storage import Project
  shell,errors=self.make_shell();runtime=shell._active_module_runtime;project=self.landmark
  project.register_model('incompatible_saved','landmark',path='models/saved',active=True)
  path=self.root/'other_schema.csv';path.write_text('id,abbr,name,role\n1,DIFFERENT,Different,BOTH\n',encoding='utf-8');project.apply_landmark_schema(path)
  runtime._attach_project(project);shell.update()
  texts=[str(w.cget('text')) for w in self.widgets(runtime.section_host) if 'text' in w.keys()]
  self.assertIn('Crop model',texts);self.assertIn('Landmark model',texts);self.assertTrue(any('incompatible_saved' in text for text in texts));self.assertEqual([],errors)
  with patch('app.modules.landmarks.filedialog.askopenfilename',return_value='') as dialog:
   runtime._import_model('landmark');self.assertEqual('landmarks_incompatible_saved.zip',dialog.call_args.kwargs['initialfile'])
  with self.assertRaisesRegex(ValueError,'identities/order do not match'):project.active_model_readonly('landmark')

 def test_inline_schema_input_stays_inside_table_at_narrow_width_and_multiple_scales(self):
  from app.schema_editor import SchemaEditor
  shell,errors=self.make_shell();editor=SchemaEditor(shell,self.landmark.schema_path);editor.geometry('680x420');editor.deiconify();shell.update()
  for scale in (1,1.25,1.5):
   shell.tk.call('tk','scaling',scale*96/72);shell.update();row=editor.table.get_children()[0];editor.table.see(row);editor.table.xview_moveto(1);shell.update()
   box=editor.table.bbox(row,'name');self.assertTrue(box)
   x=max(5,box[0]+5);event=SimpleNamespace(x=x,y=box[1]+box[3]//2)
   editor.edit_cell(event);shell.update();entry=editor._editor;self.assertIsNotNone(entry)
   self.assertLessEqual(entry.winfo_x()+entry.winfo_width(),editor.table.winfo_width())
   entry.delete(0,'end');entry.insert(0,'Long landmark name, with visible input '+('x'*90));editor.close_editor()
  editor.destroy();self.assertEqual([],errors)

 def test_measurements_workflow_has_two_steps_and_project_add_save_actions(self):
  shell,errors=self.make_shell();runtime=shell._active_module_runtime;runtime.select('measurements');shell.update()
  titles=[str(w.tab(i,'text')) for w in self.widgets(runtime.section_host) if w.winfo_class()=='TNotebook' for i in w.tabs()]
  self.assertFalse(any('Review and export' in x for x in titles))
  runtime.select('project');shell.update()
  definitions=next(w for w in self.widgets(runtime.section_host) if w.winfo_class()=='TLabelframe' and w.cget('text')=='Measurement definitions')
  texts=[w.cget('text') for w in self.widgets(definitions) if w.winfo_class()=='TButton']
  self.assertIn('+ Add',texts);self.assertIn('Save…',texts)

 def test_photo_creation_runs_off_tk_with_live_progress_and_file_status(self):
  import threading,time
  from app.project_storage import Project
  shell,errors=self.make_shell();shell.deiconify();runtime=shell._active_module_runtime
  entered=threading.Event();release=threading.Event();finished=threading.Event();threads=[];scan=Project.scan_originals
  def slow(project,*args,**kwargs):
   threads.append(threading.get_ident());entered.set();release.wait(5);result=scan(project,*args,**kwargs);finished.set();return result
  try:
   with patch('app.modules.landmarks.simpledialog.askstring',return_value='live_photo'),patch('app.modules.landmarks.filedialog.askdirectory',side_effect=[str(self.landmark.source_root),str(self.root)]),patch.object(runtime,'_source_layout',return_value=('direct','')),patch.object(Project,'scan_originals',slow):
    runtime.new_project();self.assertTrue(entered.wait(10));shell.update()
    self.assertNotEqual(threading.get_ident(),threads[0]);self.assertTrue(any(w.winfo_class()=='TProgressbar' for w in self.widgets(shell)))
    release.set();deadline=time.monotonic()+7
    while any(w.winfo_class()=='TProgressbar' for w in self.widgets(shell)) and time.monotonic()<deadline:shell.update();time.sleep(.01)
    self.assertTrue(finished.is_set());self.assertEqual('live_photo',runtime.project.root.name);self.assertEqual([],errors)
  finally:release.set()

 def test_human_repeatability_tab_clicks_and_structure_launcher_opens_without_verified_data(self):
  shell,errors=self.make_shell();shell.deiconify();runtime=shell._active_module_runtime;runtime.select('landmarks');shell.update()
  notebook=next(w for w in self.widgets(runtime.section_host) if w.winfo_class()=='TNotebook')
  notebook.select(0);shell.update();self.assertEqual(0,notebook.index('current'))
  button=next(w for w in self.widgets(runtime.section_host) if w.winfo_class()=='TButton' and w.cget('text')=='Human Repeatability…')
  self.assertNotIn('disabled',button.state());button.invoke();shell.update()
  dialogs=[w for w in shell.winfo_children() if w.winfo_class()=='Toplevel' and w.title()=='Human repeatability'];self.assertTrue(dialogs)
  for dialog in dialogs:dialog.destroy()
  shell.open_module('xray_counts');shell.update();runtime=shell._active_module_runtime;runtime._select('structures');shell.update()
  workspace=runtime._workspace;workspace.project.annotation_summary=lambda *args,**kw:{'verified':0,'draft':0,'unstarted':0}
  workspace._refresh_workflow();self.assertNotIn('disabled',workspace.repeat_button.state())
  workspace.repeat_button.invoke();shell.update();self.assertTrue(any(w.winfo_class()=='Toplevel' and w.title()=='Human repeatability' for w in shell.winfo_children()))
  self.assertEqual([],errors)
