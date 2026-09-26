"""Read-only diagnostics for one immutable prospective AI batch."""
from __future__ import annotations
import json, math
from .landmark_qc import evaluate_model, prediction_input_identity

def _pct(values,p):
 values=sorted(values);return values[min(len(values)-1,max(0,math.ceil(len(values)*p)-1))] if values else None
def _median(values):return _pct(values,.5)
def _mad(values):
 mid=_median(values);return _median([abs(value-mid) for value in values]) if values else None
def _rank(values):
 ordered=sorted(enumerate(values),key=lambda pair:pair[1]);out=[0.0]*len(values);i=0
 while i<len(ordered):
  j=i+1
  while j<len(ordered) and ordered[j][1]==ordered[i][1]:j+=1
  value=(i+j-1)/2+1
  for index,_ in ordered[i:j]:out[index]=value
  i=j
 return out
def _pearson(left,right):
 if len(left)<2:return None
 lx=sum(left)/len(left);ly=sum(right)/len(right);top=sum((x-lx)*(y-ly) for x,y in zip(left,right));bottom=math.sqrt(sum((x-lx)**2 for x in left)*sum((y-ly)**2 for y in right));return top/bottom if bottom else None
def _spearman(left,right):return _pearson(_rank(left),_rank(right)) if len(left)==len(right) else None
def _slope(x,y):
 if len(x)<2:return None
 mid=sum(x)/len(x);y_mid=sum(y)/len(y);den=sum((value-mid)**2 for value in x);return sum((a-mid)*(b-y_mid) for a,b in zip(x,y))/den if den else None

def evaluate_prospective_batch(project,batch):
 """Compare immutable run manifests to current Checked final rows; never writes Project."""
 ids=[item['image_id'] for item in batch['selected_images']];runs=set(batch['prediction_runs'].values())
 base=evaluate_model(project,batch['model_id'],unseen_only=True,image_ids=ids,prediction_run_ids=runs)
 catalog={row['image_id']:row for row in project.catalog_rows()};errors=[];dx=[];dy=[];confidence=[];predx=[];predy=[];finalx=[];finaly=[];edge=[];widths=[];heights=[];by_landmark={str(i):{'landmark_id':i,'errors':[],'dx':[],'dy':[],'confidence':[],'accepted':0,'corrected':0,'missing_after_prediction':0,'omitted_but_human_present':0} for i in [int(row['id']) for row in project.schema]};by_image=[]
 for image_id in ids:
  run_id=batch['prediction_runs'].get(image_id);path=project.data_root/'ai'/'predictions'/str(run_id)/'manifest.json'
  run=json.loads(path.read_text(encoding='utf8'));matches,reason=prediction_input_identity(project,run)
  if not matches: continue
  points=project.load_landmarks(image_id);returned={int(item['landmark_id']):item for item in run['returned_predictions']};image_errors=[];image_dx=[];image_dy=[];accepted=corrected=missing=omitted=0
  for ident in run['required_landmark_ids']:
   ident=int(ident);bucket=by_landmark[str(ident)];pred=returned.get(ident);current=points.get(ident)
   if pred is None:
    if current and current.get('state')!='missing':bucket['omitted_but_human_present']+=1;omitted+=1
    continue
   if current is None or current.get('state')=='missing':bucket['missing_after_prediction']+=1;missing+=1;continue
   if current.get('prediction_run_id')!=run_id:continue
   delta_x=float(current['x_standardized'])-float(pred['x']);delta_y=float(current['y_standardized'])-float(pred['y']);value=math.hypot(delta_x,delta_y)
   errors.append(value);dx.append(delta_x);dy.append(delta_y);confidence.append(float(pred['confidence']) if pred.get('confidence') is not None else None);predx.append(float(pred['x']));predy.append(float(pred['y']));finalx.append(float(current['x_standardized']));finaly.append(float(current['y_standardized']))
   edge.append(math.hypot(float(pred['x'])-run['standardized_width']/2,float(pred['y'])-run['standardized_height']/2)/math.hypot(run['standardized_width'],run['standardized_height']));widths.append(run['standardized_width']);heights.append(run['standardized_height'])
   bucket['errors'].append(value);bucket['dx'].append(delta_x);bucket['dy'].append(delta_y)
   if pred.get('confidence') is not None:bucket['confidence'].append(float(pred['confidence']))
   if current.get('state')=='auto':accepted+=1;bucket['accepted']+=1
   else:corrected+=1;bucket['corrected']+=1
   image_errors.append(value);image_dx.append(delta_x);image_dy.append(delta_y)
  by_image.append({'image_id':image_id,'image_name':catalog[image_id]['original_name'],'comparable_landmarks':len(image_errors),'median_error_px':_median(image_errors),'p95_error_px':_pct(image_errors,.95),'max_error_px':max(image_errors) if image_errors else None,'accepted_without_correction_fraction':accepted/(accepted+corrected) if accepted+corrected else None,'corrected_count':corrected,'missing_after_prediction':missing,'omitted_but_human_present':omitted,'median_dx':_median(image_dx),'median_dy':_median(image_dy)})
 pairs=[(c,e) for c,e in zip(confidence,errors) if c is not None];pairs.sort(key=lambda item:item[0]);q=max(1,math.ceil(len(pairs)/4));low=[e for _,e in pairs[:q]];high=[e for _,e in pairs[-q:]]
 landmark={key:{'landmark_id':row['landmark_id'],'n':len(row['errors']),'median_error_px':_median(row['errors']),'p95_error_px':_pct(row['errors'],.95),'median_dx':_median(row['dx']),'median_dy':_median(row['dy']),'median_confidence':_median(row['confidence']),'accepted_without_correction_fraction':row['accepted']/(row['accepted']+row['corrected']) if row['accepted']+row['corrected'] else None,'predicted_on_human_missing':row['missing_after_prediction'],'omitted_but_human_present':row['omitted_but_human_present']} for key,row in by_landmark.items()}
 shift=math.hypot(_median(dx) or 0,_median(dy) or 0);spread=math.hypot(_mad(dx) or 0,_mad(dy) or 0);slope_x=_slope(predx,finalx);slope_y=_slope(predy,finaly)
 diagnostics={'global_median_dx':_median(dx),'global_median_dy':_median(dy),'global_mad_dx':_mad(dx),'global_mad_dy':_mad(dy),'global_shift_magnitude':shift,'global_shift_mad_magnitude':spread,'spearman_error_vs_predicted_x':_spearman(errors,predx),'spearman_error_vs_predicted_y':_spearman(errors,predy),'spearman_error_vs_width':_spearman(errors,widths),'spearman_error_vs_height':_spearman(errors,heights),'spearman_error_vs_edge_distance':_spearman(errors,edge),'final_vs_prediction_slope_x':slope_x,'final_vs_prediction_slope_y':slope_y,'median_error_px_if_xy_swapped':_median([math.hypot(y-a,x-b) for x,y,a,b in zip(predx,predy,finalx,finaly)])}
 common_translation=bool(shift>=20 and spread<=shift*.5 and slope_x is not None and slope_y is not None and abs(slope_x-1)<=.15 and abs(slope_y-1)<=.15)
 diagnostics['common_translation_evidence']=common_translation;diagnostics['coordinate_pattern']='likely_common_translation' if common_translation else 'no_strong_common_translation'
 result=dict(base);result.update({'batch_id':batch['batch_id'],'batch_manifest_selection':ids,'metric_definitions':{'error_px':'Euclidean distance between immutable returned prediction and current Checked final standardized coordinates','dx':'human_final_x - ai_predicted_x','dy':'human_final_y - ai_predicted_y','confidence':'immutable RTMPose output confidence; no threshold applied'},'per_landmark':landmark,'per_image':sorted(by_image,key=lambda row:(row['median_error_px'] or -1),reverse=True),'signed_coordinate_diagnostics':diagnostics,'confidence_diagnostics':{'spearman_confidence_vs_error':_spearman([c for c,_ in pairs],[e for _,e in pairs]),'lowest_confidence_quartile_n':len(low),'lowest_confidence_quartile_median_error_px':_median(low),'highest_confidence_quartile_n':len(high),'highest_confidence_quartile_median_error_px':_median(high)},'human_final_snapshot':base['per_image'],'input_changed_after_prediction':base.get('input_changed_after_prediction',[])})
 return result