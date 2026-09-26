"""Current opened Project context, isolated per worker thread."""
from contextlib import contextmanager
from pathlib import Path
import threading
from .project_storage import Project
from .landmark_state import load_current_landmark_state

_state=threading.local()

def open_project(root):
 project=root if isinstance(root,Project) else Project.open(root)
 _state.active=project
 return project

def active_project():
 return getattr(_state,'active',None)

@contextmanager
def scoped_project(root):
 """Temporarily activate a Project for an existing Project-aware operation."""
 previous=active_project()
 try:yield open_project(root)
 finally:_state.active=previous

def rows(project=None):
 p=project or active_project()
 if not p:return None
 return [r | {'source_path':str(p.source_root/r['relative_path']),'source_relpath':r['relative_path']} for r in p.catalog_rows()]
def landmark_state(project,image_or_id):
 p=project or active_project();image_id=image_or_id['image_id'] if isinstance(image_or_id,dict) else image_or_id
 return load_current_landmark_state(p,image_id)
def record(project,image):
 p=project or active_project()
 if not p:return None
 points={str(i):{'landmark_id':str(i),'point_number':i,'point_code':'','state':v['state'],'provenance':v.get('provenance',v['state']),'x_standardized':v['x_standardized'],'y_standardized':v['y_standardized'],'final_x':v['x_standardized'],'final_y':v['y_standardized'],'model_id':v['model_id'],'predicted_x':v['predicted_x'],'predicted_y':v['predicted_y'],'confidence':v['confidence'],'prediction_run_id':v.get('prediction_run_id'),'reviewed':bool(v['reviewed']),'timestamp':v['updated_at']} for i,v in p.load_landmarks(image['image_id']).items()}
 return {'image_id':image['image_id'],'sample_id':image['sample_id'],'source_relpath':image['relative_path'],'source_sha256':image.get('source_sha256'),'human_verified':bool(image.get('human_verified',False)),'points':points}
def save(project,record):project.replace_landmarks(record['image_id'],record.get('points',{}))