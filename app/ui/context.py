"""Cached UI-only view state; Project remains the scientific authority."""
from dataclasses import dataclass, field
from app.project_storage import Project
from app.landmark_dataset import v2_human_final_eligible, v2_human_final_eligible_image_ids, model_seen_image_ids, model_training_state_fingerprints, current_training_state_fingerprint, current_training_state_fingerprints, training_ready_image_ids

_KEYS = ("Manual", "Auto", "Checked", "Remaining", "Needs review")
_LANDMARK_KEYS = ("Human reviewed / Checked", "Remaining", "Train ready")


def _training_seen_image_ids(project):
 """Images already represented in the compatible active model lineage.

 A stale active flag can remain after the landmark schema changes.  Header
 counters are UI state and must never make the whole Landmarks workspace fail
 just because that older model is no longer compatible.
 """
 try:active=project.active_model_readonly("landmark") or {}
 except ValueError:return set()
 model_id=active.get("model_id")
 if not model_id:return set()
 try:return set(model_seen_image_ids(project,model_id))
 except Exception:return set()

def _training_ready_image_ids(project):
 """Human-final images whose current labels/Crop are new relative to the active lineage."""
 return set(training_ready_image_ids(project))


@dataclass
class UIContext:
 project: Project | None = None
 section: str = "project"
 selected: int = 0
 rows: list = field(default_factory=list)
 _catalog_valid: bool = False
 _counts_cache: dict | None = None
 _image_classification: dict = field(default_factory=dict)
 _landmark_counts_cache: dict | None = None
 _landmark_classification: dict = field(default_factory=dict)
 _permanent_ids: frozenset = field(default_factory=frozenset)
 _landmark_seen_ids: frozenset = field(default_factory=frozenset)
 _landmark_model_fingerprints: dict = field(default_factory=dict)
 def refresh(self, force=False):
  current_id=(self.current() or {}).get("image_id")
  if self.project and (force or not self._catalog_valid):
   self.rows=list(self.project.catalog_rows());self._catalog_valid=True;self._counts_cache=None;self._image_classification.clear()
   self._landmark_counts_cache=None;self._landmark_classification.clear();self._permanent_ids=self.project.permanent_test_image_ids()
  if not self.project:self.rows=[]
  if current_id:
   index=next((i for i,row in enumerate(self.rows) if row.get("image_id")==current_id),None)
   if index is not None:self.selected=index
  self.selected=min(self.selected,max(0,len(self.rows)-1));return self.rows
 def select_image(self,image_id):
  image_id=str(image_id)
  index=next((i for i,row in enumerate(self.rows) if str(row.get("image_id"))==image_id),None)
  if index is None:return False
  self.selected=index;return True
 def invalidate_catalog(self):
  self._catalog_valid=False;self._counts_cache=None;self._image_classification.clear();self._landmark_counts_cache=None;self._landmark_classification.clear()
 def invalidate_counts(self):
  self._counts_cache=None;self._image_classification.clear();self._landmark_counts_cache=None;self._landmark_classification.clear();self._landmark_seen_ids=frozenset();self._landmark_model_fingerprints={}
 def refresh_landmark_state(self,image_id):
  """Replace one cached landmark row from Project authority after a persisted edit."""
  if not self.project:return False
  fresh=self.project.catalog_row(image_id)
  if fresh is None:return False
  for index,row in enumerate(self.rows):
   if row.get("image_id")==image_id:
    self.rows[index]=fresh;return True
  return False
 def refresh_crop_state(self,image_id):
  if not self.project:return False
  row=next((item for item in self.rows if item.get('image_id')==image_id),None)
  if row is None:return False
  row['has_crop']=bool(self.project.landmark_crop_ready(image_id));self.invalidate_counts();return True
 def current(self):return self.rows[self.selected] if self.rows else None
 def navigate(self,step):
  if self.rows:self.selected=(self.selected+int(step))%len(self.rows)
  return self.current()
 def search(self,text):
  q=str(text or '').casefold();return [r for r in self.rows if q in str(r.get('original_name','')).casefold() or q in str(r.get('locality',r.get('sample_id',''))).casefold()]
 def crop_enabled(self):return bool(self.project and self.project.get_ui_state('crop_enabled',True))
 def set_crop_enabled(self,enabled):
  if self.project:self.project.set_ui_state('crop_enabled',bool(enabled))
 def _classify(self,row):
  points=self.project.load_landmarks(row['image_id']);crop=self.project.crop_record(row['image_id']) or {};status=self.project.annotation_status(row['image_id'])
  return {'Manual':bool(points) and any(p.get('provenance') in {'manual','corrected','corrected_by_human','reviewed_by_human'} for p in points.values()),'Auto':any(p.get('provenance','').startswith('ai_') for p in points.values()) or crop.get('provenance')=='ai_unreviewed','Checked':bool(status.get('human_verified')),'Remaining':bool(status.get('unresolved_ids')),'Needs review':crop.get('qc_level') in {'BAD','REVIEW'}}
 def counts(self):
  if not self.project:return {'Total':0,**{key:0 for key in _KEYS}}
  if self._counts_cache is None:
   self._image_classification={row['image_id']:self._classify(row) for row in self.rows}
   self._counts_cache={'Total':len(self.rows),**{key:sum(int(flags[key]) for flags in self._image_classification.values()) for key in _KEYS}}
  return self._counts_cache
 def update_image_counts(self,image_id=None):
  """Delta-update header counters after one edit; never rescan the catalog."""
  if self._counts_cache is None:return self.counts()
  target=image_id or (self.current() or {}).get('image_id');row=next((item for item in self.rows if item['image_id']==target),None)
  if not row:return self._counts_cache
  old=self._image_classification.get(target,{key:False for key in _KEYS});new=self._classify(row)
  for key in _KEYS:self._counts_cache[key]+=int(new[key])-int(old[key])
  self._image_classification[target]=new;return self._counts_cache
 def _classify_landmark(self,row):
  """Exact v2 trainer predicate from this already-authoritative catalog row."""
  unresolved=bool(row.get('missing_ids') or row.get('extra_ids') or row.get('placed',0)<row.get('expected_landmarks',0))
  checked=bool(row.get('human_verified'))
  ready=row.get('image_id') in getattr(self,'_landmark_ready_ids',set())
  return {'Human reviewed / Checked':checked,'Remaining':unresolved,'Train ready':ready}
 def landmark_counts(self):
  if not self.project:return {'Total':0,**{key:0 for key in _LANDMARK_KEYS}}
  if self._landmark_counts_cache is None:
   self._permanent_ids=self.project.permanent_test_image_ids()
   try:active=self.project.active_model_readonly("landmark") or {}
   except ValueError:active={}
   model_id=active.get("model_id")
   try:self._landmark_model_fingerprints=model_training_state_fingerprints(self.project,model_id) if model_id else {}
   except Exception:self._landmark_model_fingerprints={}
   self._landmark_seen_ids=frozenset(self._landmark_model_fingerprints)
   eligible=set(v2_human_final_eligible_image_ids(self.project))
   current_fingerprints=current_training_state_fingerprints(self.project,eligible)
   self._landmark_ready_ids={image_id for image_id in eligible if self._landmark_model_fingerprints.get(str(image_id))!=current_fingerprints.get(str(image_id))}
   self._landmark_classification={row['image_id']:self._classify_landmark(row) for row in self.rows}
   included={row['image_id'] for row in self.rows if not row.get('excluded')}
   self._landmark_counts_cache={'Total':len(included),**{key:sum(int(flags[key]) for image_id,flags in self._landmark_classification.items() if image_id in included) for key in _LANDMARK_KEYS}}
  return self._landmark_counts_cache
 def update_landmark_counts(self,image_id=None):
  """One-row delta only: never catalogue/status scan after a landmark gesture."""
  if self._landmark_counts_cache is None:return self.landmark_counts()
  target=image_id or (self.current() or {}).get('image_id');row=next((item for item in self.rows if item.get('image_id')==target),None)
  if not row:return self._landmark_counts_cache
  ready=(v2_human_final_eligible(self.project,target) and self._landmark_model_fingerprints.get(str(target))!=current_training_state_fingerprint(self.project,str(target)))
  if ready:self._landmark_ready_ids.add(target)
  else:self._landmark_ready_ids.discard(target)
  old=self._landmark_classification.get(target,{key:False for key in _LANDMARK_KEYS});new=self._classify_landmark(row)
  if not row.get('excluded'):
   for key in _LANDMARK_KEYS:self._landmark_counts_cache[key]+=int(new[key])-int(old[key])
  self._landmark_classification[target]=new;return self._landmark_counts_cache
