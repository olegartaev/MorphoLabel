import json
from pathlib import Path
from app.project_storage import Project, schema_hash
from app.rtmpose_backend import RTMPoseBackend,RTMPoseModelSpec
from app.landmark_ai_service import LandmarkAIService
root=Path('data/ai/gate4a_smoke/project/gate4a-smoke').resolve();p=Project.open(root);model=p.model_metadata('rtmpose_smoke_v001');artifact=p.data_root/model['path'];rows=p.catalog_rows();image=rows[0]['image_id']
# Clear canonical labels only for true AI write test; this temporary Project preserves the immutable dataset snapshot.
p.replace_landmarks(image,{})
spec=RTMPoseModelSpec('rtmpose_smoke_v001',schema_hash(p.schema_path),artifact/'config.py',artifact/'epoch_20.pth')
result=LandmarkAIService(p,RTMPoseBackend(spec)).predict_one(image)
loaded=p.load_landmarks(image);out={'result':{'saved':result.saved_landmarks,'run':result.prediction_run_id,'manifest':str(result.manifest_path)},'landmarks':loaded,'human_verified':p.annotation_status(image)['verified']}
Path('data/ai/gate4a_smoke/inference_result.json').write_text(json.dumps(out,indent=2,default=str),encoding='utf-8');print(json.dumps(out,indent=2,default=str))
