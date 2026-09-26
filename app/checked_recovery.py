"""Safe one-time recovery of historical Human Checked state.

The recovery is deliberately project-data driven.  A diagnostic plan supplies
candidate image IDs, but every candidate is revalidated against the reference
backup immediately before any write.  No scientific coordinates/crops are
changed: only review metadata is restored for an exactly identical state.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .project_storage import landmark_schema_identity, now, schema_hash

_FINAL_CROP_PROVENANCE={"manual","ai_accepted","ai_corrected"}


class CheckedRecoveryError(RuntimeError):
    pass


def _ro(path):
    path=Path(path).resolve()
    return sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)


def _rows(connection,query,args=()):
    connection.row_factory=sqlite3.Row
    return connection.execute(query,args).fetchall()


def _schema_identity(connection):
    try:rows=_rows(connection,"SELECT abbr FROM landmark_schema ORDER BY landmark_id")
    except sqlite3.Error:return ()
    return tuple(str(row["abbr"] or "").strip() for row in rows)


def _parse_json(value):
    if isinstance(value,(dict,list)):return value
    if value is None:return None
    try:return json.loads(value)
    except (TypeError,json.JSONDecodeError):return None


def _crop_state(connection,image_id):
    connection.row_factory=sqlite3.Row
    row=connection.execute(
        "SELECT crop_json,transform_json,rotation_degrees,provenance,human_verified FROM crops WHERE image_id=?",
        (str(image_id),),
    ).fetchone()
    if not row:return None
    bounds=_parse_json(row["crop_json"]);transform=_parse_json(row["transform_json"])
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=4 or not isinstance(transform,dict):return None
    try:
        semantic=(tuple(float(value) for value in bounds),transform,float(row["rotation_degrees"] or 0.0))
    except (TypeError,ValueError):return None
    return {
        "semantic":semantic,
        "final":str(row["provenance"] or "") in _FINAL_CROP_PROVENANCE and bool(row["human_verified"]),
    }


def _landmark_state(connection,image_id,abbrs):
    connection.row_factory=sqlite3.Row
    columns={str(row["name"]) for row in connection.execute("PRAGMA table_info(landmarks)")}
    if "landmark_abbr" in columns:
        query="SELECT landmark_abbr,x_standardized,y_standardized,state FROM landmarks WHERE image_id=?"
    else:
        # Historical pre-migration databases stored only the persistent numeric
        # landmark_id.  Resolve it through the immutable landmark_schema table,
        # exactly as Project.ensure_schema() does during the normal migration.
        query="""SELECT s.abbr AS landmark_abbr,l.x_standardized,l.y_standardized,l.state
                 FROM landmarks l
                 JOIN landmark_schema s ON s.landmark_id=l.landmark_id
                 WHERE l.image_id=?"""
    rows={
        str(row["landmark_abbr"]):row
        for row in connection.execute(query,(str(image_id),))
    }
    state=[]
    for abbr in abbrs:
        row=rows.get(str(abbr))
        if row is None:return None
        if str(row["state"] or "")=="missing":
            state.append((str(abbr),"missing",None,None));continue
        if row["x_standardized"] is None or row["y_standardized"] is None:return None
        try:x=float(row["x_standardized"]);y=float(row["y_standardized"])
        except (TypeError,ValueError):return None
        state.append((str(abbr),"present",x,y))
    return tuple(state)


def _raw_checked(connection,image_id):
    connection.row_factory=sqlite3.Row
    row=connection.execute("SELECT human_verified FROM image_review WHERE image_id=?",(str(image_id),)).fetchone()
    return bool(row and row["human_verified"])


def _active_nonexcluded(connection,image_id):
    connection.row_factory=sqlite3.Row
    row=connection.execute(
        "SELECT COALESCE(active,1) active,COALESCE(excluded,0) excluded FROM images WHERE image_id=?",
        (str(image_id),),
    ).fetchone()
    return bool(row and row["active"] and not row["excluded"])


def _crop_review_pending(connection,image_id):
    return bool(connection.execute(
        "SELECT 1 FROM image_attributes WHERE image_id=? AND attribute_key='landmark_crop_review_required' AND lower(value)='true'",
        (str(image_id),),
    ).fetchone())


def _pending_machine_review(connection,image_id):
    return bool(connection.execute(
        "SELECT 1 FROM landmarks WHERE image_id=? AND provenance='machine' AND COALESCE(reviewed,0)=0",
        (str(image_id),),
    ).fetchone())


def _state_hash(crop_state,landmark_state):
    payload={"crop":crop_state["semantic"],"landmarks":landmark_state}
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_recovery_plan(project,reference_backup,safe_image_ids):
    """Revalidate every proposed restoration against the live DB and backup."""
    reference_backup=Path(reference_backup).resolve()
    if not reference_backup.is_file():raise CheckedRecoveryError(f"reference backup not found: {reference_backup}")
    current_db=Path(project.path).resolve()
    current_identity=landmark_schema_identity(project.schema)
    safe_ids=tuple(dict.fromkeys(str(value) for value in safe_image_ids))
    if not safe_ids:raise CheckedRecoveryError("recovery plan contains no safe image IDs")
    with _ro(current_db) as current,_ro(reference_backup) as backup:
        backup_identity=_schema_identity(backup)
        if backup_identity!=current_identity:
            raise CheckedRecoveryError("reference backup landmark identities/order do not match the current project schema")
        valid=[];already_checked=[];failures=[]
        for image_id in safe_ids:
            if not _active_nonexcluded(current,image_id) or not _active_nonexcluded(backup,image_id):
                failures.append((image_id,"inactive_or_excluded"));continue
            if not _raw_checked(backup,image_id):
                failures.append((image_id,"not_checked_in_backup"));continue
            current_crop=_crop_state(current,image_id);backup_crop=_crop_state(backup,image_id)
            if not current_crop or not backup_crop or not current_crop["final"] or not backup_crop["final"]:
                failures.append((image_id,"crop_not_final"));continue
            if current_crop["semantic"]!=backup_crop["semantic"]:
                failures.append((image_id,"crop_changed"));continue
            current_landmarks=_landmark_state(current,image_id,current_identity);backup_landmarks=_landmark_state(backup,image_id,current_identity)
            if current_landmarks is None or backup_landmarks is None:
                failures.append((image_id,"landmarks_incomplete"));continue
            if current_landmarks!=backup_landmarks:
                failures.append((image_id,"landmarks_changed"));continue
            if _crop_review_pending(current,image_id):
                failures.append((image_id,"crop_review_pending"));continue
            item={"image_id":image_id,"state_sha256":_state_hash(current_crop,current_landmarks)}
            effectively_checked=_raw_checked(current,image_id) and not _pending_machine_review(current,image_id)
            if effectively_checked:already_checked.append(item)
            else:valid.append(item)
    if failures:
        sample=", ".join(f"{image_id}:{reason}" for image_id,reason in failures[:5])
        raise CheckedRecoveryError(f"{len(failures)} planned image(s) no longer match the proven safe state; no recovery was applied. First differences: {sample}")
    return {
        "reference_backup":str(reference_backup),
        "planned":len(safe_ids),
        "restore":tuple(valid),
        "already_checked":tuple(already_checked),
        "reference_backup_sha256":hashlib.sha256(reference_backup.read_bytes()).hexdigest(),
    }


def _backup_current_database(project):
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory=Path(project.root)/"backups"/f"checked_recovery_{stamp}"
    directory.mkdir(parents=True,exist_ok=False)
    target=directory/"project.sqlite"
    source=sqlite3.connect(Path(project.path).resolve())
    destination=sqlite3.connect(target)
    try:source.backup(destination)
    finally:
        destination.close();source.close()
    return target


def apply_checked_recovery(project,reference_backup,safe_image_ids,*,plan_sha256=None):
    """Atomically restore effective Checked metadata for exactly identical states."""
    validation=validate_recovery_plan(project,reference_backup,safe_image_ids)
    restore=validation["restore"]
    if not restore:
        return {
            **validation,
            "restored":0,
            "backup_path":None,
            "recovery_id":None,
        }
    backup_path=_backup_current_database(project)
    recovery_id="checked-recovery-"+uuid.uuid4().hex
    stamp=now();identity=landmark_schema_identity(project.schema);digest=schema_hash(project.schema_path)
    with project.transaction() as connection:
        for item in restore:
            image_id=item["image_id"]
            ai_rows=project._active_ai_rows(connection,image_id)
            if ai_rows:
                connection.execute(
                    "UPDATE landmarks SET reviewed=1,updated_at=? WHERE image_id=? AND (provenance=? OR model_id IS NOT NULL OR prediction_run_id IS NOT NULL)",
                    (stamp,image_id,"machine"),
                )
                fingerprint=project._ai_review_fingerprint(connection,image_id,schema_identity=identity)
                run_ids=sorted({str(row["prediction_run_id"]) for row in ai_rows if row.get("prediction_run_id")})
                model_ids=sorted({str(row["model_id"]) for row in ai_rows if row.get("model_id")})
                confirmation={
                    "image_id":image_id,
                    "batch_id":recovery_id,
                    "prediction_run_ids":run_ids,
                    "model_ids":model_ids,
                    "schema_sha256":digest,
                    "schema_identity":list(identity),
                    "state_fingerprint":fingerprint,
                    "confirmed_at":stamp,
                    "restored_from_historical_checked_state":True,
                }
                existing=connection.execute(
                    "SELECT payload_json FROM qc WHERE image_id=? AND kind=? ORDER BY qc_id DESC",
                    (image_id,"landmark_ai_review_confirmation"),
                ).fetchall()
                found=False
                for row in existing:
                    try:payload=json.loads(row["payload_json"])
                    except (TypeError,json.JSONDecodeError):continue
                    if payload.get("state_fingerprint")==fingerprint:
                        found=True;break
                if not found:
                    connection.execute(
                        "INSERT INTO qc(image_id,kind,payload_json,created_at) VALUES (?,?,?,?)",
                        (image_id,"landmark_ai_review_confirmation",json.dumps(confirmation,sort_keys=True),stamp),
                    )
            connection.execute(
                "INSERT INTO image_review(image_id,human_verified,updated_at) VALUES (?,?,?) ON CONFLICT(image_id) DO UPDATE SET human_verified=1,updated_at=excluded.updated_at",
                (image_id,1,stamp),
            )
            connection.execute("DELETE FROM annotation_drafts WHERE image_id=?",(image_id,))
            audit={
                "recovery_id":recovery_id,
                "reference_backup_sha256":validation["reference_backup_sha256"],
                "plan_sha256":plan_sha256,
                "state_sha256":item["state_sha256"],
                "reason":"exact semantic Crop + landmark state previously Human Checked",
                "restored_at":stamp,
            }
            connection.execute(
                "INSERT INTO qc(image_id,kind,payload_json,created_at) VALUES (?,?,?,?)",
                (image_id,"checked_history_recovery",json.dumps(audit,sort_keys=True),stamp),
            )
    not_verified=[item["image_id"] for item in restore if not project.annotation_status(item["image_id"]).get("verified")]
    if not_verified:
        raise CheckedRecoveryError(f"recovery committed but {len(not_verified)} image(s) are not effectively Checked; restore database backup {backup_path}")
    return {
        **validation,
        "restored":len(restore),
        "backup_path":str(backup_path),
        "recovery_id":recovery_id,
    }
