"""Independent, GUI-free operator repeat annotation sessions."""
import json,math,random,uuid,shutil,hashlib
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
from .io import atomic_json_write
from .project_storage import schema_hash, landmark_schema_identity, load_schema

def _now():return datetime.now(timezone.utc).isoformat()
def _path(p,s):return p.data_root/'ai'/'operator_sessions'/str(s)/'session.json'
def _load(p,s):return json.loads(_path(p,s).read_text(encoding='utf-8'))
def _save(p,s,d):atomic_json_write(_path(p,s),d)
def _pct(v,p):
 v=sorted(v);return v[min(len(v)-1,max(0,math.ceil(len(v)*p)-1))] if v else None
def operator_eligible_image_ids(p):
 """Bulk eligibility for Human repeatability; no per-image SQLite loop."""
 human={'manual','corrected','corrected_by_human','reviewed_by_human'}
 display_by_abbr={str(row['abbr']):int(row['id']) for row in p.schema};required=set(display_by_abbr.values())
 catalog=p.catalog_rows();grouped={}
 with p.transaction() as c:
  rows=c.execute("SELECT image_id,landmark_abbr,state,provenance FROM landmarks").fetchall()
 for raw in rows:
  ident=display_by_abbr.get(str(raw['landmark_abbr'] or ''))
  if ident is None:continue
  grouped.setdefault(raw['image_id'],{})[ident]=dict(raw)
 out=[]
 for row in catalog:
  if row.get('excluded') or row.get('missing_ids'):continue
  points=grouped.get(row['image_id'],{})
  if required and all((point:=points.get(ident)) and (point.get('state')=='missing' or point.get('provenance') in human) for ident in required):
   out.append(row['image_id'])
 return tuple(sorted(out))
def _repeat_session_required_ids(d):
 """Frozen landmark IDs for this repeat session; baseline is authoritative for legacy sessions."""
 baseline=[]
 for point in d.get('baseline',()):
  try:baseline.append(int(point['landmark_id']))
  except (KeyError,TypeError,ValueError):continue
 if baseline:return tuple(dict.fromkeys(baseline))
 stored=[]
 for row in d.get('schema',()):
  try:stored.append(int(row['id']))
  except (KeyError,TypeError,ValueError):continue
 return tuple(dict.fromkeys(stored))

def _repeat_session_schema(p,d):
 """Return the scheme frozen with the session; never reinterpret legacy IDs through a changed scheme."""
 required=_repeat_session_required_ids(d)
 stored=d.get('schema') or ()
 by_id={int(row['id']):dict(row) for row in stored if row.get('id') is not None}
 if required and all(ident in by_id for ident in required):return [by_id[ident] for ident in required]
 current_hash=schema_hash(p.schema_path)
 if d.get('schema_sha256')==current_hash:
  current={int(row['id']):dict(row) for row in p.schema}
  if required and all(ident in current for ident in required):return [current[ident] for ident in required]
 if required:
  return [{'id':ident,'abbr':f'LM{ident}','name':f'Original landmark {ident}','role':'BOTH','category':''} for ident in required]
 return [dict(row) for row in p.schema]

def create_repeat_session(p,image_id,operator_id=None,eligibility_prevalidated=False,standardized_source=None):
 if not eligibility_prevalidated and image_id not in operator_eligible_image_ids(p):raise ValueError('image is not fully manual operator-QC eligible')
 schema=p.schema;rows=p.load_landmarks(image_id);canonical=p.cache_root/'standardized'/f'{image_id}.png';std=Path(standardized_source) if standardized_source is not None else canonical
 with Image.open(std) as im:w,h=im.size
 baseline=[{'landmark_id':x['id'],'state':'missing' if rows[x['id']]['state']=='missing' else 'present','x':None if rows[x['id']]['state']=='missing' else rows[x['id']]['x_standardized'],'y':None if rows[x['id']]['state']=='missing' else rows[x['id']]['y_standardized'],'provenance':rows[x['id']]['provenance']} for x in schema]
 sid=str(uuid.uuid4());session_dir=_path(p,sid).parent;session_dir.mkdir(parents=True,exist_ok=True)
 # Human-repeatability must never depend on the mutable standardized cache.
 # Freeze the exact raster used for this blind annotation inside the session.
 frozen=session_dir/'standardized.png';shutil.copy2(std,frozen)
 frozen_sha=hashlib.sha256(frozen.read_bytes()).hexdigest()
 source_relpath=std.relative_to(p.data_root).as_posix()
 d={'format_version':1,'repeat_session_id':sid,'image_id':image_id,'created_at':_now(),'completed_at':None,'status':'in_progress','operator_id':operator_id,'schema_sha256':schema_hash(p.schema_path),'schema':[dict(row) for row in schema],'standardized_relpath':frozen.relative_to(p.data_root).as_posix(),'standardized_source_relpath':source_relpath,'standardized_snapshot':True,'standardized_width':w,'standardized_height':h,'standardized_sha256':frozen_sha,'baseline':baseline,'repeat':[]};_save(p,sid,d);return d
def blind_session_input(p,sid):
 d=_load(p,sid);stored=d.get('schema') or ();stored_identity=landmark_schema_identity(stored) if stored else ();current_identity=landmark_schema_identity(load_schema(p.schema_path))
 changed=(stored_identity!=current_identity) if stored_identity else bool(d.get('schema_sha256') and d.get('schema_sha256')!=schema_hash(p.schema_path))
 return {'repeat_session_id':sid,'image_id':d['image_id'],'standardized_image_path':p.data_root/d['standardized_relpath'],'schema':_repeat_session_schema(p,d),'schema_changed':changed}
def set_repeat_landmark(p,sid,ident,x,y,state='present'):
 d=_load(p,sid)
 if d['status']!='in_progress':raise ValueError('repeat session is immutable')
 ident=int(ident);ids=set(_repeat_session_required_ids(d))
 if ident not in ids:raise ValueError('landmark ID is not part of this repeat session scheme')
 previous=next((item for item in d.get('repeat',()) if int(item.get('landmark_id'))==ident),None)
 point={'landmark_id':ident,'state':'missing' if state=='missing' else 'present','x':None if state=='missing' else x,'y':None if state=='missing' else y,'updated_at':_now()}
 if state=='missing':
  if previous and previous.get('state')=='present' and previous.get('x') is not None and previous.get('y') is not None:
   point.update({'previous_x':previous.get('x'),'previous_y':previous.get('y'),'previous_state':'present'})
  elif previous and previous.get('state')=='missing' and previous.get('previous_x') is not None and previous.get('previous_y') is not None:
   point.update({'previous_x':previous.get('previous_x'),'previous_y':previous.get('previous_y'),'previous_state':'present'})
 d['repeat']=[item for item in d['repeat'] if item['landmark_id']!=ident];d['repeat'].append(point);_save(p,sid,d)

def unmark_repeat_landmark(p,sid,ident):
 d=_load(p,sid)
 if d['status']!='in_progress':raise ValueError('repeat session is immutable')
 ident=int(ident);current=next((item for item in d.get('repeat',()) if int(item.get('landmark_id'))==ident),None)
 if not current or current.get('state')!='missing':return False
 d['repeat']=[item for item in d['repeat'] if int(item.get('landmark_id'))!=ident]
 restored=current.get('previous_x') is not None and current.get('previous_y') is not None
 if restored:d['repeat'].append({'landmark_id':ident,'state':'present','x':current.get('previous_x'),'y':current.get('previous_y'),'updated_at':_now()})
 _save(p,sid,d);return restored

def remove_repeat_landmark(p,sid,ident):
 d=_load(p,sid)
 if d['status']!='in_progress':raise ValueError('repeat session is immutable')
 d['repeat']=[x for x in d['repeat'] if x['landmark_id']!=int(ident)];_save(p,sid,d)
def clear_repeat_landmarks(p,sid):
 """Clear only blind repeat-session points; canonical project annotations are never read or written."""
 d=_load(p,sid)
 if d['status']!='in_progress':raise ValueError('repeat session is immutable')
 d['repeat']=[];_save(p,sid,d)
def reopen_repeat_session_for_correction(p,sid):
 """Make a completed repeat editable again while retaining an auditable snapshot."""
 d=_load(p,sid)
 if d.get("status")!="completed":
  return d
 d.setdefault("revisions",[]).append({"timestamp":_now(),"kind":"repeat_before_correction","repeat":list(d.get("repeat",()))})
 d["status"]="in_progress";d["completed_at"]=None;_save(p,sid,d)
 return d
def discard_repeat_session_correction(p,sid):
 """Restore the pre-correction snapshot for a review session and close it as completed."""
 d=_load(p,sid)
 if d.get('status')!='in_progress':return d
 snapshot=None
 for revision in reversed(d.get('revisions',())):
  if revision.get('kind')=='repeat_before_correction':
   snapshot=list(revision.get('repeat',()));break
 if snapshot is None:raise ValueError('no saved pre-correction snapshot is available')
 d['repeat']=snapshot;d['status']='completed';d['completed_at']=_now()
 d.setdefault('revisions',[]).append({'timestamp':_now(),'kind':'repeat_correction_discarded'})
 _save(p,sid,d);return d

def complete_repeat_session(p,sid):
 d=_load(p,sid);required=set(_repeat_session_required_ids(d));resolved={int(x['landmark_id']) for x in d.get('repeat',())}
 if d.get('status')!='in_progress':raise ValueError('repeat session is not open for editing')
 missing=sorted(required-resolved);unexpected=sorted(resolved-required)
 if missing or unexpected:
  details=[]
  if missing:details.append('missing IDs: '+', '.join(map(str,missing)))
  if unexpected:details.append('unexpected IDs: '+', '.join(map(str,unexpected)))
  raise ValueError('repeat session does not match its saved landmark scheme ('+'; '.join(details)+')')
 if 'blind_final_repeat' not in d:d['blind_final_repeat']=[dict(point) for point in d.get('repeat',())]
 d['status']='completed';d['completed_at']=_now();_save(p,sid,d);return d
def cancel_repeat_session(p,sid):
 d=_load(p,sid)
 if d['status']!='in_progress':raise ValueError('repeat session is immutable')
 d['status']='cancelled';d['completed_at']=_now();_save(p,sid,d);return d
def select_repeat_candidates(p,count,seed):
 eligible=list(operator_eligible_image_ids(p));done={_load(p,x.parent.name)['image_id'] for x in (p.data_root/'ai'/'operator_sessions').glob('*/session.json') if _load(p,x.parent.name).get('status')=='completed'} if (p.data_root/'ai'/'operator_sessions').exists() else set();pool=[x for x in eligible if x not in done] or eligible;random.Random(seed).shuffle(pool);return {'image_ids':tuple(pool[:count]),'available':len(pool)}
def evaluate_operator_sessions(p,session_ids):
 sessions=[_load(p,s) for s in session_ids if _load(p,s).get('status')=='completed'];errors=[];normalized=[];millimeters=[];per=[];land={};dis={'baseline_present_repeat_missing':0,'baseline_missing_repeat_present':0,'both_missing':0}
 catalog={row['image_id']:row for row in p.catalog_rows()}
 for d in sessions:
  base={x['landmark_id']:x for x in d['baseline']};rep={x['landmark_id']:x for x in d['repeat']};diag=math.hypot(d['standardized_width'],d['standardized_height']);ie=[];ine=[];ime=[];bad=0
  row=catalog.get(d['image_id'],{});cal=p.locality_calibration(row.get('locality') or row.get('sample_id')) if row else None;scale=cal.get('scale') if cal else None
  for ident,b in base.items():
   r=rep[ident];m=land.setdefault(str(ident),{'landmark_id':ident,'errors':[],'normalized_errors':[],'mm_errors':[],'disagreement':0})
   if b['state']=='present' and r['state']=='present':
    e=math.hypot(b['x']-r['x'],b['y']-r['y']);n=e/diag if diag else None;mm=e/scale if scale else None;errors.append(e);ie.append(e);m['errors'].append(e)
    if n is not None: normalized.append(n);ine.append(n);m['normalized_errors'].append(n)
    if mm is not None: millimeters.append(mm);ime.append(mm);m['mm_errors'].append(mm)
   elif b['state']=='missing' and r['state']=='missing':dis['both_missing']+=1
   else:
    bad+=1;m['disagreement']+=1;dis['baseline_present_repeat_missing' if b['state']=='present' else 'baseline_missing_repeat_present']+=1
  per.append({'repeat_session_id':d['repeat_session_id'],'image_id':d['image_id'],'comparable_landmarks':len(ie),'median_error_px':_pct(ie,.5),'p95_error_px':_pct(ie,.95),'max_error_px':max(ie) if ie else None,'median_error_normalized':_pct(ine,.5),'p95_error_normalized':_pct(ine,.95),'max_error_normalized':max(ine) if ine else None,'median_error_mm':_pct(ime,.5),'p95_error_mm':_pct(ime,.95),'max_error_mm':max(ime) if ime else None,'disagreement_count':bad})
 return {'metric_version':1,'repeat_session_ids':[x['repeat_session_id'] for x in sessions],'image_ids':[x['image_id'] for x in per],'aggregate':{'n_sessions':len(sessions),'n_images':len(per),'n_comparable_landmarks':len(errors),'median_error_px':_pct(errors,.5),'p95_error_px':_pct(errors,.95),'max_error_px':max(errors) if errors else None,'median_error_normalized':_pct(normalized,.5),'p95_error_normalized':_pct(normalized,.95),'max_error_normalized':max(normalized) if normalized else None,'median_error_mm':_pct(millimeters,.5),'p95_error_mm':_pct(millimeters,.95),'max_error_mm':max(millimeters) if millimeters else None,'insufficient_data':len(errors)<3,**dis},'per_landmark':{k:{'landmark_id':v['landmark_id'],'n':len(v['errors']),'median_error_px':_pct(v['errors'],.5),'p95_error_px':_pct(v['errors'],.95),'max_error_px':max(v['errors']) if v['errors'] else None,'median_error_normalized':_pct(v['normalized_errors'],.5),'p95_error_normalized':_pct(v['normalized_errors'],.95),'median_error_mm':_pct(v['mm_errors'],.5),'p95_error_mm':_pct(v['mm_errors'],.95),'presence_missing_disagreements':v['disagreement']} for k,v in land.items()},'per_image':per}
def save_operator_report(p,result,report_id=None):
 rid=str(report_id or uuid.uuid4());path=p.data_root/'ai'/'qc'/'operator'/f'{rid}.json'
 if path.exists():raise FileExistsError(rid)
 atomic_json_write(path,dict(result,report_id=rid,created_at=_now(),schema_sha256=schema_hash(p.schema_path)));return path