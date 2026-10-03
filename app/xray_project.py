"""SQLite persistence for the MorphoLabel X-ray module."""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import sqlite3
import shutil
from datetime import datetime, timezone
import uuid

from .xray_crop import apply_orientation_defaults, normalize_orientation_policy
from .xray_schema import bundled_scheme, calculate_trait_values, compatible_reference_roles, normalize_scheme, scheme_hash, spatial_series_order

IMAGE_EXTENSIONS={".png",".jpg",".jpeg",".tif",".tiff",".bmp"}
STRUCTURE_VISIBILITY_STATES=("complete","partial","not_visible","absent")

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))

class XRayProject:
    def __init__(self,root):
        self.root=Path(root);self.db_path=self.root/"xray_project.sqlite3"
        if not self.db_path.is_file():raise FileNotFoundError(self.db_path)
        self._ensure_schema()

    @staticmethod
    def _source_files(source):
        source=Path(source)
        return [path for path in sorted(source.rglob("*")) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]

    @staticmethod
    def _copy_source_files(source,target,relative_paths=None):
        source=Path(source);target=Path(target);target.mkdir(parents=True,exist_ok=True)
        paths=XRayProject._source_files(source) if relative_paths is None else [source/Path(value) for value in relative_paths]
        hardlinked=copied=0;bytes_total=0
        for path in paths:
            if not path.is_file():raise FileNotFoundError(path)
            relative=path.relative_to(source);destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():raise FileExistsError(destination)
            try:
                os.link(path,destination);hardlinked+=1
            except OSError:
                shutil.copy2(path,destination);copied+=1
            try:bytes_total+=int(path.stat().st_size)
            except OSError:pass
        return {"files":len(paths),"hardlinked":hardlinked,"copied":copied,"bytes":bytes_total}

    @classmethod
    def create(cls,name,source,destination,scheme,scheme_note="Initial trait scheme",orientation_policy=None):
        source=Path(source).resolve()
        if not source.is_dir():raise FileNotFoundError(source)
        source_files=cls._source_files(source)
        root=Path(destination)/str(name);root.mkdir(parents=True,exist_ok=False);db=root/"xray_project.sqlite3"
        try:
            cls._copy_source_files(source,root/"source",[path.relative_to(source) for path in source_files])
            policy=normalize_orientation_policy(orientation_policy)
            with sqlite3.connect(db) as c:
                cls._create_tables(c)
                c.executemany("INSERT INTO meta(key,value) VALUES(?,?)",(
                    ("name",str(name)),("source","source"),("source_storage","managed_v1"),
                    ("orientation_policy",_json(policy)),("created_at",_now()),
                ))
            project=cls(root);project.save_scheme(scheme,scheme_note);project.scan_source();return project
        except Exception:
            shutil.rmtree(root,ignore_errors=True);raise

    @staticmethod
    def _create_tables(c):
        c.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS schema_versions(
          version_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, scheme_hash TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS source_images(
          image_id TEXT PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, excluded INTEGER NOT NULL DEFAULT 0,
          crop_reviewed INTEGER NOT NULL DEFAULT 0, crop_reviewed_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS specimens(
          specimen_id TEXT PRIMARY KEY, image_id TEXT NOT NULL, label TEXT NOT NULL,
          crop_json TEXT, excluded INTEGER NOT NULL DEFAULT 0, ordinal INTEGER NOT NULL DEFAULT 0,
          crop_source TEXT NOT NULL DEFAULT '', crop_status TEXT NOT NULL DEFAULT 'proposed',
          crop_qc_json TEXT NOT NULL DEFAULT '[]', model_id TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(image_id) REFERENCES source_images(image_id)
        );
        CREATE TABLE IF NOT EXISTS crop_events(
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, specimen_id TEXT NOT NULL,
          created_at TEXT NOT NULL, action TEXT NOT NULL, source TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(specimen_id) REFERENCES specimens(specimen_id)
        );
        CREATE TABLE IF NOT EXISTS xray_crop_models(
          model_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, path TEXT NOT NULL,
          config_path TEXT NOT NULL DEFAULT '', parent_model_id TEXT,
          metrics_json TEXT NOT NULL DEFAULT '{}', training_plate_count INTEGER NOT NULL DEFAULT 0,
          training_specimen_count INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS xray_crop_training_membership(
          model_id TEXT NOT NULL, image_id TEXT NOT NULL,
          PRIMARY KEY(model_id,image_id),
          FOREIGN KEY(model_id) REFERENCES xray_crop_models(model_id),
          FOREIGN KEY(image_id) REFERENCES source_images(image_id)
        );
        CREATE TABLE IF NOT EXISTS xray_structure_models(
          model_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, path TEXT NOT NULL,
          metadata_path TEXT NOT NULL, parent_model_id TEXT, schema_digest TEXT NOT NULL,
          backend TEXT NOT NULL, metrics_json TEXT NOT NULL DEFAULT '{}',
          training_specimen_count INTEGER NOT NULL DEFAULT 0,
          validation_specimen_count INTEGER NOT NULL DEFAULT 0,
          active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS xray_structure_training_membership(
          model_id TEXT NOT NULL, specimen_id TEXT NOT NULL, split TEXT NOT NULL,
          PRIMARY KEY(model_id,specimen_id),
          FOREIGN KEY(model_id) REFERENCES xray_structure_models(model_id),
          FOREIGN KEY(specimen_id) REFERENCES specimens(specimen_id)
        );
        CREATE TABLE IF NOT EXISTS xray_structure_repeatability_runs(
          run_id TEXT PRIMARY KEY, schema_version_id TEXT NOT NULL,
          created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'in_progress',
          requested_count INTEGER NOT NULL DEFAULT 0, seed INTEGER NOT NULL DEFAULT 42,
          annotation1_pass_no INTEGER NOT NULL DEFAULT 0,
          annotation2_pass_no INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS xray_structure_repeatability_membership(
          run_id TEXT NOT NULL, specimen_id TEXT NOT NULL, position INTEGER NOT NULL,
          baseline_json TEXT NOT NULL DEFAULT '[]',
          baseline_visibility_json TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY(run_id,specimen_id),
          FOREIGN KEY(run_id) REFERENCES xray_structure_repeatability_runs(run_id) ON DELETE CASCADE,
          FOREIGN KEY(specimen_id) REFERENCES specimens(specimen_id)
        );
        CREATE TABLE IF NOT EXISTS ui_state(
          key TEXT PRIMARY KEY, payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS annotation_runs(
          run_id TEXT PRIMARY KEY, specimen_id TEXT NOT NULL, pass_no INTEGER NOT NULL,
          source TEXT NOT NULL, schema_version_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
          coordinate_space TEXT NOT NULL DEFAULT 'crop_normalized_v1',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT '', verified_at TEXT NOT NULL DEFAULT '',
          UNIQUE(specimen_id,pass_no,source,schema_version_id)
        );
        CREATE TABLE IF NOT EXISTS annotation_structure_states(
          run_id TEXT NOT NULL, structure_id TEXT NOT NULL,
          visibility TEXT NOT NULL DEFAULT 'complete', updated_at TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(run_id,structure_id),
          FOREIGN KEY(run_id) REFERENCES annotation_runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS annotations(
          annotation_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          structure_id TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(run_id) REFERENCES annotation_runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS annotation_roles(
          role_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          annotation_id INTEGER NOT NULL, structure_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(run_id,structure_id),
          FOREIGN KEY(run_id) REFERENCES annotation_runs(run_id) ON DELETE CASCADE,
          FOREIGN KEY(annotation_id) REFERENCES annotations(annotation_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS annotation_events(
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          created_at TEXT NOT NULL, action TEXT NOT NULL, structure_id TEXT NOT NULL DEFAULT '',
          annotation_id INTEGER, payload_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(run_id) REFERENCES annotation_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS annotation_archives(
          archive_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          specimen_id TEXT NOT NULL, created_at TEXT NOT NULL, reason TEXT NOT NULL,
          crop_json TEXT NOT NULL DEFAULT '{}', annotations_json TEXT NOT NULL DEFAULT '[]',
          structure_states_json TEXT NOT NULL DEFAULT '{}',
          schema_version_id TEXT NOT NULL, pass_no INTEGER NOT NULL, source TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS trait_results(
          specimen_id TEXT NOT NULL, trait_id TEXT NOT NULL, schema_version_id TEXT NOT NULL,
          value_text TEXT, qc_note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
          PRIMARY KEY(specimen_id,trait_id,schema_version_id)
        );
        """)

    @staticmethod
    def _ensure_columns(c,table,wanted):
        existing={row[1] for row in c.execute(f"PRAGMA table_info({table})")}
        for name,definition in wanted.items():
            if name not in existing:c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _ensure_schema(self):
        with sqlite3.connect(self.db_path) as c:
            self._create_tables(c)
            self._ensure_columns(c,"source_images",{
                "crop_reviewed":"INTEGER NOT NULL DEFAULT 0",
                "crop_reviewed_at":"TEXT NOT NULL DEFAULT ''",
            })
            self._ensure_columns(c,"specimens",{
                "ordinal":"INTEGER NOT NULL DEFAULT 0",
                "crop_source":"TEXT NOT NULL DEFAULT ''",
                "crop_status":"TEXT NOT NULL DEFAULT 'proposed'",
                "crop_qc_json":"TEXT NOT NULL DEFAULT '[]'",
                "model_id":"TEXT NOT NULL DEFAULT ''",
                "updated_at":"TEXT NOT NULL DEFAULT ''",
            })
            self._ensure_columns(c,"annotation_runs",{
                "coordinate_space":"TEXT NOT NULL DEFAULT 'crop_normalized_v1'",
                "updated_at":"TEXT NOT NULL DEFAULT ''",
                "verified_at":"TEXT NOT NULL DEFAULT ''",
            })
            self._ensure_columns(c,"annotation_archives",{
                "structure_states_json":"TEXT NOT NULL DEFAULT '{}'",
            })
            self._ensure_columns(c,"xray_structure_repeatability_runs",{
                "annotation1_pass_no":"INTEGER NOT NULL DEFAULT 0",
                "annotation2_pass_no":"INTEGER NOT NULL DEFAULT 0",
            })

    def meta(self,key,default=""):
        with sqlite3.connect(self.db_path) as c:row=c.execute("SELECT value FROM meta WHERE key=?",(key,)).fetchone()
        return default if row is None else row[0]

    @property
    def name(self):return self.meta("name",self.root.name)

    @property
    def source_storage(self):return self.meta("source_storage","external_v0")

    @property
    def source(self):
        value=Path(self.meta("source"))
        return (self.root/value) if self.source_storage.startswith("managed") or not value.is_absolute() else value

    @property
    def is_self_contained(self):
        try:self.source.resolve().relative_to(self.root.resolve());return True
        except ValueError:return False

    @property
    def orientation_policy(self):
        try:return normalize_orientation_policy(json.loads(self.meta("orientation_policy","{}")))
        except Exception:return normalize_orientation_policy()

    def set_orientation_policy(self,value):
        policy=normalize_orientation_policy(value)
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT INTO meta(key,value) VALUES('orientation_policy',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(_json(policy),))
        return policy

    def make_self_contained(self):
        """Import a legacy external source once; hard-link on the same volume, copy otherwise."""
        if self.is_self_contained:return {"changed":False,"files":len(self.source_images()),"hardlinked":0,"copied":0,"bytes":0}
        source=self.source
        if not source.is_dir():raise FileNotFoundError(source)
        self.scan_source();relative=[row["relative_path"] for row in self.source_images()]
        target=self.root/"source";staging=self.root/".source_importing"
        if target.exists():raise FileExistsError(target)
        shutil.rmtree(staging,ignore_errors=True)
        try:
            result=self._copy_source_files(source,staging,relative);staging.replace(target)
            with sqlite3.connect(self.db_path) as c:
                c.execute("INSERT INTO meta(key,value) VALUES('source','source') ON CONFLICT(key) DO UPDATE SET value='source'")
                c.execute("INSERT INTO meta(key,value) VALUES('source_storage','managed_v1') ON CONFLICT(key) DO UPDATE SET value='managed_v1'")
            return {"changed":True,**result}
        except Exception:
            shutil.rmtree(staging,ignore_errors=True);raise

    @staticmethod
    def _tree_bytes(path):
        path=Path(path)
        if not path.exists():return 0
        total=0
        for item in path.rglob("*"):
            if item.is_file():
                try:total+=int(item.stat().st_size)
                except OSError:pass
        return total

    def storage_summary(self):
        return {
            "self_contained":self.is_self_contained,
            "source_bytes":self._tree_bytes(self.source),
            "models_bytes":self._tree_bytes(self.root/"models"),
            "cache_bytes":self._tree_bytes(self.root/"cache"),
        }

    @property
    def models_root(self):
        path=self.root/"models";path.mkdir(parents=True,exist_ok=True);return path

    @property
    def cache_root(self):
        path=self.root/"cache";path.mkdir(parents=True,exist_ok=True);return path

    def compact_disposable_ai_artifacts(self):
        """Remove only reproducible X-ray AI scratch data, never science/model finals."""
        removed_files=0;removed_bytes=0
        targets=[]
        for path in (self.root/"cache"/"xray_detector",self.root/"cache"/"xray_training"):
            if path.exists():targets.append(path)
        models=self.root/"models"
        if models.is_dir():
            for model_dir in models.iterdir():
                if not model_dir.is_dir():continue
                dataset=model_dir/"dataset"
                if dataset.exists():targets.append(dataset)
                targets.extend(path for path in model_dir.glob("work*") if path.is_dir())
        unique=[]
        seen=set()
        for target in targets:
            key=str(target.resolve())
            if key in seen:continue
            seen.add(key);unique.append(target)
        for target in unique:
            for path in target.rglob("*") if target.is_dir() else ():
                if not path.is_file():continue
                try:removed_bytes+=int(path.stat().st_size);removed_files+=1
                except OSError:pass
            shutil.rmtree(target,ignore_errors=True)
        return {"removed_files":removed_files,"removed_bytes":removed_bytes}

    def scan_source(self):
        source=self.source
        if not source.is_dir():return 0
        rows=[]
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                relative=path.relative_to(source).as_posix()
                image_id=str(uuid.uuid5(uuid.NAMESPACE_URL,relative.lower()))
                rows.append((image_id,relative))
        with sqlite3.connect(self.db_path) as c:c.executemany("INSERT OR IGNORE INTO source_images(image_id,relative_path) VALUES(?,?)",rows)
        return len(rows)

    def source_images(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            return [dict(row) for row in c.execute("SELECT image_id,relative_path,excluded,crop_reviewed,crop_reviewed_at FROM source_images ORDER BY relative_path")]

    def source_image(self,image_id):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;row=c.execute("SELECT * FROM source_images WHERE image_id=?",(image_id,)).fetchone()
        if row is None:raise KeyError(f"Unknown X-ray source image: {image_id}")
        return dict(row)

    def source_image_path(self,image_id):
        return self.source/self.source_image(image_id)["relative_path"]

    def set_source_excluded(self,image_id,excluded=True):
        self.source_image(image_id)
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE source_images SET excluded=? WHERE image_id=?",(int(bool(excluded)),image_id))
        return bool(excluded)

    @staticmethod
    def _decode_specimen(row):
        item=dict(row)
        try:item["crop"]=json.loads(item.pop("crop_json") or "{}")
        except Exception:item["crop"]={}
        try:item["crop_qc"]=json.loads(item.pop("crop_qc_json") or "[]")
        except Exception:item["crop_qc"]=[]
        return item

    def specimens(self,image_id=None,active_only=True):
        where=[];args=[]
        if image_id is not None:where.append("image_id=?");args.append(image_id)
        if active_only:where.append("crop_status NOT IN ('superseded','rejected')")
        sql="SELECT * FROM specimens"+((" WHERE "+" AND ".join(where)) if where else "")+" ORDER BY image_id,ordinal,label"
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            return [self._decode_specimen(row) for row in c.execute(sql,args)]

    def specimen(self,specimen_id):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;row=c.execute("SELECT * FROM specimens WHERE specimen_id=?",(specimen_id,)).fetchone()
        if row is None:raise KeyError(f"Unknown specimen: {specimen_id}")
        return self._decode_specimen(row)

    @staticmethod
    def _bbox_iou(a,b):
        a=a.get("bounds") or ();b=b.get("bounds") or ()
        if len(a)!=4 or len(b)!=4:return 0.0
        left=max(float(a[0]),float(b[0]));top=max(float(a[1]),float(b[1]))
        right=min(float(a[2]),float(b[2]));bottom=min(float(a[3]),float(b[3]))
        inter=max(0.0,right-left)*max(0.0,bottom-top)
        if not inter:return 0.0
        aa=max(0.0,float(a[2])-float(a[0]))*max(0.0,float(a[3])-float(a[1]))
        bb=max(0.0,float(b[2])-float(b[0]))*max(0.0,float(b[3])-float(b[1]))
        return inter/max(1e-9,aa+bb-inter)

    @staticmethod
    def _event(c,specimen_id,action,source,payload=None):
        c.execute("INSERT INTO crop_events(specimen_id,created_at,action,source,payload_json) VALUES(?,?,?,?,?)",
                  (specimen_id,_now(),str(action),str(source),_json(payload or {})))

    def _replace_proposals(self,image_id,proposals,source,algorithm,model_id=""):
        if int(self.source_image(image_id).get("crop_reviewed") or 0):
            return {"proposed":0,"high":0,"review":0,"protected":len(self.specimens(image_id))}
        proposals=[p.to_dict() if hasattr(p,"to_dict") else dict(p) for p in proposals]
        now=_now();stem=self.source_image_path(image_id).stem
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            protected=[self._decode_specimen(row) for row in c.execute(
                "SELECT * FROM specimens WHERE image_id=? AND excluded=0 AND (crop_status='confirmed' OR crop_source='manual')",(image_id,))]
            old=[row[0] for row in c.execute(
                "SELECT specimen_id FROM specimens WHERE image_id=? AND crop_status='proposed' AND crop_source!='manual'",(image_id,))]
            for specimen_id in old:
                c.execute("UPDATE specimens SET crop_status='superseded',excluded=1,updated_at=? WHERE specimen_id=?",(now,specimen_id))
                self._event(c,specimen_id,"supersede",source,{"reason":"new_proposal_set","model_id":model_id})
            kept=high=review=0
            for ordinal,crop in enumerate(proposals,1):
                crop=apply_orientation_defaults(crop,self.orientation_policy)
                if any(self._bbox_iou(crop,item.get("crop") or {})>=0.25 for item in protected):
                    kept+=1;continue
                key=f"{image_id}:{source}:{model_id or algorithm}:{ordinal}:{round(float(crop.get('center_x',0)),1)}:{round(float(crop.get('center_y',0)),1)}"
                specimen_id=str(uuid.uuid5(uuid.NAMESPACE_URL,key))
                crop["algorithm"]=str(algorithm);qc=list(crop.get("qc") or [])
                confidence=str(crop.get("confidence") or ("review" if qc else "high"));crop["confidence"]=confidence
                c.execute("""
                    INSERT INTO specimens(specimen_id,image_id,label,crop_json,excluded,ordinal,crop_source,crop_status,crop_qc_json,model_id,updated_at)
                    VALUES(?,?,?,?,0,?,?, 'proposed',?,?,?)
                    ON CONFLICT(specimen_id) DO UPDATE SET
                      image_id=excluded.image_id,label=excluded.label,crop_json=excluded.crop_json,excluded=0,
                      ordinal=excluded.ordinal,crop_source=excluded.crop_source,crop_status='proposed',
                      crop_qc_json=excluded.crop_qc_json,model_id=excluded.model_id,updated_at=excluded.updated_at
                """,(specimen_id,image_id,f"{stem}-{ordinal:02d}",_json(crop),ordinal,str(source),_json(qc),str(model_id or ""),now))
                self._event(c,specimen_id,"detect",source,{"algorithm":algorithm,"model_id":model_id,"confidence":confidence,"qc":qc})
                if confidence=="high":high+=1
                else:review+=1
        return {"proposed":high+review,"high":high,"review":review,"protected":kept}

    def replace_auto_proposals(self,image_id,proposals,algorithm):
        return self._replace_proposals(image_id,proposals,"auto",algorithm)

    def replace_model_proposals(self,image_id,proposals,model_id,algorithm="rtmdet-tiny-v1"):
        return self._replace_proposals(image_id,proposals,"model",str(algorithm),model_id)

    @staticmethod
    def _orientation_verified_crop(crop,source,now):
        value=dict(crop or {});value["orientation_verified"]=True
        value["orientation_verified_at"]=str(now);value["orientation_verified_by"]=str(source)
        return value

    def confirm_specimen(self,specimen_id,source="human"):
        item=self.specimen(specimen_id)
        if item["crop_status"]=="confirmed" and not item["excluded"] and bool((item.get("crop") or {}).get("orientation_verified")):return False
        now=_now();crop=self._orientation_verified_crop(item.get("crop") or {},source,now)
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET crop_json=?,crop_status='confirmed',excluded=0,updated_at=? WHERE specimen_id=?",(_json(crop),now,specimen_id))
            self._event(c,specimen_id,"confirm",source,{"previous_status":item["crop_status"],"orientation_verified":True})
        return True

    def confirm_plate(self,image_id,source="human"):
        rows=[item for item in self.specimens(image_id) if not item["excluded"]]
        if not rows:raise ValueError("This plate has no specimen crops to confirm.")
        now=_now();confirmed=0
        with sqlite3.connect(self.db_path) as c:
            for item in rows:
                crop=self._orientation_verified_crop(item.get("crop") or {},source,now)
                if item["crop_status"]!="confirmed":confirmed+=1
                c.execute("UPDATE specimens SET crop_json=?,crop_status='confirmed',excluded=0,updated_at=? WHERE specimen_id=?",(_json(crop),now,item["specimen_id"]))
                self._event(c,item["specimen_id"],"confirm_plate",source,{"previous_status":item["crop_status"],"orientation_verified":True})
            c.execute("UPDATE source_images SET crop_reviewed=1,crop_reviewed_at=? WHERE image_id=?",(now,image_id))
        return {"specimens":len(rows),"newly_confirmed":confirmed}

    def confirm_clear_proposals(self,image_id=None):
        rows=self.specimens(image_id);accepted=0
        for item in rows:
            if item["crop_status"]!="proposed" or item["excluded"]:continue
            if str((item.get("crop") or {}).get("confidence"))!="high":continue
            accepted+=int(self.confirm_specimen(item["specimen_id"],"human-bulk"))
        return accepted

    def crop_review_candidates(self):
        return [item for item in self.specimens() if item["crop_status"]=="proposed" and not item["excluded"]]

    def pending_clear_crop_count(self,image_id=None):
        return sum(1 for item in self.specimens(image_id) if item["crop_status"]=="proposed" and not item["excluded"] and str((item.get("crop") or {}).get("confidence"))=="high")

    def update_specimen_crop(self,specimen_id,crop,qc=()):
        item=self.specimen(specimen_id);crop=apply_orientation_defaults(crop,self.orientation_policy);crop["confidence"]="high";crop["orientation_verified"]=False;now=_now()
        reviewed=bool(self.source_image(item["image_id"]).get("crop_reviewed"))
        status="confirmed" if reviewed else "proposed"
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET crop_json=?,crop_source='manual',crop_status=?,crop_qc_json=?,model_id='',excluded=0,updated_at=? WHERE specimen_id=?",
                      (_json(crop),status,_json(list(qc)),now,specimen_id))
            self._event(c,specimen_id,"edit","human",{"previous_crop":item.get("crop") or {},"crop":crop})
            if crop!=item.get("crop"):_archive=self._invalidate_annotation_verification(c,specimen_id,"crop_changed",item.get("crop") or {})
        return self.specimen(specimen_id)

    def add_manual_specimen(self,image_id,crop,label=""):
        crop=apply_orientation_defaults(crop,self.orientation_policy);crop["confidence"]="high";crop["orientation_verified"]=False;specimen_id=str(uuid.uuid4());now=_now()
        ordinal=1+max((int(x.get("ordinal") or 0) for x in self.specimens(image_id)),default=0)
        if not label:label=f"{self.source_image_path(image_id).stem}-{ordinal:02d}"
        status="confirmed" if self.source_image(image_id).get("crop_reviewed") else "proposed"
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT INTO specimens(specimen_id,image_id,label,crop_json,excluded,ordinal,crop_source,crop_status,crop_qc_json,model_id,updated_at) VALUES(?,?,?,?,0,?,'manual',?,'[]','',?)",
                      (specimen_id,image_id,label,_json(crop),ordinal,status,now))
            self._event(c,specimen_id,"add","human",{"crop":crop})
        return specimen_id

    def reject_specimen(self,specimen_id):
        item=self.specimen(specimen_id)
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET crop_status='rejected',excluded=1,updated_at=? WHERE specimen_id=?",(_now(),specimen_id))
            self._event(c,specimen_id,"reject","human",{"previous_status":item["crop_status"]})

    def apply_plate_crop_edits(self,image_id,edits=(),new_crops=(),removed_ids=()):
        """Atomically persist one plate's staged Crop edits without confirming it."""
        image=self.source_image(image_id);reviewed=bool(image.get("crop_reviewed"));status="confirmed" if reviewed else "proposed";now=_now()
        edits=[dict(item) for item in edits];new_crops=[dict(item) for item in new_crops];removed_ids={str(value) for value in removed_ids}
        id_map={};updated=added=removed=0
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            rows={row["specimen_id"]:self._decode_specimen(row) for row in c.execute("SELECT * FROM specimens WHERE image_id=?",(image_id,))}
            for specimen_id in removed_ids:
                item=rows.get(specimen_id)
                if item is None:raise KeyError(f"Unknown specimen on this plate: {specimen_id}")
                if item["crop_status"] in {"rejected","superseded"} or item["excluded"]:continue
                c.execute("UPDATE specimens SET crop_status='rejected',excluded=1,updated_at=? WHERE specimen_id=?",(now,specimen_id))
                self._event(c,specimen_id,"reject","human",{"previous_status":item["crop_status"],"reason":"apply_crop"})
                self._invalidate_annotation_verification(c,specimen_id,"crop_removed",item.get("crop") or {})
                removed+=1
            for edit in edits:
                specimen_id=str(edit.get("specimen_id") or "");item=rows.get(specimen_id)
                if item is None:raise KeyError(f"Unknown specimen on this plate: {specimen_id}")
                if specimen_id in removed_ids:continue
                crop=apply_orientation_defaults(edit.get("crop") or {},self.orientation_policy);crop["confidence"]="high";crop["orientation_verified"]=False
                if not crop.get("corners") or not crop.get("bounds"):raise ValueError("Crop geometry is incomplete.")
                c.execute(
                    "UPDATE specimens SET crop_json=?,crop_source='manual',crop_status=?,crop_qc_json='[]',model_id='',excluded=0,updated_at=? WHERE specimen_id=?",
                    (_json(crop),status,now,specimen_id),
                )
                self._event(c,specimen_id,"edit","human",{"previous_crop":item.get("crop") or {},"crop":crop,"action":"apply_crop"})
                if crop!=item.get("crop"):self._invalidate_annotation_verification(c,specimen_id,"crop_changed",item.get("crop") or {})
                updated+=1
            ordinal=max((int(item.get("ordinal") or 0) for item in rows.values()),default=0);stem=self.source_image_path(image_id).stem
            for entry in new_crops:
                crop=apply_orientation_defaults(entry.get("crop") or {},self.orientation_policy);crop["confidence"]="high";crop["orientation_verified"]=False
                if not crop.get("corners") or not crop.get("bounds"):raise ValueError("Crop geometry is incomplete.")
                ordinal+=1;specimen_id=str(uuid.uuid4());client_id=str(entry.get("client_id") or specimen_id);label=f"{stem}-{ordinal:02d}"
                c.execute(
                    "INSERT INTO specimens(specimen_id,image_id,label,crop_json,excluded,ordinal,crop_source,crop_status,crop_qc_json,model_id,updated_at) VALUES(?,?,?,?,0,?,'manual',?,'[]','',?)",
                    (specimen_id,image_id,label,_json(crop),ordinal,status,now),
                )
                self._event(c,specimen_id,"add","human",{"crop":crop,"action":"apply_crop"});id_map[client_id]=specimen_id;added+=1
        return {"updated":updated,"added":added,"removed":removed,"id_map":id_map}

    def remove_all_plate_crops(self,image_id):
        """Retire every current crop on a plate while preserving event/archive history."""
        self.source_image(image_id);now=_now();removed=0
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            rows=[self._decode_specimen(row) for row in c.execute("SELECT * FROM specimens WHERE image_id=?",(image_id,))]
            for item in rows:
                if item["crop_status"] in {"rejected","superseded"} or item["excluded"]:continue
                c.execute("UPDATE specimens SET crop_status='rejected',excluded=1,updated_at=? WHERE specimen_id=?",(now,item["specimen_id"]))
                self._event(c,item["specimen_id"],"reject","human",{"previous_status":item["crop_status"],"reason":"clear_plate"})
                self._invalidate_annotation_verification(c,item["specimen_id"],"crop_removed",item.get("crop") or {})
                removed+=1
            c.execute("UPDATE source_images SET crop_reviewed=0,crop_reviewed_at='' WHERE image_id=?",(image_id,))
        return removed

    def set_specimen_excluded(self,specimen_id,excluded=True):
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET excluded=?,updated_at=? WHERE specimen_id=?",(int(bool(excluded)),_now(),specimen_id))
            self._event(c,specimen_id,"exclude" if excluded else "restore","human",{})

    def crop_events(self,specimen_id):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;rows=[dict(row) for row in c.execute("SELECT * FROM crop_events WHERE specimen_id=? ORDER BY event_id",(specimen_id,))]
        for row in rows:
            try:row["payload"]=json.loads(row.pop("payload_json"))
            except Exception:row["payload"]={}
        return rows

    def get_ui_state(self,key,default=None):
        with sqlite3.connect(self.db_path) as c:row=c.execute("SELECT payload_json FROM ui_state WHERE key=?",(str(key),)).fetchone()
        if row is None:return {} if default is None else default
        try:return json.loads(row[0])
        except Exception:return {} if default is None else default

    def set_ui_state(self,key,value):
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT INTO ui_state(key,payload_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json",(str(key),_json(value)))

    def training_plates(self):
        rows=[]
        for image in self.source_images():
            if image["excluded"] or not image["crop_reviewed"]:continue
            specimens=[item for item in self.specimens(image["image_id"]) if item["crop_status"]=="confirmed" and not item["excluded"]]
            if specimens:rows.append({**image,"specimens":specimens})
        return rows

    def training_specimen_count(self):
        return sum(len(row["specimens"]) for row in self.training_plates())

    def orientation_training_rows(self):
        """Human-confirmed crop orientation truth, separate from detector truth."""
        rows=[]
        for plate in self.training_plates():
            for specimen in plate["specimens"]:
                crop=dict(specimen.get("crop") or {})
                if not bool(crop.get("orientation_verified")):continue
                rows.append({**specimen,"relative_path":plate["relative_path"],"crop":crop})
        return rows

    def orientation_training_specimen_count(self):
        return len(self.orientation_training_rows())

    def untouched_plate_ids(self):
        result=[]
        for image in self.source_images():
            if image["excluded"] or image["crop_reviewed"]:continue
            if any(not item["excluded"] for item in self.specimens(image["image_id"])):continue
            result.append(image["image_id"])
        return result

    @staticmethod
    def _sample_crop_plate_ids(image_ids,count,seed=42):
        """Seeded random sample from the whole eligible plate pool."""
        candidates=list(dict.fromkeys(str(value) for value in image_ids))
        return random.Random(int(seed)).sample(candidates,min(max(0,int(count)),len(candidates)))

    def training_candidate_ids(self):
        return [image["image_id"] for image in self.source_images() if not image["excluded"] and not image["crop_reviewed"]]

    def select_training_plate_ids(self,count):
        candidates=[image for image in self.source_images() if not image["excluded"] and not image["crop_reviewed"]]
        return self._sample_crop_plate_ids((image["image_id"] for image in candidates),max(1,int(count)))

    def prediction_candidate_ids(self):
        ids=[]
        for image in self.source_images():
            if image["excluded"] or image["crop_reviewed"]:continue
            active=self.specimens(image["image_id"])
            has_protected_pending=any(
                item["crop_status"]=="proposed" and not item["excluded"] and item["crop_source"] in {"model","manual"}
                for item in active
            )
            if not has_protected_pending:ids.append(image["image_id"])
        return ids

    def select_prediction_plate_ids(self,count):
        allowed=set(self.prediction_candidate_ids())
        candidates=[image for image in self.source_images() if image["image_id"] in allowed]
        return self._sample_crop_plate_ids((image["image_id"] for image in candidates),max(1,int(count)))

    def ai_review_plate_ids(self):
        ids=[]
        for image in self.source_images():
            if image["excluded"] or image["crop_reviewed"]:continue
            if any(item["crop_source"]=="model" and item["crop_status"]=="proposed" and not item["excluded"] for item in self.specimens(image["image_id"])):
                ids.append(image["image_id"])
        return ids

    def select_ai_review_plate_ids(self,count=None):
        candidates=self.ai_review_plate_ids()
        return self._sample_crop_plate_ids(candidates,len(candidates) if count is None else max(1,int(count)))

    def next_crop_model_id(self):
        with sqlite3.connect(self.db_path) as c:
            count=c.execute("SELECT COUNT(*) FROM xray_crop_models").fetchone()[0]
        return f"xray_crop_model_v{int(count)+1:03d}"

    def active_crop_model(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;row=c.execute("SELECT * FROM xray_crop_models WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:return None
        out=dict(row)
        try:out["metrics"]=json.loads(out.pop("metrics_json") or "{}")
        except Exception:out["metrics"]={}
        return out

    def crop_models(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;rows=[dict(row) for row in c.execute("SELECT * FROM xray_crop_models ORDER BY created_at DESC")]
        for row in rows:
            try:row["metrics"]=json.loads(row.pop("metrics_json") or "{}")
            except Exception:row["metrics"]={}
        return rows

    def register_crop_model(self,model_id,path,config_path,parent_model_id,metrics,training_plate_ids,training_specimen_count,activate=True):
        now=_now()
        with sqlite3.connect(self.db_path) as c:
            if activate:c.execute("UPDATE xray_crop_models SET active=0")
            c.execute("""INSERT INTO xray_crop_models(model_id,created_at,path,config_path,parent_model_id,metrics_json,training_plate_count,training_specimen_count,active)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (model_id,now,str(path),str(config_path),parent_model_id,_json(metrics or {}),len(training_plate_ids),int(training_specimen_count),int(bool(activate))))
            c.executemany("INSERT OR IGNORE INTO xray_crop_training_membership(model_id,image_id) VALUES(?,?)",[(model_id,image_id) for image_id in training_plate_ids])
        return model_id

    def activate_crop_model(self,model_id):
        """Select a registered crop model as the sole active model."""
        with sqlite3.connect(self.db_path) as c:
            if not c.execute("SELECT 1 FROM xray_crop_models WHERE model_id=?",(str(model_id),)).fetchone():
                raise KeyError(f"Unknown X-ray crop model: {model_id}")
            c.execute("UPDATE xray_crop_models SET active=CASE WHEN model_id=? THEN 1 ELSE 0 END",(str(model_id),))
        return self.active_crop_model()

    def delete_crop_model(self,model_id):
        """Delete a managed model and its registry rows without breaking descendants."""
        model_id=str(model_id)
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            row=c.execute("SELECT * FROM xray_crop_models WHERE model_id=?",(model_id,)).fetchone()
            if row is None:raise KeyError(f"Unknown X-ray crop model: {model_id}")
            child=c.execute("SELECT model_id FROM xray_crop_models WHERE parent_model_id=? LIMIT 1",(model_id,)).fetchone()
            if child:raise ValueError(f"Model is the training parent of {child[0]} and cannot be deleted yet.")
            paths=[Path(row["path"])]
            if row["config_path"]:paths.append(Path(row["config_path"]))
            resolved=[(self.root/path if not path.is_absolute() else path).resolve() for path in paths]
            models_root=(self.root/"models").resolve()
            if any(models_root not in path.parents for path in resolved):
                raise ValueError("Model files are outside this project's managed models folder.")
            model_dirs={path.parent for path in resolved}
            if len(model_dirs)!=1:raise ValueError("Model files do not share one managed model folder.")
            model_dir=next(iter(model_dirs))
            if model_dir.name!=model_id:raise ValueError("Model folder does not match its registered model id.")
            c.execute("DELETE FROM xray_crop_training_membership WHERE model_id=?",(model_id,))
            c.execute("DELETE FROM xray_crop_models WHERE model_id=?",(model_id,))
            if row["active"]:
                c.execute("UPDATE xray_crop_models SET active=1 WHERE model_id=(SELECT model_id FROM xray_crop_models ORDER BY created_at DESC,model_id DESC LIMIT 1)")
        if model_dir.exists():shutil.rmtree(model_dir)
        return model_id

    def next_structure_model_id(self):
        with sqlite3.connect(self.db_path) as c:
            existing={str(row[0]) for row in c.execute("SELECT model_id FROM xray_structure_models")}
        number=1
        while True:
            candidate=f"xray_structure_model_v{number:03d}"
            if candidate not in existing and not (self.models_root/candidate).exists():return candidate
            number+=1

    @staticmethod
    def _structure_model_dict(row):
        if row is None:return None
        out=dict(row)
        try:out["metrics"]=json.loads(out.pop("metrics_json") or "{}")
        except Exception:out["metrics"]={}
        return out

    def active_structure_model(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            row=c.execute("SELECT * FROM xray_structure_models WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        return self._structure_model_dict(row)

    def structure_models(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            rows=[self._structure_model_dict(row) for row in c.execute(
                "SELECT * FROM xray_structure_models ORDER BY created_at DESC,model_id DESC"
            )]
        return rows

    def register_structure_model(
        self,model_id,path,metadata_path,parent_model_id,schema_digest,backend,metrics,membership=(),
        training_specimen_count=None,validation_specimen_count=None,activate=True,
    ):
        model_id=str(model_id);rows=[dict(item) for item in membership]
        train_count=sum(str(item.get("split"))=="train" for item in rows) if training_specimen_count is None else int(training_specimen_count)
        val_count=sum(str(item.get("split"))=="val" for item in rows) if validation_specimen_count is None else int(validation_specimen_count)
        now=_now()
        with sqlite3.connect(self.db_path) as c:
            if parent_model_id and not c.execute(
                "SELECT 1 FROM xray_structure_models WHERE model_id=?",(str(parent_model_id),)
            ).fetchone():
                raise KeyError(f"Unknown parent X-ray structure model: {parent_model_id}")
            if activate:c.execute("UPDATE xray_structure_models SET active=0")
            c.execute(
                """INSERT INTO xray_structure_models(
                     model_id,created_at,path,metadata_path,parent_model_id,schema_digest,backend,metrics_json,
                     training_specimen_count,validation_specimen_count,active
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (model_id,now,str(path),str(metadata_path),parent_model_id,str(schema_digest),str(backend),
                 _json(metrics or {}),train_count,val_count,int(bool(activate))),
            )
            c.executemany(
                "INSERT OR IGNORE INTO xray_structure_training_membership(model_id,specimen_id,split) VALUES(?,?,?)",
                [(model_id,str(item["specimen_id"]),str(item["split"])) for item in rows],
            )
        return model_id

    def structure_model_membership(self,model_id):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            return [dict(row) for row in c.execute(
                "SELECT model_id,specimen_id,split FROM xray_structure_training_membership WHERE model_id=? ORDER BY split,specimen_id",
                (str(model_id),),
            )]

    def activate_structure_model(self,model_id):
        model_id=str(model_id)
        with sqlite3.connect(self.db_path) as c:
            if not c.execute("SELECT 1 FROM xray_structure_models WHERE model_id=?",(model_id,)).fetchone():
                raise KeyError(f"Unknown X-ray structure model: {model_id}")
            c.execute("UPDATE xray_structure_models SET active=CASE WHEN model_id=? THEN 1 ELSE 0 END",(model_id,))
        return self.active_structure_model()

    def delete_structure_model(self,model_id):
        model_id=str(model_id)
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            row=c.execute("SELECT * FROM xray_structure_models WHERE model_id=?",(model_id,)).fetchone()
            if row is None:raise KeyError(f"Unknown X-ray structure model: {model_id}")
            child=c.execute(
                "SELECT model_id FROM xray_structure_models WHERE parent_model_id=? LIMIT 1",(model_id,)
            ).fetchone()
            if child:raise ValueError(f"Model is the training parent of {child[0]} and cannot be deleted yet.")
            paths=[Path(row["path"]),Path(row["metadata_path"])]
            resolved=[(self.root/path if not path.is_absolute() else path).resolve() for path in paths]
            models_root=self.models_root.resolve()
            if any(models_root not in path.parents for path in resolved):
                raise ValueError("Structure model files are outside this project's managed models folder.")
            model_dirs={path.parent for path in resolved}
            if len(model_dirs)!=1:raise ValueError("Structure model files do not share one managed model folder.")
            model_dir=next(iter(model_dirs))
            if model_dir.name!=model_id:raise ValueError("Structure model folder does not match its registered model id.")
            c.execute("DELETE FROM xray_structure_training_membership WHERE model_id=?",(model_id,))
            c.execute("DELETE FROM xray_structure_models WHERE model_id=?",(model_id,))
            if row["active"]:
                c.execute(
                    "UPDATE xray_structure_models SET active=1 WHERE model_id=("
                    "SELECT model_id FROM xray_structure_models ORDER BY created_at DESC,model_id DESC LIMIT 1)"
                )
        if model_dir.exists():shutil.rmtree(model_dir)
        return model_id

    def structure_prediction_candidate_ids(self,pass_no=1):
        """Every eligible specimen except a human-verified annotation in this pass.

        Drafts are intentionally eligible: Predict current / Predict all may refresh
        unverified AI or manual drafts, while Apply/verified work is protected.
        """
        ids=[]
        for row in self.structure_specimens(int(pass_no)):
            if str(row.get("annotation_status") or "")=="verified":continue
            ids.append(str(row["specimen_id"]))
        return ids

    def select_structure_prediction_ids(self,count,seed=42,pass_no=1):
        return self._sample_crop_plate_ids(
            self.structure_prediction_candidate_ids(pass_no),
            max(1,int(count)),seed=seed,
        )

    def structure_ai_review_ids(self):
        schema_id=self.active_scheme_record()["version_id"]
        with sqlite3.connect(self.db_path) as c:
            rows=c.execute(
                """SELECT r.specimen_id,e.event_id
                   FROM annotation_events e
                   JOIN annotation_runs r ON r.run_id=e.run_id
                   JOIN specimens s ON s.specimen_id=r.specimen_id
                   JOIN source_images i ON i.image_id=s.image_id
                   WHERE e.action='model_seed' AND r.pass_no=1 AND r.source='human'
                     AND r.schema_version_id=? AND r.status='draft'
                     AND s.crop_status='confirmed' AND s.excluded=0 AND i.excluded=0 AND i.crop_reviewed=1
                   ORDER BY e.event_id""",
                (schema_id,),
            ).fetchall()
        seen=set();result=[]
        for specimen_id,_event_id in rows:
            specimen_id=str(specimen_id)
            if specimen_id not in seen:seen.add(specimen_id);result.append(specimen_id)
        return result

    def _archive_annotation_snapshot(self,c,run,reason):
        """Persist the current annotation state before an explicit AI replacement."""
        run_id=str(run["run_id"]);specimen_id=str(run["specimen_id"])
        specimen=self.specimen(specimen_id)
        rows=c.execute(
            "SELECT annotation_id,structure_id,x,y,sort_order FROM annotations WHERE run_id=? ORDER BY structure_id,sort_order,annotation_id",
            (run_id,),
        ).fetchall()
        roles=c.execute(
            "SELECT annotation_id,structure_id FROM annotation_roles WHERE run_id=? ORDER BY role_id",(run_id,)
        ).fetchall()
        states=c.execute(
            "SELECT structure_id,visibility FROM annotation_structure_states WHERE run_id=? ORDER BY structure_id",(run_id,)
        ).fetchall()
        if not rows and not roles and not states:return None
        role_map={}
        for annotation_id,structure_id in roles:
            role_map.setdefault(int(annotation_id),[]).append(str(structure_id))
        payload=[
            {
                "annotation_id":int(row[0]),"structure_id":str(row[1]),
                "x":float(row[2]),"y":float(row[3]),"sort_order":int(row[4]),
                "role_structure_ids":role_map.get(int(row[0]),[]),
            }
            for row in rows
        ]
        state_payload={
            str(structure_id):str(visibility)
            for structure_id,visibility in states
            if str(visibility) in STRUCTURE_VISIBILITY_STATES
        }
        cur=c.execute(
            """INSERT INTO annotation_archives(
                 run_id,specimen_id,created_at,reason,crop_json,annotations_json,structure_states_json,
                 schema_version_id,pass_no,source,status
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,specimen_id,_now(),str(reason),_json(specimen.get("crop") or {}),
                _json(payload),_json(state_payload),str(run["schema_version_id"]),
                int(run["pass_no"]),str(run["source"]),str(run["status"]),
            ),
        )
        return int(cur.lastrowid)

    def seed_structure_predictions(self,specimen_id,predictions,model_id,role_tolerance=0.035,pass_no=1,allow_verified=False):
        specimen_id=str(specimen_id);specimen=self.specimen(specimen_id);image=self.source_image(specimen["image_id"])
        if specimen["excluded"] or specimen["crop_status"]!="confirmed" or image["excluded"] or not image["crop_reviewed"]:
            raise ValueError("AI structure markers can be seeded only on confirmed specimen crops.")
        pass_no=int(pass_no)
        run=self.annotation_run(specimen_id,pass_no,"human",False)
        if run and str(run.get("status") or "")=="verified" and not bool(allow_verified):
            return {"protected":True,"annotations":0,"roles":0,"model_id":str(model_id),"pass_no":pass_no}
        if run is None:
            self.ensure_annotation_run(specimen_id,pass_no,"human")
            run=self.annotation_run(specimen_id,pass_no,"human",False)
        run_id=str(run["run_id"]);now=_now()
        structures=list(self.scheme.get("structures") or ());by_id={str(item["id"]):item for item in structures}
        grouped={}
        for raw in predictions or ():
            sid=str(raw.get("structure_id") or "")
            if sid not in by_id:continue
            try:x=max(0.0,min(1.0,float(raw["x"])));y=max(0.0,min(1.0,float(raw["y"])));score=float(raw.get("score") or 0.0)
            except (KeyError,TypeError,ValueError):continue
            grouped.setdefault(sid,[]).append({"x":x,"y":y,"score":score})
        inserted=[];role_count=0
        with sqlite3.connect(self.db_path) as c:
            archive_id=self._archive_annotation_snapshot(
                c,run,"predict_current_replace_verified" if str(run.get("status") or "")=="verified" else "model_seed_refresh"
            )
            c.execute("DELETE FROM annotation_roles WHERE run_id=?",(run_id,))
            c.execute("DELETE FROM annotations WHERE run_id=?",(run_id,))
            for structure in structures:
                sid=str(structure["id"])
                if not bool(structure.get("repeated")):continue
                points=sorted(grouped.get(sid,()),key=lambda point:(point["x"],point["y"],-point["score"]))
                for order,point in enumerate(points):
                    cur=c.execute(
                        "INSERT INTO annotations(run_id,structure_id,x,y,sort_order) VALUES(?,?,?,?,?)",
                        (run_id,sid,point["x"],point["y"],order),
                    )
                    inserted.append({"annotation_id":int(cur.lastrowid),"structure_id":sid,**point})
            compatibility={
                str(base["id"]):{str(role["id"]) for role in compatible_reference_roles(self.scheme,str(base["id"]))}
                for base in structures if bool(base.get("repeated"))
            }
            for structure in structures:
                sid=str(structure["id"])
                if bool(structure.get("repeated")):continue
                points=sorted(grouped.get(sid,()),key=lambda point:point["score"],reverse=True)
                if not points:continue
                point=points[0];near=None
                for base in inserted:
                    if sid not in compatibility.get(base["structure_id"],set()):continue
                    distance=((base["x"]-point["x"])**2+(base["y"]-point["y"])**2)**0.5
                    if distance<=float(role_tolerance) and (near is None or distance<near[0]):near=(distance,base)
                if near is not None:
                    c.execute(
                        "INSERT INTO annotation_roles(run_id,annotation_id,structure_id,created_at) VALUES(?,?,?,?)",
                        (run_id,int(near[1]["annotation_id"]),sid,now),
                    )
                    role_count+=1
                else:
                    cur=c.execute(
                        "INSERT INTO annotations(run_id,structure_id,x,y,sort_order) VALUES(?,?,?,?,0)",
                        (run_id,sid,point["x"],point["y"]),
                    )
                    inserted.append({"annotation_id":int(cur.lastrowid),"structure_id":sid,**point})
            safe_predictions=[
                {"structure_id":sid,"points":[
                    {"x":round(point["x"],8),"y":round(point["y"],8),"score":round(point["score"],6)}
                    for point in grouped.get(sid,())
                ]}
                for sid in by_id if grouped.get(sid)
            ]
            self._annotation_event(
                c,run_id,"model_seed",payload={
                    "model_id":str(model_id),"pass_no":pass_no,"predictions":safe_predictions,
                    "annotations":len(inserted),"roles":role_count,"replaced_archive_id":archive_id,
                    "replaced_verified":bool(str(run.get("status") or "")=="verified"),
                },
            )
            c.execute(
                "UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",
                (now,run_id),
            )
        if pass_no==1:self.recalculate_trait_results(specimen_id)
        return {"protected":False,"annotations":len(inserted),"roles":role_count,"model_id":str(model_id),"pass_no":pass_no}

    def crop_workspace_status(self):
        """Fast aggregate state for the interactive Crop workspace.

        Navigation must not walk the whole project through specimens(image_id)
        hundreds of times.  Keep these counters DB-authoritative, but calculate
        them with set-based queries in one connection.
        """
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            plate=c.execute("""
                SELECT
                  SUM(CASE WHEN excluded=0 THEN 1 ELSE 0 END) AS plates,
                  SUM(CASE WHEN excluded=0 AND crop_reviewed=1 THEN 1 ELSE 0 END) AS verified_plates,
                  SUM(CASE WHEN excluded=0 AND crop_reviewed=0 AND NOT EXISTS(
                    SELECT 1 FROM specimens s
                    WHERE s.image_id=source_images.image_id AND s.excluded=0
                      AND s.crop_status NOT IN ('rejected','superseded')
                  ) THEN 1 ELSE 0 END) AS uncropped_plates,
                  SUM(CASE WHEN excluded=0 AND crop_reviewed=0 AND NOT EXISTS(
                    SELECT 1 FROM specimens s
                    WHERE s.image_id=source_images.image_id AND s.excluded=0
                      AND s.crop_status='proposed' AND s.crop_source IN ('model','manual')
                  ) THEN 1 ELSE 0 END) AS prediction_candidates
                FROM source_images
            """).fetchone()
            specimen=c.execute("""
                SELECT
                  SUM(CASE WHEN s.excluded=0 AND s.crop_status NOT IN ('rejected','superseded') THEN 1 ELSE 0 END) AS specimens,
                  SUM(CASE WHEN s.excluded=0 AND s.crop_status='confirmed' THEN 1 ELSE 0 END) AS confirmed,
                  SUM(CASE WHEN s.excluded=0 AND s.crop_status='proposed' THEN 1 ELSE 0 END) AS review,
                  COUNT(DISTINCT CASE WHEN s.excluded=0 AND s.crop_status='confirmed'
                    AND i.excluded=0 AND i.crop_reviewed=1 THEN s.image_id END) AS training_plates,
                  SUM(CASE WHEN s.excluded=0 AND s.crop_status='confirmed'
                    AND i.excluded=0 AND i.crop_reviewed=1 THEN 1 ELSE 0 END) AS training_specimens,
                  COUNT(DISTINCT CASE WHEN s.excluded=0 AND s.crop_status='proposed'
                    AND s.crop_source='model' AND i.excluded=0 AND i.crop_reviewed=0 THEN s.image_id END) AS ai_pending_plates
                FROM specimens s JOIN source_images i ON i.image_id=s.image_id
            """).fetchone()
            orientation_rows=c.execute("""
                SELECT s.crop_json
                FROM specimens s JOIN source_images i ON i.image_id=s.image_id
                WHERE s.excluded=0 AND s.crop_status='confirmed'
                  AND i.excluded=0 AND i.crop_reviewed=1
            """).fetchall()
        orientation_training=0
        for row in orientation_rows:
            try:orientation_training+=int(bool(json.loads(row["crop_json"] or "{}").get("orientation_verified")))
            except (TypeError,ValueError,json.JSONDecodeError):pass
        out={
            "plates":int(plate["plates"] or 0),
            "verified_plates":int(plate["verified_plates"] or 0),
            "uncropped_plates":int(plate["uncropped_plates"] or 0),
            "prediction_candidates":int(plate["prediction_candidates"] or 0),
            "specimens":int(specimen["specimens"] or 0),
            "confirmed":int(specimen["confirmed"] or 0),
            "review":int(specimen["review"] or 0),
            "training_plates":int(specimen["training_plates"] or 0),
            "training_specimens":int(specimen["training_specimens"] or 0),
            "ai_pending_plates":int(specimen["ai_pending_plates"] or 0),
            "orientation_training":int(orientation_training),
        }
        return out

    def crop_summary(self):
        status=self.crop_workspace_status()
        return {key:status[key] for key in (
            "plates","verified_plates","training_specimens","ai_pending_plates",
            "uncropped_plates","specimens","confirmed","review",
        )}

    def save_scheme(self,scheme,note="Scheme update"):
        normalized=normalize_scheme(scheme);digest=scheme_hash(normalized)
        with sqlite3.connect(self.db_path) as c:
            existing=c.execute("SELECT version_id FROM schema_versions WHERE scheme_hash=? ORDER BY created_at DESC LIMIT 1",(digest,)).fetchone()
            if existing:
                c.execute("UPDATE schema_versions SET active=CASE WHEN version_id=? THEN 1 ELSE 0 END",(existing[0],));return existing[0]
            version_id=str(uuid.uuid4());c.execute("UPDATE schema_versions SET active=0")
            c.execute("INSERT INTO schema_versions(version_id,created_at,scheme_hash,note,payload_json,active) VALUES(?,?,?,?,?,1)",
                      (version_id,_now(),digest,str(note),json.dumps(normalized,ensure_ascii=False,sort_keys=True)))
        return version_id

    def active_scheme_record(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            row=c.execute("SELECT * FROM schema_versions WHERE active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:raise RuntimeError("X-ray project has no active trait scheme")
        out=dict(row);out["scheme"]=json.loads(out.pop("payload_json"));return out

    @property
    def scheme(self):return self.active_scheme_record()["scheme"]

    def ensure_initial_bundled_scheme(self,scheme_id="phoxinus_vertebral_counts"):
        """Upgrade only the untouched program-created blank placeholder, preserving its history."""
        record=self.active_scheme_record();scheme=record["scheme"];history=self.schema_history()
        untouched=(
            len(history)==1 and not scheme.get("structures") and not scheme.get("traits")
            and str(scheme.get("name") or "")=="Untitled X-ray trait scheme"
        )
        if not untouched:return False
        with sqlite3.connect(self.db_path) as c:
            annotations=int(c.execute("SELECT COUNT(*) FROM annotations").fetchone()[0])
            results=int(c.execute("SELECT COUNT(*) FROM trait_results").fetchone()[0])
        if annotations or results:return False
        self.save_scheme(bundled_scheme(scheme_id),"Built-in starter scheme activated for untouched blank project")
        return True

    def ensure_phoxinus_count_semantics(self):
        """Correct the legacy bundled count rules without discarding compatible annotations.

        The old starter scheme added four Weberian vertebrae numerically even though
        the annotation tool asks users to mark the complete vertebral series. The
        literature definition counts those vertebrae directly, so an all-vertebra
        annotation must not receive a hidden +4 correction.
        """
        record=self.active_scheme_record();old_scheme=normalize_scheme(record["scheme"])
        if str(old_scheme.get("scheme_id") or "")!="phoxinus_vertebral_counts":return False
        traits={str(item["id"]):item for item in old_scheme.get("traits") or ()}
        legacy={"tv":4,"abdv":4,"predv":4}
        if any(int(((traits.get(trait_id) or {}).get("rule") or {}).get("offset",0) or 0)!=offset for trait_id,offset in legacy.items()):
            return False
        corrected=deepcopy(old_scheme)
        corrected_traits={str(item["id"]):item for item in corrected.get("traits") or ()}
        for trait_id in legacy:corrected_traits[trait_id].setdefault("rule",{}).pop("offset",None)
        old_structure_contract=[
            (str(item["id"]),bool(item.get("repeated")),str(item.get("annotation") or "point"),
             str(item.get("learning_relation") or ""),tuple(str(value) for value in item.get("reuse_from") or ()))
            for item in old_scheme.get("structures") or ()
        ]
        new_structure_contract=[
            (str(item["id"]),bool(item.get("repeated")),str(item.get("annotation") or "point"),
             str(item.get("learning_relation") or ""),tuple(str(value) for value in item.get("reuse_from") or ()))
            for item in corrected.get("structures") or ()
        ]
        if old_structure_contract!=new_structure_contract:raise RuntimeError("Unsafe X-ray scheme correction was refused.")
        old_version=str(record["version_id"])
        new_version=self.save_scheme(
            corrected,
            "Corrected Phoxinus vertebral count rules: every marked vertebra is counted directly; legacy hidden +4 offsets removed.",
        )
        if new_version==old_version:return False
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE annotation_runs SET schema_version_id=? WHERE schema_version_id=?",(new_version,old_version))
            c.execute("UPDATE xray_structure_repeatability_runs SET schema_version_id=? WHERE schema_version_id=?",(new_version,old_version))
            c.execute("DELETE FROM trait_results WHERE schema_version_id=?",(new_version,))
        for row in self.structure_specimens(1,include_excluded=True):
            self.recalculate_trait_results(row["specimen_id"])
        return True

    def current_selection(self):
        state=dict(self.get_ui_state("xray_current_selection",{}) or {})
        image_id=str(state.get("image_id") or "");specimen_id=str(state.get("specimen_id") or "")
        if specimen_id:
            try:
                specimen=self.specimen(specimen_id)
                if specimen["crop_status"] in {"rejected","superseded"}:specimen_id=""
                else:image_id=str(specimen["image_id"])
            except KeyError:specimen_id=""
        if image_id:
            try:
                image=self.source_image(image_id)
                if image["excluded"]:image_id="";specimen_id=""
            except KeyError:image_id="";specimen_id=""
        return {"image_id":image_id,"specimen_id":specimen_id}

    def set_current_selection(self,image_id=None,specimen_id=None):
        specimen_id=str(specimen_id or "");image_id=str(image_id or "")
        if specimen_id:
            specimen=self.specimen(specimen_id);image_id=str(specimen["image_id"])
        if image_id:self.source_image(image_id)
        value={"image_id":image_id,"specimen_id":specimen_id}
        self.set_ui_state("xray_current_selection",value);return value

    def schema_history(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            return [dict(row) for row in c.execute("SELECT version_id,created_at,scheme_hash,note,active FROM schema_versions ORDER BY created_at DESC")]

    def structure_specimens(self,pass_no=1,include_excluded=False):
        """Confirmed specimens in one stable project-wide order.

        workflow_no is assigned before exclusion/filtering and is therefore the
        same number in Structures, Export and later review screens.
        """
        schema_id=self.active_scheme_record()["version_id"];pass_no=int(pass_no)
        sql="""
            SELECT s.*,i.relative_path,i.crop_reviewed,i.excluded AS image_excluded,
                   r.run_id,r.status AS annotation_status,r.updated_at AS annotation_updated_at
            FROM specimens s
            JOIN source_images i ON i.image_id=s.image_id
            LEFT JOIN annotation_runs r
              ON r.specimen_id=s.specimen_id AND r.pass_no=? AND r.source='human' AND r.schema_version_id=?
            WHERE s.crop_status='confirmed' AND i.crop_reviewed=1 AND i.excluded=0
            ORDER BY i.relative_path,s.ordinal,s.label,s.specimen_id
        """
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;rows=[dict(row) for row in c.execute(sql,(pass_no,schema_id))]
        for workflow_no,row in enumerate(rows,1):row["workflow_no"]=workflow_no
        if not include_excluded:rows=[row for row in rows if not bool(row.get("excluded"))]
        if pass_no>1:
            verified=set()
            with sqlite3.connect(self.db_path) as c:
                verified={row[0] for row in c.execute(
                    "SELECT specimen_id FROM annotation_runs WHERE pass_no=1 AND source='human' AND schema_version_id=? AND status='verified'",
                    (schema_id,),
                )}
            rows=[row for row in rows if row["specimen_id"] in verified]
        return rows

    def structure_workflow_number(self,specimen_id):
        specimen_id=str(specimen_id)
        row=next((item for item in self.structure_specimens(1,include_excluded=True) if str(item["specimen_id"])==specimen_id),None)
        return int((row or {}).get("workflow_no") or 0)

    def ensure_annotation_run(self,specimen_id,pass_no=1,source="human"):
        specimen=self.specimen(specimen_id);image=self.source_image(specimen["image_id"])
        if specimen["excluded"] or specimen["crop_status"]!="confirmed" or image["excluded"] or not image["crop_reviewed"]:
            raise ValueError("Structures can be annotated only on human-confirmed specimen crops.")
        record=self.active_scheme_record();schema_id=record["version_id"];pass_no=int(pass_no);now=_now()
        if pass_no>1:
            first=self.annotation_run(specimen_id,1,source,False)
            if not first or first.get("status")!="verified":
                raise ValueError("Verify manual pass 1 before starting repeatability pass 2.")
        with sqlite3.connect(self.db_path) as c:
            row=c.execute(
                "SELECT run_id FROM annotation_runs WHERE specimen_id=? AND pass_no=? AND source=? AND schema_version_id=?",
                (specimen_id,pass_no,str(source),schema_id),
            ).fetchone()
            if row:return row[0]
            run_id=str(uuid.uuid4())
            c.execute(
                """INSERT INTO annotation_runs(
                     run_id,specimen_id,pass_no,source,schema_version_id,status,coordinate_space,created_at,updated_at
                   ) VALUES(?,?,?,?,?,'draft','crop_normalized_v1',?,?)""",
                (run_id,specimen_id,pass_no,str(source),schema_id,now,now),
            )
        return run_id

    def annotation_run(self,specimen_id,pass_no=1,source="human",create=False):
        schema_id=self.active_scheme_record()["version_id"]
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;row=c.execute(
                "SELECT * FROM annotation_runs WHERE specimen_id=? AND pass_no=? AND source=? AND schema_version_id=?",
                (specimen_id,int(pass_no),str(source),schema_id),
            ).fetchone()
        if row is None and create:
            self.ensure_annotation_run(specimen_id,pass_no,source);return self.annotation_run(specimen_id,pass_no,source,False)
        return dict(row) if row is not None else None

    def annotations(self,specimen_id,pass_no=1,source="human"):
        run=self.annotation_run(specimen_id,pass_no,source,False)
        if run is None:return []
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            return [dict(row) for row in c.execute(
                "SELECT annotation_id,run_id,structure_id,x,y,sort_order FROM annotations WHERE run_id=? ORDER BY structure_id,sort_order,annotation_id",
                (run["run_id"],),
            )]

    def annotation_roles(self,specimen_id,pass_no=1,source="human"):
        run=self.annotation_run(specimen_id,pass_no,source,False)
        if run is None:return []
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            return [dict(row) for row in c.execute(
                """SELECT ar.role_id,ar.run_id,ar.annotation_id,ar.structure_id,
                          a.structure_id AS base_structure_id,a.x,a.y,a.sort_order
                   FROM annotation_roles ar
                   JOIN annotations a ON a.annotation_id=ar.annotation_id
                   WHERE ar.run_id=? ORDER BY ar.role_id""",
                (run["run_id"],),
            )]

    def effective_annotations(self,specimen_id,pass_no=1,source="human"):
        rows=[dict(row) for row in self.annotations(specimen_id,pass_no,source)]
        for role in self.annotation_roles(specimen_id,pass_no,source):
            rows.append({
                "annotation_id":int(role["annotation_id"]),"run_id":role["run_id"],
                "structure_id":role["structure_id"],"x":float(role["x"]),"y":float(role["y"]),
                "sort_order":int(role.get("sort_order",0) or 0),"role_source_annotation_id":int(role["annotation_id"]),
            })
        return rows

    def structure_visibility_states(self,specimen_id,pass_no=1,source="human"):
        known=[str(item["id"]) for item in self.scheme.get("structures",())]
        states={structure_id:"complete" for structure_id in known}
        run=self.annotation_run(specimen_id,pass_no,source,False)
        if run is None:return states
        with sqlite3.connect(self.db_path) as c:
            rows=c.execute(
                "SELECT structure_id,visibility FROM annotation_structure_states WHERE run_id=?",
                (run["run_id"],),
            ).fetchall()
        for structure_id,visibility in rows:
            structure_id=str(structure_id);visibility=str(visibility or "complete")
            if structure_id in states and visibility in STRUCTURE_VISIBILITY_STATES:states[structure_id]=visibility
        return states

    def structure_visibility(self,specimen_id,structure_id,pass_no=1,source="human"):
        structure_id=str(structure_id)
        if structure_id not in {str(item["id"]) for item in self.scheme.get("structures",())}:
            raise KeyError(f"Unknown structure in active scheme: {structure_id}")
        return self.structure_visibility_states(specimen_id,pass_no,source).get(structure_id,"complete")

    def set_structure_visibility(self,specimen_id,structure_id,visibility="complete",pass_no=1,source="human"):
        structure_id=str(structure_id);visibility=str(visibility or "complete")
        known={str(item["id"]) for item in self.scheme.get("structures",())}
        if structure_id not in known:raise KeyError(f"Unknown structure in active scheme: {structure_id}")
        if visibility not in STRUCTURE_VISIBILITY_STATES:raise ValueError(f"Unsupported structure visibility: {visibility}")
        if visibility in {"not_visible","absent"} and any(
            row["structure_id"]==structure_id for row in self.effective_annotations(specimen_id,pass_no,source)
        ):
            raise ValueError("Clear existing markers for this structure before marking it Not visible or Absent.")
        run_id=self.ensure_annotation_run(specimen_id,pass_no,source);now=_now()
        with sqlite3.connect(self.db_path) as c:
            if visibility=="complete":
                c.execute("DELETE FROM annotation_structure_states WHERE run_id=? AND structure_id=?",(run_id,structure_id))
            else:
                c.execute(
                    """INSERT INTO annotation_structure_states(run_id,structure_id,visibility,updated_at)
                       VALUES(?,?,?,?)
                       ON CONFLICT(run_id,structure_id) DO UPDATE SET
                         visibility=excluded.visibility,updated_at=excluded.updated_at""",
                    (run_id,structure_id,visibility,now),
                )
            self._annotation_event(c,run_id,"structure_visibility",structure_id,payload={"visibility":visibility})
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
        self.recalculate_trait_results(specimen_id)
        return visibility

    def assign_annotation_role(self,annotation_id,role_structure_id):
        annotation_id=int(annotation_id);role_structure_id=str(role_structure_id);now=_now()
        with sqlite3.connect(self.db_path) as c:
            row=c.execute(
                """SELECT a.run_id,a.structure_id,r.specimen_id
                   FROM annotations a JOIN annotation_runs r ON r.run_id=a.run_id
                   WHERE a.annotation_id=?""",(annotation_id,)
            ).fetchone()
            if row is None:raise KeyError(f"Unknown annotation: {annotation_id}")
            run_id,base_structure_id,specimen_id=row
            allowed={item["id"] for item in compatible_reference_roles(self.scheme,base_structure_id)}
            if role_structure_id not in allowed:
                raise ValueError("This marker cannot use the selected point as that start / stop role.")
            standalone=c.execute(
                "SELECT annotation_id,x,y,sort_order FROM annotations WHERE run_id=? AND structure_id=? ORDER BY annotation_id",
                (run_id,role_structure_id),
            ).fetchall()
            for existing in standalone:
                self._annotation_event(c,run_id,"replace_reference_with_role",role_structure_id,int(existing[0]),{"at":[existing[1],existing[2]],"sort_order":existing[3]})
                c.execute("DELETE FROM annotation_roles WHERE annotation_id=?",(int(existing[0]),))
                c.execute("DELETE FROM annotations WHERE annotation_id=?",(int(existing[0]),))
            previous=c.execute(
                "SELECT role_id,annotation_id FROM annotation_roles WHERE run_id=? AND structure_id=?",
                (run_id,role_structure_id),
            ).fetchone()
            if previous and int(previous[1])==annotation_id:return False
            if previous:c.execute("DELETE FROM annotation_roles WHERE role_id=?",(int(previous[0]),))
            c.execute("INSERT INTO annotation_roles(run_id,annotation_id,structure_id,created_at) VALUES(?,?,?,?)",(run_id,annotation_id,role_structure_id,now))
            self._annotation_event(c,run_id,"assign_role",role_structure_id,annotation_id,{"base_structure_id":base_structure_id})
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
        self.recalculate_trait_results(specimen_id);return True

    def remove_annotation_role(self,annotation_id,role_structure_id):
        annotation_id=int(annotation_id);role_structure_id=str(role_structure_id);now=_now();specimen_id=None
        with sqlite3.connect(self.db_path) as c:
            row=c.execute(
                """SELECT ar.role_id,ar.run_id,r.specimen_id,a.structure_id
                   FROM annotation_roles ar
                   JOIN annotation_runs r ON r.run_id=ar.run_id
                   JOIN annotations a ON a.annotation_id=ar.annotation_id
                   WHERE ar.annotation_id=? AND ar.structure_id=?""",
                (annotation_id,role_structure_id),
            ).fetchone()
            if row is None:return False
            role_id,run_id,specimen_id,base_structure_id=row
            c.execute("DELETE FROM annotation_roles WHERE role_id=?",(int(role_id),))
            self._annotation_event(c,run_id,"remove_role",role_structure_id,annotation_id,{"base_structure_id":base_structure_id})
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
        self.recalculate_trait_results(specimen_id);return True

    def _annotation_event(self,c,run_id,action,structure_id="",annotation_id=None,payload=None):
        c.execute(
            "INSERT INTO annotation_events(run_id,created_at,action,structure_id,annotation_id,payload_json) VALUES(?,?,?,?,?,?)",
            (run_id,_now(),str(action),str(structure_id or ""),annotation_id,_json(payload or {})),
        )

    def structure_batch(self,pass_no=1):
        pass_no=int(pass_no);state=dict(self.get_ui_state("xray_structure_active_batch",{}) or {})
        if int(state.get("pass_no",0) or 0)!=pass_no:return {}
        eligible={row["specimen_id"] for row in self.structure_specimens(pass_no)}
        ids=[str(value) for value in state.get("ids",()) if str(value) in eligible]
        if not ids:return {}
        pos=max(0,min(len(ids)-1,int(state.get("position",0) or 0)))
        return {"pass_no":pass_no,"ids":ids,"position":pos}

    def start_structure_batch(self,count,pass_no=1,start_specimen_id=None):
        pass_no=int(pass_no);count=max(1,int(count));rows=self.structure_specimens(pass_no)
        candidates=[row for row in rows if str(row.get("annotation_status") or "")!="verified"]
        if not candidates:
            self.set_ui_state("xray_structure_active_batch",{});return {}
        ids=[row["specimen_id"] for row in candidates]
        start=str(start_specimen_id or "")
        if start in ids:
            index=ids.index(start);ids=ids[index:]+ids[:index]
        ids=ids[:count]
        state={"pass_no":pass_no,"ids":ids,"position":0}
        self.set_ui_state("xray_structure_active_batch",state);return state

    def move_structure_batch(self,current_specimen_id,step,pass_no=1):
        state=self.structure_batch(pass_no);ids=list(state.get("ids") or ())
        if not ids or str(current_specimen_id) not in ids:return {"finished":False,"specimen_id":None,"state":state}
        pos=ids.index(str(current_specimen_id))+int(step)
        if pos>=len(ids):
            self.set_ui_state("xray_structure_active_batch",{})
            return {"finished":True,"specimen_id":None,"state":{}}
        pos=max(0,pos);state["position"]=pos;self.set_ui_state("xray_structure_active_batch",state)
        return {"finished":False,"specimen_id":ids[pos],"state":state}

    def _invalidate_annotation_verification(self,c,specimen_id,reason="source_changed",previous_crop=None):
        """Archive coordinate-dependent marks before an upstream crop/orientation change."""
        now=_now();runs=c.execute(
            "SELECT run_id,pass_no,source,schema_version_id,status FROM annotation_runs WHERE specimen_id=?",(specimen_id,)
        ).fetchall()
        archived=0
        for run_id,pass_no,source,schema_version_id,status in runs:
            rows=c.execute(
                "SELECT annotation_id,structure_id,x,y,sort_order FROM annotations WHERE run_id=? ORDER BY structure_id,sort_order,annotation_id",
                (run_id,),
            ).fetchall()
            role_rows=c.execute("SELECT annotation_id,structure_id FROM annotation_roles WHERE run_id=? ORDER BY role_id",(run_id,)).fetchall()
            state_rows=c.execute("SELECT structure_id,visibility FROM annotation_structure_states WHERE run_id=? ORDER BY structure_id",(run_id,)).fetchall()
            states={str(structure_id):str(visibility) for structure_id,visibility in state_rows if str(visibility) in STRUCTURE_VISIBILITY_STATES}
            role_map={}
            for base_id,role_sid in role_rows:role_map.setdefault(int(base_id),[]).append(str(role_sid))
            if rows or states:
                payload=[
                    {"annotation_id":int(row[0]),"structure_id":row[1],"x":float(row[2]),"y":float(row[3]),"sort_order":int(row[4]),
                     "role_structure_ids":role_map.get(int(row[0]),[])}
                    for row in rows
                ]
                cur=c.execute(
                    """INSERT INTO annotation_archives(
                         run_id,specimen_id,created_at,reason,crop_json,annotations_json,structure_states_json,
                         schema_version_id,pass_no,source,status
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id,specimen_id,now,str(reason),_json(previous_crop or {}),_json(payload),_json(states),
                     schema_version_id,int(pass_no),source,status),
                )
                archived+=len(payload);c.execute("DELETE FROM annotation_roles WHERE run_id=?",(run_id,));c.execute("DELETE FROM annotations WHERE run_id=?",(run_id,))
                c.execute("DELETE FROM annotation_structure_states WHERE run_id=?",(run_id,))
                self._annotation_event(c,run_id,"invalidate",payload={"reason":str(reason),"archive_id":int(cur.lastrowid),"archived_annotations":len(payload)})
            else:
                c.execute("DELETE FROM annotation_structure_states WHERE run_id=?",(run_id,))
                self._annotation_event(c,run_id,"invalidate",payload={"reason":str(reason),"archived_annotations":0})
        if runs:c.execute("UPDATE annotation_runs SET status='stale_crop',updated_at=?,verified_at='' WHERE specimen_id=?",(now,specimen_id))
        c.execute("UPDATE trait_results SET value_text=NULL,qc_note=?,updated_at=? WHERE specimen_id=?",(str(reason),now,specimen_id))
        return archived

    def annotation_archives(self,specimen_id):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;rows=[dict(row) for row in c.execute(
                "SELECT * FROM annotation_archives WHERE specimen_id=? ORDER BY archive_id",(str(specimen_id),)
            )]
        for row in rows:
            try:row["crop"]=json.loads(row.pop("crop_json") or "{}")
            except Exception:row["crop"]={}
            try:row["annotations"]=json.loads(row.pop("annotations_json") or "[]")
            except Exception:row["annotations"]=[]
            try:row["structure_states"]=json.loads(row.pop("structure_states_json") or "{}")
            except Exception:row["structure_states"]={}
        return rows

    @staticmethod
    def _value_text(value):
        if value is None:return None
        if isinstance(value,float):
            if abs(value-round(value))<1e-9:return str(int(round(value)))
            return f"{value:.6g}"
        return str(value)

    def recalculate_trait_results(self,specimen_id):
        record=self.active_scheme_record();scheme=record["scheme"];schema_id=record["version_id"]
        run=self.annotation_run(specimen_id,1,"human",False);status=str((run or {}).get("status") or "not_started")
        annotations=self.effective_annotations(specimen_id,1,"human") if run and not status.startswith("stale") else []
        visibility=self.structure_visibility_states(specimen_id,1,"human") if run and not status.startswith("stale") else {}
        unknown={sid for sid,value in visibility.items() if value in {"partial","not_visible"}}
        values=({trait["id"]:None for trait in scheme.get("traits",())} if status.startswith("stale") else calculate_trait_values(scheme,annotations,unknown_structures=unknown))
        qc="" if status=="verified" else status
        now=_now()
        with sqlite3.connect(self.db_path) as c:
            for trait in scheme.get("traits",()):
                ident=trait["id"];text=self._value_text(values.get(ident))
                c.execute(
                    """INSERT INTO trait_results(specimen_id,trait_id,schema_version_id,value_text,qc_note,updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(specimen_id,trait_id,schema_version_id) DO UPDATE SET
                         value_text=excluded.value_text,qc_note=excluded.qc_note,updated_at=excluded.updated_at""",
                    (specimen_id,ident,schema_id,text,qc,now),
                )
        return {"values":values,"status":qc or "verified","schema_version_id":schema_id}

    def trait_rows(self):
        scheme=self.scheme;rows=[]
        for item in self.structure_specimens(1):
            run=self.annotation_run(item["specimen_id"],1,"human",False);status=str((run or {}).get("status") or "not_started")
            annotations=self.effective_annotations(item["specimen_id"],1,"human") if run and not status.startswith("stale") else []
            visibility=self.structure_visibility_states(item["specimen_id"],1,"human") if run and not status.startswith("stale") else {}
            unknown={sid for sid,value in visibility.items() if value in {"partial","not_visible"}}
            values=({trait["id"]:None for trait in scheme.get("traits",())} if status.startswith("stale") else calculate_trait_values(scheme,annotations,unknown_structures=unknown))
            rows.append({**item,"trait_values":values,"result_status":status})
        return rows

    def add_annotation(self,specimen_id,structure_id,x,y,pass_no=1,source="human",replace_single=False):
        structure_id=str(structure_id)
        known={item["id"] for item in self.scheme.get("structures",())}
        if structure_id not in known:raise KeyError(f"Unknown structure in active scheme: {structure_id}")
        x=max(0.0,min(1.0,float(x)));y=max(0.0,min(1.0,float(y)))
        run_id=self.ensure_annotation_run(specimen_id,pass_no,source);now=_now()
        with sqlite3.connect(self.db_path) as c:
            if replace_single:
                role=c.execute(
                    "SELECT role_id,annotation_id FROM annotation_roles WHERE run_id=? AND structure_id=?",
                    (run_id,structure_id),
                ).fetchone()
                if role:
                    c.execute("DELETE FROM annotation_roles WHERE role_id=?",(int(role[0]),))
                    self._annotation_event(c,run_id,"remove_role",structure_id,int(role[1]),{"reason":"standalone_reference_added"})
                existing=c.execute(
                    "SELECT annotation_id,x,y FROM annotations WHERE run_id=? AND structure_id=? ORDER BY annotation_id LIMIT 1",
                    (run_id,structure_id),
                ).fetchone()
                if existing:
                    c.execute("UPDATE annotations SET x=?,y=? WHERE annotation_id=?",(x,y,existing[0]))
                    self._annotation_event(c,run_id,"move",structure_id,existing[0],{"from":[existing[1],existing[2]],"to":[x,y]})
                    c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
                    annotation_id=int(existing[0])
                else:annotation_id=None
            else:annotation_id=None
            if annotation_id is None:
                order=c.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM annotations WHERE run_id=? AND structure_id=?",(run_id,structure_id)).fetchone()[0]
                cur=c.execute("INSERT INTO annotations(run_id,structure_id,x,y,sort_order) VALUES(?,?,?,?,?)",(run_id,structure_id,x,y,int(order)))
                annotation_id=int(cur.lastrowid);self._annotation_event(c,run_id,"add",structure_id,annotation_id,{"at":[x,y],"sort_order":int(order)})
                c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
        self.recalculate_trait_results(specimen_id)
        return annotation_id

    def move_annotation(self,annotation_id,x,y):
        x=max(0.0,min(1.0,float(x)));y=max(0.0,min(1.0,float(y)));now=_now();specimen_id=None
        with sqlite3.connect(self.db_path) as c:
            row=c.execute("""SELECT a.run_id,a.structure_id,a.x,a.y,r.specimen_id
                             FROM annotations a JOIN annotation_runs r ON r.run_id=a.run_id
                             WHERE a.annotation_id=?""",(int(annotation_id),)).fetchone()
            if row is None:raise KeyError(f"Unknown annotation: {annotation_id}")
            specimen_id=row[4];c.execute("UPDATE annotations SET x=?,y=? WHERE annotation_id=?",(x,y,int(annotation_id)))
            self._annotation_event(c,row[0],"move",row[1],int(annotation_id),{"from":[row[2],row[3]],"to":[x,y]})
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,row[0]))
        self.recalculate_trait_results(specimen_id);return True

    def delete_annotation(self,annotation_id):
        now=_now();specimen_id=None
        with sqlite3.connect(self.db_path) as c:
            row=c.execute("""SELECT a.run_id,a.structure_id,a.x,a.y,a.sort_order,r.specimen_id
                             FROM annotations a JOIN annotation_runs r ON r.run_id=a.run_id
                             WHERE a.annotation_id=?""",(int(annotation_id),)).fetchone()
            if row is None:return False
            specimen_id=row[5]
            roles=[role[0] for role in c.execute("SELECT structure_id FROM annotation_roles WHERE annotation_id=?",(int(annotation_id),))]
            self._annotation_event(c,row[0],"delete",row[1],int(annotation_id),{"at":[row[2],row[3]],"sort_order":row[4],"removed_roles":roles})
            c.execute("DELETE FROM annotation_roles WHERE annotation_id=?",(int(annotation_id),))
            c.execute("DELETE FROM annotations WHERE annotation_id=?",(int(annotation_id),))
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,row[0]))
        self.recalculate_trait_results(specimen_id);return True

    def missing_required_structures(self,specimen_id,pass_no=1,source="human"):
        counts={}
        for row in self.effective_annotations(specimen_id,pass_no,source):
            counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        states=self.structure_visibility_states(specimen_id,pass_no,source)
        return [
            s for s in self.scheme.get("structures",())
            if s.get("required",True)
            and counts.get(s["id"],0)<1
            and states.get(str(s["id"]),"complete") not in {"not_visible","absent"}
        ]

    def clear_annotations(self,specimen_id,pass_no=1,source="human",structure_id=None):
        run=self.annotation_run(specimen_id,pass_no,source,False)
        if run is None:return {"annotations":0,"roles":0}
        run_id=run["run_id"];now=_now();structure_id=None if structure_id is None else str(structure_id)
        if structure_id is not None:
            known={item["id"] for item in self.scheme.get("structures",())}
            if structure_id not in known:raise KeyError(f"Unknown structure in active scheme: {structure_id}")
        with sqlite3.connect(self.db_path) as c:
            if structure_id is None:
                annotations=int(c.execute("SELECT COUNT(*) FROM annotations WHERE run_id=?",(run_id,)).fetchone()[0])
                roles=int(c.execute("SELECT COUNT(*) FROM annotation_roles WHERE run_id=?",(run_id,)).fetchone()[0])
                if not annotations and not roles:return {"annotations":0,"roles":0}
                self._annotation_event(c,run_id,"clear_all",payload={"annotations":annotations,"roles":roles})
                c.execute("DELETE FROM annotation_roles WHERE run_id=?",(run_id,))
                c.execute("DELETE FROM annotations WHERE run_id=?",(run_id,))
            else:
                annotations=int(c.execute(
                    "SELECT COUNT(*) FROM annotations WHERE run_id=? AND structure_id=?",(run_id,structure_id)
                ).fetchone()[0])
                direct_roles=int(c.execute(
                    "SELECT COUNT(*) FROM annotation_roles WHERE run_id=? AND structure_id=?",(run_id,structure_id)
                ).fetchone()[0])
                attached_roles=int(c.execute(
                    """SELECT COUNT(*) FROM annotation_roles
                       WHERE run_id=? AND annotation_id IN (
                           SELECT annotation_id FROM annotations WHERE run_id=? AND structure_id=?
                       )""",(run_id,run_id,structure_id)
                ).fetchone()[0])
                roles=direct_roles+attached_roles
                if not annotations and not roles:return {"annotations":0,"roles":0}
                self._annotation_event(c,run_id,"clear_structure",structure_id,payload={"annotations":annotations,"roles":roles})
                c.execute("DELETE FROM annotation_roles WHERE run_id=? AND structure_id=?",(run_id,structure_id))
                c.execute(
                    """DELETE FROM annotation_roles
                       WHERE run_id=? AND annotation_id IN (
                           SELECT annotation_id FROM annotations WHERE run_id=? AND structure_id=?
                       )""",(run_id,run_id,structure_id)
                )
                c.execute("DELETE FROM annotations WHERE run_id=? AND structure_id=?",(run_id,structure_id))
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
        self.recalculate_trait_results(specimen_id)
        return {"annotations":annotations,"roles":roles}

    def verify_annotations(self,specimen_id,pass_no=1,source="human"):
        scheme=self.scheme;run=self.annotation_run(specimen_id,pass_no,source,True);rows=self.effective_annotations(specimen_id,pass_no,source)
        counts={}
        for row in rows:counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        missing=self.missing_required_structures(specimen_id,pass_no,source)
        if missing:
            raise ValueError("Before continuing, mark every required category. Missing: "+", ".join(item["name"] for item in missing))
        now=_now()
        states=self.structure_visibility_states(specimen_id,pass_no,source)
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE annotation_runs SET status='verified',updated_at=?,verified_at=? WHERE run_id=?",(now,now,run["run_id"]))
            self._annotation_event(c,run["run_id"],"verify",payload={"counts":counts,"structure_visibility":states})
        self.recalculate_trait_results(specimen_id)
        if int(pass_no)>1 and str(source)=="human":
            self._update_structure_repeatability_completion(specimen_id,int(pass_no))
        return {"run_id":run["run_id"],"counts":counts}

    def annotation_events(self,specimen_id,pass_no=1,source="human"):
        run=self.annotation_run(specimen_id,pass_no,source,False)
        if run is None:return []
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;rows=[dict(row) for row in c.execute(
                "SELECT * FROM annotation_events WHERE run_id=? ORDER BY event_id",(run["run_id"],)
            )]
        for row in rows:
            try:row["payload"]=json.loads(row.pop("payload_json") or "{}")
            except Exception:row["payload"]={}
        return rows

    @staticmethod
    def _repeatability_pass_numbers(run):
        """Dedicated blind pass numbers; legacy snapshot-based runs stay readable."""
        first=int(run.get("annotation1_pass_no") or 0)
        second=int(run.get("annotation2_pass_no") or 0)
        return (first,second,False) if first>1 and second>1 else (1,2,True)

    def structure_repeatability(self,run_id=None):
        """Latest persisted Human repeatability run and both blind-pass progress values."""
        schema_id=self.active_scheme_record()["version_id"]
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            if run_id:
                row=c.execute("SELECT * FROM xray_structure_repeatability_runs WHERE run_id=?",(str(run_id),)).fetchone()
            else:
                row=c.execute(
                    """SELECT * FROM xray_structure_repeatability_runs
                       ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'completed' THEN 1 ELSE 2 END,
                                created_at DESC LIMIT 1"""
                ).fetchone()
            if row is None:return None
            run=dict(row);p1_no,p2_no,legacy=self._repeatability_pass_numbers(run)
            members=[dict(item) for item in c.execute(
                """SELECT specimen_id,position,baseline_json,baseline_visibility_json
                   FROM xray_structure_repeatability_membership
                   WHERE run_id=? ORDER BY position""",(run["run_id"],)
            )]
            def verified_ids(pass_no):
                return {str(item[0]) for item in c.execute(
                    """SELECT specimen_id FROM annotation_runs
                       WHERE pass_no=? AND source='human' AND schema_version_id=? AND status='verified'""",
                    (int(pass_no),run["schema_version_id"]),
                )}
            verified1=verified_ids(p1_no);verified2=verified_ids(p2_no)
        decoded=[]
        for item in members:
            try:baseline=json.loads(item.pop("baseline_json") or "[]")
            except Exception:baseline=[]
            try:visibility=json.loads(item.pop("baseline_visibility_json") or "{}")
            except Exception:visibility={}
            decoded.append({**item,"baseline":baseline,"baseline_visibility":visibility})
        ids=[str(item["specimen_id"]) for item in decoded]
        p1_completed=(len(ids) if legacy else sum(specimen_id in verified1 for specimen_id in ids))
        p2_completed=sum(specimen_id in verified2 for specimen_id in ids)
        return {
            **run,"members":decoded,"ids":ids,"total":len(ids),"legacy":legacy,
            "annotation1_pass_no":p1_no,"annotation2_pass_no":p2_no,
            "annotation1_verified":p1_completed,"annotation2_verified":p2_completed,
            "verified":p2_completed,"remaining":max(0,len(ids)-p2_completed),
            "schema_current":str(run["schema_version_id"])==str(schema_id),
        }

    def start_structure_repeatability(self,count,seed=42):
        """Create a random control sample with two dedicated blind manual annotations."""
        count=max(1,int(count));seed=int(seed);schema_id=self.active_scheme_record()["version_id"]
        active=self.structure_repeatability()
        if active and active.get("status")=="in_progress":return active
        candidates=[row for row in self.structure_specimens(1) if str(row.get("annotation_status") or "")=="verified"]
        if not candidates:raise ValueError("No human-verified specimens are available for a repeatability sample.")
        count=min(count,len(candidates));selected=random.Random(seed).sample(candidates,count)
        with sqlite3.connect(self.db_path) as c:
            highest=int(c.execute("SELECT COALESCE(MAX(pass_no),1) FROM annotation_runs WHERE source='human'").fetchone()[0] or 1)
            prior=int(c.execute("SELECT COALESCE(MAX(annotation2_pass_no),1) FROM xray_structure_repeatability_runs").fetchone()[0] or 1)
        highest=max(highest,prior);p1_no=max(2,highest+1);p2_no=p1_no+1
        run_id=str(uuid.uuid4());now=_now();payload=[]
        for position,row in enumerate(selected):
            specimen_id=str(row["specimen_id"])
            baseline=[
                {"structure_id":str(point["structure_id"]),"x":float(point["x"]),"y":float(point["y"]),
                 "sort_order":int(point.get("sort_order",0) or 0)}
                for point in self.effective_annotations(specimen_id,1,"human")
            ]
            visibility=self.structure_visibility_states(specimen_id,1,"human")
            payload.append((run_id,specimen_id,position,_json(baseline),_json(visibility)))
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                """INSERT INTO xray_structure_repeatability_runs(
                     run_id,schema_version_id,created_at,status,requested_count,seed,
                     annotation1_pass_no,annotation2_pass_no
                   ) VALUES(?,?,?,'in_progress',?,?,?,?)""",
                (run_id,schema_id,now,count,seed,p1_no,p2_no),
            )
            c.executemany(
                """INSERT INTO xray_structure_repeatability_membership(
                     run_id,specimen_id,position,baseline_json,baseline_visibility_json
                   ) VALUES(?,?,?,?,?)""",payload,
            )
        return self.structure_repeatability(run_id)

    def retire_structure_repeatability(self,run_id):
        run=self.structure_repeatability(run_id)
        if not run:return False
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                "UPDATE xray_structure_repeatability_runs SET status='retired',completed_at=? WHERE run_id=?",
                (_now(),str(run_id)),
            )
        self.set_ui_state("xray_structure_active_batch",{})
        return True

    def structure_repeatability_progress(self,run_id=None):
        run=self.structure_repeatability(run_id)
        if not run:return {"run":None,"total":0,"annotation1":0,"annotation2":0}
        return {
            "run":run,"total":int(run["total"]),
            "annotation1":int(run["annotation1_verified"]),
            "annotation2":int(run["annotation2_verified"]),
        }

    def _update_structure_repeatability_completion(self,specimen_id,pass_no=None):
        specimen_id=str(specimen_id);pass_no=None if pass_no is None else int(pass_no)
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            runs=[dict(row) for row in c.execute(
                """SELECT r.* FROM xray_structure_repeatability_runs r
                   JOIN xray_structure_repeatability_membership m ON m.run_id=r.run_id
                   WHERE r.status='in_progress' AND m.specimen_id=?""",(specimen_id,)
            )]
            for run in runs:
                p1_no,p2_no,legacy=self._repeatability_pass_numbers(run)
                if pass_no is not None and pass_no not in {p1_no,p2_no}:continue
                total=int(c.execute(
                    "SELECT COUNT(*) FROM xray_structure_repeatability_membership WHERE run_id=?",(run["run_id"],)
                ).fetchone()[0])
                def completed(number):
                    return int(c.execute(
                        """SELECT COUNT(*) FROM xray_structure_repeatability_membership m
                           JOIN annotation_runs a ON a.specimen_id=m.specimen_id
                           WHERE m.run_id=? AND a.pass_no=? AND a.source='human'
                             AND a.schema_version_id=? AND a.status='verified'""",
                        (run["run_id"],int(number),run["schema_version_id"]),
                    ).fetchone()[0])
                p1_done=total if legacy else completed(p1_no);p2_done=completed(p2_no)
                if total and p1_done>=total and p2_done>=total:
                    c.execute(
                        "UPDATE xray_structure_repeatability_runs SET status='completed',completed_at=? WHERE run_id=?",
                        (_now(),run["run_id"]),
                    )

    @staticmethod
    def _repeatability_match_distances(first,second):
        remaining=[dict(point) for point in second];distances=[]
        for point in first:
            if not remaining:break
            index=min(
                range(len(remaining)),
                key=lambda i:(float(point["x"])-float(remaining[i]["x"]))**2+(float(point["y"])-float(remaining[i]["y"]))**2,
            )
            other=remaining.pop(index)
            distances.append(((float(point["x"])-float(other["x"]))**2+(float(point["y"])-float(other["y"]))**2)**0.5)
        return distances

    def _repeatability_annotations(self,run,member,number):
        p1_no,p2_no,legacy=self._repeatability_pass_numbers(run)
        if int(number)==1 and legacy:return list(member.get("baseline") or ())
        pass_no=p1_no if int(number)==1 else p2_no
        current=self.annotation_run(member["specimen_id"],pass_no,"human",False)
        if not current or str(current.get("status") or "")!="verified":return None
        return self.effective_annotations(member["specimen_id"],pass_no,"human")

    def structure_repeatability_metrics(self,run_id=None):
        run=self.structure_repeatability(run_id)
        if not run:return {"run":None,"structures":[],"completed":0,"total":0}
        structures=list(self.scheme.get("structures") or ())
        role_ids={str(item["id"]) for item in structures if str(item.get("learning_relation") or "")=="role_on_structure"}
        accum={
            str(item["id"]):{"name":str(item.get("name") or item["id"]),"specimens":0,"exact":0,"abs_error":0.0,
                             "distances":[],"role_checks":0,"role_same":0}
            for item in structures
        }
        def role_ordinal(points,structure):
            sid=str(structure["id"]);roles=[point for point in points if str(point["structure_id"])==sid]
            if len(roles)!=1:return None
            target=roles[0];best=None
            for base_id in structure.get("reuse_from") or ():
                base=spatial_series_order([point for point in points if str(point["structure_id"])==str(base_id)])
                for index,point in enumerate(base,1):
                    distance=((float(point["x"])-float(target["x"]))**2+(float(point["y"])-float(target["y"]))**2)**0.5
                    if best is None or distance<best[0]:best=(distance,index)
            return None if best is None else int(best[1])
        for member in run["members"]:
            first=self._repeatability_annotations(run,member,1);second=self._repeatability_annotations(run,member,2)
            if first is None or second is None:continue
            for structure in structures:
                sid=str(structure["id"]);a=[p for p in first if p["structure_id"]==sid];b=[p for p in second if p["structure_id"]==sid]
                bucket=accum[sid];bucket["specimens"]+=1;bucket["exact"]+=int(len(a)==len(b));bucket["abs_error"]+=abs(len(a)-len(b))
                bucket["distances"].extend(self._repeatability_match_distances(a,b))
                if sid in role_ids:
                    one=role_ordinal(first,structure);two=role_ordinal(second,structure)
                    if one is not None and two is not None:
                        bucket["role_checks"]+=1;bucket["role_same"]+=int(one==two)
        result=[]
        for structure in structures:
            sid=str(structure["id"]);bucket=accum[sid];n=int(bucket["specimens"]);dist=bucket.pop("distances")
            result.append({
                "structure_id":sid,"name":bucket["name"],"specimens":n,
                "exact_count_accuracy":(bucket["exact"]/n if n else None),
                "count_mae":(bucket["abs_error"]/n if n else None),
                "mean_marker_difference":(sum(dist)/len(dist) if dist else None),
                "role_same_ordinal_accuracy":(bucket["role_same"]/bucket["role_checks"] if bucket["role_checks"] else None),
            })
        return {"run":run,"structures":result,"completed":min(run["annotation1_verified"],run["annotation2_verified"]),"total":run["total"]}

    def annotation_summary(self,pass_no=1):
        rows=self.structure_specimens(pass_no)
        return {
            "eligible":len(rows),
            "verified":sum(str(row.get("annotation_status") or "")=="verified" for row in rows),
            "draft":sum(bool(str(row.get("annotation_status") or "")) and str(row.get("annotation_status") or "")!="verified" for row in rows),
            "unstarted":sum(not row.get("run_id") for row in rows),
        }

    def annotation_counts_by_structure(self):
        counts={}
        with sqlite3.connect(self.db_path) as c:
            for sid,count in c.execute("SELECT structure_id,COUNT(*) FROM annotations GROUP BY structure_id"):counts[sid]=counts.get(sid,0)+int(count)
            for sid,count in c.execute("SELECT structure_id,COUNT(*) FROM annotation_roles GROUP BY structure_id"):counts[sid]=counts.get(sid,0)+int(count)
        return counts