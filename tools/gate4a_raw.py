from pathlib import Path
from app.project_storage import Project,schema_hash
from app.rtmpose_backend import RTMPoseBackend,RTMPoseModelSpec
from app.landmark_ai_service import LandmarkAIService
p=Project.open(Path('data/ai/gate4a_smoke/project/gate4a-smoke'));a=p.data_root/p.model_metadata('rtmpose_smoke_v001')['path'];image=p.catalog_rows()[0]['image_id'];b=RTMPoseBackend(RTMPoseModelSpec('rtmpose_smoke_v001',schema_hash(p.schema_path),a/'config.py',a/'epoch_20.pth'));print(b.predict(LandmarkAIService(p,b)._request(image)))
