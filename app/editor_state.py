"""Single authoritative landmark selection state."""
from dataclasses import dataclass
from .landmark_ids import number_from_id
@dataclass
class EditorState:
 point_count:int=25
 current_landmark:int=1
 point_ids:tuple|None=None
 def __post_init__(self):
  if self.point_ids is None:self.point_ids=tuple(range(1,self.point_count+1))
  else:self.point_ids=tuple(sorted(self.point_ids));self.point_count=len(self.point_ids);self.current_landmark=self.point_ids[0]
 def open_record(self,record):
  present={number_from_id(key) for key in record.get("points",{})};self.current_landmark=next((n for n in self.point_ids if n not in present),self.point_ids[0]);return self.current_landmark
 def select(self,number):
  self.current_landmark=number if number in self.point_ids else self.point_ids[0];return self.current_landmark
 def _advance(self):
  i=self.point_ids.index(self.current_landmark);self.current_landmark=self.point_ids[min(i+1,len(self.point_ids)-1)];return self.current_landmark
 def after_missing(self):return self._advance()
 def after_place_new(self,was_existing):return self.current_landmark if was_existing else self._advance()
