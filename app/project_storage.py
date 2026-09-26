"""Portable SQLite project storage; cache is never the scientific source of truth."""
from __future__ import annotations
import csv, hashlib, json, shutil, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .io import read_json
from .manifest import sha256
from .profile import read_schema_csv

PROJECT_FILE="project.yaml"; SCHEMA_FILE="landmark_schema.csv"; DATABASE_FILE="project.sqlite"
SUPPORTED_SOURCE_TYPES={"nef":".nef","jpg":".jpg","jpeg":".jpeg","png":".png","tif":".tif","tiff":".tiff"}
EXCLUDED_DIR_NAMES={"_points","png","bad","cache","output","outputs","reference","references","work","standardized","developed_full"}

def natural_key(value):
 import re
 return tuple(int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)",str(value)))
def now(): return datetime.now(timezone.utc).isoformat()
def schema_hash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def landmark_schema_identity(rows):
 return tuple(str(row.get("abbr") or "").strip() for row in rows)
def landmark_model_schema_compatible(project, model):
 """Return whether a stored landmark model has the same ordered landmark identities.

 Raw CSV bytes are retained as immutable provenance, but display names,
 categories, roles or harmless CSV formatting must not disable a model whose
 output indices still map to the same ordered landmark abbreviations.
 """
 if not model or model.get("kind")!="landmark":return False
 if model.get("schema_sha256")==schema_hash(project.schema_path):return True
 manifest_path=model.get("dataset_manifest_path")
 if not manifest_path:return False
 path=Path(manifest_path);path=path if path.is_absolute() else project.data_root/path
 try:
  manifest=json.loads(path.read_text(encoding="utf-8"))
  stored=landmark_schema_identity(manifest.get("schema_landmarks") or ())
 except (OSError,json.JSONDecodeError,TypeError):
  return False
 current=landmark_schema_identity(load_schema(project.schema_path))
 return bool(stored) and stored==current
def schema_file_signature(path):
 st=Path(path).stat();return (st.st_mtime_ns,st.st_size)
def _json(path,data): Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
def schema_migration_backup(project):
 stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ");folder=project.root/"backups"/f"schema_identity_{stamp}";folder.mkdir(parents=True,exist_ok=False)
 manifest={"created_at":now(),"files":[]}
 for source in (project.path,project.schema_path):
  if source.exists():
   target=folder/source.name;shutil.copy2(source,target);manifest["files"].append({"path":str(target.relative_to(project.root)),"sha256":sha256(target)})
 (folder/"migration.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8");return folder
def load_schema(path):
 """CSV row order is display order; abbreviation is the stable identity."""
 delimiter,fieldnames,raw_rows=read_schema_csv(path)
 if not {"abbr","name"}.issubset(fieldnames): raise ValueError("landmark schema requires columns: abbr, name, role")
 rows=[];abbrs=set();allowed={"CLASSICAL","GM","BOTH"}
 for line_number,row in enumerate(raw_rows,start=2):
  abbr=(row.get("abbr") or "").strip();name=(row.get("name") or "").strip();role=(row.get("role") or "BOTH").strip().upper()
  if not abbr or not name: raise ValueError(f"landmark schema row {line_number}: abbreviation and name must be non-empty")
  if abbr in abbrs: raise ValueError(f"duplicate landmark abbreviation: {abbr}")
  if role not in allowed: raise ValueError(f"landmark schema row {line_number}: invalid role {role!r}; expected CLASSICAL, GM or BOTH")
  abbrs.add(abbr);rows.append({"id":len(rows)+1,"abbr":abbr,"name":name,"role":role,"category":(row.get("category") or "").strip()})
 return rows
class Project:
 def __init__(self,root):
  self.root=Path(root);self.data_root=self.root/"project_data" if (self.root/"project_data").is_dir() else self.root;self.path=self.data_root/DATABASE_FILE;self.config_path=self.root/PROJECT_FILE;self.schema_path=self.root/SCHEMA_FILE;self._orphan_warned=set();self._schema_cache=None;self._schema_cache_signature=None;self._schema_error=None
 def resolve_data_path(self,value,default=""):
  """Resolve current cache-relative and legacy project_data-prefixed paths."""
  path=Path(str(value or default))
  if path.is_absolute():return path
  if path.parts and path.parts[0].casefold()==self.data_root.name.casefold():return self.root/path
  return self.data_root/path
 @property
 def cache_root(self): return self.data_root/"cache"
 @property
 def models_root(self): return self.data_root/"models"
 @property
 def results_root(self): return self.root/"results"
 @classmethod
 def create(cls,name,source_root,destination,schema_csv=None,source_types=None,source_image_subfolder="orig",source_layout=None):
  source_root=Path(source_root).resolve();destination=Path(destination).resolve();schema=load_schema(Path(schema_csv).resolve()) if schema_csv else [];root=destination/name
  if source_layout is None: source_layout="subfolder" if any(p.is_dir() and p.name.casefold()==str(source_image_subfolder).casefold() for loc in source_root.iterdir() if loc.is_dir() for p in loc.iterdir()) else "direct"
  if root.exists() and any(root.iterdir()): raise FileExistsError(f"project directory is not empty: {root}")
  root.mkdir(parents=True,exist_ok=True)
  for folder in ("project_data/cache/developed","project_data/cache/standardized","project_data/models","results"): (root/folder).mkdir(parents=True,exist_ok=True)
  (shutil.copy2(schema_csv,root/SCHEMA_FILE) if schema_csv else (root/SCHEMA_FILE).write_text("id,abbr,name,role"+chr(10),encoding="utf-8"));project=cls(root);_json(project.config_path,{"format_version":1,"name":name,"source_root":str(source_root),"source_layout":source_layout,"source_image_subfolder":source_image_subfolder if source_layout=="subfolder" else "","schema_sha256":schema_hash(project.schema_path),"created_at":now()});chosen=project.choose_source_types(source_types);_json(project.config_path,{"format_version":1,"name":name,"source_root":str(source_root),"source_layout":source_layout,"source_image_subfolder":source_image_subfolder if source_layout=="subfolder" else "","source_types":chosen,"schema_sha256":schema_hash(project.schema_path),"created_at":now()});project.initialize(schema);project.scan_originals(source_types=chosen);return project
 @classmethod
 def open(cls,root):
  project=cls(root)
  if not project.path.exists() or not project.config_path.exists() or not project.schema_path.exists(): raise FileNotFoundError("not a Morphology Pipeline project")
  project._schema_cache_signature=schema_file_signature(project.schema_path)
  try: project._schema_cache=load_schema(project.schema_path)
  except Exception as exc: project._schema_cache=[];project._schema_error=exc
  project.ensure_schema();project._sync_schema_hash_metadata();project._refresh_source_availability();project._sync_auto_verified_images();return project
 @property
 def schema_error(self): return self._schema_error
 @property
 def config(self): return json.loads(self.config_path.read_text(encoding="utf-8"))
 @property
 def source_root(self): return Path(self.config["source_root"])
 @property
 def schema(self):
  signature=schema_file_signature(self.schema_path)
  if self._schema_cache is not None and signature==self._schema_cache_signature:return self._schema_cache
  try: parsed=load_schema(self.schema_path)
  except Exception as exc:
   self._schema_error=exc
   if self._schema_cache is not None:return self._schema_cache
   raise
  self._schema_cache=parsed;self._schema_cache_signature=signature;self._schema_error=None
  return parsed
 def ensure_schema(self):
  with self.transaction() as c:
   legacy_landmark_columns={r[1] for r in c.execute("PRAGMA table_info(landmarks)")}; legacy_landmark_rows=c.execute("SELECT COUNT(*) FROM landmarks").fetchone()[0]
  if legacy_landmark_columns and legacy_landmark_rows and "landmark_abbr" not in legacy_landmark_columns: schema_migration_backup(self)
  self.reconcile_landmark_schema()
  with self.transaction() as c:
   cols={r[1] for r in c.execute("PRAGMA table_info(images)")}
   for name,definition in (("active","INTEGER NOT NULL DEFAULT 1"),("locality","TEXT"),("index_in_locality","INTEGER"),("total_in_locality","INTEGER"),("specimen_id","TEXT"),("excluded","INTEGER NOT NULL DEFAULT 0"),("exclusion_reason","TEXT"),("exclusion_note","TEXT")):
    if name not in cols: c.execute(f"ALTER TABLE images ADD COLUMN {name} {definition}")
   c.execute("UPDATE images SET specimen_id=image_id WHERE specimen_id IS NULL")
   model_cols={r[1] for r in c.execute("PRAGMA table_info(models)")}
   for name,definition in (("dataset_id","TEXT"),("parent_model_id","TEXT"),("dataset_manifest_path","TEXT")):
    if name not in model_cols: c.execute(f"ALTER TABLE models ADD COLUMN {name} {definition}")
   landmark_cols={r[1] for r in c.execute("PRAGMA table_info(landmarks)")}
   if "prediction_run_id" not in landmark_cols: c.execute("ALTER TABLE landmarks ADD COLUMN prediction_run_id TEXT")
   if "landmark_abbr" not in landmark_cols: c.execute("ALTER TABLE landmarks ADD COLUMN landmark_abbr TEXT")
   c.execute("UPDATE landmarks SET landmark_abbr=(SELECT abbr FROM landmark_schema s WHERE s.landmark_id=landmarks.landmark_id) WHERE landmark_abbr IS NULL")
   correction_cols={r[1] for r in c.execute("PRAGMA table_info(corrections)")}
   if "landmark_abbr" not in correction_cols: c.execute("ALTER TABLE corrections ADD COLUMN landmark_abbr TEXT")
   c.execute("UPDATE corrections SET landmark_abbr=(SELECT abbr FROM landmark_schema s WHERE s.landmark_id=corrections.landmark_id) WHERE landmark_id IS NOT NULL AND landmark_abbr IS NULL")
   for example in c.execute("SELECT example_id,label_json FROM training_examples WHERE kind='landmark'").fetchall():
    try: label=json.loads(example["label_json"])
    except (TypeError,json.JSONDecodeError): continue
    if not label.get("landmark_abbr") and label.get("landmark_id") is not None:
     mapped=c.execute("SELECT abbr FROM landmark_schema WHERE landmark_id=?",(int(label["landmark_id"]),)).fetchone()
     if mapped:
      label["landmark_abbr"]=mapped["abbr"];c.execute("UPDATE training_examples SET label_json=? WHERE example_id=?",(json.dumps(label),example["example_id"]))
   unresolved=c.execute("SELECT COUNT(*) FROM landmarks WHERE landmark_abbr IS NULL").fetchone()[0]
   if unresolved: raise ValueError(f"Cannot migrate {unresolved} landmarks: old numeric IDs are not resolvable in persisted schema")
   c.execute("CREATE INDEX IF NOT EXISTS idx_landmarks_image_abbr ON landmarks(image_id,landmark_abbr)")
   c.execute("CREATE TABLE IF NOT EXISTS ai_permanent_holdouts (image_id TEXT PRIMARY KEY,reserved_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id))")
   c.execute("CREATE TABLE IF NOT EXISTS image_review (image_id TEXT PRIMARY KEY,human_verified INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id))")
   c.execute("CREATE TABLE IF NOT EXISTS annotation_drafts (image_id TEXT PRIMARY KEY,workflow_stage TEXT,workflow_position INTEGER,manual_rebuild INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id))")
   draft_cols={r[1] for r in c.execute("PRAGMA table_info(annotation_drafts)")}
   if "manual_rebuild" not in draft_cols:c.execute("ALTER TABLE annotation_drafts ADD COLUMN manual_rebuild INTEGER NOT NULL DEFAULT 0")
   c.execute("CREATE TABLE IF NOT EXISTS locality_calibrations (locality_id TEXT PRIMARY KEY,scale REAL NOT NULL,units TEXT NOT NULL,calibration_reference_image_id TEXT NOT NULL,calibration_data TEXT NOT NULL,updated_at TEXT NOT NULL)")
   c.execute("CREATE TABLE IF NOT EXISTS image_attributes (image_id TEXT NOT NULL,attribute_key TEXT NOT NULL,value TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(image_id,attribute_key),FOREIGN KEY(image_id) REFERENCES images(image_id))")
   crop_cols={r[1] for r in c.execute("PRAGMA table_info(crops)")}
   for name,definition in (("active_prediction_id","TEXT"),("ai_proposal_json","TEXT"),("human_verified","INTEGER NOT NULL DEFAULT 0"),("human_changed","INTEGER NOT NULL DEFAULT 0"),("prediction_at","TEXT"),("reviewed_at","TEXT"),("qc_level","TEXT"),("qc_score","INTEGER"),("qc_reasons_json","TEXT")):
    if name not in crop_cols: c.execute(f"ALTER TABLE crops ADD COLUMN {name} {definition}")
   c.execute("CREATE TABLE IF NOT EXISTS crop_predictions (prediction_id TEXT PRIMARY KEY,image_id TEXT NOT NULL,model_id TEXT,proposal_json TEXT NOT NULL,qc_level TEXT,qc_score INTEGER,qc_reasons_json TEXT,created_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(image_id) REFERENCES images(image_id))")
   c.execute("CREATE TABLE IF NOT EXISTS crop_holdout (holdout_id TEXT NOT NULL,image_id TEXT NOT NULL,seed INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(holdout_id,image_id),FOREIGN KEY(image_id) REFERENCES images(image_id))")
   c.execute("CREATE TABLE IF NOT EXISTS crop_holdout_references (reference_id TEXT PRIMARY KEY,holdout_id TEXT NOT NULL,image_id TEXT NOT NULL,crop_json TEXT NOT NULL,revision INTEGER NOT NULL,created_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,FOREIGN KEY(image_id) REFERENCES images(image_id))")
   c.execute("CREATE TABLE IF NOT EXISTS crop_evaluations (evaluation_id TEXT PRIMARY KEY,holdout_id TEXT NOT NULL,model_id TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)")
   c.execute("CREATE TABLE IF NOT EXISTS crop_verified_observations (image_id TEXT PRIMARY KEY,verified_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id))")
   c.execute("CREATE TABLE IF NOT EXISTS crop_training_membership (model_id TEXT NOT NULL,image_id TEXT NOT NULL,recorded_at TEXT NOT NULL,PRIMARY KEY(model_id,image_id),FOREIGN KEY(image_id) REFERENCES images(image_id))")
   c.execute("UPDATE crops SET provenance='manual',human_verified=1,human_changed=1,reviewed_at=COALESCE(reviewed_at,updated_at) WHERE provenance IS NULL OR provenance NOT IN ('manual','ai_unreviewed','ai_accepted','ai_corrected')")
   # One-way repair for pre-human_verified projects only. Old manual Crop rows
   # already used by Landmarks had no reviewed_at column/value, so ALTER TABLE
   # left them at human_verified=0 even though their geometry was the accepted
   # working frame. Modern unverified rows are not touched.
   c.execute("""UPDATE crops
SET human_verified=1,human_changed=1,reviewed_at=updated_at
WHERE provenance='manual'
  AND COALESCE(human_verified,0)=0
  AND reviewed_at IS NULL
  AND crop_json IS NOT NULL AND crop_json!='null'
  AND transform_json IS NOT NULL AND transform_json!='null'
  AND EXISTS(SELECT 1 FROM landmarks l WHERE l.image_id=crops.image_id)""")
 def _sync_schema_hash_metadata(self):
  """Keep derived config/SQLite hash metadata aligned with authoritative CSV bytes."""
  digest=schema_hash(self.schema_path);config=self.config
  if config.get("schema_sha256")!=digest:
   config["schema_sha256"]=digest;_json(self.config_path,config)
  with self.transaction() as c:
   c.execute("INSERT INTO project(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",("schema_sha256",digest))
  return digest
 def get_ui_state(self,key,default=None):
  with self.transaction() as c:r=c.execute("SELECT value FROM project WHERE key=?",("ui."+key,)).fetchone()
  return json.loads(r[0]) if r else default
 def set_ui_state(self,key,value):
  with self.transaction() as c:c.execute("INSERT INTO project(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",("ui."+key,json.dumps(value)))
 def sync_results(self):
  from .results_export import export_project_results
  return export_project_results(self)
 def configure_source_layout(self, source_layout="subfolder", source_image_subfolder="orig"):
  cfg=self.config;cfg["source_layout"]=source_layout;cfg["source_image_subfolder"]=source_image_subfolder if source_layout=="subfolder" else "";_json(self.config_path,cfg);return self.scan_originals()
 def choose_source_types(self, source_types=None):
  return sorted({str(x).lower().lstrip(".") for x in (source_types or SUPPORTED_SOURCE_TYPES) if str(x).lower().lstrip(".") in SUPPORTED_SOURCE_TYPES})
 def _source_items(self):
  cfg=self.config; layout=cfg.get("source_layout","direct"); sub=cfg.get("source_image_subfolder",""); root=self.source_root; items=[]
  if not root.exists(): return items
  for p in root.rglob("*"):
   if not p.is_file() or p.suffix.lower() not in set(SUPPORTED_SOURCE_TYPES.values()): continue
   rel=p.relative_to(root); parts=rel.parts; parent_parts={x.lower() for x in parts[:-1]}
   if parent_parts & EXCLUDED_DIR_NAMES: continue
   if layout=="subfolder":
    if len(parts)<3 or parts[-2].casefold()!=str(sub).casefold(): continue
    locality=parts[-3]
   else:
    # Direct projects may contain arbitrarily nested source folders.  The
    # first directory below source_root remains the locality; root-level files
    # belong to source_root itself.  Silently dropping deeper paths loses
    # specimens from the catalogue.
    locality=root.name if len(parts)==1 else parts[0]
   items.append((p,rel.as_posix(),locality))
  items.sort(key=lambda x:(natural_key(x[2]),natural_key(x[0].name),x[1].casefold()))
  totals={}
  for _,_,loc in items: totals[loc]=totals.get(loc,0)+1
  return [(p,rel,loc,i,totals[loc]) for i,(p,rel,loc) in enumerate(items,1)]
 def catalog_candidates(self, source_types=None):
  items=self._source_items(); counts={}
  for _,_,loc,_,_ in items: counts[loc]=counts.get(loc,0)+1
  seen={};included=[]
  for p,rel,loc,_,_ in items:
   seen[loc]=seen.get(loc,0)+1; included.append({"path":rel,"locality":loc,"index_in_locality":seen[loc],"total_in_locality":counts[loc],"reason":None})
  included_paths={x["path"] for x in included}; excluded=[]
  if self.source_root.exists():
   for p in self.source_root.rglob("*"):
    if not p.is_file() or p.suffix.lower() not in set(SUPPORTED_SOURCE_TYPES.values()): continue
    rel=p.relative_to(self.source_root).as_posix()
    if rel not in included_paths: excluded.append({"path":rel,"reason":"non_source_structure"})
  return included,excluded
 def connect(self):
  conn=sqlite3.connect(self.path);conn.row_factory=sqlite3.Row;conn.execute("PRAGMA journal_mode=DELETE");conn.execute("PRAGMA foreign_keys=ON");conn.execute("PRAGMA synchronous=FULL");return conn
 @contextmanager
 def transaction(self):
  conn=self.connect()
  try:
   with conn: yield conn
  finally: conn.close()
 def initialize(self,schema=None):
  schema=self.schema if schema is None else schema
  with self.transaction() as c:
   c.executescript('''
CREATE TABLE IF NOT EXISTS project (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS images (image_id TEXT PRIMARY KEY,original_name TEXT NOT NULL,relative_path TEXT NOT NULL,sample_id TEXT,file_size INTEGER,mtime_ns INTEGER,width INTEGER,height INTEGER,source_sha256 TEXT,source_available INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS landmark_schema (landmark_id INTEGER PRIMARY KEY,abbr TEXT NOT NULL UNIQUE,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS landmarks (image_id TEXT NOT NULL,landmark_id INTEGER NOT NULL,x_standardized REAL,y_standardized REAL,x_original REAL,y_original REAL,state TEXT NOT NULL,provenance TEXT NOT NULL,model_id TEXT,predicted_x REAL,predicted_y REAL,confidence REAL,prediction_run_id TEXT,reviewed INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL,PRIMARY KEY(image_id,landmark_id),FOREIGN KEY(image_id) REFERENCES images(image_id),FOREIGN KEY(landmark_id) REFERENCES landmark_schema(landmark_id));
CREATE TABLE IF NOT EXISTS crops (image_id TEXT PRIMARY KEY,developed_relpath TEXT,standardized_relpath TEXT,source_sha256 TEXT,crop_json TEXT,transform_json TEXT,rotation_degrees REAL,status TEXT,provenance TEXT,model_id TEXT,updated_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id));
CREATE TABLE IF NOT EXISTS corrections (correction_id INTEGER PRIMARY KEY,image_id TEXT NOT NULL,landmark_id INTEGER,kind TEXT NOT NULL,previous_json TEXT,accepted_json TEXT,created_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id));
CREATE TABLE IF NOT EXISTS training_examples (example_id INTEGER PRIMARY KEY,image_id TEXT NOT NULL,kind TEXT NOT NULL,label_json TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id));
CREATE TABLE IF NOT EXISTS models (model_id TEXT PRIMARY KEY,kind TEXT NOT NULL,schema_sha256 TEXT,path TEXT,active INTEGER NOT NULL DEFAULT 0,pinned INTEGER NOT NULL DEFAULT 0,metrics_json TEXT,dataset_id TEXT,parent_model_id TEXT,dataset_manifest_path TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qc (qc_id INTEGER PRIMARY KEY,image_id TEXT,kind TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(image_id) REFERENCES images(image_id));''')
   c.execute("INSERT OR REPLACE INTO project(key,value) VALUES (?,?)",("schema_sha256",schema_hash(self.schema_path)))
  self.ensure_schema()
 def scan_originals(self,hashes=False,source_types=None):
  self.ensure_schema(); items=self._source_items(); root=self.source_root
  with self.transaction() as c:
   c.execute("UPDATE images SET active=0,source_available=0")
   totals={}; positions={}
   for _,_,loc,_,_ in items: totals[loc]=totals.get(loc,0)+1
   for p,rel,loc,_,_ in items:
    positions[loc]=positions.get(loc,0)+1; st=p.stat(); ident=hashlib.sha256(f"orig_photos/{rel}".encode()).hexdigest()[:16]; digest=sha256(p) if hashes else None
    c.execute("INSERT INTO images(image_id,specimen_id,original_name,relative_path,sample_id,locality,index_in_locality,total_in_locality,file_size,mtime_ns,source_sha256,active,source_available,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET specimen_id=COALESCE(images.specimen_id,excluded.specimen_id),original_name=excluded.original_name,relative_path=excluded.relative_path,sample_id=excluded.locality,locality=excluded.locality,index_in_locality=excluded.index_in_locality,total_in_locality=excluded.total_in_locality,file_size=excluded.file_size,mtime_ns=excluded.mtime_ns,source_sha256=COALESCE(excluded.source_sha256,images.source_sha256),active=1,source_available=1",(ident,ident,p.name,rel,loc,loc,positions[loc],totals[loc],st.st_size,st.st_mtime_ns,digest,1,1,now()))
  return len(items)
 def _refresh_source_availability(self):
  """Refresh source presence without deleting catalogue/history state."""
  root=self.source_root
  with self.transaction() as c:
   rows=c.execute("SELECT image_id,relative_path FROM images").fetchall()
   c.executemany(
    "UPDATE images SET source_available=? WHERE image_id=?",
    [(int((root/row["relative_path"]).is_file()),row["image_id"]) for row in rows],
   )
  return sum(int((root/row["relative_path"]).is_file()) for row in rows)
 def image_path(self,image_id):
  with self.transaction() as c:r=c.execute("SELECT relative_path,source_available FROM images WHERE image_id=?",(image_id,)).fetchone()
  if not r or not r["source_available"]:return None
  path=self.source_root/r["relative_path"]
  return path if path.is_file() else None
 def relink(self,new_root):
  new_root=Path(new_root).resolve();files=[p for p in new_root.rglob("*") if p.is_file()];by_rel={p.relative_to(new_root).as_posix():p for p in files};by_sig={(p.name,p.stat().st_size):p for p in files};matched=0
  with self.transaction() as c:
   for row in c.execute("SELECT image_id,relative_path,original_name,file_size,source_sha256 FROM images"):
    p=by_rel.get(row["relative_path"]) or by_sig.get((row["original_name"],row["file_size"]));ok=bool(p) and (not row["source_sha256"] or sha256(p)==row["source_sha256"]);c.execute("UPDATE images SET source_available=? WHERE image_id=?",(int(ok),row["image_id"]));matched+=int(ok)
  config=self.config;config["source_root"]=str(new_root);_json(self.config_path,config);return {"matched":matched,"total":self.count("images")}
 def _abbr_for_display(self, display_id):
  item=next((row for row in self.schema if int(row["id"])==int(display_id)),None)
  if item:return item["abbr"]
  return self.historical_abbr_for_numeric(display_id) or (_ for _ in ()).throw(ValueError(f"Unknown active landmark display number: {display_id}"))
 def _display_for_abbr(self, abbr):
  item=next((row for row in self.schema if row["abbr"]==abbr),None)
  return int(item["id"]) if item else None
 def _catalog_reconciliation_required(self):
  active={str(row["abbr"]) for row in self.schema}
  with self.transaction() as c: persisted={str(row["abbr"]) for row in c.execute("SELECT abbr FROM landmark_schema")}
  return bool(active-persisted)
 def reconcile_landmark_schema(self):
  """Add active abbreviations without ever repurposing a persistent numeric key."""
  active=list(self.schema)
  if not active or not self._catalog_reconciliation_required(): return False
  schema_migration_backup(self)
  with self.transaction() as c:
   persisted={str(row["abbr"]):int(row["landmark_id"]) for row in c.execute("SELECT landmark_id,abbr FROM landmark_schema")}
   missing=[row for row in active if str(row["abbr"]) not in persisted]
   if not missing:return False
   if not persisted:
    for row in missing:c.execute("INSERT INTO landmark_schema(landmark_id,abbr,name) VALUES (?,?,?)",(int(row["id"]),str(row["abbr"]),str(row["name"])))
   else:
    next_key=max(0,*persisted.values())+1
    for row in missing:
     c.execute("INSERT INTO landmark_schema(landmark_id,abbr,name) VALUES (?,?,?)",(next_key,str(row["abbr"]),str(row["name"])));next_key+=1
  return True
 def _persistent_landmark_id(self, connection, abbr):
  row=connection.execute("SELECT landmark_id FROM landmark_schema WHERE abbr=?",(str(abbr),)).fetchone()
  if not row: raise ValueError(f"Persistent landmark identity is missing for abbreviation {abbr!r}; reopen the project to reconcile its schema.")
  return int(row["landmark_id"])
 def historical_abbr_for_numeric(self, landmark_id):
  """Resolve a legacy numeric reference through the persisted pre-migration scheme."""
  with self.transaction() as c: row=c.execute("SELECT abbr FROM landmark_schema WHERE landmark_id=?",(int(landmark_id),)).fetchone()
  return row["abbr"] if row else None
 def active_landmark_id_for_abbr(self, abbr):
  return self._display_for_abbr(abbr)
 def save_landmark(self,image_id,landmark_id,x,y,state,provenance="manual",**extra):
  abbr=self._abbr_for_display(landmark_id);self.reconcile_landmark_schema();timestamp=now()
  with self.transaction() as c:
   old=c.execute("SELECT * FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,abbr)).fetchone();old=dict(old) if old else {}
   stored_id=int(old["landmark_id"]) if old else self._persistent_landmark_id(c,abbr)
   extra={**{key:old.get(key) for key in ("model_id","predicted_x","predicted_y","confidence","prediction_run_id") if old.get(key) is not None},**extra}
   if "reviewed" not in extra and (old.get("provenance")=="machine" or old.get("model_id") is not None or old.get("prediction_run_id") is not None): extra["reviewed"]=False
   c.execute('''INSERT INTO landmarks(image_id,landmark_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,predicted_x,predicted_y,confidence,prediction_run_id,reviewed,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(image_id,landmark_id) DO UPDATE SET landmark_abbr=excluded.landmark_abbr,x_standardized=excluded.x_standardized,y_standardized=excluded.y_standardized,state=excluded.state,provenance=excluded.provenance,model_id=excluded.model_id,predicted_x=excluded.predicted_x,predicted_y=excluded.predicted_y,confidence=excluded.confidence,prediction_run_id=excluded.prediction_run_id,reviewed=excluded.reviewed,updated_at=excluded.updated_at''',(image_id,stored_id,abbr,x,y,state,provenance,extra.get("model_id"),extra.get("predicted_x"),extra.get("predicted_y"),extra.get("confidence"),extra.get("prediction_run_id"),int(extra.get("reviewed",True)),timestamp))
   c.execute("INSERT INTO corrections(image_id,landmark_id,landmark_abbr,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?,?)",(image_id,stored_id,abbr,"landmark",json.dumps(old or None),json.dumps({"landmark_abbr":abbr,"x":x,"y":y,"state":state,"provenance":provenance}),timestamp))
   if provenance in {"manual","corrected","corrected_by_human","reviewed_by_human"}:c.execute("INSERT INTO training_examples(image_id,kind,label_json,created_at) VALUES (?,?,?,?)",(image_id,"landmark",json.dumps({"landmark_id":landmark_id,"landmark_abbr":abbr,"x":x,"y":y,"state":state}),timestamp))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,timestamp))
  self._auto_verify_if_fully_human(image_id)
 def save_machine_landmarks(self,image_id,points,*,model_id,prediction_run_id):
  """Persist one complete machine prediction without invalidating identical reviewed state.

  Human-derived points are never overwritten.  Reapplying a prediction whose
  scientific coordinates are identical to the current machine state preserves
  its reviewed flag and the image Checked state; only a real coordinate/state
  change invalidates human verification.
  """
  self.reconcile_landmark_schema();timestamp=now();human={"manual","corrected","corrected_by_human","reviewed_by_human"};saved=skipped=0;scientific_changed=False
  with self.transaction() as c:
   existing={str(row["landmark_abbr"]):dict(row) for row in c.execute("SELECT * FROM landmarks WHERE image_id=?",(image_id,))}
   for point in points:
    display_id=int(point["landmark_id"]);abbr=self._abbr_for_display(display_id);old=existing.get(abbr,{})
    if old.get("provenance") in human:
     skipped+=1;continue
    x=float(point["x"]);y=float(point["y"])
    same=bool(old) and old.get("state")!="missing" and old.get("x_standardized") is not None and old.get("y_standardized") is not None and float(old["x_standardized"])==x and float(old["y_standardized"])==y
    reviewed=int(bool(old.get("reviewed"))) if same else 0
    scientific_changed=scientific_changed or not same
    stored_id=int(old["landmark_id"]) if old else self._persistent_landmark_id(c,abbr)
    c.execute('''INSERT INTO landmarks(image_id,landmark_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,predicted_x,predicted_y,confidence,prediction_run_id,reviewed,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(image_id,landmark_id) DO UPDATE SET landmark_abbr=excluded.landmark_abbr,x_standardized=excluded.x_standardized,y_standardized=excluded.y_standardized,state=excluded.state,provenance=excluded.provenance,model_id=excluded.model_id,predicted_x=excluded.predicted_x,predicted_y=excluded.predicted_y,confidence=excluded.confidence,prediction_run_id=excluded.prediction_run_id,reviewed=excluded.reviewed,updated_at=excluded.updated_at''',(image_id,stored_id,abbr,x,y,"auto","machine",model_id,x,y,point.get("confidence"),prediction_run_id,reviewed,timestamp))
    if not same:c.execute("INSERT INTO corrections(image_id,landmark_id,landmark_abbr,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?,?)",(image_id,stored_id,abbr,"landmark",json.dumps(old or None),json.dumps({"landmark_abbr":abbr,"x":x,"y":y,"state":"auto","provenance":"machine"}),timestamp))
    saved+=1
   if scientific_changed:c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,timestamp))
  return saved,skipped
 def restore_landmark_before_missing(self,image_id,landmark_id):
  """Undo the latest Mark missing action, restoring the previous point when one existed."""
  abbr=self._abbr_for_display(landmark_id);self.reconcile_landmark_schema();timestamp=now()
  with self.transaction() as c:
   current=c.execute("SELECT * FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,abbr)).fetchone()
   if not current or dict(current).get("state")!="missing":return False
   rows=c.execute("SELECT previous_json FROM corrections WHERE image_id=? AND landmark_abbr=? AND kind='landmark' ORDER BY correction_id DESC",(image_id,abbr)).fetchall()
   previous=None
   for row in rows:
    try:candidate=json.loads(row["previous_json"]) if row["previous_json"] else None
    except (TypeError,json.JSONDecodeError):candidate=None
    if candidate:
     previous=candidate;break
   if previous and previous.get("x_standardized") is not None and previous.get("y_standardized") is not None:
    stored_id=int(current["landmark_id"])
    c.execute("""UPDATE landmarks SET x_standardized=?,y_standardized=?,state=?,provenance=?,model_id=?,predicted_x=?,predicted_y=?,confidence=?,prediction_run_id=?,reviewed=?,updated_at=? WHERE image_id=? AND landmark_abbr=?""",
     (previous.get("x_standardized"),previous.get("y_standardized"),previous.get("state") or "manual",previous.get("provenance") or "manual",previous.get("model_id"),previous.get("predicted_x"),previous.get("predicted_y"),previous.get("confidence"),previous.get("prediction_run_id"),int(previous.get("reviewed",1)),timestamp,image_id,abbr))
    accepted={"restored_from_missing":True,"landmark_abbr":abbr,"x":previous.get("x_standardized"),"y":previous.get("y_standardized"),"state":previous.get("state"),"provenance":previous.get("provenance")}
    c.execute("INSERT INTO corrections(image_id,landmark_id,landmark_abbr,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?,?)",(image_id,stored_id,abbr,"landmark_unmark_missing",json.dumps(dict(current)),json.dumps(accepted),timestamp))
   else:
    stored_id=int(current["landmark_id"]);c.execute("DELETE FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,abbr))
    c.execute("INSERT INTO corrections(image_id,landmark_id,landmark_abbr,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?,?)",(image_id,stored_id,abbr,"landmark_unmark_missing",json.dumps(dict(current)),None,timestamp))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,timestamp))
  return bool(previous and previous.get("x_standardized") is not None and previous.get("y_standardized") is not None)

 def delete_landmark(self,image_id,landmark_id):
  abbr=self._abbr_for_display(landmark_id);self.reconcile_landmark_schema()
  with self.transaction() as c:
   old=c.execute("SELECT * FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,abbr)).fetchone();stored_id=int(old["landmark_id"]) if old else self._persistent_landmark_id(c,abbr);c.execute("DELETE FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,abbr));c.execute("INSERT INTO corrections(image_id,landmark_id,landmark_abbr,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?,?)",(image_id,stored_id,abbr,"landmark_delete",json.dumps(dict(old) if old else None),None,now()));c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,now()))
 def load_landmarks(self,image_id):
  with self.transaction() as c: rows=c.execute("SELECT * FROM landmarks WHERE image_id=?",(image_id,)).fetchall()
  out={}
  for raw in rows:
   row=dict(raw);display=self._display_for_abbr(row.get("landmark_abbr"))
   if display is not None: out[display]=row
  return out
 def replace_landmarks(self,image_id,points):
  """Replace only active-scheme points; removed scheme entries stay historical."""
  active={int(row["id"]):row["abbr"] for row in self.schema};self.reconcile_landmark_schema()
  with self.transaction() as c:
   for abbr in active.values(): c.execute("DELETE FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,abbr))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,now()))
   for identifier,point in points.items():
    ident=int(str(identifier).lstrip("Pp"));abbr=active.get(ident)
    if not abbr: raise ValueError(f"Unknown active landmark display number: {ident}")
    c.execute("INSERT INTO landmarks(image_id,landmark_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,predicted_x,predicted_y,confidence,prediction_run_id,reviewed,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(image_id,self._persistent_landmark_id(c,abbr),abbr,point.get("x_standardized"),point.get("y_standardized"),point.get("state","manual"),point.get("provenance",point.get("state","manual")),point.get("model_id"),point.get("predicted_x"),point.get("predicted_y"),point.get("confidence"),point.get("prediction_run_id"),int(point.get("reviewed",True)),point.get("timestamp",now())))
  self._auto_verify_if_fully_human(image_id)
 def _auto_verify_if_fully_human(self,image_id):
  # "missing" is the legacy spelling of a manually marked missing landmark.
  human={"manual","corrected","corrected_by_human","reviewed_by_human","missing"};rows=self.load_landmarks(image_id);required=[int(row["id"]) for row in self.schema]
  if not required or not all((row:=rows.get(identifier)) and row.get("provenance") in human and (row.get("state")=="missing" or (row.get("x_standardized") is not None and row.get("y_standardized") is not None)) for identifier in required):return False
  from .landmark_state import landmark_needs_ai_review
  pending_ai=any(landmark_needs_ai_review(row) for row in rows.values())
  with self.transaction() as c:
   crop_review=c.execute("SELECT 1 FROM image_attributes WHERE image_id=? AND attribute_key='landmark_crop_review_required' AND lower(value)='true'",(image_id,)).fetchone()
   if crop_review or pending_ai:return False
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=1,updated_at=excluded.updated_at",(image_id,1,now()))
  return True
 def _sync_auto_verified_images(self):
  """Backfill positive legacy Checked state without destructively rewriting human history.

  Pending AI/Crop review already makes the *effective* catalog/annotation state
  unchecked.  Opening a project must not overwrite persisted human review rows:
  the state-changing operation that introduced new AI/Crop content owns that
  invalidation.  This migration therefore only fills provably human-final rows.
  """
  human={"manual","corrected","corrected_by_human","reviewed_by_human","missing"};required={row["abbr"] for row in self.schema}
  if not required:return
  with self.transaction() as c:
   by_image={row["image_id"]:{} for row in c.execute("SELECT image_id FROM images WHERE COALESCE(active,1)=1")}
   from .landmark_state import landmark_needs_ai_review
   pending_ai=set()
   for row in c.execute("SELECT image_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,prediction_run_id,reviewed FROM landmarks"):
    if row["image_id"] not in by_image or row["landmark_abbr"] not in required:continue
    item=dict(row);by_image[row["image_id"]][row["landmark_abbr"]]=item
    if landmark_needs_ai_review(item):pending_ai.add(row["image_id"])
   crop_review={row["image_id"] for row in c.execute("SELECT image_id FROM image_attributes WHERE attribute_key='landmark_crop_review_required' AND lower(value)='true'")}
   blocked=crop_review|pending_ai;stamp=now()
   for image_id,rows in by_image.items():
    if image_id in blocked:continue
    if all((row:=rows.get(abbr)) and row.get("provenance") in human and (row.get("state")=="missing" or (row.get("x_standardized") is not None and row.get("y_standardized") is not None)) for abbr in required):
     c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=1,updated_at=excluded.updated_at",(image_id,1,stamp))
 def reassign_present_landmarks(self,image_id,assignment):
  assignment={int(target):int(source) for target,source in assignment.items()};group=set(assignment)
  if len(group)<2 or len(group)>4 or group!=set(assignment.values()):raise ValueError("reassignment requires a 2–4 landmark permutation")
  abbr_assignment={self._abbr_for_display(target):self._abbr_for_display(source) for target,source in assignment.items()}
  with self.transaction() as c:
   rows={abbr:c.execute("SELECT * FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,abbr)).fetchone() for abbr in set(abbr_assignment)|set(abbr_assignment.values())}
   if any(not row or row["state"]=="missing" or row["x_standardized"] is None or row["y_standardized"] is None for row in rows.values()):raise ValueError("reassignment requires present landmarks")
   before={target:dict(rows[abbr]) for target,abbr in abbr_assignment.items()};stamp=now()
   for target,source in abbr_assignment.items():
    row=rows[source];c.execute("UPDATE landmarks SET x_standardized=?,y_standardized=?,state='corrected',provenance='corrected_by_human',reviewed=0,updated_at=? WHERE image_id=? AND landmark_abbr=?",(row['x_standardized'],row['y_standardized'],stamp,image_id,target))
    c.execute("INSERT INTO corrections(image_id,landmark_id,landmark_abbr,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?,?)",(image_id,rows[target]['landmark_id'],target,'landmark_reassignment',json.dumps(dict(rows[target])),json.dumps({'landmark_abbr':target,'x':row['x_standardized'],'y':row['y_standardized'],'state':'corrected','provenance':'corrected_by_human'}),stamp))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,stamp))
  return before
 def swap_present_landmarks(self,image_id,first,second):
  first,second=int(first),int(second)
  if first==second: raise ValueError("select two different landmarks")
  first_abbr,second_abbr=self._abbr_for_display(first),self._abbr_for_display(second)
  with self.transaction() as c:
   a=c.execute("SELECT * FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,first_abbr)).fetchone();b=c.execute("SELECT * FROM landmarks WHERE image_id=? AND landmark_abbr=?",(image_id,second_abbr)).fetchone()
   if not a or not b or a["state"]=="missing" or b["state"]=="missing" or a["x_standardized"] is None or b["x_standardized"] is None: raise ValueError("swap requires two present landmarks")
   before={first:dict(a),second:dict(b)};stamp=now()
   for target,source in ((first_abbr,b),(second_abbr,a)):
    c.execute("UPDATE landmarks SET x_standardized=?,y_standardized=?,state='corrected',provenance='corrected_by_human',reviewed=0,updated_at=? WHERE image_id=? AND landmark_abbr=?",(source['x_standardized'],source['y_standardized'],stamp,image_id,target))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,stamp))
  return before
 def restore_landmark_finals(self,image_id,snapshot,human_verified=False):
  with self.transaction() as c:
   for ident,row in snapshot.items(): c.execute("UPDATE landmarks SET x_standardized=?,y_standardized=?,state=?,provenance=?,reviewed=?,updated_at=? WHERE image_id=? AND landmark_id=?",(row['x_standardized'],row['y_standardized'],row['state'],row['provenance'],row['reviewed'],now(),image_id,int(ident)))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=excluded.human_verified,updated_at=excluded.updated_at",(image_id,int(human_verified),now()))
 def remap_landmarks_for_transform(self,image_id,old_transform,new_transform):
  """Atomically move mutable standardized coordinates through a transform change."""
  from .transforms import Transform
  import math
  def coerce(value): return value if isinstance(value,Transform) else Transform(**value)
  new_transform=coerce(new_transform);old_transform=coerce(old_transform) if old_transform is not None else None
  with self.transaction() as c:
   rows=[dict(row) for row in c.execute("SELECT * FROM landmarks WHERE image_id=? ORDER BY landmark_id",(image_id,))]
   needs_old=any((row["x_standardized"] is not None and row["y_standardized"] is not None) or (row["predicted_x"] is not None and row["predicted_y"] is not None) for row in rows)
   if needs_old and old_transform is None: raise ValueError("Cannot safely remap landmarks: previous crop transform is unavailable.")
   stamp=now();before={row["landmark_id"]:row for row in rows};after={};outside=0;present_before=0;present_after=0
   def remap_pair(x,y):
    if x is None or y is None:return (x,y)
    original=old_transform.standardized_to_original(float(x),float(y));return new_transform.original_to_standardized(*original)
   for row in rows:
    current_x,current_y=row["x_standardized"],row["y_standardized"];pred_x,pred_y=remap_pair(row["predicted_x"],row["predicted_y"]) if old_transform is not None else (row["predicted_x"],row["predicted_y"])
    state=row["state"];reviewed=row["reviewed"]
    if state!="missing" and current_x is not None and current_y is not None:
     present_before+=1;x,y=remap_pair(current_x,current_y)
     if not (math.isfinite(x) and math.isfinite(y) and 0<=x<new_transform.output_width and 0<=y<new_transform.output_height):
      x=y=None;state="unresolved";reviewed=0;outside+=1
     else:present_after+=1
    else:x,y=current_x,current_y
    c.execute("UPDATE landmarks SET x_standardized=?,y_standardized=?,state=?,predicted_x=?,predicted_y=?,reviewed=?,updated_at=? WHERE image_id=? AND landmark_id=?",(x,y,state,pred_x,pred_y,reviewed,stamp,image_id,row["landmark_id"]))
    after[row["landmark_id"]]={"x_standardized":x,"y_standardized":y,"state":state,"predicted_x":pred_x,"predicted_y":pred_y,"reviewed":reviewed}
   c.execute("INSERT INTO corrections(image_id,landmark_id,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?)",(image_id,None,"landmark_transform_remap",json.dumps({"transform":old_transform.__dict__ if old_transform else None,"landmarks":before}),json.dumps({"transform":new_transform.__dict__,"landmarks":after}),stamp))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,stamp))
  return {"present_before":present_before,"present_after":present_after,"outside_count":outside}
 def save_crop(self,image_id,crop,provenance="automatic",model_id=None,previous_frame_proven=False):
  with self.transaction() as c:
   invalidation=self._invalidate_landmarks_for_crop_change(c,image_id,crop,previous_frame_proven=previous_frame_proven)
   c.execute('''INSERT INTO crops(image_id,developed_relpath,standardized_relpath,source_sha256,crop_json,transform_json,rotation_degrees,status,provenance,model_id,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET developed_relpath=excluded.developed_relpath,standardized_relpath=excluded.standardized_relpath,source_sha256=excluded.source_sha256,crop_json=excluded.crop_json,transform_json=excluded.transform_json,rotation_degrees=excluded.rotation_degrees,status=excluded.status,provenance=excluded.provenance,model_id=excluded.model_id,updated_at=excluded.updated_at''',(image_id,crop.get("developed_full_relpath"),crop.get("standardized_relpath"),crop.get("source_sha256"),json.dumps(crop.get("crop_bounds")),json.dumps(crop.get("transform")),crop.get("rotation_degrees"),crop.get("normalization_status"),provenance,model_id,now()))

  return invalidation
 def _same_crop_frame(self,old,crop):
  """Semantic frame equality: JSON formatting and int/float spelling are not scientific changes."""
  if not old:return False
  try:
   old_bounds=json.loads(old["crop_json"]) if isinstance(old["crop_json"],str) else old["crop_json"]
   new_bounds=crop.get("crop_bounds")
   if not isinstance(old_bounds,(list,tuple)) or not isinstance(new_bounds,(list,tuple)) or len(old_bounds)!=4 or len(new_bounds)!=4:return False
   if tuple(float(value) for value in old_bounds)!=tuple(float(value) for value in new_bounds):return False
   old_transform=json.loads(old["transform_json"]) if isinstance(old["transform_json"],str) else old["transform_json"]
   new_transform=crop.get("transform")
   if not isinstance(old_transform,dict) or not isinstance(new_transform,dict):return False
   from .transforms import Transform
   if Transform(**old_transform)!=Transform(**new_transform):return False
   return float(old["rotation_degrees"] or 0.0)==float(crop.get("rotation_degrees") or 0.0)
  except (TypeError,ValueError,KeyError,json.JSONDecodeError):
   return False
 def _invalidate_landmarks_for_crop_change(self,connection,image_id,crop,previous_frame_proven=False):
  """A changed scientific frame never silently keeps checked landmarks."""
  old=connection.execute("SELECT crop_json,transform_json,rotation_degrees FROM crops WHERE image_id=?",(image_id,)).fetchone()
  rows=[dict(row) for row in connection.execute("SELECT * FROM landmarks WHERE image_id=? ORDER BY landmark_id",(image_id,))]
  if self._same_crop_frame(old,crop) or not rows:return {"legacy_landmarks_invalidated":False}
  stamp=now()
  if not previous_frame_proven:
   review=connection.execute("SELECT human_verified FROM image_review WHERE image_id=?",(image_id,)).fetchone()
   snapshot={"reason":"previous_landmark_frame_unknown_before_crop_change","landmarks":rows,"human_verified":int(review["human_verified"]) if review else 0}
   connection.execute("INSERT INTO corrections(image_id,landmark_id,kind,previous_json,accepted_json,created_at) VALUES (?,?,?,?,?,?)",(image_id,None,"landmark_frame_unknown_before_crop_change",json.dumps(snapshot),json.dumps({"action":"coordinates_invalidated_before_new_crop"}),stamp))
   connection.execute("UPDATE landmarks SET x_standardized=CASE WHEN state='missing' THEN x_standardized ELSE NULL END,y_standardized=CASE WHEN state='missing' THEN y_standardized ELSE NULL END,predicted_x=NULL,predicted_y=NULL,state=CASE WHEN state='missing' THEN state ELSE 'unresolved' END,provenance=CASE WHEN state='missing' THEN provenance ELSE 'crop_frame_unknown' END,reviewed=0,updated_at=? WHERE image_id=?",(stamp,image_id))
   connection.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,stamp))
   connection.execute("INSERT INTO image_attributes(image_id,attribute_key,value,updated_at) VALUES (?,?,?,?) ON CONFLICT(image_id,attribute_key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(image_id,"landmark_crop_review_required","true",stamp))
   return {"legacy_landmarks_invalidated":True}
  connection.execute("UPDATE landmarks SET reviewed=0 WHERE image_id=? AND (provenance=? OR model_id IS NOT NULL OR prediction_run_id IS NOT NULL)",(image_id,"machine"))
  connection.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,stamp))
  connection.execute("INSERT INTO image_attributes(image_id,attribute_key,value,updated_at) VALUES (?,?,?,?) ON CONFLICT(image_id,attribute_key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(image_id,"landmark_crop_review_required","true",stamp))
  return {"legacy_landmarks_invalidated":False}

 def landmark_crop_review_required(self,image_id):
  with self.transaction() as c: row=c.execute("SELECT value FROM image_attributes WHERE image_id=? AND attribute_key='landmark_crop_review_required'",(image_id,)).fetchone()
  return bool(row and str(row["value"]).casefold()=="true")
 def crop_exists(self,image_id):
  with self.transaction() as c:
   row=c.execute("SELECT 1 FROM crops WHERE image_id=? AND ((crop_json IS NOT NULL AND crop_json!='null') OR rotation_degrees IS NOT NULL)",(image_id,)).fetchone()
  return bool(row)
 def landmark_crop_ready(self,image_id):
  """Sidebar Crop marker: a final human-confirmed Crop exists; Landmark review is shown separately."""
  with self.transaction() as c:
   row=c.execute("""SELECT 1
FROM crops cr
WHERE cr.image_id=?
  AND cr.crop_json IS NOT NULL AND cr.crop_json!='null'
  AND cr.transform_json IS NOT NULL AND cr.transform_json!='null'
  AND cr.provenance IN ('manual','ai_accepted','ai_corrected')
  AND COALESCE(cr.human_verified,0)=1""",(image_id,)).fetchone()
  return bool(row)
 def crop_record(self,image_id):
  with self.transaction() as c: row=c.execute("SELECT * FROM crops WHERE image_id=?",(image_id,)).fetchone()
  if not row:return None
  d=dict(row)
  for key in ("crop_json","transform_json","ai_proposal_json","qc_reasons_json"):
   try:d[key]=json.loads(d[key]) if d.get(key) else None
   except (TypeError,json.JSONDecodeError):d[key]=None
  return d
 def crop_prediction_history(self,image_id):
  with self.transaction() as c: rows=c.execute("SELECT * FROM crop_predictions WHERE image_id=? ORDER BY created_at",(image_id,)).fetchall()
  return [dict(r) for r in rows]
 def crop_auto_candidates(self,rerun=False,image_ids=None):
  """Automatic Crop never changes a frame that already has downstream landmarks."""
  wanted=set(image_ids) if image_ids is not None else None;selected=[];protected=0
  with self.transaction() as c:
   rows=c.execute("SELECT i.image_id,cr.provenance,EXISTS(SELECT 1 FROM landmarks l WHERE l.image_id=i.image_id) has_landmarks FROM images i LEFT JOIN crops cr ON cr.image_id=i.image_id WHERE COALESCE(i.active,1)=1 AND COALESCE(i.excluded,0)=0 AND NOT EXISTS(SELECT 1 FROM crop_holdout h WHERE h.image_id=i.image_id)").fetchall()
  for r in rows:
   if wanted is not None and r["image_id"] not in wanted:continue
   if r["has_landmarks"]:
    protected+=1;continue
   if (r["provenance"]=="ai_unreviewed") if rerun else (r["provenance"] is None):selected.append(r["image_id"])
   elif r["provenance"] in {"manual","ai_accepted","ai_corrected"}:protected+=1
  return tuple(selected),protected
 def record_ai_crop_prediction(self,image_id,crop,model_id):
  from .crop_quality import assess_crop
  bounds=list(crop.get("crop_bounds") or []);width=int(crop.get("original_width") or 0);height=int(crop.get("original_height") or 0)
  if width<=0 or height<=0:
   try:
    from PIL import Image
    with Image.open(self.resolve_data_path(crop.get("developed_full_relpath"))) as image: width,height=image.size
   except Exception: pass
  q=assess_crop(bounds,width,height);level={"green":"OK","yellow":"REVIEW","red":"BAD"}[q.level];stamp=now();pid="crop-"+uuid.uuid4().hex
  with self.transaction() as c:
   c.execute("UPDATE crop_predictions SET active=0 WHERE image_id=?",(image_id,));c.execute("INSERT INTO crop_predictions VALUES (?,?,?,?,?,?,?,?,1)",(pid,image_id,model_id,json.dumps(bounds),level,q.score,json.dumps(list(q.reasons)),stamp))
   c.execute("UPDATE crops SET crop_json=?,provenance='ai_unreviewed',model_id=?,active_prediction_id=?,ai_proposal_json=?,human_verified=0,human_changed=0,prediction_at=?,reviewed_at=NULL,qc_level=?,qc_score=?,qc_reasons_json=?,updated_at=? WHERE image_id=?",(json.dumps(bounds),model_id,pid,json.dumps(bounds),stamp,level,q.score,json.dumps(list(q.reasons)),stamp,image_id))
  return {"prediction_id":pid,"qc_result":level,"quality":q}
 def _auto_reserve_crop_holdout(self,image_id,crop):
  """Forward-only: only observations written after this feature exists are provably clean."""
  with self.transaction() as c:
   seen=c.execute("SELECT 1 FROM crop_training_membership WHERE image_id=?",(image_id,)).fetchone()
   current=c.execute("SELECT 1 FROM crop_holdout WHERE image_id=?",(image_id,)).fetchone()
   count=c.execute("SELECT COUNT(*) FROM crop_holdout").fetchone()[0]
  if seen or current or count>=50:return False
  # deterministic approximately one-in-five sampling; no retrospective inference.
  import hashlib
  if int(hashlib.sha256(str(image_id).encode()).hexdigest()[:8],16)%5:return False
  holdout_id=self.crop_holdout_id() or "crop-holdout-auto-v1";stamp=now()
  with self.transaction() as c:c.execute("INSERT OR IGNORE INTO crop_holdout(holdout_id,image_id,seed,created_at) VALUES (?,?,?,?)",(holdout_id,image_id,0,stamp))
  self.save_crop_holdout_reference(image_id,crop.get("crop_bounds") or [],holdout_id)
  import logging;logging.getLogger("morphology.crop").info("crop_holdout_auto_reserved image_id=%s reason=forward_verified_clean holdout_count=%s",image_id,count+1)
  return True
 def save_reviewed_crop(self,image_id,crop,tolerance=1.0,previous_frame_proven=False):
  old=self.crop_record(image_id);bounds=list(crop.get("crop_bounds") or [])
  if old and old.get("provenance")=="ai_unreviewed" and old.get("ai_proposal_json"):
   changed=(len(bounds)!=len(old["ai_proposal_json"]) or any(abs(float(a)-float(b))>tolerance for a,b in zip(bounds,old["ai_proposal_json"])) or abs(float(crop.get("rotation_degrees") or 0.0)-float(old.get("rotation_degrees") or 0.0))>tolerance)
   provenance="ai_corrected" if changed else "ai_accepted"
   with self.transaction() as c:
    invalidation=self._invalidate_landmarks_for_crop_change(c,image_id,crop,previous_frame_proven=previous_frame_proven)
    c.execute("UPDATE crops SET crop_json=?,transform_json=?,rotation_degrees=?,status=?,provenance=?,human_verified=1,human_changed=?,reviewed_at=?,updated_at=? WHERE image_id=?",(json.dumps(bounds),json.dumps(crop.get("transform")),crop.get("rotation_degrees"),crop.get("normalization_status","PASS"),provenance,int(changed),now(),now(),image_id))
   with self.transaction() as c:c.execute("INSERT INTO crop_verified_observations(image_id,verified_at) VALUES (?,?) ON CONFLICT(image_id) DO UPDATE SET verified_at=excluded.verified_at",(image_id,now()))
   self._auto_reserve_crop_holdout(image_id,crop)
   return {"provenance":provenance,"changed":changed,**invalidation}
  invalidation=self.save_crop(image_id,crop,provenance="manual",model_id=None,previous_frame_proven=previous_frame_proven)
  with self.transaction() as c:c.execute("UPDATE crops SET human_verified=1,human_changed=1,reviewed_at=? WHERE image_id=?",(now(),image_id))
  with self.transaction() as c:c.execute("INSERT INTO crop_verified_observations(image_id,verified_at) VALUES (?,?) ON CONFLICT(image_id) DO UPDATE SET verified_at=excluded.verified_at",(image_id,now()))
  self._auto_reserve_crop_holdout(image_id,crop)
  return {"provenance":"manual","changed":True,**invalidation}
 def crop_training_rows(self):
  """Canonical Project crops for the actual crop trainer; never legacy CSV."""
  with self.transaction() as c:rows=c.execute("SELECT cr.*,i.image_id FROM crops cr JOIN images i ON i.image_id=cr.image_id WHERE cr.provenance IN ('manual','ai_accepted','ai_corrected') AND COALESCE(cr.human_verified,0)=1 AND COALESCE(i.excluded,0)=0 AND cr.crop_json IS NOT NULL AND NOT EXISTS(SELECT 1 FROM crop_holdout h WHERE h.image_id=cr.image_id)").fetchall()
  result=[]
  for row in rows:
   d=dict(row)
   try:bounds=json.loads(d['crop_json'])
   except Exception:continue
   if not isinstance(bounds,list) or len(bounds)!=4:continue
   relpath=d.get('developed_relpath')
   if not relpath:continue
   d['crop_bounds']=bounds;d['developed_path']=str(self.resolve_data_path(relpath))
   if Path(d['developed_path']).is_file():result.append(d)
  return tuple(result)
 def crop_model_lineage_ids(self,model_id):
  ids=set();current=model_id
  while current:
   with self.transaction() as c:
    ids.update(r[0] for r in c.execute("SELECT image_id FROM crop_training_membership WHERE model_id=?",(current,)))
    row=c.execute("SELECT parent_model_id FROM models WHERE model_id=?",(current,)).fetchone()
   current=row[0] if row else None
  return ids
 def crop_training_candidate_breakdown(self,previous_model_id,current_image_ids):
  """One mutually-exclusive post-parent candidate set for UI/audit."""
  with self.transaction() as c:
   created=c.execute("SELECT created_at FROM models WHERE model_id=?",(previous_model_id,)).fetchone();cutoff=created[0] if created else ""
   rows=c.execute("SELECT o.image_id,cr.crop_json,cr.provenance,cr.human_verified,cr.developed_relpath FROM crop_verified_observations o LEFT JOIN crops cr ON cr.image_id=o.image_id WHERE o.verified_at>? ORDER BY o.verified_at,o.image_id",(cutoff,)).fetchall()
   holdout={r[0] for r in c.execute("SELECT image_id FROM crop_holdout")}
  lineage=self.crop_model_lineage_ids(previous_model_id) if previous_model_id else set();current=set(current_image_ids);seen=set();counts={k:0 for k in ("ADDED_TO_TRAINING","ALREADY_SEEN","HOLDOUT","INVALID_CACHE","INVALID_CROP","DUPLICATE","OTHER")}
  for row in rows:
   i=row['image_id']
   if i in seen:cat='DUPLICATE'
   elif i in current:cat='ADDED_TO_TRAINING'
   elif i in lineage:cat='ALREADY_SEEN'
   elif i in holdout:cat='HOLDOUT'
   elif not row['crop_json'] or not row['human_verified']:cat='INVALID_CROP'
   elif not row['developed_relpath'] or not self.resolve_data_path(row['developed_relpath']).is_file():cat='INVALID_CACHE'
   else:cat='OTHER'
   seen.add(i);counts[cat]+=1
  return {"new_considered_verified_crops":len(rows),"added_to_training_now":counts['ADDED_TO_TRAINING'],"already_seen_in_lineage":counts['ALREADY_SEEN'],"holdout_reserved":counts['HOLDOUT'],"invalid_or_missing_cache":counts['INVALID_CACHE'],"no_valid_final_crop":counts['INVALID_CROP'],"duplicates":counts['DUPLICATE'],"other_excluded":counts['OTHER'],"candidate_categories":counts}
 def reconcile_crop_holdout_references(self):
  holdout_id=self.crop_holdout_id();created=skipped=0
  if not holdout_id:return {"eligible":0,"created":0,"skipped":0}
  seen=set()
  with self.transaction() as c:seen={r[0] for r in c.execute("SELECT DISTINCT image_id FROM crop_training_membership")}
  for row in self.crop_holdout_images(holdout_id):
   i=row['image_id'];rec=self.crop_record(i)
   if self.crop_holdout_reference(i,holdout_id):skipped+=1;continue
   if rec and rec.get('human_verified') and rec.get('provenance') in {'manual','ai_accepted','ai_corrected'} and rec.get('crop_json') and i not in seen:
    self.save_crop_holdout_reference(i,rec['crop_json'],holdout_id);created+=1
   else:skipped+=1
  import logging;logging.getLogger('morphology.crop').info('crop_holdout_reference_backfill eligible=%s created=%s skipped=%s',created+skipped,created,skipped)
  return {"eligible":created+skipped,"created":created,"skipped":skipped}
 def crop_training_breakdown(self,previous_model_id,current_image_ids):
  current=set(current_image_ids);previous=self.crop_model_lineage_ids(previous_model_id) if previous_model_id else set()
  with self.transaction() as c:
   verified={r[0] for r in c.execute("SELECT image_id FROM crop_verified_observations")};holdout={r[0] for r in c.execute("SELECT image_id FROM crop_holdout")}
  return {"previous_training_count":len(previous) if previous_model_id else None,"current_training_count":len(current),"delta_training_count":len(current)-len(previous) if previous_model_id else None,"new_human_verified_since_previous":len(verified-previous) if previous_model_id else None,"added_to_training_now":len(current-previous),"already_seen_in_lineage":len(current & previous),"holdout_reserved":len(holdout),"invalid_or_missing_cache":0,"no_valid_final_crop":0,"duplicates":len(current_image_ids)-len(current),"other_excluded":0}
 def record_crop_training_membership(self,model_id,image_ids):
  stamp=now()
  with self.transaction() as c:
   for image_id in image_ids:c.execute("INSERT OR IGNORE INTO crop_training_membership(model_id,image_id,recorded_at) VALUES (?,?,?)",(model_id,image_id,stamp))
 def crop_training_eligible_ids(self):
  with self.transaction() as c:rows=c.execute("SELECT cr.image_id FROM crops cr JOIN images i ON i.image_id=cr.image_id WHERE cr.provenance IN ('manual','ai_accepted','ai_corrected') AND COALESCE(cr.human_verified,0)=1 AND COALESCE(i.excluded,0)=0 AND NOT EXISTS(SELECT 1 FROM crop_holdout h WHERE h.image_id=cr.image_id)").fetchall()
  return tuple(r[0] for r in rows)
 def crop_holdout_id(self):
  with self.transaction() as c:r=c.execute("SELECT holdout_id FROM crop_holdout ORDER BY created_at LIMIT 1").fetchone()
  return r[0] if r else None
 def create_crop_holdout(self,count=50,seed=42):
  existing=self.crop_holdout_id()
  if existing:return existing,tuple(self.crop_holdout_images(existing))
  with self.transaction() as c:rows=c.execute("SELECT image_id,locality,sample_id FROM images WHERE COALESCE(active,1)=1 AND COALESCE(excluded,0)=0 ORDER BY locality,image_id").fetchall()
  import random
  rng=random.Random(seed);groups={}
  for row in rows:groups.setdefault(row['locality'] or row['sample_id'] or '',[]).append(row['image_id'])
  for values in groups.values():rng.shuffle(values)
  selected=[]
  while len(selected)<count and any(groups.values()):
   for key in sorted(groups):
    if groups[key] and len(selected)<count:selected.append(groups[key].pop())
  holdout_id='crop-holdout-'+uuid.uuid4().hex;stamp=now()
  with self.transaction() as c:
   for ident in selected:c.execute("INSERT INTO crop_holdout(holdout_id,image_id,seed,created_at) VALUES (?,?,?,?)",(holdout_id,ident,seed,stamp))
  return holdout_id,tuple(selected)
 def crop_holdout_images(self,holdout_id=None):
  holdout_id=holdout_id or self.crop_holdout_id()
  if not holdout_id:return ()
  with self.transaction() as c:rows=c.execute("SELECT h.image_id,i.original_name,i.relative_path,i.locality FROM crop_holdout h JOIN images i ON i.image_id=h.image_id WHERE h.holdout_id=? ORDER BY i.locality,i.relative_path",(holdout_id,)).fetchall()
  return tuple(dict(r) for r in rows)
 def save_crop_holdout_reference(self,image_id,crop,holdout_id=None):
  holdout_id=holdout_id or self.crop_holdout_id()
  if not holdout_id:raise ValueError('crop holdout has not been created')
  stamp=now();rid='crop-reference-'+uuid.uuid4().hex
  with self.transaction() as c:
   if not c.execute("SELECT 1 FROM crop_holdout WHERE holdout_id=? AND image_id=?",(holdout_id,image_id)).fetchone():raise ValueError('image is not in crop holdout')
   row=c.execute("SELECT COALESCE(MAX(revision),0) FROM crop_holdout_references WHERE holdout_id=? AND image_id=?",(holdout_id,image_id)).fetchone();revision=int(row[0])+1
   c.execute("UPDATE crop_holdout_references SET active=0 WHERE holdout_id=? AND image_id=?",(holdout_id,image_id));c.execute("INSERT INTO crop_holdout_references VALUES (?,?,?,?,?,?,1)",(rid,holdout_id,image_id,json.dumps(list(crop)),revision,stamp))
  return rid
 def crop_holdout_reference(self,image_id,holdout_id=None):
  holdout_id=holdout_id or self.crop_holdout_id()
  if not holdout_id:return None
  with self.transaction() as c:r=c.execute("SELECT * FROM crop_holdout_references WHERE holdout_id=? AND image_id=? AND active=1",(holdout_id,image_id)).fetchone()
  if not r:return None
  d=dict(r);d['crop_json']=json.loads(d['crop_json']);return d
 def crop_holdout_ready_count(self,holdout_id=None):return sum(bool(self.crop_holdout_reference(row['image_id'],holdout_id)) for row in self.crop_holdout_images(holdout_id))
 def pending_ai_crop_ids(self):
  """All active non-excluded AI Crop proposals awaiting human confirmation."""
  with self.transaction() as c:
   rows=c.execute("""SELECT cr.image_id
FROM crops cr
JOIN images i ON i.image_id=cr.image_id
WHERE cr.provenance='ai_unreviewed'
  AND COALESCE(i.active,1)=1
  AND COALESCE(i.excluded,0)=0
ORDER BY cr.image_id""").fetchall()
  return tuple(str(row["image_id"]) for row in rows)
 def pending_ai_crop_summary(self):
  with self.transaction() as c:
   rows=c.execute("""SELECT COALESCE(cr.qc_level,'UNKNOWN') qc_level,COUNT(*) n
FROM crops cr
JOIN images i ON i.image_id=cr.image_id
WHERE cr.provenance='ai_unreviewed'
  AND COALESCE(i.active,1)=1
  AND COALESCE(i.excluded,0)=0
GROUP BY COALESCE(cr.qc_level,'UNKNOWN')""").fetchall()
  counts={str(row["qc_level"]):int(row["n"]) for row in rows}
  return {"total":sum(counts.values()),"by_qc":counts}
 def accept_all_ai_crops(self):
  """Explicit bulk human acceptance of unchanged pending AI Crop proposals."""
  stamp=now();accepted=[];skipped=[]
  with self.transaction() as c:
   rows=c.execute("""SELECT cr.image_id,cr.crop_json,cr.transform_json,cr.rotation_degrees
FROM crops cr
JOIN images i ON i.image_id=cr.image_id
WHERE cr.provenance='ai_unreviewed'
  AND COALESCE(i.active,1)=1
  AND COALESCE(i.excluded,0)=0
ORDER BY cr.image_id""").fetchall()
   for row in rows:
    image_id=str(row["image_id"])
    try:
     bounds=json.loads(row["crop_json"]) if row["crop_json"] else None
     transform=json.loads(row["transform_json"]) if row["transform_json"] else None
     valid=isinstance(bounds,list) and len(bounds)==4 and isinstance(transform,dict)
     if valid:
      left,top,right,bottom=(float(value) for value in bounds)
      valid=right>left and bottom>top
    except (TypeError,ValueError,json.JSONDecodeError):
     valid=False
    if not valid:
     skipped.append(image_id);continue
    c.execute("""UPDATE crops
SET provenance='ai_accepted',
    human_verified=1,
    human_changed=0,
    reviewed_at=?,
    updated_at=?
WHERE image_id=? AND provenance='ai_unreviewed'""",(stamp,stamp,image_id))
    c.execute("""INSERT INTO crop_verified_observations(image_id,verified_at)
VALUES (?,?)
ON CONFLICT(image_id) DO UPDATE SET verified_at=excluded.verified_at""",(image_id,stamp))
    accepted.append(image_id)
  # Preserve the existing forward-only crop holdout policy for newly verified crops.
  for image_id in accepted:
   record=self.crop_record(image_id)
   if record:self._auto_reserve_crop_holdout(image_id,record)
  return {"accepted":len(accepted),"skipped":len(skipped),"accepted_ids":tuple(accepted),"skipped_ids":tuple(skipped)}
 def crop_review_candidates(self,include_ok=True):
  # Review worst orders all pending AI work; severity is never a membership gate.
  levels=("BAD","REVIEW","OK") if include_ok else ("BAD","REVIEW");marks=','.join('?'*len(levels))
  with self.transaction() as c:rows=c.execute(f"SELECT cr.image_id FROM crops cr JOIN images i ON i.image_id=cr.image_id WHERE cr.provenance='ai_unreviewed' AND COALESCE(i.active,1)=1 AND COALESCE(i.excluded,0)=0 AND cr.qc_level IN ({marks}) ORDER BY CASE cr.qc_level WHEN 'BAD' THEN 0 WHEN 'REVIEW' THEN 1 ELSE 2 END, COALESCE(cr.qc_score,0) ASC, cr.image_id",levels).fetchall()
  return tuple(r[0] for r in rows)
 def crop_manual_review_candidates(self):
  """Human-made Crop records available for optional re-review in the main Crop editor."""
  with self.transaction() as c:
   rows=c.execute("SELECT cr.image_id FROM crops cr JOIN images i ON i.image_id=cr.image_id WHERE cr.provenance='manual' AND COALESCE(cr.human_verified,0)=1 AND cr.crop_json IS NOT NULL AND COALESCE(i.active,1)=1 AND COALESCE(i.excluded,0)=0 ORDER BY COALESCE(cr.reviewed_at,cr.updated_at),cr.image_id").fetchall()
  return tuple(r[0] for r in rows)
 def crop_counts(self):
  """Canonical Crop-only status counts; never derive Crop UI from landmarks."""
  with self.transaction() as c:
   total=c.execute("SELECT COUNT(*) FROM images WHERE COALESCE(active,1)=1 AND COALESCE(excluded,0)=0").fetchone()[0]
   rows=c.execute("SELECT cr.provenance,cr.human_verified,cr.qc_level FROM crops cr JOIN images i ON i.image_id=cr.image_id WHERE COALESCE(i.active,1)=1 AND COALESCE(i.excluded,0)=0").fetchall()
  auto=sum(1 for r in rows if r['provenance']=='ai_unreviewed')
  checked=sum(1 for r in rows if r['human_verified'] and r['provenance'] in {'manual','ai_accepted','ai_corrected'})
  uncropped=max(0,total-checked-auto)
  return {'Total':total,'Reviewed':checked,'AI pending':auto,'Train ready':len(self.crop_training_eligible_ids()),'Uncropped':uncropped}
 def crop_section_counts(self):
  return self.crop_counts()
 def crop_batch_counts(self,image_ids):
  """Persisted Crop batch truth; UI completed_ids are never scientific authority."""
  ids=tuple(dict.fromkeys(str(x) for x in image_ids))
  if not ids:return {"Reviewed":0,"Remaining":0,"Train ready":0,"Total":0}
  marks=','.join('?'*len(ids))
  with self.transaction() as c:
   rows=c.execute(f"SELECT i.image_id,i.excluded,cr.provenance,cr.human_verified,cr.crop_json FROM images i LEFT JOIN crops cr ON cr.image_id=i.image_id WHERE i.image_id IN ({marks})",ids).fetchall()
   train={r[0] for r in c.execute(f"SELECT image_id FROM crops WHERE provenance IN ('manual','ai_accepted','ai_corrected') AND COALESCE(human_verified,0)=1 AND image_id IN ({marks})",ids)}
  present={r['image_id']:r for r in rows};eligible=[ident for ident in ids if ident in present and not present[ident]['excluded']]
  reviewed=sum(bool(present[i]['human_verified']) and present[i]['provenance'] in {'manual','ai_accepted','ai_corrected'} and bool(present[i]['crop_json']) for i in eligible)
  return {"Reviewed":reviewed,"Remaining":max(0,len(eligible)-reviewed),"Train ready":len(train),"Total":len(eligible)}
 def landmark_counts(self):
  """Landmark counts with Train ready meaning current verified training states not in the active lineage."""
  from .landmark_dataset import training_ready_image_ids
  rows=[row for row in self.catalog_rows() if not row.get('excluded')]
  checked=sum(bool(row.get('human_verified')) for row in rows)
  unresolved=sum(bool(row.get('missing_ids') or row.get('extra_ids') or row.get('placed',0)<row.get('expected_landmarks',0)) for row in rows)
  ready=training_ready_image_ids(self)
  return {"Total":len(rows),"Human reviewed / Checked":checked,"Remaining":unresolved,"Train ready":len(ready)}
 def exclude_image(self,image_id,reason,note=None):
  reason=(reason or "Other").strip() or "Other"
  with self.transaction() as c:c.execute("UPDATE images SET excluded=1,exclusion_reason=?,exclusion_note=? WHERE image_id=?",(reason,(note or "").strip() or None,image_id))
 def restore_image(self,image_id):
  with self.transaction() as c:c.execute("UPDATE images SET excluded=0,exclusion_reason=NULL,exclusion_note=NULL WHERE image_id=?",(image_id,))
 def image_exclusion(self,image_id):
  with self.transaction() as c:row=c.execute("SELECT excluded,exclusion_reason,exclusion_note FROM images WHERE image_id=?",(image_id,)).fetchone()
  return dict(row) if row else {"excluded":0,"exclusion_reason":None,"exclusion_note":None}
 def reserve_permanent_test(self,image_ids):
  ids=tuple(dict.fromkeys(str(image_id) for image_id in image_ids))
  with self.transaction() as c:
   for image_id in ids:
    if not c.execute("SELECT 1 FROM images WHERE image_id=?",(image_id,)).fetchone(): raise KeyError(f"unknown image_id: {image_id}")
    c.execute("INSERT OR IGNORE INTO ai_permanent_holdouts(image_id,reserved_at) VALUES (?,?)",(image_id,now()))
  return ids
 def permanent_test_image_ids(self):
  with self.transaction() as c:return frozenset(row[0] for row in c.execute("SELECT image_id FROM ai_permanent_holdouts"))
 def get_landmarks_for_classical(self):
  return tuple(row for row in self.schema if row.get("role","BOTH") in {"CLASSICAL","BOTH"})
 def get_landmarks_for_gm(self):
  return tuple(row for row in self.schema if row.get("role","BOTH") in {"GM","BOTH"})
 def expected_landmarks(self): return len(self.schema)
 def save_annotation_draft(self,image_id,workflow_stage=None,workflow_position=None,manual_rebuild=None):
  """Mark current canonical landmark rows as unfinished; retain explicit rebuild intent."""
  stamp=now()
  with self.transaction() as c:
   old=c.execute("SELECT manual_rebuild FROM annotation_drafts WHERE image_id=?",(image_id,)).fetchone();flag=int(manual_rebuild) if manual_rebuild is not None else int(old[0]) if old else 0
   c.execute("INSERT INTO annotation_drafts(image_id,workflow_stage,workflow_position,manual_rebuild,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET workflow_stage=excluded.workflow_stage,workflow_position=excluded.workflow_position,manual_rebuild=excluded.manual_rebuild,updated_at=excluded.updated_at",(image_id,workflow_stage,workflow_position,flag,stamp))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,stamp))
 def annotation_draft(self,image_id):
  with self.transaction() as c: row=c.execute("SELECT * FROM annotation_drafts WHERE image_id=?",(image_id,)).fetchone()
  return dict(row) if row else None
 def clear_annotation_draft(self,image_id):
  with self.transaction() as c:c.execute("DELETE FROM annotation_drafts WHERE image_id=?",(image_id,))
 def clear_landmark_finals_for_draft(self,image_id,workflow_stage=None,workflow_position=None):
  """Clear editable finals, retain AI history, and persist explicit manual-rebuild intent."""
  stamp=now()
  with self.transaction() as c:
   c.execute("UPDATE landmarks SET x_standardized=NULL,y_standardized=NULL,state='unresolved',reviewed=0,updated_at=? WHERE image_id=?",(stamp,image_id))
   c.execute("INSERT INTO annotation_drafts(image_id,workflow_stage,workflow_position,manual_rebuild,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET workflow_stage=excluded.workflow_stage,workflow_position=excluded.workflow_position,manual_rebuild=1,updated_at=excluded.updated_at",(image_id,workflow_stage,workflow_position,1,stamp))
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,stamp))
 def _ai_review_fingerprint(self, connection, image_id, *, schema_identity=None, legacy_schema_sha256=None):
  active={str(row["abbr"]) for row in self.schema}
  rows=[dict(row) for row in connection.execute("SELECT landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,predicted_x,predicted_y,prediction_run_id,reviewed FROM landmarks WHERE image_id=? ORDER BY landmark_abbr",(image_id,)) if str(row["landmark_abbr"]) in active]
  crop=connection.execute("SELECT crop_json,transform_json,rotation_degrees FROM crops WHERE image_id=?",(image_id,)).fetchone()
  schema_part={"schema_sha256":str(legacy_schema_sha256)} if legacy_schema_sha256 is not None else {"schema_identity":tuple(schema_identity or landmark_schema_identity(self.schema))}
  payload={**schema_part,"rows":rows,"crop":dict(crop) if crop else None}
  return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
 def _active_ai_rows(self, connection, image_id):
  active={str(row["abbr"]) for row in self.schema}
  return [dict(row) for row in connection.execute("SELECT * FROM landmarks WHERE image_id=?",(image_id,)) if str(row["landmark_abbr"]) in active and (row["provenance"]=="machine" or row["model_id"] is not None or row["prediction_run_id"] is not None)]
 def landmark_ai_review_ready(self,image_id):
  """True only when the current AI-origin final state has an explicit matching human confirmation."""
  status=self.annotation_status(image_id)
  if not status["complete"]: return False
  identity=landmark_schema_identity(self.schema);digest=schema_hash(self.schema_path)
  with self.transaction() as c:
   ai_rows=self._active_ai_rows(c,image_id)
   if not ai_rows:return True
   current_machine=[row for row in ai_rows if row.get("provenance")=="machine"]
   if not current_machine:return True
   if any(not bool(row.get("reviewed")) for row in current_machine):return False
   verified=c.execute("SELECT human_verified FROM image_review WHERE image_id=?",(image_id,)).fetchone()
   if not verified or not bool(verified[0]):return False
   fingerprint=self._ai_review_fingerprint(c,image_id,schema_identity=identity)
   records=c.execute("SELECT payload_json FROM qc WHERE image_id=? AND kind=? ORDER BY qc_id DESC",(image_id,"landmark_ai_review_confirmation")).fetchall()
   payloads=[]
   for record in records:
    try:payloads.append(json.loads(record["payload_json"]))
    except (TypeError,json.JSONDecodeError):continue
   legacy={str(payload.get("schema_sha256")):self._ai_review_fingerprint(c,image_id,legacy_schema_sha256=payload.get("schema_sha256")) for payload in payloads if payload.get("schema_identity") is None and payload.get("schema_sha256")}
  for payload in payloads:
   stored_identity=payload.get("schema_identity")
   if stored_identity is not None and tuple(str(value) for value in stored_identity)==identity and payload.get("state_fingerprint")==fingerprint:return True
   legacy_digest=payload.get("schema_sha256")
   if stored_identity is None and legacy_digest and payload.get("state_fingerprint")==legacy.get(str(legacy_digest)):
    if legacy_digest==digest:return True
    for model_id in payload.get("model_ids") or ():
     model=self.model_metadata(str(model_id))
     if model and landmark_model_schema_compatible(self,model):return True
  return False
 def unverified_landmark_image_ids(self):
  """Return active images that already have landmark rows but are not human-verified."""
  active=tuple(sorted(str(row["abbr"]) for row in self.schema))
  if not active:return ()
  placeholders=",".join("?" for _ in active)
  with self.transaction() as c:
   rows=c.execute(f"""SELECT DISTINCT l.image_id
FROM landmarks l
JOIN images i ON i.image_id=l.image_id
LEFT JOIN image_review r ON r.image_id=l.image_id
WHERE COALESCE(i.active,1)=1
  AND COALESCE(i.excluded,0)=0
  AND l.landmark_abbr IN ({placeholders})
  AND COALESCE(r.human_verified,0)=0
ORDER BY l.image_id""",active).fetchall()
  return tuple(str(row["image_id"]) for row in rows)

 def pending_ai_landmark_image_ids(self):
  """Return active non-excluded images whose current AI-origin landmarks still need human confirmation."""
  active=tuple(sorted(str(row["abbr"]) for row in self.schema))
  if not active:return ()
  placeholders=",".join("?" for _ in active)
  with self.transaction() as c:
   rows=c.execute(f"""SELECT DISTINCT l.image_id
FROM landmarks l
JOIN images i ON i.image_id=l.image_id
WHERE COALESCE(i.active,1)=1
  AND COALESCE(i.excluded,0)=0
  AND l.landmark_abbr IN ({placeholders})
  AND (l.provenance='machine' OR l.model_id IS NOT NULL OR l.prediction_run_id IS NOT NULL)
ORDER BY l.image_id""",active).fetchall()
  return tuple(image_id for image_id in (str(row["image_id"]) for row in rows) if not self.landmark_ai_review_ready(image_id))
 def confirm_landmark_ai_review(self,image_id,batch_id=None):
  """Transactionally confirm the current complete AI landmark state after human inspection."""
  from .landmark_frames import crop_frame_record
  if self.catalog_row(image_id) is None:raise KeyError(f"unknown image: {image_id}")
  crop=crop_frame_record(self,image_id)
  if not crop or crop.get("provenance") not in {"manual","ai_accepted","ai_corrected"} or not crop.get("human_verified"):raise ValueError("canonical Crop frame is required before confirming AI landmarks")
  status=self.annotation_status(image_id)
  if not status["complete"]:raise ValueError("all landmarks must be resolved before confirming AI review")
  stamp=now()
  with self.transaction() as c:
   ai_rows=self._active_ai_rows(c,image_id)
   if not ai_rows:raise ValueError("image has no current AI-origin landmarks to confirm")
   c.execute("UPDATE landmarks SET reviewed=1,updated_at=? WHERE image_id=? AND (provenance=? OR model_id IS NOT NULL OR prediction_run_id IS NOT NULL)",(stamp,image_id,"machine"))
   identity=landmark_schema_identity(self.schema);fingerprint=self._ai_review_fingerprint(c,image_id,schema_identity=identity)
   run_ids=sorted({str(row["prediction_run_id"]) for row in ai_rows if row.get("prediction_run_id")})
   model_ids=sorted({str(row["model_id"]) for row in ai_rows if row.get("model_id")})
   payload={"image_id":str(image_id),"batch_id":None if batch_id is None else str(batch_id),"prediction_run_ids":run_ids,"model_ids":model_ids,"schema_sha256":schema_hash(self.schema_path),"schema_identity":list(identity),"state_fingerprint":fingerprint,"confirmed_at":stamp}
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=excluded.human_verified,updated_at=excluded.updated_at",(image_id,1,stamp))
   c.execute("DELETE FROM annotation_drafts WHERE image_id=?",(image_id,))
   c.execute("DELETE FROM image_attributes WHERE image_id=? AND attribute_key=?",(image_id,"landmark_crop_review_required"))
   existing=c.execute("SELECT payload_json FROM qc WHERE image_id=? AND kind=? ORDER BY qc_id DESC",(image_id,"landmark_ai_review_confirmation")).fetchall()
   if not any((json.loads(row["payload_json"]).get("state_fingerprint")==fingerprint) for row in existing):
    c.execute("INSERT INTO qc(image_id,kind,payload_json,created_at) VALUES (?,?,?,?)",(image_id,"landmark_ai_review_confirmation",json.dumps(payload,sort_keys=True),stamp))
  return payload
 def mark_checked(self,image_id):
  status=self.annotation_status(image_id)
  if not status["complete"]: raise ValueError("all landmarks must be resolved before checking")
  with self.transaction() as c:has_ai=bool(self._active_ai_rows(c,image_id))
  if has_ai:return self.confirm_landmark_ai_review(image_id)
  with self.transaction() as c:
   c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=excluded.human_verified,updated_at=excluded.updated_at",(image_id,1,now()))
   c.execute("DELETE FROM annotation_drafts WHERE image_id=?",(image_id,))
   c.execute("DELETE FROM image_attributes WHERE image_id=? AND attribute_key='landmark_crop_review_required'",(image_id,))
 def clear_checked(self,image_id):
  with self.transaction() as c:c.execute("INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=0,updated_at=excluded.updated_at",(image_id,0,now()))
 def accept_review_warning(self,image_id,warning):
  """Persist a human acceptance without touching canonical landmark coordinates."""
  from .landmark_review import warning_landmark_ids,warning_state_fingerprint
  ids=warning_landmark_ids(warning);payload={"image_id":str(image_id),"schema_sha256":schema_hash(self.schema_path),"schema_identity":list(landmark_schema_identity(self.schema)),"warning_kind":str(warning.get("kind","")),"landmark_ids":list(ids),"state_fingerprint":warning_state_fingerprint(self,image_id,warning),"accepted_by_human":True,"timestamp":now()}
  with self.transaction() as c:c.execute("INSERT INTO qc(image_id,kind,payload_json,created_at) VALUES (?,?,?,?)",(image_id,"landmark_review_acceptance",json.dumps(payload,sort_keys=True),payload["timestamp"]))
  return payload
 def review_warning_is_accepted(self,image_id,warning):
  """Acceptance follows semantic landmark identity and the reviewed final states."""
  from .landmark_review import warning_landmark_ids,warning_state_fingerprint
  ids=list(warning_landmark_ids(warning));digest=schema_hash(self.schema_path);identity=landmark_schema_identity(self.schema);fingerprint=warning_state_fingerprint(self,image_id,warning)
  with self.transaction() as c:rows=c.execute("SELECT payload_json FROM qc WHERE image_id=? AND kind=? ORDER BY qc_id DESC",(image_id,"landmark_review_acceptance")).fetchall()
  for row in rows:
   try:payload=json.loads(row["payload_json"])
   except (TypeError,json.JSONDecodeError):continue
   stored_identity=payload.get("schema_identity")
   schema_ok=(tuple(map(str,stored_identity))==identity) if stored_identity is not None else payload.get("schema_sha256")==digest
   if payload.get("accepted_by_human") and schema_ok and payload.get("warning_kind")==warning.get("kind") and payload.get("landmark_ids")==ids and payload.get("state_fingerprint")==fingerprint:return True
  return False
 def annotation_status(self,image_id):
  from .landmark_state import load_current_landmark_state
  state=load_current_landmark_state(self,image_id)
  if state.extra_ids and (image_id,tuple(sorted(state.extra_ids))) not in self._orphan_warned:
   import logging
   logging.getLogger("morphology.project").warning("orphan_landmarks_found image_id=%s extra_ids=%s",image_id,sorted(state.extra_ids))
   self._orphan_warned.add((image_id,tuple(sorted(state.extra_ids))))
  return {"image_id":state.image_id,"placed":state.placed_count,"resolved":state.resolved_count,"expected":state.expected_count,"human_placed":len(state.human_ids),"verified":state.human_verified,"missing":sorted(state.unresolved_ids),"missing_ids":sorted(state.unresolved_ids),"unresolved_ids":sorted(state.unresolved_ids),"explicitly_missing_ids":sorted(state.explicitly_missing_ids),"extra_ids":sorted(state.extra_ids),"complete":state.complete,"color":state.color}
 def set_locality_calibration(self,locality_id,reference_image_id,scale,units,calibration_data):
  with self.transaction() as c:c.execute("INSERT INTO locality_calibrations(locality_id,scale,units,calibration_reference_image_id,calibration_data,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(locality_id) DO UPDATE SET scale=excluded.scale,units=excluded.units,calibration_reference_image_id=excluded.calibration_reference_image_id,calibration_data=excluded.calibration_data,updated_at=excluded.updated_at",(locality_id,scale,units,reference_image_id,json.dumps(calibration_data),now()))
 def locality_calibration(self,locality_id):
  with self.transaction() as c:r=c.execute("SELECT * FROM locality_calibrations WHERE locality_id=?",(locality_id,)).fetchone()
  return dict(r) if r else None
 def attributes_schema(self):
  path=self.root/"attributes.csv"
  if not path.exists(): return []
  with path.open(encoding="utf-8-sig",newline="") as f:return [{"key":r["key"].strip(),"label":r["label"].strip(),"values":[x.strip() for x in r["values"].split("|") if x.strip()]} for r in csv.DictReader(f) if r.get("key") and r.get("values")]
 def set_attribute(self,image_id,key,value):
  with self.transaction() as c:c.execute("INSERT INTO image_attributes(image_id,attribute_key,value,updated_at) VALUES (?,?,?,?) ON CONFLICT(image_id,attribute_key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(image_id,key,value,now()))
 def attributes_for_image(self,image_id):
  with self.transaction() as c:return {r[0]:r[1] for r in c.execute("SELECT attribute_key,value FROM image_attributes WHERE image_id=?",(image_id,))}
 def catalog_row(self,image_id):
  """Read and decorate one authoritative catalog row without rebuilding the list."""
  with self.transaction() as c:
   image=c.execute("SELECT i.*,COALESCE(r.human_verified,0) human_verified,EXISTS(SELECT 1 FROM locality_calibrations lc WHERE lc.locality_id=COALESCE(i.locality,i.sample_id)) calibrated,EXISTS(SELECT 1 FROM crops cr WHERE cr.image_id=i.image_id AND cr.crop_json IS NOT NULL AND cr.crop_json!='null' AND cr.transform_json IS NOT NULL AND cr.transform_json!='null' AND cr.provenance IN ('manual','ai_accepted','ai_corrected') AND COALESCE(cr.human_verified,0)=1) has_crop FROM images i LEFT JOIN image_review r ON r.image_id=i.image_id WHERE COALESCE(i.active,1)=1 AND i.image_id=?",(image_id,)).fetchone()
  if not image:return None
  d=dict(image);status=self.annotation_status(d["image_id"])
  d.update({"human_verified":bool(status["verified"]),"expected_landmarks":status["expected"],"placed":status["placed"],"human_placed":status["human_placed"],"missing_ids":status["missing_ids"],"extra_ids":status["extra_ids"],"status_color":"excluded" if d.get("excluded") else status["color"],"status_image_id":d["image_id"],"has_crop":bool(d.get("has_crop"))})
  return d
 def catalog_rows(self):
  """Bulk-build authoritative catalogue rows without one SQLite round-trip per image."""
  schema_by_abbr={str(row["abbr"]):int(row["id"]) for row in self.schema}
  required_ids=frozenset(schema_by_abbr.values())
  from .landmark_state import landmark_needs_ai_review
  human={"manual","corrected","corrected_by_human","reviewed_by_human"}
  with self.transaction() as c:
   images=c.execute("SELECT i.*,COALESCE(r.human_verified,0) human_verified,EXISTS(SELECT 1 FROM locality_calibrations lc WHERE lc.locality_id=COALESCE(i.locality,i.sample_id)) calibrated,EXISTS(SELECT 1 FROM crops cr WHERE cr.image_id=i.image_id AND cr.crop_json IS NOT NULL AND cr.crop_json!='null' AND cr.transform_json IS NOT NULL AND cr.transform_json!='null' AND cr.provenance IN ('manual','ai_accepted','ai_corrected') AND COALESCE(cr.human_verified,0)=1) has_crop FROM images i LEFT JOIN image_review r ON r.image_id=i.image_id WHERE COALESCE(i.active,1)=1 ORDER BY locality COLLATE NOCASE,index_in_locality,relative_path").fetchall()
   image_ids={row["image_id"] for row in images}
   review_required={row["image_id"] for row in c.execute("SELECT image_id FROM image_attributes WHERE attribute_key='landmark_crop_review_required' AND lower(value)='true'") if row["image_id"] in image_ids}
   grouped={image_id:{} for image_id in image_ids}
   for raw in c.execute("SELECT image_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,prediction_run_id,reviewed FROM landmarks"):
    image_id=raw["image_id"]
    if image_id not in grouped:continue
    abbr=str(raw["landmark_abbr"] or "")
    display=schema_by_abbr.get(abbr)
    if display is None:continue
    grouped[image_id][display]=dict(raw)
  result=[]
  for image in images:
   d=dict(image);points=grouped.get(d["image_id"],{})
   present={ident for ident,row in points.items() if row.get("state")!="missing" and row.get("x_standardized") is not None and row.get("y_standardized") is not None}
   explicit_missing={ident for ident,row in points.items() if row.get("state")=="missing"}
   unresolved=required_ids-(present|explicit_missing)
   human_present={ident for ident,row in points.items() if ident in present and row.get("provenance") in human}
   pending_ai=any(landmark_needs_ai_review(row) for row in points.values())
   needs_review=d["image_id"] in review_required or pending_ai
   verified=bool(d.get("human_verified")) and not needs_review
   color="red" if unresolved else "yellow" if needs_review else "green" if verified or present<=human_present else "yellow"
   # load_landmarks() ignores historical abbreviations that are no longer in
   # the active schema, so the bulk catalogue must preserve the same semantics.
   d.update({"human_verified":verified,"expected_landmarks":len(required_ids),"placed":len(present),"human_placed":len(human_present),"missing_ids":sorted(unresolved),"extra_ids":[],"status_color":"excluded" if d.get("excluded") else color,"status_image_id":d["image_id"],"has_crop":bool(d.get("has_crop"))})
   result.append(d)
  return result
 def count(self,table):
  if table not in {"images","landmarks","crops","corrections","training_examples","models","qc","landmark_schema"}:raise ValueError("unknown project table")
  with self.transaction() as c:return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
 def backup(self):
  target=self.root/"project.backup.sqlite";source=self.connect();dest=sqlite3.connect(target)
  try:source.backup(dest)
  finally:dest.close();source.close()
  return target

 def register_model(self,model_id,kind,path=None,metrics=None,active=False,pinned=False,schema_digest=None,dataset_id=None,parent_model_id=None,dataset_manifest_path=None):
  digest=schema_digest or schema_hash(self.schema_path)
  if kind=="landmark" and digest!=schema_hash(self.schema_path): raise ValueError("landmark model schema hash does not match project schema")
  with self.transaction() as c:
   if parent_model_id==model_id: raise ValueError("model cannot be its own parent")
   if parent_model_id and not c.execute("SELECT 1 FROM models WHERE model_id=?",(parent_model_id,)).fetchone(): raise ValueError("parent model does not exist")
   if active:c.execute("UPDATE models SET active=0 WHERE kind=?",(kind,))
   c.execute("INSERT OR REPLACE INTO models(model_id,kind,schema_sha256,path,active,pinned,metrics_json,dataset_id,parent_model_id,dataset_manifest_path,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(model_id,kind,digest,path,int(active),int(pinned),json.dumps(metrics or {}),dataset_id,parent_model_id,dataset_manifest_path,now()))
 def model_metadata(self,model_id):
  with self.transaction() as c:row=c.execute("SELECT * FROM models WHERE model_id=?",(model_id,)).fetchone()
  return dict(row) if row else None
 def set_active_model(self,kind,model_id):
  with self.transaction() as c:
   row=c.execute("SELECT * FROM models WHERE model_id=? AND kind=?",(model_id,kind)).fetchone()
   if not row: raise KeyError(f"unknown {kind} model: {model_id}")
   model=dict(row)
   if kind=="landmark" and not landmark_model_schema_compatible(self,model): raise ValueError("landmark model landmark identities/order do not match current landmark_schema.csv")
   c.execute("UPDATE models SET active=0 WHERE kind=?",(kind,));c.execute("UPDATE models SET active=1 WHERE model_id=?",(model_id,))

 def active_model(self,kind):
  with self.transaction() as c:r=c.execute("SELECT * FROM models WHERE kind=? AND active=1",(kind,)).fetchone()
  model=dict(r) if r else None
  if model and kind=="landmark" and not landmark_model_schema_compatible(self,model): raise ValueError("active landmark model landmark identities/order do not match project schema")
  return model
 def active_model_readonly(self,kind):
  """Read one active model without opening a write-capable project transaction."""
  uri=self.path.resolve().as_uri()+"?mode=ro"
  conn=sqlite3.connect(uri,uri=True,timeout=1);conn.row_factory=sqlite3.Row
  try: row=conn.execute("SELECT * FROM models WHERE kind=? AND active=1",(kind,)).fetchone()
  finally: conn.close()
  model=dict(row) if row else None
  if model and kind=="landmark" and not landmark_model_schema_compatible(self,model): raise ValueError("active landmark model landmark identities/order do not match project schema")
  return model
 def canonical_coordinates(self,image_id):
  """Return accepted full-image coordinates via stored standardized→original transform."""
  from .transforms import Transform
  with self.transaction() as c:
   crop=c.execute("SELECT transform_json FROM crops WHERE image_id=?",(image_id,)).fetchone()
  transform=Transform(**json.loads(crop[0])) if crop and crop[0] else None
  result={}
  for ident,row in self.load_landmarks(image_id).items():
   if row["state"]=="missing" or row["x_standardized"] is None: result[ident]=None
   elif transform: result[ident]=transform.standardized_to_original(row["x_standardized"],row["y_standardized"])
   else: result[ident]=(row["x_standardized"],row["y_standardized"])
  return result
 def export_landmarks(self,target=None):
  target=Path(target or self.root/"exports"/"landmarks.csv");target.parent.mkdir(parents=True,exist_ok=True)
  with self.transaction() as c:rows=c.execute("SELECT l.*,i.original_name,i.relative_path FROM landmarks l JOIN images i USING(image_id) WHERE COALESCE(i.excluded,0)=0 ORDER BY l.image_id,l.landmark_id").fetchall()
  fields=["image_id","original_name","relative_path","landmark_id","x_standardized","y_standardized","x_original","y_original","state","provenance","model_id","confidence","updated_at"]
  with target.open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows([{k:r[k] for k in fields} for r in rows])
  return target
def migrate_legacy(project,legacy_root):
 imported_landmarks=imported_crops=0
 with project.transaction() as c:
  for p in Path(legacy_root).glob("work/*/landmarks/*.json"):
   record=read_json(p,{});image_id=record.get("image_id")
   if not image_id:continue
   for key,point in record.get("points",{}).items():
    try:ident=int(str(point.get("landmark_id",point.get("point_number",key))).lstrip("Pp"))
    except (TypeError,ValueError):continue
    abbr=project.historical_abbr_for_numeric(ident) or project._abbr_for_display(ident)
    active=project.active_landmark_id_for_abbr(abbr) or ident
    c.execute('''INSERT OR REPLACE INTO landmarks(image_id,landmark_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,predicted_x,predicted_y,confidence,prediction_run_id,reviewed,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(image_id,active,abbr,point.get("x_standardized"),point.get("y_standardized"),point.get("state","manual"),point.get("provenance",point.get("state","manual")),point.get("model_id"),point.get("predicted_x"),point.get("predicted_y"),point.get("confidence"),point.get("prediction_run_id"),int(point.get("reviewed",True)),point.get("timestamp",now())))
    imported_landmarks+=1
  for p in Path(legacy_root).glob("work/*/metadata/*.json"):
   if p.name.endswith(".developed.json"):continue
   crop=read_json(p,{})
   if not crop.get("image_id"):continue
   c.execute('''INSERT OR REPLACE INTO crops(image_id,developed_relpath,standardized_relpath,source_sha256,crop_json,transform_json,rotation_degrees,status,provenance,model_id,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(crop["image_id"],crop.get("developed_full_relpath"),crop.get("standardized_relpath"),crop.get("source_sha256"),json.dumps(crop.get("crop_bounds")),json.dumps(crop.get("transform")),crop.get("rotation_degrees"),crop.get("normalization_status"),crop.get("qc_reason","legacy"),crop.get("crop_model_version"),now()));imported_crops+=1
 return {"landmarks":imported_landmarks,"crops":imported_crops}














