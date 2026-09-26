"""Read-only fixed-holdout crop model evaluation."""
from __future__ import annotations
import json, statistics, uuid
from .crop_training import current_label, predict
from .crop_editor_async_v2 import load_project_developed
from .crop_quality import assess_crop
from .project_storage import now

def iou(a,b):
 x1=max(a[0],b[0]);y1=max(a[1],b[1]);x2=min(a[2],b[2]);y2=min(a[3],b[3]);inter=max(0,x2-x1)*max(0,y2-y1);ua=max(0,a[2]-a[0])*max(0,a[3]-a[1])+max(0,b[2]-b[0])*max(0,b[3]-b[1])-inter
 return inter/ua if ua else 0.0
def percentile(values,p):
 if not values:return None
 values=sorted(values);return values[min(len(values)-1,int((len(values)-1)*p))]
def evaluate(project,model_id=None):
 project.reconcile_crop_holdout_references();holdout_id=project.crop_holdout_id();model_id=model_id or current_label(project)
 if not holdout_id:raise ValueError('No clean historical holdout is available. MorphoLabel will automatically reserve future verified crops for evaluation.')
 ready=project.crop_holdout_ready_count(holdout_id)
 if ready<20:raise ValueError(f'Crop evaluation holdout: {ready} / 50. Need {20-ready} more new human-verified crops for provisional evaluation.')
 rows=[]
 seen=project.crop_model_lineage_ids(model_id)
 for entry in project.crop_holdout_images(holdout_id):
  if entry['image_id'] in seen: continue
  ref=project.crop_holdout_reference(entry['image_id'],holdout_id)
  if not ref:continue
  item={**entry,'reference_crop':ref['crop_json'],'model_id':model_id}
  try:
   image,_=load_project_developed(project,entry['image_id']);raw,actual=predict(image,image_id=entry['image_id'],model_id=model_id)
   if raw is None:raise RuntimeError('no active crop model')
   pred=[float(raw[0])*image.width,float(raw[1])*image.height,float(raw[2])*image.width,float(raw[3])*image.height];q=assess_crop(pred,image.width,image.height);item.update(prediction=pred,iou=iou(pred,ref['crop_json']),qc={'green':'OK','yellow':'REVIEW','red':'BAD'}[q.level],failure_reason=None)
  except Exception as exc:item.update(prediction=None,iou=None,qc='BAD',failure_reason=str(exc))
  rows.append(item)
 scores=[r['iou'] for r in rows if r['iou'] is not None];n=len(scores);qc=lambda v:sum(r['qc']==v for r in rows)/len(rows)*100 if rows else 0
 payload={'evaluation_id':'crop-evaluation-'+uuid.uuid4().hex,'holdout_id':holdout_id,'model_id':model_id,'created_at':now(),'evaluation_scope':'Full evaluation' if n>=50 else 'Provisional evaluation','target_holdout_size':50,'n_evaluated':n,'failures':len(rows)-n,'median_iou':statistics.median(scores) if scores else None,'mean_iou':statistics.mean(scores) if scores else None,'p10_iou':percentile(scores,.1),'iou80_pct':sum(x>=.80 for x in scores)/n*100 if n else 0,'iou90_pct':sum(x>=.90 for x in scores)/n*100 if n else 0,'iou95_pct':sum(x>=.95 for x in scores)/n*100 if n else 0,'accept_proxy_pct':sum(x>=.90 for x in scores)/n*100 if n else 0,'qc_ok_pct':qc('OK'),'qc_review_pct':qc('REVIEW'),'qc_bad_pct':qc('BAD'),'images':rows}
 with project.transaction() as c:c.execute("INSERT INTO crop_evaluations VALUES (?,?,?,?,?)",(payload['evaluation_id'],holdout_id,model_id,json.dumps(payload),payload['created_at']))
 return payload
def previous(project,model_id):
 with project.transaction() as c:rows=c.execute("SELECT payload_json FROM crop_evaluations WHERE model_id<>? ORDER BY created_at DESC LIMIT 1",(model_id,)).fetchall()
 return json.loads(rows[0][0]) if rows else None
def comparison(current,prior):
 if not prior:return None
 delta=(current['median_iou'] or 0)-(prior['median_iou'] or 0);bad=current['qc_bad_pct']-prior['qc_bad_pct'];label='Improved' if delta>.01 and bad<=0 else 'Worse' if delta<-.01 or bad>5 else 'Mixed'
 return {'previous_model_id':prior['model_id'],'median_iou_delta':delta,'iou90_pp':current['iou90_pct']-prior['iou90_pct'],'bad_pp':bad,'conclusion':label}
