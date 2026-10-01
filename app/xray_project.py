"""SQLite persistence for the MorphoLabel X-ray module."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import shutil
from datetime import datetime, timezone
import uuid

from .xray_schema import normalize_scheme, scheme_hash

IMAGE_EXTENSIONS={".png",".jpg",".jpeg",".tif",".tiff",".bmp"}

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))

class XRayProject:
    def __init__(self,root):
        self.root=Path(root);self.db_path=self.root/"xray_project.sqlite3"
        if not self.db_path.is_file():raise FileNotFoundError(self.db_path)
        self._ensure_schema()

    @classmethod
    def create(cls,name,source,destination,scheme,scheme_note="Initial trait scheme"):
        root=Path(destination)/str(name);root.mkdir(parents=True,exist_ok=False);db=root/"xray_project.sqlite3"
        with sqlite3.connect(db) as c:
            cls._create_tables(c)
            c.executemany("INSERT INTO meta(key,value) VALUES(?,?)",(("name",str(name)),("source",str(Path(source).resolve())),("created_at",_now())))
        project=cls(root);project.save_scheme(scheme,scheme_note);project.scan_source();return project

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
        CREATE TABLE IF NOT EXISTS annotations(
          annotation_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          structure_id TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(run_id) REFERENCES annotation_runs(run_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS annotation_events(
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          created_at TEXT NOT NULL, action TEXT NOT NULL, structure_id TEXT NOT NULL DEFAULT '',
          annotation_id INTEGER, payload_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(run_id) REFERENCES annotation_runs(run_id)
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

    def meta(self,key,default=""):
        with sqlite3.connect(self.db_path) as c:row=c.execute("SELECT value FROM meta WHERE key=?",(key,)).fetchone()
        return default if row is None else row[0]

    @property
    def name(self):return self.meta("name",self.root.name)
    @property
    def source(self):return Path(self.meta("source"))

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

    def confirm_specimen(self,specimen_id,source="human"):
        item=self.specimen(specimen_id)
        if item["crop_status"]=="confirmed" and not item["excluded"]:return False
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET crop_status='confirmed',excluded=0,updated_at=? WHERE specimen_id=?",(_now(),specimen_id))
            self._event(c,specimen_id,"confirm",source,{"previous_status":item["crop_status"]})
        return True

    def confirm_plate(self,image_id,source="human"):
        rows=[item for item in self.specimens(image_id) if not item["excluded"]]
        if not rows:raise ValueError("This plate has no specimen crops to confirm.")
        now=_now();confirmed=0
        with sqlite3.connect(self.db_path) as c:
            for item in rows:
                if item["crop_status"]!="confirmed":
                    c.execute("UPDATE specimens SET crop_status='confirmed',excluded=0,updated_at=? WHERE specimen_id=?",(now,item["specimen_id"]))
                    self._event(c,item["specimen_id"],"confirm_plate",source,{"previous_status":item["crop_status"]})
                    confirmed+=1
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
        item=self.specimen(specimen_id);crop=dict(crop);crop["confidence"]="high";now=_now()
        reviewed=bool(self.source_image(item["image_id"]).get("crop_reviewed"))
        status="confirmed" if reviewed else "proposed"
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET crop_json=?,crop_source='manual',crop_status=?,crop_qc_json=?,model_id='',excluded=0,updated_at=? WHERE specimen_id=?",
                      (_json(crop),status,_json(list(qc)),now,specimen_id))
            self._event(c,specimen_id,"edit","human",{"previous_crop":item.get("crop") or {},"crop":crop})
        return self.specimen(specimen_id)

    def add_manual_specimen(self,image_id,crop,label=""):
        crop=dict(crop);crop["confidence"]="high";specimen_id=str(uuid.uuid4());now=_now()
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
                removed+=1
            for edit in edits:
                specimen_id=str(edit.get("specimen_id") or "");item=rows.get(specimen_id)
                if item is None:raise KeyError(f"Unknown specimen on this plate: {specimen_id}")
                if specimen_id in removed_ids:continue
                crop=dict(edit.get("crop") or {});crop["confidence"]="high"
                if not crop.get("corners") or not crop.get("bounds"):raise ValueError("Crop geometry is incomplete.")
                c.execute(
                    "UPDATE specimens SET crop_json=?,crop_source='manual',crop_status=?,crop_qc_json='[]',model_id='',excluded=0,updated_at=? WHERE specimen_id=?",
                    (_json(crop),status,now,specimen_id),
                )
                self._event(c,specimen_id,"edit","human",{"previous_crop":item.get("crop") or {},"crop":crop,"action":"apply_crop"})
                updated+=1
            ordinal=max((int(item.get("ordinal") or 0) for item in rows.values()),default=0);stem=self.source_image_path(image_id).stem
            for entry in new_crops:
                crop=dict(entry.get("crop") or {});crop["confidence"]="high"
                if not crop.get("corners") or not crop.get("bounds"):raise ValueError("Crop geometry is incomplete.")
                ordinal+=1;specimen_id=str(uuid.uuid4());client_id=str(entry.get("client_id") or specimen_id);label=f"{stem}-{ordinal:02d}"
                c.execute(
                    "INSERT INTO specimens(specimen_id,image_id,label,crop_json,excluded,ordinal,crop_source,crop_status,crop_qc_json,model_id,updated_at) VALUES(?,?,?,?,0,?,'manual',?,'[]','',?)",
                    (specimen_id,image_id,label,_json(crop),ordinal,status,now),
                )
                self._event(c,specimen_id,"add","human",{"crop":crop,"action":"apply_crop"});id_map[client_id]=specimen_id;added+=1
        return {"updated":updated,"added":added,"removed":removed,"id_map":id_map}

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

    def untouched_plate_ids(self):
        result=[]
        for image in self.source_images():
            if image["excluded"] or image["crop_reviewed"]:continue
            if any(not item["excluded"] for item in self.specimens(image["image_id"])):continue
            result.append(image["image_id"])
        return result

    @staticmethod
    def _round_robin_series(images,count):
        groups={}
        for image in images:
            parent=Path(image["relative_path"]).parent.as_posix()
            groups.setdefault(parent,[]).append(image["image_id"])
        ordered=[];keys=sorted(groups)
        while keys and len(ordered)<int(count):
            next_keys=[]
            for key in keys:
                values=groups[key]
                if values:ordered.append(values.pop(0))
                if values:next_keys.append(key)
                if len(ordered)>=int(count):break
            keys=next_keys
        return ordered

    def training_candidate_ids(self):
        return [image["image_id"] for image in self.source_images() if not image["excluded"] and not image["crop_reviewed"]]

    def select_training_plate_ids(self,count):
        candidates=[image for image in self.source_images() if not image["excluded"] and not image["crop_reviewed"]]
        return self._round_robin_series(candidates,max(1,int(count)))

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
        return self._round_robin_series(candidates,max(1,int(count)))

    def ai_review_plate_ids(self):
        ids=[]
        for image in self.source_images():
            if image["excluded"] or image["crop_reviewed"]:continue
            if any(item["crop_source"]=="model" and item["crop_status"]=="proposed" and not item["excluded"] for item in self.specimens(image["image_id"])):
                ids.append(image["image_id"])
        return ids

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

    def crop_summary(self):
        images=self.source_images();rows=self.specimens()
        verified_plates=sum(bool(x["crop_reviewed"]) and not x["excluded"] for x in images)
        ai_pending=len(self.ai_review_plate_ids())
        return {
            "plates":sum(not x["excluded"] for x in images),
            "verified_plates":verified_plates,
            "training_specimens":self.training_specimen_count(),
            "ai_pending_plates":ai_pending,
            "uncropped_plates":len(self.untouched_plate_ids()),
            "specimens":sum(not row["excluded"] for row in rows),
            "confirmed":sum(row["crop_status"]=="confirmed" and not row["excluded"] for row in rows),
            "review":sum(row["crop_status"]=="proposed" and not row["excluded"] for row in rows),
        }

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

    def schema_history(self):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            return [dict(row) for row in c.execute("SELECT version_id,created_at,scheme_hash,note,active FROM schema_versions ORDER BY created_at DESC")]

    def structure_specimens(self,pass_no=1):
        """Confirmed specimen crops eligible for structure annotation."""
        schema_id=self.active_scheme_record()["version_id"];pass_no=int(pass_no)
        sql="""
            SELECT s.*,i.relative_path,i.crop_reviewed,i.excluded AS image_excluded,
                   r.run_id,r.status AS annotation_status,r.updated_at AS annotation_updated_at
            FROM specimens s
            JOIN source_images i ON i.image_id=s.image_id
            LEFT JOIN annotation_runs r
              ON r.specimen_id=s.specimen_id AND r.pass_no=? AND r.source='human' AND r.schema_version_id=?
            WHERE s.crop_status='confirmed' AND s.excluded=0 AND i.excluded=0 AND i.crop_reviewed=1
            ORDER BY i.relative_path,s.ordinal,s.label
        """
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row;rows=[dict(row) for row in c.execute(sql,(pass_no,schema_id))]
        if pass_no>1:
            verified=set()
            with sqlite3.connect(self.db_path) as c:
                verified={row[0] for row in c.execute(
                    "SELECT specimen_id FROM annotation_runs WHERE pass_no=1 AND source='human' AND schema_version_id=? AND status='verified'",
                    (schema_id,),
                )}
            rows=[row for row in rows if row["specimen_id"] in verified]
        return rows

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

    def _annotation_event(self,c,run_id,action,structure_id="",annotation_id=None,payload=None):
        c.execute(
            "INSERT INTO annotation_events(run_id,created_at,action,structure_id,annotation_id,payload_json) VALUES(?,?,?,?,?,?)",
            (run_id,_now(),str(action),str(structure_id or ""),annotation_id,_json(payload or {})),
        )

    def add_annotation(self,specimen_id,structure_id,x,y,pass_no=1,source="human",replace_single=False):
        structure_id=str(structure_id)
        known={item["id"] for item in self.scheme.get("structures",())}
        if structure_id not in known:raise KeyError(f"Unknown structure in active scheme: {structure_id}")
        x=max(0.0,min(1.0,float(x)));y=max(0.0,min(1.0,float(y)))
        run_id=self.ensure_annotation_run(specimen_id,pass_no,source);now=_now()
        with sqlite3.connect(self.db_path) as c:
            if replace_single:
                existing=c.execute(
                    "SELECT annotation_id,x,y FROM annotations WHERE run_id=? AND structure_id=? ORDER BY annotation_id LIMIT 1",
                    (run_id,structure_id),
                ).fetchone()
                if existing:
                    c.execute("UPDATE annotations SET x=?,y=? WHERE annotation_id=?",(x,y,existing[0]))
                    self._annotation_event(c,run_id,"move",structure_id,existing[0],{"from":[existing[1],existing[2]],"to":[x,y]})
                    c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
                    return int(existing[0])
            order=c.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM annotations WHERE run_id=? AND structure_id=?",(run_id,structure_id)).fetchone()[0]
            cur=c.execute("INSERT INTO annotations(run_id,structure_id,x,y,sort_order) VALUES(?,?,?,?,?)",(run_id,structure_id,x,y,int(order)))
            annotation_id=int(cur.lastrowid);self._annotation_event(c,run_id,"add",structure_id,annotation_id,{"at":[x,y],"sort_order":int(order)})
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,run_id))
        return annotation_id

    def move_annotation(self,annotation_id,x,y):
        x=max(0.0,min(1.0,float(x)));y=max(0.0,min(1.0,float(y)));now=_now()
        with sqlite3.connect(self.db_path) as c:
            row=c.execute("SELECT run_id,structure_id,x,y FROM annotations WHERE annotation_id=?",(int(annotation_id),)).fetchone()
            if row is None:raise KeyError(f"Unknown annotation: {annotation_id}")
            c.execute("UPDATE annotations SET x=?,y=? WHERE annotation_id=?",(x,y,int(annotation_id)))
            self._annotation_event(c,row[0],"move",row[1],int(annotation_id),{"from":[row[2],row[3]],"to":[x,y]})
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,row[0]))
        return True

    def delete_annotation(self,annotation_id):
        now=_now()
        with sqlite3.connect(self.db_path) as c:
            row=c.execute("SELECT run_id,structure_id,x,y,sort_order FROM annotations WHERE annotation_id=?",(int(annotation_id),)).fetchone()
            if row is None:return False
            self._annotation_event(c,row[0],"delete",row[1],int(annotation_id),{"at":[row[2],row[3]],"sort_order":row[4]})
            c.execute("DELETE FROM annotations WHERE annotation_id=?",(int(annotation_id),))
            c.execute("UPDATE annotation_runs SET status='draft',updated_at=?,verified_at='' WHERE run_id=?",(now,row[0]))
        return True

    def verify_annotations(self,specimen_id,pass_no=1,source="human"):
        scheme=self.scheme;run=self.annotation_run(specimen_id,pass_no,source,True);rows=self.annotations(specimen_id,pass_no,source)
        counts={}
        for row in rows:counts[row["structure_id"]]=counts.get(row["structure_id"],0)+1
        missing=[s["id"] for s in scheme.get("structures",()) if s.get("required",True) and counts.get(s["id"],0)<1]
        if missing:
            names={s["id"]:s["name"] for s in scheme.get("structures",())}
            raise ValueError("Missing required structures: "+", ".join(names.get(item,item) for item in missing))
        now=_now()
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE annotation_runs SET status='verified',updated_at=?,verified_at=? WHERE run_id=?",(now,now,run["run_id"]))
            self._annotation_event(c,run["run_id"],"verify",payload={"counts":counts})
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

    def annotation_summary(self,pass_no=1):
        rows=self.structure_specimens(pass_no)
        return {
            "eligible":len(rows),
            "verified":sum(str(row.get("annotation_status") or "")=="verified" for row in rows),
            "draft":sum(str(row.get("annotation_status") or "")=="draft" for row in rows),
            "unstarted":sum(not row.get("run_id") for row in rows),
        }

    def annotation_counts_by_structure(self):
        with sqlite3.connect(self.db_path) as c:
            return {row[0]:int(row[1]) for row in c.execute("SELECT structure_id,COUNT(*) FROM annotations GROUP BY structure_id")}
