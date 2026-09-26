from pathlib import Path
from app.project_storage import Project,schema_hash
from app.rtmpose_backend import RTMPoseBackend,RTMPoseModelSpec
from app.landmark_ai_service import LandmarkAIService
p=Project.open(Path('data/ai/gate4a_smoke/project/gate4a-smoke'));a=p.data_root/p.model_metadata('rtmpose_smoke_v001')['path'];image=p.catalog_rows()[1]['image_id'];p.replace_landmarks(image,{'2':p.load_landmarks(image)[2]});before=p.load_landmarks(image)[2].copy();b=RTMPoseBackend(RTMPoseModelSpec('rtmpose_smoke_v001',schema_hash(p.schema_path),a/'config.py',a/'epoch_20.pth'));r=LandmarkAIService(p,b).predict_one(image);after=p.load_landmarks(image);assert after[2]['provenance']=='manual' and after[2]['x_standardized']==before['x_standardized'];assert after[5]['provenance']=='machine' and after[11]['provenance']=='machine';print({'saved':r.saved_landmarks,'skipped':r.skipped_human_landmarks,'manual_protected':True,'run':r.prediction_run_id})
