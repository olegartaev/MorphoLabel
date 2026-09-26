import shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app.project_storage import Project
from app.operator_qc import set_repeat_landmark, complete_repeat_session, create_repeat_session, blind_session_input
from app.human_baseline import ensure_baseline_set, start_or_continue_run, complete_run, grade_ratio, ensure_pass, pass_session_ids, abandon_run, current_run, previous_runs, reset_pass, available_control_image_ids, comparison_for_model, complete_pass, record_repeatability_pass_qc, latest_completed_report, invalidate_runs_for_excluded_image, repeatability_report_state
from app.human_baseline_ui import HumanBaselineWindow
from app.landmark_qc import persist_control_landmark_quality_profile, stored_control_landmark_quality_profile
from app.project_storage import schema_hash

class HumanBaselineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());src=self.tmp/'src';src.mkdir();self.schema=self.tmp/'schema.csv';self.schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8');self.p=Project.create('p',src,self.tmp,self.schema,source_layout='direct')
  self.ids=[]
  for n in range(12):
   image_id=f'i{n}';self.p._insert_image(image_id,str(src/f'{n}.jpg'),f'{n}.jpg','x',1,1,'s',None) if False else None
  # Use real catalogue IDs created by Project; create standardized/manual records for them.
  self.ids=[r['image_id'] for r in self.p.catalog_rows()]
 def tearDown(self): shutil.rmtree(self.tmp,ignore_errors=True)
 def test_grade_thresholds(self):
  self.assertEqual(grade_ratio(1.1),'Within manual repeatability');self.assertEqual(grade_ratio(1.25),'Very close to manual');self.assertEqual(grade_ratio(1.5),'Close to manual');self.assertEqual(grade_ratio(2),'Needs improvement');self.assertEqual(grade_ratio(2.01),'Clearly worse than manual')
 def test_repeatability_pool_prefers_controls_then_fills_from_other_human_images(self):
  std=self.p.cache_root/'standardized';std.mkdir(parents=True,exist_ok=True)
  for image_id in ('a','b','x'):Image.new('RGB',(8,8),'white').save(std/f'{image_id}.png')
  with patch('app.landmark_ai_workflow.control_set_summary',return_value={'current_ids':['a','b','c']}),patch('app.operator_qc.operator_eligible_image_ids',return_value=('a','b','x')):
   available=available_control_image_ids(self.p)
   first=ensure_baseline_set(self.p);second=ensure_baseline_set(self.p)
  self.assertEqual(('a','b','x'),available)
  self.assertEqual(first['image_ids'],('a','b','x'));self.assertEqual(second['image_ids'],('a','b','x'))
 def test_new_repeatability_run_uses_requested_sample_size(self):
  source=self.tmp/'count_source';(source/'sample').mkdir(parents=True)
  for name in ('a','b','c'):Image.new('RGB',(32,24),'white').save(source/'sample'/f'{name}.jpg')
  schema=self.tmp/'count_schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8')
  project=Project.create('count',source,self.tmp/'count_project',schema,source_layout='direct')
  ids=[row['image_id'] for row in project.catalog_rows()]
  std=project.cache_root/'standardized';std.mkdir(parents=True,exist_ok=True)
  for image_id in ids:
   Image.new('RGB',(32,24),'white').save(std/f'{image_id}.png')
   project.save_landmark(image_id,1,8,8,'manual','manual');project.save_landmark(image_id,2,20,14,'manual','manual')
  with patch('app.human_baseline.available_control_image_ids',return_value=tuple(ids)):
   run,_=start_or_continue_run(project,count=2)
  self.assertEqual(2,run['actual_count']);self.assertEqual(2,len(run['image_ids']))

 def test_repeatability_survives_name_only_schema_edit_but_detects_identity_change(self):
  source=self.tmp/'rename_source';(source/'sample').mkdir(parents=True);Image.new('RGB',(32,24),'white').save(source/'sample'/'a.jpg')
  schema=self.tmp/'rename_schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8')
  project=Project.create('rename',source,self.tmp/'rename_project',schema,source_layout='direct');image_id=project.catalog_rows()[0]['image_id']
  standard=project.cache_root/'standardized'/f'{image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(32,24),'white').save(standard)
  project.save_landmark(image_id,1,8,8,'manual','manual');project.save_landmark(image_id,2,20,14,'manual','manual')
  with patch('app.human_baseline.available_control_image_ids',return_value=(image_id,)):
   run,_=start_or_continue_run(project,count=1)
  first=pass_session_ids(run,1)[0]
  project.schema_path.write_text('id,abbr,name,role\n1,A,Renamed one,GM\n2,B,Renamed two,BOTH\n',encoding='utf8')
  self.assertFalse(blind_session_input(project,first)['schema_changed'])
  for ident in (1,2):set_repeat_landmark(project,first,ident,ident*5,ident*6)
  complete_repeat_session(project,first);complete_pass(project,run['run_id'],1);record_repeatability_pass_qc(project,run['run_id'],1,())
  updated,second=ensure_pass(project,run['run_id'],2)
  self.assertEqual(1,len(second));self.assertEqual(['A','B'],updated['schema_identity'])
  project.schema_path.write_text('id,abbr,name,role\n1,B,Two,BOTH\n2,A,One,BOTH\n',encoding='utf8')
  self.assertTrue(blind_session_input(project,first)['schema_changed'])

 def test_completed_repeatability_report_survives_name_edit_but_not_identity_change(self):
  source=self.tmp/'report_source';(source/'sample').mkdir(parents=True);Image.new('RGB',(32,24),'white').save(source/'sample'/'a.jpg')
  schema=self.tmp/'report_schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8')
  project=Project.create('report',source,self.tmp/'report_project',schema,source_layout='direct');image_id=project.catalog_rows()[0]['image_id']
  standard=project.cache_root/'standardized'/f'{image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(32,24),'white').save(standard)
  project.save_landmark(image_id,1,8,8,'manual','manual');project.save_landmark(image_id,2,20,14,'manual','manual')
  session=create_repeat_session(project,image_id,eligibility_prevalidated=True)
  from app.human_baseline import _save_runs,_root
  report_path=_root(project)/'report.json';report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text('{"sentinel":1}',encoding='utf8')
  _save_runs(project,{'format_version':2,'runs':[{'format_version':2,'run_id':'r','status':'completed','image_ids':[image_id],'passes':{'1':{'session_ids':[session['repeat_session_id']]}},'session_ids':[session['repeat_session_id']],'schema_sha256':schema_hash(project.schema_path),'report_path':'report.json','report_stale':False}]})
  project.schema_path.write_text('id,abbr,name,role\n1,A,Renamed one,GM\n2,B,Renamed two,BOTH\n',encoding='utf8')
  self.assertEqual(1,latest_completed_report(project)['sentinel'])
  project.schema_path.write_text('id,abbr,name,role\n1,B,Two,BOTH\n2,A,One,BOTH\n',encoding='utf8')
  self.assertIsNone(latest_completed_report(project))

 def test_completed_repeatability_recovers_identity_from_second_pass_when_first_is_legacy(self):
  source=self.tmp/'mixed_identity_source';(source/'sample').mkdir(parents=True);Image.new('RGB',(32,24),'white').save(source/'sample'/'a.jpg')
  schema=self.tmp/'mixed_identity_schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8')
  project=Project.create('mixed-identity',source,self.tmp/'mixed_identity_project',schema,source_layout='direct');image_id=project.catalog_rows()[0]['image_id']
  standard=project.cache_root/'standardized'/f'{image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(32,24),'white').save(standard)
  for ident in (1,2):project.save_landmark(image_id,ident,ident*4,ident*3,'manual','manual')
  old_sha=schema_hash(project.schema_path)
  first=create_repeat_session(project,image_id,eligibility_prevalidated=True)
  from app.operator_qc import _load,_save
  first_payload=_load(project,first['repeat_session_id']);first_payload.pop('schema',None);_save(project,first['repeat_session_id'],first_payload)
  project.schema_path.write_text('id,abbr,name,role\n1,A,Renamed one,GM\n2,B,Renamed two,BOTH\n',encoding='utf8')
  second=create_repeat_session(project,image_id,eligibility_prevalidated=True)
  from app.human_baseline import _save_runs,_root
  report_path=_root(project)/'mixed_report.json';report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text('{"sentinel":2,"run_id":"mixed-run"}',encoding='utf8')
  _save_runs(project,{'format_version':2,'runs':[{'format_version':2,'run_id':'mixed-run','status':'completed','image_ids':[image_id],'passes':{'1':{'session_ids':[first['repeat_session_id']]},'2':{'session_ids':[second['repeat_session_id']]}},'session_ids':[first['repeat_session_id']],'schema_sha256':old_sha,'report_path':'mixed_report.json','report_stale':False}]})
  self.assertEqual(2,latest_completed_report(project)['sentinel'])
  project.schema_path.write_text('id,abbr,name,role\n1,B,Two,BOTH\n2,A,One,BOTH\n',encoding='utf8')
  self.assertIsNone(latest_completed_report(project))

 def test_completed_legacy_first_pass_migrates_to_real_second_pass(self):
  source=self.tmp/'legacy_source';(source/'sample').mkdir(parents=True);Image.new('RGB',(32,24),'white').save(source/'sample'/'a.jpg')
  schema=self.tmp/'legacy_schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8')
  project=Project.create('legacy',source,self.tmp/'legacy_project',schema,source_layout='direct');image_id=project.catalog_rows()[0]['image_id']
  standard=project.cache_root/'standardized'/f'{image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(32,24),'white').save(standard)
  for ident in (1,2):project.save_landmark(image_id,ident,ident*4,ident*3,'manual','manual')
  first=create_repeat_session(project,image_id,eligibility_prevalidated=True)
  for ident in (1,2):set_repeat_landmark(project,first['repeat_session_id'],ident,ident*4,ident*3)
  complete_repeat_session(project,first['repeat_session_id'])
  from app.human_baseline import _save_runs
  _save_runs(project,{'format_version':1,'runs':[{'format_version':1,'run_id':'legacy-run','status':'in_progress','image_ids':[image_id],'session_ids':[first['repeat_session_id']]}]})
  with self.assertRaisesRegex(ValueError,"Annotation 1 point check"):
   ensure_pass(project,'legacy-run',2)
  migrated=previous_runs(project)[-1]
  self.assertEqual(2,migrated['format_version']);self.assertEqual([first['repeat_session_id']],list(pass_session_ids(migrated,1)))
  record_repeatability_pass_qc(project,'legacy-run',1,())
  migrated,second=ensure_pass(project,'legacy-run',2)
  self.assertEqual(1,len(second));self.assertNotEqual(first['repeat_session_id'],second[0])
 def test_repeatability_window_close_notifies_parent_state(self):
  events=[]
  class Fake:
   edit_completed=False
   on_review_closed=None
   on_state_changed=lambda self:events.append('changed')
   _notify_state_changed=HumanBaselineWindow._notify_state_changed
   def destroy(self):events.append('destroyed')
  fake=Fake();HumanBaselineWindow.close_window(fake)
  self.assertEqual(['changed','destroyed'],events)

 def test_previous_reopens_completed_prior_repeat_image(self):
  source=self.tmp/'previous_source';(source/'sample').mkdir(parents=True)
  for name in ('a','b'):Image.new('RGB',(32,24),'white').save(source/'sample'/f'{name}.jpg')
  schema=self.tmp/'previous_schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8')
  project=Project.create('previous',source,self.tmp/'previous_project',schema,source_layout='direct')
  ids=[row['image_id'] for row in project.catalog_rows()]
  std=project.cache_root/'standardized';std.mkdir(parents=True,exist_ok=True)
  for image_id in ids:
   Image.new('RGB',(32,24),'white').save(std/f'{image_id}.png')
   project.save_landmark(image_id,1,8,8,'manual','manual');project.save_landmark(image_id,2,20,14,'manual','manual')
  with patch('app.human_baseline.available_control_image_ids',return_value=tuple(ids)):
   run,_=start_or_continue_run(project,count=2)
  sessions=pass_session_ids(run,1);first=sessions[0]
  for ident in (1,2):set_repeat_landmark(project,first,ident,ident*5,ident*6)
  complete_repeat_session(project,first)
  class Fake:
   index=1
   edit_completed=False
   session_ids=list(sessions)
   def __init__(self):self.project=project;self.loaded=False
   def load(self):self.loaded=True
  fake=Fake();HumanBaselineWindow.previous(fake)
  self.assertEqual(0,fake.index);self.assertTrue(fake.loaded)
  from app.operator_qc import _load
  self.assertEqual('in_progress',_load(project,first)['status'])

 def test_reset_pass_replaces_sessions_but_keeps_audit_history(self):
  source=self.tmp/'reset_source';(source/'sample').mkdir(parents=True);Image.new('RGB',(32,24),'white').save(source/'sample'/'a.jpg')
  schema=self.tmp/'reset_schema.csv';schema.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n',encoding='utf8')
  project=Project.create('reset',source,self.tmp/'reset_project',schema,source_layout='direct');image_id=project.catalog_rows()[0]['image_id']
  standard=project.cache_root/'standardized'/f'{image_id}.png';standard.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(32,24),'white').save(standard)
  for ident in (1,2):project.save_landmark(image_id,ident,ident*4,ident*3,'manual','manual')
  with patch('app.human_baseline.available_control_image_ids',return_value=(image_id,)):
   run,_=start_or_continue_run(project,count=1)
  old=pass_session_ids(run,1);self.assertEqual(1,len(old))
  run,new=reset_pass(project,run['run_id'],1)
  self.assertEqual(1,len(new));self.assertNotEqual(old,new)
  self.assertEqual(list(old),list(run['history'][-1]['session_ids']))
  self.assertEqual(1,run['history'][-1]['pass'])

 def test_superseded_run_remains_auditable_and_is_no_longer_current(self):
  from app.human_baseline import _save_runs
  _save_runs(self.p,{"format_version":2,"runs":[{"format_version":2,"run_id":"old","status":"in_progress","image_ids":["x"],"passes":{}}]})
  retired=abandon_run(self.p,"old")
  self.assertEqual("abandoned",retired["status"]);self.assertEqual("superseded_by_new_run",retired["abandoned_reason"])
  self.assertIsNone(current_run(self.p));self.assertEqual("old",previous_runs(self.p)[0]["run_id"])

 def test_excluding_repeatability_image_preserves_history_but_invalidates_reference(self):
  from app.human_baseline import _save_runs,_root
  report_path=_root(self.p)/'exclude_report.json';report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text('{"run_id":"r","sentinel":1}',encoding='utf8')
  _save_runs(self.p,{"format_version":2,"runs":[{"format_version":2,"run_id":"r","status":"completed","image_ids":["bad-image"],"passes":{},"report_path":"exclude_report.json","report_stale":False}]})
  self.assertEqual(1,latest_completed_report(self.p)['sentinel'])
  changed=invalidate_runs_for_excluded_image(self.p,"bad-image")
  self.assertEqual(1,changed)
  run=previous_runs(self.p)[0]
  self.assertEqual("invalidated",run["status"])
  self.assertEqual("image_excluded",run["invalidated_reason"])
  self.assertTrue(report_path.is_file())
  self.assertIsNone(latest_completed_report(self.p))
  state=repeatability_report_state(self.p)
  self.assertFalse(state["ready"]);self.assertIn("excluded",state["message"].lower())
  self.assertIn("Start a new Human repeatability sample",state["message"])

 def test_same_image_ai_human_ratio_uses_p90_repeatability(self):
  human_report={'run_id':'r','image_ids':['a','b'],'human':{'aggregate':{'median_error_percent':.4,'p90_error_percent':.5,'p95_error_percent':.7},'per_landmark':{}}}
  model={'model_id':'m','aggregate':{'median_error_percent':.44,'p90_error_percent':.59,'p95_error_percent':.77},'per_landmark':{}}
  comparison=comparison_for_model(human_report,model)
  self.assertAlmostEqual(1.18,comparison['ratios']['p90'],places=6)
  self.assertEqual('Very close to manual',comparison['grade'])

 def test_control_profile_requires_exact_repeatability_membership(self):
  result={'model_id':'m','schema_sha256':schema_hash(self.p.schema_path),'control_image_ids':('a','b'),'aggregate':{'n_images':2,'n_comparable_landmarks':4,'median_error_percent':.4,'p90_error_percent':.6,'p95_error_percent':.8},'per_landmark':{'1':{'landmark_id':1,'median_error_percent':.3,'p90_error_percent':.5}}}
  persist_control_landmark_quality_profile(self.p,result)
  current=stored_control_landmark_quality_profile(self.p,'m',image_ids=('a','b'),schema_digest=schema_hash(self.p.schema_path))
  stale=stored_control_landmark_quality_profile(self.p,'m',image_ids=('a','c'),schema_digest=schema_hash(self.p.schema_path))
  self.assertIsNotNone(current);self.assertEqual(.6,current['aggregate']['p90_error_percent']);self.assertIsNone(stale)

if __name__=='__main__':unittest.main()
