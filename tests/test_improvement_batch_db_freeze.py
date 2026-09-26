import shutil, sqlite3, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from app.project_storage import Project, schema_hash
from app.editor_ready_v15 import ReadyEditorV15

class _Window:
 def title(self,*args): pass
 def transient(self,*args): pass
 def resizable(self,*args): pass
 def winfo_exists(self): return True
 def destroy(self): pass
class _Label:
 def __init__(self,*args,**kwargs): pass
 def pack(self): pass
class _Value:
 def __init__(self,value='',master=None): self.value=value
 def set(self,value): self.value=value
class _Status:
 def __init__(self): self.values=[]
 def config(self,**kwargs): self.values.append(kwargs.get('text'))
class _Thread:
 def __init__(self,target,**kwargs): self.target=target
 def start(self): self.target()

class ImprovementBatchDbFreezeTests(unittest.TestCase):
 def setUp(self):
  self.temp=Path(tempfile.mkdtemp());source=self.temp/'source';source.mkdir();(source/'a.jpg').write_bytes(b'image');schema=self.temp/'schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n',encoding='utf8')
  self.project=Project.create('p',source,self.temp,schema,source_layout='direct');self.project.register_model('m','landmark',path='ai/models/m',active=True,schema_digest=schema_hash(self.project.schema_path))
 def tearDown(self): shutil.rmtree(self.temp,ignore_errors=True)
 def test_01_gui_defers_db_lookup_until_worker_starts_and_reaches_selection(self):
  editor=ReadyEditorV15.__new__(ReadyEditorV15);editor.project=self.project;editor.status=_Status();editor.after=lambda _delay,callback:callback();editor._refresh_landmark_ai_panel=lambda:None;editor._set_landmark_workflow_controls=lambda:None;editor.continue_landmark_ai=lambda:None
  calls=[]
  original=self.project.active_model_readonly
  def readonly(kind): calls.append('readonly');return original(kind)
  self.project.active_model_readonly=readonly
  info={'stage':'READY_FOR_FULL_PREDICTION','state':{'seed':5,'control_image_ids':[],'initial_image_ids':[],'improvement_history_ids':[],'improvement_image_ids':[]}}
  result={'selected_images':[],'weak_landmark_ids':[]}
  with patch('app.editor_ready_v15.stage_summary',return_value=info),patch('app.editor_ready_v15.simpledialog.askinteger',return_value=10),patch('app.editor_ready_v15.tk.Toplevel',return_value=_Window()),patch('app.editor_ready_v15.tk.StringVar',side_effect=_Value),patch('app.editor_ready_v15.ttk.Label',_Label),patch('app.editor_ready_v15.threading.Thread',_Thread),patch('app.editor_ready_v15.create_improvement_selection',side_effect=lambda *args,**kwargs:(calls.append('selection') or (result,self.project.data_root/'ai/selections/selection.json',None))),patch('app.editor_ready_v15.begin_improvement'):
   editor.new_improvement_batch()
  self.assertEqual(calls,['readonly','selection']);self.assertEqual(editor.status.values[0],'Preparing candidate pool...')
 def test_02_readonly_lookup_uses_readonly_uri_and_no_journal_pragma(self):
  calls=[];connections=[];original=sqlite3.connect
  def connect(*args,**kwargs):
   connections.append((args,kwargs));conn=original(*args,**kwargs);conn.set_trace_callback(calls.append);return conn
  with patch('app.project_storage.sqlite3.connect',side_effect=connect): model=self.project.active_model_readonly('landmark')
  self.assertEqual(model['model_id'],'m');self.assertIn('mode=ro',connections[0][0][0]);self.assertTrue(connections[0][1]['uri']);self.assertTrue(any('SELECT * FROM models' in query for query in calls));self.assertFalse(any('journal_mode' in query.lower() for query in calls))
 def test_03_locked_writer_does_not_block_readonly_active_model(self):
  writer=sqlite3.connect(self.project.path);writer.execute('BEGIN IMMEDIATE')
  try:
   started=time.monotonic();model=self.project.active_model_readonly('landmark');elapsed=time.monotonic()-started
  finally: writer.rollback();writer.close()
  self.assertEqual(model['model_id'],'m');self.assertLess(elapsed,1)

 def test_04_worker_never_calls_tk_after(self):
  import threading
  real_thread=threading.Thread;started=[];after_calls=[]
  class AsyncThread:
   def __init__(self,target,**kwargs): self.inner=real_thread(target=target,daemon=True);started.append(self)
   def start(self): self.inner.start()
  editor=ReadyEditorV15.__new__(ReadyEditorV15);editor.project=self.project;editor.status=_Status();editor.after=lambda _delay,callback:after_calls.append((threading.current_thread().name,callback));editor._refresh_landmark_ai_panel=lambda:None;editor._set_landmark_workflow_controls=lambda:None;editor.continue_landmark_ai=lambda:None
  info={'stage':'READY_FOR_FULL_PREDICTION','state':{'seed':5,'control_image_ids':[],'initial_image_ids':[],'improvement_history_ids':[],'improvement_image_ids':[]}};result={'selected_images':[],'weak_landmark_ids':[]}
  def selection(*args,**kwargs):
   kwargs['progress_callback']('SCORING',0,2);kwargs['progress_callback']('SCORING',2,2);kwargs['progress_callback']('SELECTING',0,0);return result,self.project.data_root/'ai/selections/selection.json',None
  with patch('app.editor_ready_v15.stage_summary',return_value=info),patch('app.editor_ready_v15.simpledialog.askinteger',return_value=10),patch('app.editor_ready_v15.tk.Toplevel',return_value=_Window()),patch('app.editor_ready_v15.tk.StringVar',side_effect=_Value),patch('app.editor_ready_v15.ttk.Label',_Label),patch('app.editor_ready_v15.threading.Thread',AsyncThread),patch('app.editor_ready_v15.create_improvement_selection',side_effect=selection),patch('app.editor_ready_v15.begin_improvement'):
   editor.new_improvement_batch();started[0].inner.join(timeout=1)
   self.assertFalse(started[0].inner.is_alive());self.assertEqual([name for name,_ in after_calls],['MainThread'])
   after_calls.pop()[1]()
  self.assertEqual(editor.status.values[0],'Preparing candidate pool...')
 def test_05_improvement_selection_reuses_read_model(self):
  from app.ai_batch import active_backend
  model={'model_id':'m','kind':'landmark','schema_sha256':schema_hash(self.project.schema_path),'path':'ai/models/m','active':True}
  with patch('app.ai_batch.backend_for_model',return_value=(model,'backend')) as make:
   def fail(*args,**kwargs): raise AssertionError('normal active_model lookup used')
   self.project.active_model=fail
   resolved,backend=active_backend(self.project,model=model)
  self.assertEqual('m',resolved['model_id']);make.assert_called_once_with(self.project,'m',model=model)
 def test_06_create_selection_reaches_candidate_pool_with_supplied_model(self):
  import app.smart_selection as selection
  model={'model_id':'m','kind':'landmark','schema_sha256':schema_hash(self.project.schema_path),'path':'ai/models/m','active':True};reached=[]
  class Stop(Exception): pass
  def pool(*args,**kwargs): reached.append(True);raise Stop()
  with patch.object(selection,'active_backend',return_value=(model,'backend')),patch.object(selection,'_readonly_selection_snapshot',return_value={'human_descriptors':()}),patch.object(selection,'_candidate_pool_from_snapshot',side_effect=pool):
   with self.assertRaises(Stop):selection.create_improvement_selection(self.project,'m',count=10,active_model=model)
  self.assertEqual([True],reached)
 def test_07_candidate_snapshot_is_readonly_while_writer_lock_is_held(self):
  import app.smart_selection as selection
  writer=sqlite3.connect(self.project.path);writer.execute('BEGIN IMMEDIATE')
  try:
   started=time.monotonic();snapshot=selection._readonly_selection_snapshot(self.project);elapsed=time.monotonic()-started
  finally: writer.rollback();writer.close()
  self.assertLess(elapsed,1);self.assertIn('rows',snapshot);self.assertIn('annotated',snapshot)
if __name__=='__main__': unittest.main()