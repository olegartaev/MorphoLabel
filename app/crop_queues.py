"""Keep unfinished finite Crop queues until explicit close or completion."""
import uuid


def replace_batch(project,key,state):
 old=dict(project.get_ui_state(key,{}) or {});state=dict(state)
 saved=list(project.get_ui_state(key+'_saved',[]) or [])
 members=old.get('ids') or old.get('image_ids') or old.get('issues') or old.get('items')
 if members and not old.get('finished') and not old.get('complete') and old.get('active') is not False:
  old.setdefault('queue_id',uuid.uuid4().hex)
  saved=[item for item in saved if item.get('queue_id')!=old['queue_id']]
  saved.append(old)
 # Allocate archive identities only when needed. A first queue keeps the
 # legacy state shape, without creating an empty archive record.
 missing=object()
 if saved or project.get_ui_state(key+'_saved',missing) is not missing:project.set_ui_state(key+'_saved',saved)
 project.set_ui_state(key,state)
 return state


def saved_batches(project,key):return tuple(project.get_ui_state(key+'_saved',[]) or [])


def open_saved_batch(project,key,queue_id):
 saved=list(saved_batches(project,key));target=next((x for x in saved if x.get('queue_id')==queue_id),None)
 if target is None:return None
 project.set_ui_state(key+'_saved',[x for x in saved if x.get('queue_id')!=queue_id])
 return replace_batch(project,key,target)


def close_saved_batch(project,key,queue_id):
 project.set_ui_state(key+'_saved',[x for x in saved_batches(project,key) if x.get('queue_id')!=queue_id])
