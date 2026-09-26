"""Small authoritative mutations for persisted finite Crop batches."""

def remove_crop_batch_member(project, image_id, current_image_id=None):
    """Remove one member without applying an unsaved crop; choose its batch neighbour."""
    state=dict(project.get_ui_state("crop_active_batch", {}) or {})
    ids=[str(value) for value in state.get("ids", ())]
    image_id=str(image_id)
    current_id=str(current_image_id) if current_image_id is not None else None
    if image_id not in ids:
        return state, current_id, not ids
    old_index=ids.index(image_id)
    ids.pop(old_index)
    state["ids"]=ids
    for key in ("prepared_ids", "completed_ids"):
        state[key]=[str(value) for value in state.get(key, ()) if str(value) in ids]
    proposals=dict(state.get("proposals", {}) or {})
    proposals.pop(image_id, None)
    state["proposals"]=proposals
    if current_id in ids:
        target=current_id
    elif ids:
        target=ids[min(old_index, len(ids)-1)]
    else:
        target=None
    state["position"]=ids.index(target) if target in ids else 0
    if not ids:
        state["completion_announced"]=False
    project.set_ui_state("crop_active_batch",state)
    return state,target,not bool(ids)