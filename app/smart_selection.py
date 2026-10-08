"""Read-only ranking plus immutable smart prospective-batch selection."""
from __future__ import annotations
import json, math, random, sqlite3, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
from .ai import InferenceRequest
from .ai_batch import BatchError, active_backend
from .io import atomic_json_write
from .landmark_ai_service import LandmarkAIService
from .project_storage import load_schema, schema_hash, landmark_model_schema_compatible
from .landmark_qc import stable_weak_landmark_profile
from .landmark_frames import landmark_frame_ready

def _now(): return datetime.now(timezone.utc).isoformat()
def _group(row): return str(row.get('locality') or row.get('sample_id') or '')
def _model_development(project, model, *, diagnostic_callback=None):
 diagnostic_callback and diagnostic_callback('MODEL_DEVELOPMENT_START')
 try:
  path=Path(model.get('dataset_manifest_path') or '');path=path if path.is_absolute() else project.data_root/path
  return {str(x['image_id']) for x in json.loads(path.read_text(encoding='utf8')).get('images',())}
 finally: diagnostic_callback and diagnostic_callback('MODEL_DEVELOPMENT_END')
def _readonly_selection_snapshot(project, *, diagnostic_callback=None):
 """One read-only snapshot for Improvement selection; never uses Project.transaction()."""
 diagnostic_callback and diagnostic_callback("READONLY_SNAPSHOT_START")
 uri=project.path.resolve().as_uri()+"?mode=ro"
 conn=sqlite3.connect(uri,uri=True,timeout=1);conn.row_factory=sqlite3.Row
 try:
  rows=tuple(dict(row) for row in conn.execute("SELECT * FROM images WHERE COALESCE(active,1)=1 ORDER BY locality COLLATE NOCASE,index_in_locality,relative_path"))
  held=frozenset(row[0] for row in conn.execute("SELECT image_id FROM ai_permanent_holdouts"))
  annotated=frozenset(row[0] for row in conn.execute("SELECT DISTINCT image_id FROM landmarks"))
  human_rows=tuple(dict(row) for row in conn.execute("SELECT l.image_id,l.landmark_id,l.x_standardized AS x,l.y_standardized AS y,l.state FROM landmarks l JOIN image_review r ON r.image_id=l.image_id WHERE r.human_verified=1 AND l.state!='missing' AND l.x_standardized IS NOT NULL AND l.y_standardized IS NOT NULL ORDER BY l.image_id,l.landmark_id"))
 finally:
  conn.close()
 by_image={}
 for row in human_rows: by_image.setdefault(row["image_id"],[]).append(row)
 humans=tuple(_descriptor(rows) for rows in by_image.values())
 result={"rows":rows,"held":held,"annotated":annotated,"human_descriptors":tuple(value for value in humans if value)}
 diagnostic_callback and diagnostic_callback("READONLY_SNAPSHOT_END")
 return result
def _candidate_pool_from_snapshot(project, model, snapshot, *, excluded_image_ids=(), diagnostic_callback=None):
 if not model or not model.get('active'): raise BatchError('requested model is not active')
 if not landmark_model_schema_compatible(project,model): raise BatchError('active model schema mismatch')
 diagnostic_callback and diagnostic_callback('CANDIDATE_FILTER_START')
 development=_model_development(project,model,diagnostic_callback=diagnostic_callback);blocked=set(excluded_image_ids);out=[]
 for row in snapshot["rows"]:
  image_id=row['image_id'];cache=project.cache_root/'standardized'/f'{image_id}.png'
  if row.get('excluded') or image_id in blocked or image_id in snapshot["held"] or image_id in development or image_id in snapshot["annotated"] or not landmark_frame_ready(project,image_id): continue
  out.append(dict(row))
 result=tuple(out);diagnostic_callback and diagnostic_callback("CANDIDATE_FILTER_END");return result
def candidate_pool(project, model_id, *, excluded_image_ids=()):
 model=project.model_metadata(model_id)
 if not model or not model.get('active'): raise BatchError('requested model is not active')
 if not landmark_model_schema_compatible(project,model): raise BatchError('active model schema mismatch')
 development=_model_development(project,model);held=project.permanent_test_image_ids();blocked=set(excluded_image_ids);out=[]
 for row in project.catalog_rows():
  image_id=row['image_id'];cache=project.cache_root/'standardized'/f'{image_id}.png'
  if row.get('excluded') or image_id in blocked or image_id in held or image_id in development or project.load_landmarks(image_id) or not landmark_frame_ready(project,image_id): continue
  out.append(dict(row))
 return tuple(out)

def _descriptor(points):
 values=[(float(x['x']),float(x['y'])) for x in sorted(points,key=lambda x:int(x['landmark_id'])) if math.isfinite(float(x['x'])) and math.isfinite(float(x['y']))]
 if len(values)<3:return ()
 cx=sum(x for x,_ in values)/len(values);cy=sum(y for _,y in values)/len(values);scale=math.sqrt(sum((x-cx)**2+(y-cy)**2 for x,y in values))
 return tuple(((x-cx)/scale,(y-cy)/scale) for x,y in values) if scale else ()
def _distance(a,b):
 if not a or not b or len(a)!=len(b):return 0.0
 dot=sum(x*u+y*v for (x,y),(u,v) in zip(a,b));cross=sum(x*v-y*u for (x,y),(u,v) in zip(a,b));norm=math.hypot(dot,cross)
 if not norm:return math.sqrt(sum((x-u)**2+(y-v)**2 for (x,y),(u,v) in zip(a,b)))
 c,s=dot/norm,cross/norm
 return math.sqrt(sum(((c*x-s*y-u)**2+(s*x+c*y-v)**2) for (x,y),(u,v) in zip(a,b))/len(a))
def rank_candidates(project, backend, candidates, *, progress_callback=None):
 schema=tuple(dict(x) for x in load_schema(project.schema_path));digest=schema_hash(project.schema_path);requests=[]
 for row in candidates:
  path=project.cache_root/'standardized'/f"{row['image_id']}.png"
  with Image.open(path) as image:w,h=image.size
  requests.append(InferenceRequest(row['image_id'],path,schema,digest,w,h))
 started=time.perf_counter();predictions=backend.predict_readonly_many(requests,progress_callback=progress_callback) if progress_callback else backend.predict_readonly_many(requests);duration=time.perf_counter()-started;lookup={x.image_id:x for x in predictions};rows=[]
 for row in candidates:
  p=lookup[row['image_id']];points=[{'landmark_id':q.landmark_id,'x':q.x,'y':q.y,'confidence':q.confidence} for q in p.landmarks];conf=[q['confidence'] for q in points if q['confidence'] is not None]
  rows.append({'image_id':row['image_id'],'original_name':row.get('original_name'),'locality':row.get('locality'),'sample_id':row.get('sample_id'),'median_confidence':sorted(conf)[len(conf)//2] if conf else None,'low_confidence':min(conf) if conf else None,'predictions':points,'descriptor':_descriptor(points)})
 return rows,duration
def _human_descriptors(project):
 result=[]
 for row in project.catalog_rows():
  status=project.annotation_status(row['image_id'])
  if not status['verified'] or not status['complete']:continue
  points=project.load_landmarks(row['image_id']);values=[]
  for ident in sorted(points):
   value=points[ident]
   if value.get('state')!='missing':values.append({'landmark_id':ident,'x':value['x_standardized'],'y':value['y_standardized']})
  result.append(_descriptor(values))
 return tuple(x for x in result if x)
def select_ranked(project, ranked, seed, active_count=7, random_count=3):
 rng=random.Random(seed);humans=_human_descriptors(project);ordered=sorted(ranked,key=lambda x:(x['median_confidence'] if x['median_confidence'] is not None else 1.0,x['image_id']))
 pool=ordered[:max(active_count*6,min(len(ordered),80))];active=[];groups={}
 while pool and len(active)<active_count:
  choices=[x for x in pool if groups.get(_group(x),0)<2] or pool
  def score(item):
   ref=list(humans)+[x['descriptor'] for x in active]
   diverse=min((_distance(item['descriptor'],other) for other in ref if other),default=1.0)
   uncertainty=1-(item['median_confidence'] if item['median_confidence'] is not None else 1.0)
   return (diverse,uncertainty,-(int(item['image_id'],16) % 997))
  chosen=max(choices,key=score);active.append(chosen);groups[_group(chosen)]=groups.get(_group(chosen),0)+1;pool.remove(chosen)
 remaining=[x for x in ranked if x not in active];rng.shuffle(remaining);controls=[];seen=set()
 for item in remaining:
  if _group(item) not in seen:
   controls.append(item);seen.add(_group(item))
  if len(controls)==random_count:break
 if len(controls)<random_count:
  for item in remaining:
   if item not in controls: controls.append(item)
   if len(controls)==random_count:break
 if len(active)!=active_count or len(controls)!=random_count:raise BatchError('insufficient smart-selection candidates')
 return tuple(active),tuple(controls)
def select_improvement_ranked(project, ranked, seed, count, *, human_descriptors=None):
 """Choose one informative, diverse Improvement batch without random controls."""
 count=int(count)
 if count < 1 or count > len(ranked):raise BatchError('insufficient smart-selection candidates')
 ordered=sorted(ranked,key=lambda x:(x['median_confidence'] if x['median_confidence'] is not None else 1.0,x['image_id']))
 pool=list(ordered[:max(count*6,min(len(ordered),80))]);humans=_human_descriptors(project) if human_descriptors is None else tuple(human_descriptors);selected=[];groups={}
 while pool and len(selected)<count:
  choices=[item for item in pool if groups.get(_group(item),0)<2] or pool
  def score(item):
   references=list(humans)+[chosen['descriptor'] for chosen in selected]
   diversity=min((_distance(item['descriptor'],reference) for reference in references if reference),default=1.0)
   uncertainty=1-(item['median_confidence'] if item['median_confidence'] is not None else 1.0)
   return (diversity,uncertainty,-(int(item['image_id'],16)%997))
  chosen=max(choices,key=score);selected.append(chosen);groups[_group(chosen)]=groups.get(_group(chosen),0)+1;pool.remove(chosen)
 if len(selected)!=count:raise BatchError('insufficient smart-selection candidates')
 return tuple(selected)

def _control_quality_profile(project, model_id):
 path=project.data_root/"ai"/"qc"/"control"/f"{model_id}.json"
 try:
  profile=json.loads(path.read_text(encoding="utf8"))
 except (OSError,json.JSONDecodeError): return None
 return profile if profile.get("model_id")==str(model_id) else None

def _weak_confidence(item, weak_landmark_ids):
 values=[point.get("confidence") for point in item.get("predictions",()) if int(point.get("landmark_id")) in weak_landmark_ids and point.get("confidence") is not None]
 return min(values) if values else 1.0

def select_improvement_weak_aware(project, ranked, seed, count, weak_landmark_ids, *, human_descriptors=None):
 """Select a diverse 30/70 weak-landmark/general Improvement batch."""
 focus_target=round(int(count)*.3);general_target=int(count)-focus_target;weak_ids={int(value) for value in weak_landmark_ids};humans=_human_descriptors(project) if human_descriptors is None else tuple(human_descriptors);selected=[];groups={}
 def take(pool,target,uncertainty):
  pool=list(pool)
  while pool and target:
   choices=[item for item in pool if groups.get(_group(item),0)<2] or pool
   def score(item):
    references=list(humans)+[chosen["descriptor"] for chosen in selected]
    diversity=min((_distance(item["descriptor"],reference) for reference in references if reference),default=1.0)
    return (diversity,uncertainty(item),-(int(item["image_id"],16)%997))
   chosen=max(choices,key=score);selected.append(chosen);groups[_group(chosen)]=groups.get(_group(chosen),0)+1;pool.remove(chosen);target-=1
  return target
 focus_order=sorted(ranked,key=lambda item:(_weak_confidence(item,weak_ids),item["image_id"]))
 missing=take(focus_order[:max(focus_target*6,min(len(focus_order),80))],focus_target,lambda item:1-_weak_confidence(item,weak_ids))
 focus_count=focus_target-missing
 remaining=[item for item in ranked if item not in selected]
 missing=take(sorted(remaining,key=lambda item:(item["median_confidence"] if item["median_confidence"] is not None else 1.0,item["image_id"])),general_target+missing,lambda item:1-(item["median_confidence"] if item["median_confidence"] is not None else 1.0))
 if missing: raise BatchError("insufficient smart-selection candidates")
 return tuple(selected),focus_count,len(selected)-focus_count
def create_improvement_selection(project, model_id, *, count, seed=20260821, excluded_image_ids=(), progress_callback=None, active_model=None, diagnostic_callback=None):
 """Persist a read-only ranking and N-item improvement selection artifact."""
 model,backend=active_backend(project,model=active_model)
 if model['model_id']!=model_id:raise BatchError('requested model is not active')
 snapshot=_readonly_selection_snapshot(project,diagnostic_callback=diagnostic_callback);candidates=_candidate_pool_from_snapshot(project,model,snapshot,excluded_image_ids=excluded_image_ids,diagnostic_callback=diagnostic_callback);diagnostic_callback and diagnostic_callback("CANDIDATES_READY",len(candidates));progress_callback and progress_callback("CANDIDATES",len(candidates),len(candidates));diagnostic_callback and diagnostic_callback("RANK_START");ranked,duration=rank_candidates(project,backend,candidates,progress_callback=(lambda done,total:(diagnostic_callback and diagnostic_callback("RANK_PROGRESS",done,total),progress_callback("SCORING",done,total))[1]) if progress_callback else None);diagnostic_callback and diagnostic_callback("RANK_END");profile=stable_weak_landmark_profile(project,model_id);weak_ids=tuple(profile.get("weak_landmark_ids",())) if profile else ();progress_callback and progress_callback("SELECTING",0,0);diagnostic_callback and diagnostic_callback("DIVERSITY_START");selected,focused_count,general_count=select_improvement_weak_aware(project,ranked,seed,count,weak_ids,human_descriptors=snapshot["human_descriptors"]) if weak_ids else (select_improvement_ranked(project,ranked,seed,count,human_descriptors=snapshot["human_descriptors"]),0,int(count));diagnostic_callback and diagnostic_callback("DIVERSITY_END")
 selection_id=f'{model_id}_improvement_selection_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}_{uuid.uuid4().hex[:8]}';path=project.data_root/'ai'/'selections'/selection_id/'selection.json';path.parent.mkdir(parents=True,exist_ok=False)
 chosen=[{'image_id':item['image_id'],'original_name':item['original_name'],'locality':item['locality'],'sample_id':item['sample_id'],'selection_type':'IMPROVEMENT','selection_focus':'WEAK_LANDMARK' if index<focused_count else 'GENERAL','median_confidence':item['median_confidence'],'low_confidence':item['low_confidence']} for index,item in enumerate(selected)]
 data={'format_version':1,'selection_id':selection_id,'created_at':_now(),'model_id':model_id,'model_dataset_id':model.get('dataset_id'),'schema_sha256':schema_hash(project.schema_path),'candidate_count':len(candidates),'selection_seed':int(seed),'requested_count':int(count),'uncertainty_method':'median landmark confidence only; stability probing skipped','diversity_method':'centred, scale-normalized Procrustes-style farthest-first descriptor','locality_rule':'soft cap of two selected images per locality while alternatives exist','selection_rule':'weak-landmark 30/70 focus/general selection only after two consecutive activated Control Set profiles agree; otherwise uncertainty-ranked pool followed by scale-normalized farthest-first diversity; no random-control images','weak_landmark_ids':list(weak_ids),'weak_landmarks':[] if not profile else profile.get('weak_landmarks',[]),'weak_landmark_focus_count':focused_count,'general_selection_count':general_count,'ranking_seconds':duration,'ranked_candidates':ranked,'selected_images':chosen};atomic_json_write(path,data);return data,path,backend
def create_selection(project, model_id, seed=20260821):
 model,backend=active_backend(project)
 if model['model_id']!=model_id:raise BatchError('requested model is not active')
 candidates=candidate_pool(project,model_id);ranked,duration=rank_candidates(project,backend,candidates);active,controls=select_ranked(project,ranked,seed);selection_id=f'{model_id}_selection_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}_{uuid.uuid4().hex[:8]}';path=project.data_root/'ai'/'selections'/selection_id/'selection.json';path.parent.mkdir(parents=True,exist_ok=False)
 chosen=[]
 for kind,items in (('ACTIVE_SELECTION',active),('RANDOM_CONTROL',controls)):
  for item in items:chosen.append({'image_id':item['image_id'],'original_name':item['original_name'],'locality':item['locality'],'sample_id':item['sample_id'],'selection_type':kind,'median_confidence':item['median_confidence'],'low_confidence':item['low_confidence']})
 data={'format_version':1,'selection_id':selection_id,'created_at':_now(),'model_id':model_id,'model_dataset_id':model.get('dataset_id'),'schema_sha256':schema_hash(project.schema_path),'candidate_count':len(candidates),'selection_seed':seed,'uncertainty_method':'median landmark confidence only; stability probing skipped','diversity_method':'centred, scale-normalized Procrustes-style farthest-first descriptor','ranking_seconds':duration,'ranked_candidates':ranked,'selected_images':chosen};atomic_json_write(path,data);return data,path,backend
def create_batch_from_selection(project, selection_path):
 data=json.loads(Path(selection_path).read_text(encoding='utf8'));batch_id=f"{data['model_id']}_batch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}";path=project.data_root/'ai'/'batches'/batch_id/'manifest.json';path.parent.mkdir(parents=True,exist_ok=False)
 batch={'format_version':1,'batch_id':batch_id,'created_at':_now(),'model_id':data['model_id'],'model_dataset_id':data['model_dataset_id'],'schema_sha256':data['schema_sha256'],'selection_id':data['selection_id'],'selection_rule':'immutable smart selection artifact','selected_images':data['selected_images'],'prediction_runs':{},'failures':{}};atomic_json_write(path,batch);project.set_ui_state('active_ai_batch',batch_id);return batch,path
