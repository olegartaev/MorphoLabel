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
          image_id TEXT PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE, excluded INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS specimens(
          specimen_id TEXT PRIMARY KEY, image_id TEXT NOT NULL, label TEXT NOT NULL,
          crop_json TEXT, excluded INTEGER NOT NULL DEFAULT 0, ordinal INTEGER NOT NULL DEFAULT 0,
          crop_source TEXT NOT NULL DEFAULT '', crop_status TEXT NOT NULL DEFAULT 'proposed',
          crop_qc_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(image_id) REFERENCES source_images(image_id)
        );
        CREATE TABLE IF NOT EXISTS crop_events(
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, specimen_id TEXT NOT NULL,
          created_at TEXT NOT NULL, action TEXT NOT NULL, source TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(specimen_id) REFERENCES specimens(specimen_id)
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
    def _ensure_specimen_columns(c):
        existing={row[1] for row in c.execute("PRAGMA table_info(specimens)")}
        wanted={
            "ordinal":"INTEGER NOT NULL DEFAULT 0",
            "crop_source":"TEXT NOT NULL DEFAULT ''",
            "crop_status":"TEXT NOT NULL DEFAULT 'proposed'",
            "crop_qc_json":"TEXT NOT NULL DEFAULT '[]'",
            "updated_at":"TEXT NOT NULL DEFAULT ''",
        }
        for name,definition in wanted.items():
            if name not in existing:c.execute(f"ALTER TABLE specimens ADD COLUMN {name} {definition}")

    def _ensure_schema(self):
        with sqlite3.connect(self.db_path) as c:
            self._create_tables(c);self._ensure_specimen_columns(c)

    def meta(self,key,default=""):
        with sqlite3.connect(self.db_path) as c:row=c.execute("SELECT value FROM meta WHERE key=?",(key,)).fetchone()
        return default if row is None else row[0]

    @property
    def name(self):return self.meta("name",self.root.name)
    @property
    def source(self):return Path(self.meta("source"))

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
            return [dict(row) for row in c.execute("SELECT image_id,relative_path,excluded FROM source_images ORDER BY relative_path")]

    def source_image_path(self,image_id):
        with sqlite3.connect(self.db_path) as c:row=c.execute("SELECT relative_path FROM source_images WHERE image_id=?",(image_id,)).fetchone()
        if row is None:raise KeyError(f"Unknown X-ray source image: {image_id}")
        return self.source/row[0]

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

    def replace_auto_proposals(self,image_id,proposals,algorithm):
        proposals=[p.to_dict() if hasattr(p,"to_dict") else dict(p) for p in proposals]
        now=_now();stem=self.source_image_path(image_id).stem
        with sqlite3.connect(self.db_path) as c:
            c.row_factory=sqlite3.Row
            protected=[self._decode_specimen(row) for row in c.execute(
                "SELECT * FROM specimens WHERE image_id=? AND crop_status='confirmed' AND excluded=0",(image_id,))]
            old=[row[0] for row in c.execute(
                "SELECT specimen_id FROM specimens WHERE image_id=? AND crop_source='auto' AND crop_status='proposed'",(image_id,))]
            for specimen_id in old:
                c.execute("UPDATE specimens SET crop_status='superseded',excluded=1,updated_at=? WHERE specimen_id=?",(now,specimen_id))
                self._event(c,specimen_id,"supersede","auto",{"reason":"redetect"})
            kept=high=review=0
            for ordinal,crop in enumerate(proposals,1):
                if any(self._bbox_iou(crop,item.get("crop") or {})>=0.25 for item in protected):
                    kept+=1;continue
                key=f"{image_id}:{algorithm}:{round(float(crop.get('center_x',0)),1)}:{round(float(crop.get('center_y',0)),1)}"
                specimen_id=str(uuid.uuid5(uuid.NAMESPACE_URL,key))
                crop["algorithm"]=str(algorithm)
                qc=list(crop.get("qc") or [])
                confidence=str(crop.get("confidence") or ("review" if qc else "high"))
                crop["confidence"]=confidence
                c.execute("""
                    INSERT INTO specimens(specimen_id,image_id,label,crop_json,excluded,ordinal,crop_source,crop_status,crop_qc_json,updated_at)
                    VALUES(?,?,?,?,0,?,'auto','proposed',?,?)
                    ON CONFLICT(specimen_id) DO UPDATE SET
                      image_id=excluded.image_id,label=excluded.label,crop_json=excluded.crop_json,excluded=0,
                      ordinal=excluded.ordinal,crop_source='auto',crop_status='proposed',
                      crop_qc_json=excluded.crop_qc_json,updated_at=excluded.updated_at
                """,(specimen_id,image_id,f"{stem}-{ordinal:02d}",_json(crop),ordinal,_json(qc),now))
                self._event(c,specimen_id,"detect","auto",{"algorithm":algorithm,"confidence":confidence,"qc":qc})
                if confidence=="high":high+=1
                else:review+=1
        return {"proposed":high+review,"high":high,"review":review,"protected":kept}

    def confirm_specimen(self,specimen_id,source="human"):
        item=self.specimen(specimen_id)
        if item["crop_status"]=="confirmed" and not item["excluded"]:return False
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET crop_status='confirmed',excluded=0,updated_at=? WHERE specimen_id=?",(_now(),specimen_id))
            self._event(c,specimen_id,"confirm",source,{"previous_status":item["crop_status"]})
        return True

    def confirm_clear_proposals(self,image_id=None):
        rows=self.specimens(image_id)
        accepted=0
        for item in rows:
            if item["crop_source"]!="auto" or item["crop_status"]!="proposed" or item["excluded"]:continue
            if str((item.get("crop") or {}).get("confidence"))!="high":continue
            accepted+=int(self.confirm_specimen(item["specimen_id"],"human-bulk"))
        return accepted

    def crop_review_candidates(self):
        return [
            item for item in self.specimens()
            if item["crop_status"]=="proposed" and not item["excluded"]
            and str((item.get("crop") or {}).get("confidence"))!="high"
        ]

    def pending_clear_crop_count(self,image_id=None):
        return sum(
            1 for item in self.specimens(image_id)
            if item["crop_source"]=="auto" and item["crop_status"]=="proposed" and not item["excluded"]
            and str((item.get("crop") or {}).get("confidence"))=="high"
        )

    def update_specimen_crop(self,specimen_id,crop,qc=()):
        item=self.specimen(specimen_id);crop=dict(crop);crop["confidence"]="high";now=_now()
        with sqlite3.connect(self.db_path) as c:
            c.execute("UPDATE specimens SET crop_json=?,crop_source='manual',crop_status='confirmed',crop_qc_json=?,excluded=0,updated_at=? WHERE specimen_id=?",
                      (_json(crop),_json(list(qc)),now,specimen_id))
            self._event(c,specimen_id,"edit","human",{"previous_crop":item.get("crop") or {},"crop":crop})
        return self.specimen(specimen_id)

    def add_manual_specimen(self,image_id,crop,label=""):
        crop=dict(crop);crop["confidence"]="high";specimen_id=str(uuid.uuid4());now=_now()
        ordinal=1+max((int(x.get("ordinal") or 0) for x in self.specimens(image_id)),default=0)
        if not label:label=f"{self.source_image_path(image_id).stem}-{ordinal:02d}"
        with sqlite3.connect(self.db_path) as c:
            c.execute("INSERT INTO specimens(specimen_id,image_id,label,crop_json,excluded,ordinal,crop_source,crop_status,crop_qc_json,updated_at) VALUES(?,?,?,?,0,?,'manual','confirmed','[]',?)",
                      (specimen_id,image_id,label,_json(crop),ordinal,now))
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

    def crop_summary(self):
        rows=self.specimens()
        clear_pending=sum(
            row["crop_status"]=="proposed" and not row["excluded"]
            and str((row.get("crop") or {}).get("confidence"))=="high"
            for row in rows
        )
        exceptions=sum(
            row["crop_status"]=="proposed" and not row["excluded"]
            and str((row.get("crop") or {}).get("confidence"))!="high"
            for row in rows
        )
        return {
            "plates":len(self.source_images()),
            "plates_with_specimens":len({row["image_id"] for row in rows if not row["excluded"]}),
            "specimens":sum(not row["excluded"] for row in rows),
            "confirmed":sum(row["crop_status"]=="confirmed" and not row["excluded"] for row in rows),
            "clear_pending":clear_pending,
            "exceptions":exceptions,
            "review":clear_pending+exceptions,
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
