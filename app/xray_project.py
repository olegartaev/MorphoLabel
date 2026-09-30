"""SQLite persistence for the MorphoLabel X-ray module."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
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
          created_at TEXT NOT NULL, UNIQUE(specimen_id,pass_no,source,schema_version_id)
        );
        CREATE TABLE IF NOT EXISTS annotations(
          annotation_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          structure_id TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(run_id) REFERENCES annotation_runs(run_id) ON DELETE CASCADE
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
                "SELECT * FROM specimens WHERE image_id=? AND crop_status='confirmed' AND excluded=0",(image_id,))]
            old=[row[0] for row in c.execute(
                "SELECT specimen_id FROM specimens WHERE image_id=? AND crop_status='proposed'",(image_id,))]
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

    def replace_model_proposals(self,image_id,proposals,model_id):
        return self._replace_proposals(image_id,proposals,"model","rtmdet-tiny-v1",model_id)

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

    def training_candidate_ids(self):
        return [image["image_id"] for image in self.source_images() if not image["excluded"] and not image["crop_reviewed"]]

    def prediction_candidate_ids(self):
        ids=[]
        for image in self.source_images():
            if image["excluded"] or image["crop_reviewed"]:continue
            has_model_pending=any(
                item["crop_source"]=="model" and item["crop_status"]=="proposed" and not item["excluded"]
                for item in self.specimens(image["image_id"])
            )
            if not has_model_pending:ids.append(image["image_id"])
        return ids

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

    def annotation_counts_by_structure(self):
        with sqlite3.connect(self.db_path) as c:
            return {row[0]:int(row[1]) for row in c.execute("SELECT structure_id,COUNT(*) FROM annotations GROUP BY structure_id")}
