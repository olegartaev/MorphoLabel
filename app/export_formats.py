"""Additional transparent Project coordinate exports built from canonical landmark rows."""
import csv, math
from pathlib import Path
from app.landmark_state import load_current_landmark_state
from app.results_export import MISSING_TPS

def group_label(item):
 """Use real schema category first; role is the canonical fallback for older schemes."""
 return str(item.get('category') or item.get('role') or item.get('morphometry_role') or '').strip()
def available_groups(project):return sorted({group_label(item) for item in project.schema if group_label(item)},key=str.casefold)
def _allowed(project,groups):
 selected={str(value) for value in groups if str(value)}
 return [item for item in project.schema if not selected or group_label(item) in selected]

def _morphoj_identifier(image):
 """MorphoJ text identifiers must occupy the first field and be unique."""
 return str(image.get("image_id") or image.get("specimen_id") or image.get("original_name") or "")

def _scale_mm_per_px_text(project,image):
 locality=image.get("locality") or image.get("sample_id")
 calibration=project.locality_calibration(locality) if locality else None
 if not calibration or not calibration.get("scale"):return None
 try:value=1.0/float(calibration["scale"])
 except (TypeError,ValueError,ZeroDivisionError):return None
 return f"{value:.12g}" if math.isfinite(value) and value>0 else None

def _selected_complete_coordinates(project,image_id,schema):
 """Return ordered numeric coordinates when every selected landmark is present."""
 state=load_current_landmark_state(project,image_id);coords=[]
 for item in schema:
  ident=int(item["id"])
  if ident in state.explicitly_missing_ids:return None
  point=state.points_by_id.get(ident) or {}
  try:x=float(point["x_standardized"]);y=float(point["y_standardized"])
  except (KeyError,TypeError,ValueError):return None
  if not (math.isfinite(x) and math.isfinite(y)):return None
  coords.extend((x,y))
 return coords

def _selected_tps_coordinates(project,image_id,schema):
 """TPS coordinates use the original image frame so IMAGE= is truthful."""
 state=load_current_landmark_state(project,image_id);canonical=project.canonical_coordinates(image_id);coords=[]
 for item in schema:
  ident=int(item["id"])
  if ident in state.explicitly_missing_ids:
   coords.append(MISSING_TPS);continue
  point=canonical.get(ident)
  if not point:return None
  try:x=float(point[0]);y=float(point[1])
  except (TypeError,ValueError):return None
  if not (math.isfinite(x) and math.isfinite(y)):return None
  coords.append((x,y))
 return coords
def export_landmark_tps(project,groups=(),filename='landmarks.tps',target=None):
 schema=_allowed(project,groups);target=Path(target) if target else Path(project.results_root)/filename;target.parent.mkdir(parents=True,exist_ok=True);lines=[]
 for image in project.catalog_rows():
  if image.get('excluded'):continue
  coords=_selected_tps_coordinates(project,image['image_id'],schema)
  if coords is None:continue
  lines.append(f'LM={len(schema)}')
  for x,y in coords:lines.append(f'{x:.12g} {y:.12g}')
  lines.extend((f"IMAGE={image.get('original_name','')}",f"ID={image['image_id']}"))
  scale=_scale_mm_per_px_text(project,image)
  if scale:lines.append(f"SCALE={scale}")
  lines.append('')
 target.write_text('\n'.join(lines).rstrip()+'\n' if lines else '',encoding='ascii');return target
def export_landmark_csv_long(project,groups=(),target=None):
 schema=_allowed(project,groups);allowed={int(item['id']) for item in schema};target=Path(target) if target else Path(project.results_root)/'landmarks_long.csv';target.parent.mkdir(parents=True,exist_ok=True);fields=('image_id','locality','filename','landmark_id','category','x_standardized','y_standardized','state','provenance','model_id','confidence','updated_at')
 with target.open('w',encoding='utf-8',newline='') as stream:
  writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();labels={int(item['id']):group_label(item) for item in schema}
  for image in project.catalog_rows():
   if image.get('excluded'):continue
   for ident,point in sorted(project.load_landmarks(image['image_id']).items()):
    if int(ident) in allowed:writer.writerow({'image_id':image['image_id'],'locality':image.get('locality',image.get('sample_id','')),'filename':image.get('original_name',''),'landmark_id':ident,'category':labels.get(int(ident),''),'x_standardized':point.get('x_standardized'),'y_standardized':point.get('y_standardized'),'state':point.get('state'),'provenance':point.get('provenance'),'model_id':point.get('model_id'),'confidence':point.get('confidence'),'updated_at':point.get('updated_at')})
 return target
def export_landmark_wide(project,groups=(),filename='landmarks_wide.csv',delimiter=',',target=None):
 schema=_allowed(project,groups);target=Path(target) if target else Path(project.results_root)/filename;target.parent.mkdir(parents=True,exist_ok=True);fields=['specimen_id']+[item for point in schema for item in (f"x{point['id']}",f"y{point['id']}")]
 with target.open('w',encoding='utf-8',newline='') as stream:
  writer=csv.DictWriter(stream,fieldnames=fields,delimiter=delimiter);writer.writeheader()
  for image in project.catalog_rows():
   if image.get('excluded'):continue
   points=project.load_landmarks(image['image_id']);row={'specimen_id':image.get('specimen_id') or image['image_id']}
   for point in schema:
    saved=points.get(int(point['id']),{});row[f"x{point['id']}"]='' if saved.get('state')=='missing' else saved.get('x_standardized','');row[f"y{point['id']}"]='' if saved.get('state')=='missing' else saved.get('y_standardized','')
   writer.writerow(row)
 return target
def export_morphoj_text(project,groups=(),target=None):
 """MorphoJ row/column text: unique ID first, then ordered numeric X/Y pairs.

 MorphoJ expects the identifier as the first entry of each specimen row and
 coordinate values in x,y order. To keep the file directly importable, rows
 with unresolved or explicitly missing selected landmarks are omitted rather
 than emitting blanks in coordinate columns.
 """
 schema=_allowed(project,groups);target=Path(target) if target else Path(project.results_root)/'landmarks_morphoj.txt';target.parent.mkdir(parents=True,exist_ok=True)
 fields=['ID']+[axis+str(item['id']) for item in schema for axis in ('x','y')]
 with target.open('w',encoding='utf-8',newline='') as stream:
  writer=csv.writer(stream,delimiter='\t',lineterminator='\n');writer.writerow(fields)
  for image in project.catalog_rows():
   if image.get('excluded'):continue
   coords=_selected_complete_coordinates(project,image['image_id'],schema)
   if coords is None:continue
   writer.writerow([_morphoj_identifier(image),*[f'{value:.12g}' for value in coords]])
 return target