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
          crop_json TEXT, excluded INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(image_id) REFERENCES source_images(image_id)
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

    def _ensure_schema(self):
        with sqlite3.connect(self.db_path) as c:self._create_tables(c)

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
