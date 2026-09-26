import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from PIL import Image

from app.human_baseline import _new_pass_sessions, _save_runs, _runs, _swap_pair_metrics, ensure_pass, complete_pass, complete_run, evaluate_human_baseline, repeatability_qc_issues, repeatability_pass_qc_issues, record_repeatability_qc, record_repeatability_pass_qc, pass_qc_complete, final_qc_complete, mark_completed_run_stale, finalize_repeatability_after_qc, finalize_repeatability_pass_qc, repeatability_next_state, finish_repeatability_pass
from app.human_baseline_ui import HumanBaselineWindow, _repeat_resolution_status, _repeat_resolution_labels, _repeat_navigation_text
from app.landmark_annotation_ui import RepeatSessionAdapter,LandmarkAnnotationSurface
from app.operator_qc import _load, _save, blind_session_input, complete_repeat_session, create_repeat_session, set_repeat_landmark, unmark_repeat_landmark, discard_repeat_session_correction, reopen_repeat_session_for_correction
from app.ui.landmarks_section import _repeatability_pass_controls, _repeatability_flagged_review_plan, _repeatability_ask_then_scan, _dispatch_repeatability_stage

ROOT = Path(__file__).parents[1]


class _FakeProject:
 def __init__(self,root,schema):
  self.data_root=Path(root);self.cache_root=self.data_root/'cache';self.schema_path=self.data_root/'schema.csv';self.schema=list(schema)
  self.schema_path.write_text('id,abbr,name,role\n1,A,One,BOTH\n2,B,Two,BOTH\n3,C,Three,BOTH\n',encoding='utf8')
 def load_landmarks(self,_image_id):
  return {row['id']:{'state':'present','x_standardized':row['id']*2.0,'y_standardized':row['id']*3.0,'provenance':'manual'} for row in self.schema}
 def active_model_readonly(self,_kind):return None


class RepeatabilityReviewUIRegressionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp())
 def tearDown(self):
  shutil.rmtree(self.tmp,ignore_errors=True)

 def test_pass_qc_scans_only_requested_annotation(self):
  calls=[]
  payload={'status':'completed','baseline':[],'repeat':[],'standardized_width':100,'standardized_height':100,'image_id':'img'}
  run={'format_version':2,'run_id':'r','image_ids':['img'],'passes':{'1':{'session_ids':['p1']},'2':{'session_ids':['p2']}}}
  with patch('app.human_baseline._load',side_effect=lambda _project,sid:(calls.append(sid) or dict(payload))):
   self.assertEqual((),repeatability_pass_qc_issues(object(),run,1))
  self.assertEqual(['p1'],calls)

 def test_human_only_repeatability_report_does_not_run_model(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  for sid,x in (('p1',10.0),('p2',11.0)):
   _save(project,sid,{'repeat_session_id':sid,'status':'completed','repeat':[{'landmark_id':1,'state':'present','x':x,'y':10.0}],'baseline':[]})
  run={'format_version':2,'run_id':'r','model_id':'expensive-model','image_ids':['img'],'passes':{'1':{'session_ids':['p1']},'2':{'session_ids':['p2']}}}
  with patch('app.landmark_qc.evaluate_control_set',side_effect=AssertionError('model inference must be deferred')):
   report=evaluate_human_baseline(project,run,include_model=False)
  self.assertTrue(report['model_deferred']);self.assertEqual({},report['model']['aggregate'])

 def test_repeat_unmark_missing_restores_previous_position(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}]);sid='restore'
  _save(project,sid,{'repeat_session_id':sid,'status':'in_progress','schema':[{'id':1}],'repeat':[{'landmark_id':1,'state':'present','x':12.0,'y':34.0}]})
  set_repeat_landmark(project,sid,1,None,None,state='missing')
  self.assertEqual('missing',_load(project,sid)['repeat'][0]['state'])
  self.assertTrue(unmark_repeat_landmark(project,sid,1))
  point=_load(project,sid)['repeat'][0];self.assertEqual('present',point['state']);self.assertEqual((12.0,34.0),(point['x'],point['y']))

 def test_completed_annotation_1_requires_point_check_before_new_annotation2(self):
  run={'run_id':'r1'}
  controls=_repeatability_pass_controls(run,{'completed':10,'total':10,'complete':True},{'completed':0,'total':0,'complete':False},60)
  self.assertEqual('Review Annotation 1',controls['one_text']);self.assertTrue(controls['one_enabled'])
  self.assertEqual('Start Annotation 2',controls['two_text']);self.assertFalse(controls['two_enabled'])
  run['pass_qc']={'1':{'checked_at':'now'}}
  checked=_repeatability_pass_controls(run,{'completed':10,'total':10,'complete':True},{'completed':0,'total':0,'complete':False},60)
  self.assertTrue(checked['two_enabled'])

 def test_completed_annotation_2_remains_enabled_for_review_after_checks(self):
  run={'run_id':'r1','status':'completed','passes':{'2':{'session_ids':['existing-p2']}},'pass_qc':{'1':{'checked_at':'now'},'2':{'checked_at':'now'}}}
  controls=_repeatability_pass_controls(run,{'completed':10,'total':10,'complete':True},{'completed':10,'total':10,'complete':True},60)
  self.assertEqual('Review Annotation 1',controls['one_text']);self.assertEqual('Review Annotation 2',controls['two_text'])
  self.assertTrue(controls['one_enabled']);self.assertTrue(controls['two_enabled'])

 def test_same_count_but_different_ids_is_not_complete(self):
  status=_repeat_resolution_status(
   ({'id':1},{'id':2},{'id':3}),
   {1:{},2:{},4:{}},
  )
  self.assertFalse(status['complete'])
  self.assertEqual({3},status['missing'])
  self.assertEqual({4},status['unexpected'])

 def test_legacy_repeat_session_uses_its_baseline_ids_after_schema_change(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'},{'id':2,'abbr':'B','name':'Two','role':'BOTH'},{'id':3,'abbr':'C','name':'Three','role':'BOTH'}])
  sid='legacy'
  _save(project,sid,{
   'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'in_progress',
   'schema_sha256':'old-scheme','standardized_relpath':'cache/standardized/img.png',
   'baseline':[{'landmark_id':1},{'landmark_id':2},{'landmark_id':4}],
   'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1},{'landmark_id':2,'state':'present','x':2,'y':2},{'landmark_id':4,'state':'present','x':4,'y':4}],
  })
  data=blind_session_input(project,sid)
  self.assertTrue(data['schema_changed'])
  self.assertEqual([1,2,4],[row['id'] for row in data['schema']])
  set_repeat_landmark(project,sid,4,8,9)
  with self.assertRaisesRegex(ValueError,'not part of this repeat session scheme'):
   set_repeat_landmark(project,sid,3,8,9)
  completed=complete_repeat_session(project,sid)
  self.assertEqual('completed',completed['status'])

 def test_confirm_advances_to_next_session_after_legacy_scheme_recovery(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'},{'id':2,'abbr':'B','name':'Two','role':'BOTH'},{'id':3,'abbr':'C','name':'Three','role':'BOTH'}])
  sid='first'
  _save(project,sid,{
   'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'in_progress',
   'schema_sha256':'old-scheme','standardized_relpath':'cache/standardized/img.png',
   'baseline':[{'landmark_id':1},{'landmark_id':2},{'landmark_id':4}],
   'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1},{'landmark_id':2,'state':'present','x':2,'y':2},{'landmark_id':4,'state':'present','x':4,'y':4}],
  })
  data=blind_session_input(project,sid)
  class Adapter:
   def points(self):return {1:{},2:{},4:{}}
  class FakeWindow:
   def __init__(self):
    self.project=project;self.sid=sid;self.schema=data['schema'];self.adapter=Adapter();self.edit_completed=False;self.session_ids=[sid,'second'];self.index=0;self.loaded=False
   def _notify_state_changed(self):pass
   def load(self):self.loaded=True
  fake=FakeWindow();HumanBaselineWindow.confirm(fake)
  self.assertEqual(1,fake.index);self.assertTrue(fake.loaded);self.assertEqual('completed',_load(project,sid)['status'])

 def test_review_next_browses_untouched_completed_session_without_reopening(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  sid='done'
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'completed','completed_at':'now','baseline':[{'landmark_id':1}],'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1}]})
  class Adapter:
   def points(self):return {1:{'landmark_id':1,'state':'present','x':1,'y':1}}
  class FakeWindow:
   _save_review_current=HumanBaselineWindow._save_review_current
   def __init__(self):
    self.project=project;self.sid=sid;self.schema=[{'id':1}];self.adapter=Adapter();self.edit_completed=True;self.session_ids=[sid,'next'];self.index=0;self.loaded=False
   def _notify_state_changed(self):pass
   def load(self):self.loaded=True
  fake=FakeWindow();HumanBaselineWindow.confirm(fake)
  self.assertEqual('completed',_load(project,sid)['status'])
  self.assertEqual(1,fake.index);self.assertTrue(fake.loaded)

 def test_review_edit_reopens_only_on_change_then_saves_on_next(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  sid='done-edit'
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'completed','completed_at':'now','baseline':[{'landmark_id':1}],'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1}]})
  events=[]
  class FakeWindow:
   _ensure_current_editable=HumanBaselineWindow._ensure_current_editable
   _after_current_edit=HumanBaselineWindow._after_current_edit
   _save_review_current=HumanBaselineWindow._save_review_current
   def __init__(self):
    self.project=project;self.sid=sid;self.schema=[{'id':1}];self.edit_completed=True;self._dirty=False;self.on_review_modified=lambda:events.append('modified');self.on_review_saved=lambda:events.append('saved')
   def _notify_state_changed(self):events.append('state')
   def _update_navigation(self):pass
  fake=FakeWindow();adapter=RepeatSessionAdapter(project,sid,lambda:'',before_edit=fake._ensure_current_editable,after_edit=fake._after_current_edit);fake.adapter=adapter
  self.assertEqual('completed',_load(project,sid)['status'])
  adapter.place(1,5,6)
  self.assertEqual('in_progress',_load(project,sid)['status']);self.assertEqual(5,_load(project,sid)['repeat'][0]['x'])
  self.assertEqual(['modified','state'],events)
  self.assertTrue(fake._save_review_current())
  self.assertEqual('completed',_load(project,sid)['status']);self.assertEqual(['modified','state','saved','state'],events)

 def test_review_previous_browses_without_reopening_completed_target(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  for sid in ('one','two'):
   _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':sid,'status':'completed','completed_at':'now','baseline':[{'landmark_id':1}],'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1}]})
  class FakeWindow:
   _save_review_current=HumanBaselineWindow._save_review_current
   previous=HumanBaselineWindow.previous
   def __init__(self):
    self.project=project;self.sid='two';self.schema=[{'id':1}];self.adapter=type('Adapter',(),{'points':lambda _self:{1:{}}})();self.edit_completed=True;self.session_ids=['one','two'];self.index=1;self.loaded=False
   def load(self):self.loaded=True;self.sid=self.session_ids[self.index]
   def _notify_state_changed(self):pass
  fake=FakeWindow();fake.previous()
  self.assertEqual(0,fake.index);self.assertTrue(fake.loaded)
  self.assertEqual('completed',_load(project,'one')['status']);self.assertEqual('completed',_load(project,'two')['status'])

 def test_unresolved_landmark_message_names_exact_point(self):
  schema=[{'id':24,'abbr':'AnHtTip','name':'Anal height tip','role':'CLASS'},{'id':25,'abbr':'CauUTip','name':'Upper caudal tip','role':'CLASS'}]
  status=_repeat_resolution_status(schema,{24:{'state':'present'}})
  self.assertEqual(('LM25 CauUTip — Upper caudal tip',),_repeat_resolution_labels(schema,status))

 def test_unresolved_landmark_does_not_silently_disable_next(self):
  source=(ROOT/'app'/'human_baseline_ui.py').read_text(encoding='utf8')
  self.assertNotIn("self.confirm_button.configure(state='normal' if status['complete'] else 'disabled')",source)
  self.assertIn("self.confirm_button.configure(state='normal')",source)
  self.assertIn("try:self.confirm()",source)
  self.assertIn("Place each unresolved landmark or use Mark as missing.",source)

 def test_repeat_surface_drag_persists_only_once_on_release(self):
  calls=[]
  class Adapter:
   def place(self,ident,x,y):calls.append(('place',ident,x,y))
   def points(self):return {18:{'landmark_id':18,'state':'present','x':30.0,'y':40.0}}
   def finish_drag(self,ident):calls.append(('finish',ident))
  surface=LandmarkAnnotationSurface.__new__(LandmarkAnnotationSurface)
  surface.adapter=Adapter();surface.dragging=18;surface.drag_pending=(10.0,20.0);surface.points={18:{'landmark_id':18,'state':'present','x':10.0,'y':20.0}}
  surface.image_point=lambda x,y:(float(x),float(y));surface.render=lambda:None
  event=type('Event',(),{'x':30,'y':40})()
  surface.left_drag(event);self.assertEqual([],calls)
  surface.left_up(event)
  self.assertEqual([('place',18,30.0,40.0),('finish',18)],calls)

 def test_repeat_missing_toggle_restores_landmark_to_unresolved(self):
  calls=[]
  class Adapter:
   data={5:{'landmark_id':5,'state':'missing','x':None,'y':None}}
   def points(self):return dict(self.data)
   def remove(self,ident):calls.append(('remove',ident));self.data.pop(ident,None)
   def missing(self,ident):calls.append(('missing',ident));self.data[ident]={'landmark_id':ident,'state':'missing','x':None,'y':None}
   def selected(self,ident):calls.append(('selected',ident))
  surface=LandmarkAnnotationSurface.__new__(LandmarkAnnotationSurface)
  surface.adapter=Adapter();surface.current=5;surface.points=surface.adapter.points();surface.schema=({'id':5},);surface.render=lambda:None
  surface.toggle_missing()
  self.assertEqual({},surface.points);self.assertEqual(5,surface.current);self.assertIn(('remove',5),calls)

 def test_review_unresolved_edit_blocks_leaving_image(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'},{'id':2,'abbr':'B','name':'Two','role':'BOTH'}])
  sid='partial'
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'in_progress','baseline':[{'landmark_id':1},{'landmark_id':2}],'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1}]})
  class Adapter:
   def points(self):return {1:{}}
  class FakeWindow:
   _save_review_current=HumanBaselineWindow._save_review_current
   def __init__(self):self.project=project;self.sid=sid;self.schema=[{'id':1},{'id':2}];self.adapter=Adapter();self.on_review_saved=None
   def _notify_state_changed(self):pass
  fake=FakeWindow();self.assertFalse(fake._save_review_current(show_warning=False));self.assertEqual('in_progress',_load(project,sid)['status'])

 def test_suspicious_review_uses_confirm_navigation(self):
  first=_repeat_navigation_text(True,0,3,False,True);last=_repeat_navigation_text(True,2,3,False,True)
  self.assertEqual('1 / 3 suspicious image(s)',first['batch']);self.assertEqual('Confirm & Next ›',first['next'])
  self.assertEqual('Confirm & Finish',last['next'])

 def test_flagged_review_plan_deduplicates_images_and_keeps_batch_order(self):
  issues=[
   {'session_id':'s2','landmark_ids':[4]},
   {'session_id':'s1','landmark_ids':[1,2]},
   {'session_id':'s2','landmark_ids':[5]},
  ]
  ids,attention=_repeatability_flagged_review_plan(['s1','s2','s3'],issues)
  self.assertEqual(['s1','s2'],ids);self.assertEqual(1,len(attention['s1']));self.assertEqual(2,len(attention['s2']))

 def test_review_navigation_is_plain_browse_not_confirm_again(self):
  first=_repeat_navigation_text(True,0,10);last=_repeat_navigation_text(True,9,10);dirty=_repeat_navigation_text(True,0,10,True);dirty_last=_repeat_navigation_text(True,9,10,True)
  self.assertEqual('1 / 10',first['batch']);self.assertEqual('Next ›',first['next']);self.assertNotIn('Remaining',first['batch'])
  self.assertEqual('Finish review',last['next']);self.assertEqual('Save & Next ›',dirty['next']);self.assertEqual('Save & Finish review',dirty_last['next'])
  normal=_repeat_navigation_text(False,0,10)
  self.assertIn('Remaining 10',normal['batch']);self.assertEqual('Confirm & Next ›',normal['next'])

 def test_discard_review_correction_restores_completed_snapshot(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  sid='discard'
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'completed','completed_at':'old','baseline':[{'landmark_id':1}],'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1}]})
  from app.operator_qc import reopen_repeat_session_for_correction
  reopen_repeat_session_for_correction(project,sid);set_repeat_landmark(project,sid,1,9,9)
  self.assertEqual(9,_load(project,sid)['repeat'][0]['x'])
  restored=discard_repeat_session_correction(project,sid)
  self.assertEqual('completed',restored['status']);self.assertEqual(1,restored['repeat'][0]['x'])

 def test_new_repeat_session_freezes_full_schema_snapshot(self):
  schema=[{'id':1,'abbr':'A','name':'One','role':'BOTH','category':''},{'id':2,'abbr':'B','name':'Two','role':'BOTH','category':''},{'id':3,'abbr':'C','name':'Three','role':'BOTH','category':''}]
  project=_FakeProject(self.tmp,schema)
  standardized=project.cache_root/'standardized'/'img.png';standardized.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(20,10),'white').save(standardized)
  session=create_repeat_session(project,'img',eligibility_prevalidated=True)
  stored=_load(project,session['repeat_session_id'])
  self.assertEqual(['A','B','C'],[row['abbr'] for row in stored['schema']])
  project.schema=[{'id':1,'abbr':'X','name':'Changed','role':'BOTH'},{'id':2,'abbr':'Y','name':'Changed','role':'BOTH'},{'id':3,'abbr':'Z','name':'Changed','role':'BOTH'}]
  project.schema_path.write_text('id,abbr,name,role\n1,X,Changed,BOTH\n2,Y,Changed,BOTH\n3,Z,Changed,BOTH\n',encoding='utf8')
  data=blind_session_input(project,session['repeat_session_id'])
  self.assertTrue(data['schema_changed'])
  self.assertEqual(['A','B','C'],[row['abbr'] for row in data['schema']])

 def test_second_pass_is_blocked_if_scheme_changed(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  run={'schema_sha256':'different-from-current','passes':{},'image_ids':['img']}
  with self.assertRaisesRegex(ValueError,'Start a new sample'):
   _new_pass_sessions(project,run,2)

 def test_legacy_review_finish_migrates_pass1_without_keyerror_and_keeps_pass2_unstarted(self):
  schema=[{'id':1,'abbr':'A','name':'One','role':'BOTH','category':''},{'id':2,'abbr':'B','name':'Two','role':'BOTH','category':''},{'id':3,'abbr':'C','name':'Three','role':'BOTH','category':''}]
  project=_FakeProject(self.tmp,schema)
  session_ids=[]
  for index,image_id in enumerate(('img1','img2'),start=1):
   standardized=project.cache_root/'standardized'/f'{image_id}.png';standardized.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(20,10),'white').save(standardized)
   sid=f'legacy-{index}';session_ids.append(sid)
   _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':image_id,'status':'completed','completed_at':'old','schema_sha256':__import__('app.project_storage',fromlist=['schema_hash']).schema_hash(project.schema_path),'standardized_relpath':f'cache/standardized/{image_id}.png','baseline':[{'landmark_id':row['id']} for row in schema],'repeat':[{'landmark_id':row['id'],'state':'present','x':row['id'],'y':row['id']} for row in schema]})
  run={'format_version':1,'run_id':'legacy-run','created_at':'old','completed_at':None,'status':'in_progress','image_ids':['img1','img2'],'session_ids':session_ids,'report_path':None}
  _save_runs(project,{'format_version':2,'runs':[run]})
  migrated,ids=ensure_pass(project,'legacy-run',1)
  self.assertEqual(2,migrated['format_version']);self.assertEqual(tuple(session_ids),ids);self.assertIn('1',migrated['passes']);self.assertNotIn('2',migrated['passes'])
  complete_pass(project,'legacy-run',1)
  persisted=_runs(project)['runs'][0]
  self.assertIsNotNone(persisted['passes']['1']['completed_at']);self.assertNotIn('2',persisted['passes'])
  with self.assertRaisesRegex(ValueError,'Annotation 1 point check'):
   ensure_pass(project,'legacy-run',2)
  record_repeatability_pass_qc(project,'legacy-run',1,())
  migrated,two=ensure_pass(project,'legacy-run',2)
  self.assertEqual(2,len(two));self.assertIn('2',migrated['passes'])
  self.assertTrue(all(_load(project,sid)['status']=='in_progress' and _load(project,sid)['repeat']==[] for sid in two))

 def test_completed_legacy_run_becomes_in_progress_until_annotation2_is_done(self):
  schema=[{'id':1,'abbr':'A','name':'One','role':'BOTH','category':''}]
  project=_FakeProject(self.tmp,schema)
  standardized=project.cache_root/'standardized'/'img.png';standardized.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(20,10),'white').save(standardized)
  sid='legacy-completed'
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'completed','completed_at':'old','schema_sha256':__import__('app.project_storage',fromlist=['schema_hash']).schema_hash(project.schema_path),'standardized_relpath':'cache/standardized/img.png','baseline':[{'landmark_id':1}],'repeat':[{'landmark_id':1,'state':'present','x':1,'y':1}]})
  run={'format_version':1,'run_id':'legacy-completed-run','created_at':'old','completed_at':'old','status':'completed','image_ids':['img'],'session_ids':[sid],'report_path':'legacy-report.json'}
  _save_runs(project,{'format_version':2,'runs':[run]})
  migrated,ids=ensure_pass(project,'legacy-completed-run',1)
  self.assertEqual((sid,),ids);self.assertEqual('in_progress',migrated['status']);self.assertIsNone(migrated['completed_at']);self.assertTrue(migrated['report_stale']);self.assertNotIn('2',migrated['passes'])
  self.assertEqual('migrate_v1_to_v2',migrated['history'][-1]['event']);self.assertEqual('completed',migrated['history'][-1]['legacy_status'])

 def test_complete_pass_never_leaks_raw_keyerror_for_unstarted_pass(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  run={'format_version':2,'run_id':'r','created_at':'old','completed_at':None,'status':'in_progress','image_ids':['img'],'session_ids':[],'passes':{},'report_path':None}
  _save_runs(project,{'format_version':2,'runs':[run]})
  with self.assertRaisesRegex(ValueError,'not complete'):
   complete_pass(project,'r',1)

 def test_final_qc_detects_obvious_landmark_swap(self):
  project=_FakeProject(self.tmp,[{'id':i,'abbr':f'L{i}','name':f'Landmark {i}','role':'BOTH'} for i in range(1,6)])
  sid='swap'
  baseline={1:(10,10),2:(90,10),3:(10,90),4:(90,90),5:(50,50)}
  repeat=dict(baseline);repeat[1],repeat[2]=baseline[2],baseline[1]
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'completed','standardized_width':100,'standardized_height':100,'baseline':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in baseline.items()],'repeat':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in repeat.items()]})
  run={'format_version':2,'image_ids':['img'],'passes':{'1':{'session_ids':[sid]},'2':{'session_ids':[]}}}
  issues=repeatability_qc_issues(project,run)
  swaps=[item for item in issues if item['kind']=='possible_swap']
  self.assertTrue(any(item['landmark_ids']==[1,2] for item in swaps))

 def test_final_qc_does_not_flag_small_normal_placement_error(self):
  project=_FakeProject(self.tmp,[{'id':i,'abbr':f'L{i}','name':f'Landmark {i}','role':'BOTH'} for i in range(1,6)])
  sid='small-error'
  baseline={1:(10,10),2:(90,10),3:(10,90),4:(90,90),5:(50,50)}
  repeat={i:(xy[0]+1,xy[1]+1) for i,xy in baseline.items()}
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'completed','standardized_width':100,'standardized_height':100,'baseline':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in baseline.items()],'repeat':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in repeat.items()]})
  run={'format_version':2,'image_ids':['img'],'passes':{'1':{'session_ids':[sid]},'2':{'session_ids':[]}}}
  self.assertEqual((),repeatability_qc_issues(project,run))

 def test_first_completed_blind_coordinates_survive_later_corrections(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  sid='audit'
  _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'in_progress','baseline':[{'landmark_id':1,'state':'present','x':1,'y':1}],'repeat':[{'landmark_id':1,'state':'present','x':5,'y':6}]})
  complete_repeat_session(project,sid)
  self.assertEqual(5,_load(project,sid)['blind_final_repeat'][0]['x'])
  reopen_repeat_session_for_correction(project,sid);set_repeat_landmark(project,sid,1,20,30);complete_repeat_session(project,sid)
  data=_load(project,sid)
  self.assertEqual(20,data['repeat'][0]['x']);self.assertEqual(5,data['blind_final_repeat'][0]['x'])

 def test_next_state_requires_point_check_after_each_annotation(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  for sid in ('p1','p2'):_save(project,sid,{'repeat_session_id':sid,'status':'completed','repeat':[],'baseline':[]})
  base={'format_version':2,'status':'in_progress','image_ids':['img'],'passes':{'1':{'session_ids':['p1']},'2':{'session_ids':['p2']}}}
  self.assertEqual('pass_qc_1',repeatability_next_state(project,dict(base)))
  q1=dict(base,pass_qc={'1':{'checked_at':'now'}})
  self.assertEqual('pass_qc_2',repeatability_next_state(project,q1))
  q2=dict(base,pass_qc={'1':{'checked_at':'now'},'2':{'checked_at':'now'}},status='completed',report_stale=True)
  self.assertEqual('report_update',repeatability_next_state(project,q2))

 def test_pass_qc_action_is_deferred_until_annotation_callback_returns(self):
  events=[];pending=[]
  result=_dispatch_repeatability_stage('pass_qc_1',lambda number:events.append(f'qc{number}'),lambda:events.append('report'),schedule=lambda callback:pending.append(callback))
  self.assertEqual('pass_qc_1',result);self.assertEqual([],events);self.assertEqual(1,len(pending))
  pending.pop()();self.assertEqual(['qc1'],events)

 def test_report_update_action_never_opens_point_check(self):
  events=[]
  result=_dispatch_repeatability_stage('report_update',lambda number:events.append(f'qc{number}'),lambda:events.append('report'))
  self.assertEqual('report_update',result);self.assertEqual(['report'],events)

 def test_final_callback_runs_before_annotation_window_is_destroyed(self):
  events=[]
  class FakeWindow:
   edit_completed=True;index=0;session_ids=['only']
   def _save_review_current(self):return True
   def on_complete(self):events.append('complete');return True
   def destroy(self):events.append('destroy')
  HumanBaselineWindow.confirm(FakeWindow())
  self.assertEqual(['complete','destroy'],events)

 def test_pass_point_check_opens_only_after_annotation_window_is_destroyed(self):
  events=[];pending=[]
  def on_complete():
   _dispatch_repeatability_stage('pass_qc_1',lambda number:events.append(f'qc{number}'),lambda:events.append('report'),schedule=lambda callback:pending.append(callback))
   return True
  class FakeWindow:
   edit_completed=True;index=0;session_ids=['only']
   def _save_review_current(self):return True
   def destroy(self):events.append('destroy')
  fake=FakeWindow();fake.on_complete=on_complete
  HumanBaselineWindow.confirm(fake)
  self.assertEqual(['destroy'],events);self.assertEqual(1,len(pending))
  pending.pop()();self.assertEqual(['destroy','qc1'],events)

 def test_failed_next_stage_keeps_annotation_window_open(self):
  events=[]
  class FakeWindow:
   edit_completed=True;index=0;session_ids=['only']
   def _save_review_current(self):return True
   def on_complete(self):events.append('complete');return False
   def destroy(self):events.append('destroy')
  HumanBaselineWindow.confirm(FakeWindow())
  self.assertEqual(['complete'],events)

 def _completed_two_pass_run(self,project,run_id='two-pass'):
  schema=[{'id':1,'abbr':'A','name':'One','role':'BOTH','category':''},{'id':2,'abbr':'B','name':'Two','role':'BOTH','category':''}]
  project.schema=schema
  sessions=[]
  for number in (1,2):
   sid=f'{run_id}-p{number}';sessions.append(sid)
   _save(project,sid,{'format_version':1,'repeat_session_id':sid,'image_id':'img','status':'completed','completed_at':'old','schema_sha256':__import__('app.project_storage',fromlist=['schema_hash']).schema_hash(project.schema_path),'standardized_width':100,'standardized_height':100,'baseline':[{'landmark_id':1,'state':'present','x':10,'y':10},{'landmark_id':2,'state':'present','x':90,'y':90}],'repeat':[{'landmark_id':1,'state':'present','x':10+number,'y':10},{'landmark_id':2,'state':'present','x':90,'y':90-number}]})
  run={'format_version':2,'run_id':run_id,'created_at':'old','completed_at':None,'status':'in_progress','image_ids':['img'],'session_ids':[sessions[0]],'passes':{'1':{'session_ids':[sessions[0]],'completed_at':'old'},'2':{'session_ids':[sessions[1]],'completed_at':'old'}},'report_path':None}
  _save_runs(project,{'format_version':2,'runs':[run]});return run

 def test_finish_annotation1_routes_to_annotation1_point_check(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  sid='a';_save(project,sid,{'repeat_session_id':sid,'status':'completed','completed_at':'old','repeat':[],'baseline':[]})
  run={'format_version':2,'run_id':'r1','status':'in_progress','image_ids':['img'],'passes':{'1':{'session_ids':[sid],'completed_at':'old'}}}
  _save_runs(project,{'format_version':2,'runs':[run]})
  latest,action=finish_repeatability_pass(project,'r1',1)
  self.assertEqual('pass_qc_1',action);self.assertFalse(pass_qc_complete(latest,1))

 def test_finishing_already_checked_pass_still_routes_to_point_review_prompt(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  sid='checked-pass';_save(project,sid,{'repeat_session_id':sid,'status':'completed','completed_at':'old','repeat':[],'baseline':[]})
  run={'format_version':2,'run_id':'checked-run','status':'in_progress','image_ids':['img'],'passes':{'1':{'session_ids':[sid],'completed_at':'old'}},'pass_qc':{'1':{'checked_at':'old','issue_count':0}}}
  _save_runs(project,{'format_version':2,'runs':[run]})
  latest,action=finish_repeatability_pass(project,'checked-run',1)
  self.assertTrue(pass_qc_complete(latest,1))
  self.assertEqual('pass_qc_1',action)

 def test_annotation2_cannot_start_before_annotation1_point_check(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  standardized=project.cache_root/'standardized'/'img.png';standardized.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(20,10),'white').save(standardized)
  sid='a';_save(project,sid,{'repeat_session_id':sid,'image_id':'img','status':'completed','completed_at':'old','repeat':[],'baseline':[]})
  run={'format_version':2,'run_id':'gate-p2','status':'in_progress','image_ids':['img'],'passes':{'1':{'session_ids':[sid],'completed_at':'old'}},'schema_sha256':__import__('app.project_storage',fromlist=['schema_hash']).schema_hash(project.schema_path)}
  _save_runs(project,{'format_version':2,'runs':[run]})
  with self.assertRaisesRegex(ValueError,'Annotation 1 point check'):ensure_pass(project,'gate-p2',2)
  record_repeatability_pass_qc(project,'gate-p2',1,())
  _run,two=ensure_pass(project,'gate-p2',2);self.assertEqual(1,len(two))

 def test_pass_qc_scanner_can_be_filtered_to_one_annotation(self):
  project=_FakeProject(self.tmp,[{'id':i,'abbr':f'L{i}','name':f'Landmark {i}','role':'BOTH'} for i in range(1,6)])
  baseline={1:(10,10),2:(90,10),3:(10,90),4:(90,90),5:(50,50)}
  for number in (1,2):
   sid=f'q{number}';repeat=dict(baseline)
   if number==1:repeat[1],repeat[2]=baseline[2],baseline[1]
   _save(project,sid,{'repeat_session_id':sid,'image_id':'img','status':'completed','standardized_width':100,'standardized_height':100,'baseline':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in baseline.items()],'repeat':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in repeat.items()]})
  run={'format_version':2,'image_ids':['img'],'passes':{'1':{'session_ids':['q1']},'2':{'session_ids':['q2']}}}
  self.assertTrue(any(item['kind']=='possible_swap' for item in repeatability_pass_qc_issues(project,run,1)))
  self.assertEqual((),repeatability_pass_qc_issues(project,run,2))

 def test_nearby_lm18_lm19_swap_is_found_even_with_high_background_click_error(self):
  schema=[{'id':i,'abbr':f'L{i}','name':f'Landmark {i}','role':'BOTH'} for i in range(1,26)]
  project=_FakeProject(self.tmp,schema)
  baseline={i:(50+30*i,80+35*(i%5)) for i in range(1,26)}
  baseline[18]=(700,180);baseline[19]=(718,180)
  repeat={i:(xy[0]+12,xy[1]) for i,xy in baseline.items()}
  repeat[18]=baseline[19];repeat[19]=baseline[18]
  sid='nearby-18-19-swap'
  _save(project,sid,{
   'repeat_session_id':sid,'image_id':'img','status':'completed','standardized_width':1000,'standardized_height':400,
   'baseline':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in baseline.items()],
   'repeat':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in repeat.items()],
  })
  run={'format_version':2,'image_ids':['img'],'passes':{'1':{'session_ids':[sid]},'2':{'session_ids':[]}}}
  issues=repeatability_pass_qc_issues(project,run,1)
  swaps=[item for item in issues if item.get('kind')=='possible_swap']
  self.assertTrue(any(set(item.get('landmark_ids',()))=={18,19} for item in swaps),swaps)

 def test_real_logged_lm18_lm19_reversal_is_detected(self):
  reference={18:(1626.5407694250603,466.2485379127342),19:(1607.8140970308339,579.0767390879478)}
  present={18:(1548.0425646468293,487.66377122995516),19:(1581.966590552016,382.25697645312516)}
  metrics=_swap_pair_metrics(present,reference,18,19,2469.9914979610758)
  self.assertLess(metrics['pair_cos'],-.98)
  self.assertAlmostEqual(.968,metrics['length_ratio'],places=2)
  self.assertTrue(metrics['vector_reversal']);self.assertTrue(metrics['accepted'])

 def test_real_logged_normal_lm18_lm19_pair_is_not_detected(self):
  reference={18:(2360.9120931462267,527.6229308140943),19:(2351.4194883037794,702.2868599151243)}
  present={18:(2368.694209119472,532.3995487396363),19:(2356.6860639937763,701.6052300562591)}
  metrics=_swap_pair_metrics(present,reference,18,19,3000.0)
  self.assertGreater(metrics['pair_cos'],.99)
  self.assertFalse(metrics['vector_reversal']);self.assertFalse(metrics['accepted'])

 def test_global_translation_plus_lm18_lm19_swap_is_detected(self):
  schema=[{'id':i,'abbr':f'L{i}','name':f'Landmark {i}','role':'BOTH'} for i in range(1,26)]
  project=_FakeProject(self.tmp,schema)
  baseline={i:(100+55*i,120+30*(i%4)) for i in range(1,26)}
  baseline[18]=(1300,420);baseline[19]=(1320,560)
  shift=(-85,-110)
  repeat={i:(xy[0]+shift[0],xy[1]+shift[1]) for i,xy in baseline.items()}
  repeat[18]=(baseline[19][0]+shift[0],baseline[19][1]+shift[1])
  repeat[19]=(baseline[18][0]+shift[0],baseline[18][1]+shift[1])
  sid='translated-swap'
  _save(project,sid,{
   'repeat_session_id':sid,'image_id':'img','status':'completed','standardized_width':2200,'standardized_height':900,
   'baseline':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in baseline.items()],
   'repeat':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in repeat.items()],
  })
  run={'format_version':2,'run_id':'translated-swap-run','image_ids':['img'],'passes':{'1':{'session_ids':[sid]},'2':{'session_ids':[]}}}
  issues=repeatability_pass_qc_issues(project,run,1)
  self.assertTrue(any(item.get('kind')=='possible_swap' and set(item.get('landmark_ids',()))=={18,19} for item in issues),issues)

 def test_global_translation_without_local_error_is_not_flagged(self):
  schema=[{'id':i,'abbr':f'L{i}','name':f'Landmark {i}','role':'BOTH'} for i in range(1,26)]
  project=_FakeProject(self.tmp,schema)
  baseline={i:(100+55*i,120+30*(i%4)) for i in range(1,26)}
  shift=(-85,-110)
  repeat={i:(xy[0]+shift[0],xy[1]+shift[1]) for i,xy in baseline.items()}
  sid='translated-clean'
  _save(project,sid,{
   'repeat_session_id':sid,'image_id':'img','status':'completed','standardized_width':2200,'standardized_height':900,
   'baseline':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in baseline.items()],
   'repeat':[{'landmark_id':i,'state':'present','x':xy[0],'y':xy[1]} for i,xy in repeat.items()],
  })
  run={'format_version':2,'run_id':'translated-clean-run','image_ids':['img'],'passes':{'1':{'session_ids':[sid]},'2':{'session_ids':[]}}}
  self.assertEqual((),repeatability_pass_qc_issues(project,run,1))

 def test_intentionally_missing_landmark_is_not_a_probable_error(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'},{'id':2,'abbr':'B','name':'Two','role':'BOTH'}])
  sid='missing-is-valid'
  _save(project,sid,{
   'repeat_session_id':sid,'image_id':'img','status':'completed','standardized_width':100,'standardized_height':100,
   'baseline':[{'landmark_id':1,'state':'present','x':10,'y':10},{'landmark_id':2,'state':'present','x':90,'y':90}],
   'repeat':[{'landmark_id':1,'state':'missing','x':None,'y':None},{'landmark_id':2,'state':'present','x':90,'y':90}],
  })
  run={'format_version':2,'image_ids':['img'],'passes':{'1':{'session_ids':[sid]},'2':{'session_ids':[]}}}
  issues=repeatability_pass_qc_issues(project,run,1)
  self.assertFalse(any(1 in item.get('landmark_ids',()) for item in issues))
  self.assertFalse(any(item.get('kind')=='state_mismatch' for item in issues))

 def test_both_pass_checks_are_required_before_final_report(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'},{'id':2,'abbr':'B','name':'Two','role':'BOTH'}])
  run=self._completed_two_pass_run(project,'gate')
  record_repeatability_pass_qc(project,run['run_id'],1,())
  with self.assertRaisesRegex(ValueError,'point check'):complete_run(project,run['run_id'])
  _run,report=finalize_repeatability_pass_qc(project,run['run_id'],2,())
  self.assertEqual('human_baseline',report['report_type'])
  saved=_runs(project)['runs'][0];self.assertTrue(pass_qc_complete(saved,1));self.assertTrue(pass_qc_complete(saved,2));self.assertTrue(final_qc_complete(saved))

 def test_editing_one_pass_invalidates_only_that_pass_check_and_report(self):
  project=_FakeProject(self.tmp,[{'id':1,'abbr':'A','name':'One','role':'BOTH'}])
  run={'format_version':2,'run_id':'stale','status':'completed','report_path':'report.json','pass_qc':{'1':{'checked_at':'old'},'2':{'checked_at':'old'}},'final_qc':{'checked_at':'old'},'passes':{},'image_ids':[]}
  _save_runs(project,{'format_version':2,'runs':[run]})
  mark_completed_run_stale(project,'stale',pass_number=1)
  saved=_runs(project)['runs'][0]
  self.assertTrue(saved['report_stale']);self.assertFalse(pass_qc_complete(saved,1));self.assertTrue(pass_qc_complete(saved,2));self.assertFalse(final_qc_complete(saved))
  self.assertEqual('invalidate_pass_qc',saved['history'][-1]['event'])

 def test_error_scan_runs_only_after_yes(self):
  events=[]
  answer,issues=_repeatability_ask_then_scan(lambda:(events.append('ask') or True),lambda:(events.append('scan') or ({'kind':'x'},)))
  self.assertTrue(answer);self.assertEqual(({'kind':'x'},),issues);self.assertEqual(['ask','scan'],events)

 def test_error_scan_does_not_run_after_no(self):
  events=[]
  answer,issues=_repeatability_ask_then_scan(lambda:(events.append('ask') or False),lambda:(events.append('scan') or ({'kind':'x'},)))
  self.assertFalse(answer);self.assertEqual((),issues);self.assertEqual(['ask'],events)

 def test_point_check_uses_simple_prompt_and_flagged_image_cycle(self):
  source=(ROOT/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertNotIn("text='Point-error checks'",source);self.assertNotIn("ttk.Treeview(body,columns=('image','points','issue')",source)
  self.assertIn("default='yes'",source);self.assertIn("Check for likely landmark-placement errors now?",source)
  self.assertIn("Analysis complete.",source);self.assertIn("No likely landmark-placement errors were found.",source)
  self.assertIn("_repeatability_ask_then_scan(ask,scan)",source)
  self.assertIn("session_ids=flagged_ids",source);self.assertIn("review_attention=attention",source)
  self.assertIn("offer_pass_qc",source);self.assertIn("schedule=self.shell.after_idle",source)
  self.assertIn("lambda:open_pass(1)",source);self.assertIn("lambda:open_pass(2)",source)
  self.assertNotIn("handle_pass_action",source);self.assertIn("self.shell.after_idle(resume_pending_qc)",source)

 def test_post_batch_prompt_happens_before_background_scan_and_zero_issue_finalize(self):
  source=(ROOT/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  offer=source[source.index('  def offer_pass_qc(number):'):source.index('  def open_pass(number):')]
  ask=offer.index("answer=messagebox.askyesno")
  scan_def=offer.index("def start_scan")
  scan=offer.index("found=repeatability_pass_qc_issues",scan_def)
  zero=offer.index("if not issues:")
  start_call=offer.rindex("start_scan()")
  self.assertLess(ask,scan_def);self.assertLess(scan_def,scan);self.assertLess(scan,start_call)
  self.assertLess(ask,start_call);self.assertLess(zero,start_call)
  self.assertIn("'Analyzing landmark placement errors…'",offer)

 def test_suspicious_review_highlights_points_and_enter_confirms(self):
  review_source=(ROOT/'app'/'human_baseline_ui.py').read_text(encoding='utf8')
  surface_source=(ROOT/'app'/'landmark_annotation_ui.py').read_text(encoding='utf8')
  self.assertIn("self.bind('<Return>'",review_source);self.assertIn("highlight_ids=attention_ids",review_source)
  self.assertIn("self.highlight_ids",surface_source);self.assertIn("self.canvas.create_oval",surface_source)

 def test_completed_passes_keep_review_correction_flow(self):
  source=(ROOT/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertIn("review_mode=review_existing or bool(pass_meta.get('completed_at'))",source)
  self.assertIn("edit_completed=review_mode",source)
  self.assertIn("mark_completed_run_stale",source)
  self.assertIn("recompute_completed_run",source)

 def test_completed_run_counts_remain_visible(self):
  source=(ROOT/'app'/'ui'/'landmarks_section.py').read_text(encoding='utf8')
  self.assertGreaterEqual(source.count("reversed(previous_runs(self.context.project))"),2)
  self.assertIn("self._refresh_repeatability_summary();self.context.invalidate_counts();self.shell._update_status()",source)

 def test_final_repeatability_action_is_explicit(self):
  self.assertEqual('Confirm & Finish',_repeat_navigation_text(False,9,10)['next'])
  self.assertEqual('Finish review',_repeat_navigation_text(True,9,10)['next'])
  self.assertEqual('Save & Finish review',_repeat_navigation_text(True,9,10,True)['next'])


if __name__=='__main__':
 unittest.main()
