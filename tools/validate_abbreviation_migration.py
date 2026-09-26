"""Backup-first validator for the landmark abbreviation identity migration."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.project_storage import Project, schema_migration_backup

FIELDS=("image_id","landmark_id","x_standardized","y_standardized","state","provenance","model_id","predicted_x","predicted_y","confidence","prediction_run_id","reviewed")

def fingerprint(connection, uses_abbr=False):
    if uses_abbr:
        query="SELECT image_id,landmark_abbr,x_standardized,y_standardized,state,provenance,model_id,predicted_x,predicted_y,confidence,prediction_run_id,reviewed FROM landmarks ORDER BY image_id,landmark_abbr"
    else:
        query="SELECT l.image_id,s.abbr,l.x_standardized,l.y_standardized,l.state,l.provenance,l.model_id,l.predicted_x,l.predicted_y,l.confidence,l.prediction_run_id,l.reviewed FROM landmarks l JOIN landmark_schema s ON s.landmark_id=l.landmark_id ORDER BY l.image_id,s.abbr"
    rows=[tuple(row) for row in connection.execute(query)]
    return len(rows),hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--migrate", action="store_true", help="make backup then open/migrate this project")
    args=parser.parse_args()
    raw=Project(args.project)
    connection=sqlite3.connect(raw.path)
    try:
        before_count,before_hash=fingerprint(connection)
        old_schema=list(connection.execute("SELECT landmark_id,abbr FROM landmark_schema ORDER BY landmark_id"))
        has_abbr=any(row[1]=="landmark_abbr" for row in connection.execute("PRAGMA table_info(landmarks)"))
    finally:
        connection.close()
    backup=None
    if args.migrate and not has_abbr:
        backup=schema_migration_backup(raw)
    migrated=Project.open(raw.root) if args.migrate else raw
    connection=sqlite3.connect(migrated.path)
    try:
        after_count,after_hash=fingerprint(connection, uses_abbr=True)
        missing=connection.execute("SELECT COUNT(*) FROM landmarks WHERE landmark_abbr IS NULL").fetchone()[0]
        mismatches=connection.execute("SELECT COUNT(*) FROM landmarks l LEFT JOIN landmark_schema s ON s.abbr=l.landmark_abbr WHERE l.landmark_abbr IS NULL").fetchone()[0]
        models=connection.execute("SELECT COUNT(*) FROM models WHERE kind='landmark' AND schema_sha256 != (SELECT value FROM project WHERE key='schema_sha256')").fetchone()[0]
    finally:
        connection.close()
    result={"project":str(raw.root),"backup":str(backup) if backup else None,"old_schema":old_schema,"before":{"rows":before_count,"fingerprint":before_hash},"after":{"rows":after_count,"fingerprint":after_hash,"missing_abbreviation":missing,"unresolved_rows":mismatches},"incompatible_landmark_models_preserved":models,"status":"PASS" if before_count==after_count and before_hash==after_hash and not missing and not mismatches else "FAIL"}
    log_root=raw.root/"migration_logs";log_root.mkdir(exist_ok=True)
    path=log_root/"landmark_abbreviation_migration.json";path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({**result,"log":str(path)},indent=2))
    if result["status"]!="PASS": raise SystemExit(2)

if __name__=="__main__": main()