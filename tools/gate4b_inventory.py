import json
from datetime import datetime,timezone
from pathlib import Path
from collections import Counter
from app.project_storage import Project,schema_hash
p=Project.open(Path('.'));rows=p.catalog_rows();human={'manual','corrected','corrected_by_human','reviewed_by_human'}
manual=[];ai_checked=[];resolved=[];unresolved=[];excluded=[];localities=Counter()
for row in rows:
 image_id=row['image_id']; status=p.annotation_status(image_id);points=p.load_landmarks(image_id)
 if row.get('excluded'): excluded.append(image_id);continue
 (resolved if status['complete'] else unresolved).append(image_id)
 all_human=status['complete'] and all(points.get(int(s['id'])) and (points[int(s['id'])]['state']=='missing' or points[int(s['id'])].get('provenance') in human) for s in p.schema)
 if all_human: manual.append(image_id);localities[str(row.get('locality') or row.get('sample_id') or '')]+=1
 elif status['complete'] and status['verified']: ai_checked.append(image_id)
data={'timestamp':datetime.now(timezone.utc).isoformat(),'project_root':str(p.root),'schema_sha256':schema_hash(p.schema_path),'schema_landmark_count':len(p.schema),'catalog_images':len(rows),'excluded':len(excluded),'fully_resolved_nonexcluded':len(resolved),'fully_manual_eligible':len(manual),'ai_checked_eligible':len(ai_checked),'unresolved_nonexcluded':len(unresolved),'permanent_holdout':len(p.permanent_test_image_ids()),'fully_manual_by_locality':dict(sorted(localities.items())),'fully_manual_image_ids':manual}
out=p.data_root/'ai'/'training'/f"inventory_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(data,indent=2),encoding='utf-8');print(json.dumps({'inventory_path':str(out),'summary':{k:v for k,v in data.items() if k not in {'fully_manual_image_ids','fully_manual_by_locality'}},'by_locality':data['fully_manual_by_locality']},indent=2))
