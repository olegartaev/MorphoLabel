"""Small shared presentation helpers for persisted finite workflow batches."""

def position_and_remaining(ids,current_id,completed_ids=()):
    ids=tuple(str(i) for i in ids);done={str(i) for i in completed_ids}
    if not ids or str(current_id) not in ids:return {"position":0,"total":len(ids),"remaining":sum(i not in done for i in ids),"final":False}
    position=ids.index(str(current_id))+1
    return {"position":position,"total":len(ids),"remaining":sum(i not in done for i in ids),"final":position==len(ids)}

def compact(status):
    return f"{status['position']} / {status['total']}   Remaining {status['remaining']}"
