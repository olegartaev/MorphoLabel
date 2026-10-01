"""Shared policy for deciding which landmark slots AI may update."""
from __future__ import annotations

HUMAN_PROTECTED_PROVENANCE=frozenset({
 "manual","corrected","corrected_by_human","reviewed_by_human","missing",
})

def human_landmark_protected(row):
 """True when a current landmark state must never be overwritten by AI."""
 if not row:return False
 return row.get("state")=="missing" or row.get("provenance") in HUMAN_PROTECTED_PROVENANCE

def ai_editable_landmark_ids(project,image_id):
 """Required landmark IDs that AI may fill/refresh without touching human work."""
 rows=project.load_landmarks(str(image_id))
 required=tuple(int(item["id"]) for item in project.schema)
 return tuple(ident for ident in required if not human_landmark_protected(rows.get(ident)))

def ai_editable_unresolved_landmark_ids(project,image_id):
 """Unresolved required IDs for which a new AI prediction can actually help."""
 rows=project.load_landmarks(str(image_id));result=[]
 for ident in (int(item["id"]) for item in project.schema):
  row=rows.get(ident)
  if human_landmark_protected(row):continue
  resolved=bool(row and row.get("state")!="missing" and row.get("x_standardized") is not None and row.get("y_standardized") is not None)
  if not resolved:result.append(ident)
 return tuple(result)

def landmark_prediction_needed(project,image_id):
 """Whether AI has at least one editable slot and the image is not prediction-locked."""
 image_id=str(image_id)
 if project.landmark_prediction_locked(image_id):return False
 return bool(ai_editable_landmark_ids(project,image_id))
