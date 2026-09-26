"""One GUI-independent validation result for the current landmark annotation."""
from __future__ import annotations
from dataclasses import dataclass
from .landmark_review import review_warnings

HARD_KINDS=frozenset({"unresolved","nonfinite","bounds","orphan","duplicate"})

@dataclass(frozen=True)
class AnnotationCheckResult:
 image_id:str
 hard:tuple
 suspicious:tuple
 @property
 def normal(self): return not self.hard and not self.suspicious


def check_annotation(project,image_id,width,height,dimensions_by_id=None):
 """Classify existing structural/review findings without changing any annotation."""
 findings=review_warnings(project,image_id,width,height,dimensions_by_id)
 hard=[];suspicious=[]
 for finding in findings:
  if finding.get("kind") in HARD_KINDS: hard.append(finding)
  elif not project.review_warning_is_accepted(image_id,finding): suspicious.append(finding)
 return AnnotationCheckResult(str(image_id),tuple(hard),tuple(suspicious))
