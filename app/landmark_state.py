"""Canonical, SQLite-backed landmark state for one Project image."""
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType

_HUMAN_PROVENANCE=frozenset({"manual","corrected","corrected_by_human","reviewed_by_human"})

def landmark_needs_ai_review(row):
 return row.get("provenance")=="machine" and not bool(row.get("reviewed"))

@dataclass(frozen=True)
class CurrentLandmarkState:
 image_id:str
 schema_ids:frozenset[int]
 points_by_id:MappingProxyType
 present_ids:frozenset[int]
 explicitly_missing_ids:frozenset[int]
 resolved_ids:frozenset[int]
 unresolved_ids:frozenset[int]
 missing_ids:frozenset[int]
 extra_ids:frozenset[int]
 human_ids:frozenset[int]
 human_verified:bool
 color:str

 @property
 def expected_count(self): return len(self.schema_ids)
 @property
 def placed_count(self): return len(self.present_ids)
 @property
 def resolved_count(self): return len(self.resolved_ids)
 @property
 def complete(self): return not self.unresolved_ids
 @property
 def all_required_human(self): return self.complete and self.present_ids <= self.human_ids
 @property
 def fingerprint(self):
  rows=tuple((ident,tuple(sorted(dict(row).items()))) for ident,row in sorted(self.points_by_id.items()))
  return (self.image_id,tuple(sorted(self.schema_ids)),rows,self.human_verified)

 @classmethod
 def load(cls,project,image_id):
  schema_ids=frozenset(int(row["id"]) for row in project.schema)
  source=project.load_landmarks(image_id)
  points=MappingProxyType({int(ident):MappingProxyType(dict(row)) for ident,row in source.items()})
  present=frozenset(ident for ident,row in points.items() if row.get("state")!="missing" and row.get("x_standardized") is not None and row.get("y_standardized") is not None) & schema_ids
  explicitly_missing=frozenset(ident for ident,row in points.items() if row.get("state")=="missing") & schema_ids
  resolved=present | explicitly_missing
  unresolved=schema_ids-resolved
  missing=unresolved # backward-compatible alias: only unresolved landmarks block completion
  extras=frozenset(points)-schema_ids
  human=frozenset(ident for ident,row in points.items() if ident in schema_ids and ident in present and row.get("provenance") in _HUMAN_PROVENANCE)
  pending_ai=any(landmark_needs_ai_review(row) for row in points.values())
  with project.transaction() as c:
   row=c.execute("SELECT human_verified FROM image_review WHERE image_id=?",(image_id,)).fetchone()
   crop_review=c.execute("SELECT 1 FROM image_attributes WHERE image_id=? AND attribute_key IN ('landmark_crop_review_required','landmark_scheme_review_required') AND lower(value)='true'",(image_id,)).fetchone()
   draft=c.execute("SELECT 1 FROM annotation_drafts WHERE image_id=?",(image_id,)).fetchone()
  needs_review=bool(crop_review) or pending_ai or bool(draft)
  verified=bool(schema_ids) and not unresolved and (bool(row[0]) if row else False) and not needs_review
  confirmation=getattr(project,"_landmark_ai_confirmation_matches",None)
  if verified and confirmation and any(row.get("provenance")=="machine" for row in points.values()):verified=confirmation(image_id)
  color="red" if unresolved else "green" if verified else "yellow"
  return cls(str(image_id),schema_ids,points,present,explicitly_missing,resolved,unresolved,missing,extras,human,verified,color)

def load_current_landmark_state(project,image_id):
 return CurrentLandmarkState.load(project,image_id)
