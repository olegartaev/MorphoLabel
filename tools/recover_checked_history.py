from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.checked_recovery import CheckedRecoveryError, apply_checked_recovery, validate_recovery_plan
from app.project_storage import Project


def main():
    parser=argparse.ArgumentParser(description="Safely restore historical Human Checked state from a proven diagnostic plan.")
    parser.add_argument("--project",required=True)
    parser.add_argument("--plan",required=True)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()

    project=Project(Path(args.project))
    plan_path=Path(args.plan)
    plan=json.loads(plan_path.read_text(encoding="utf-8"))
    planned_project=plan.get("current_project_path")
    if planned_project and Path(planned_project).resolve()!=project.root.resolve():
        raise CheckedRecoveryError(f"plan belongs to a different project: {planned_project}")
    backup=plan.get("reference_backup_path")
    safe_ids=plan.get("safe_restore_image_ids") or []
    if not backup:raise CheckedRecoveryError("plan has no reference_backup_path")
    plan_sha=hashlib.sha256(plan_path.read_bytes()).hexdigest()

    if args.apply:
        result=apply_checked_recovery(project,backup,safe_ids,plan_sha256=plan_sha)
        print("MODE: APPLY")
        print(f"PLANNED: {result['planned']}")
        print(f"RESTORED: {result['restored']}")
        print(f"ALREADY CHECKED: {len(result['already_checked'])}")
        print(f"BACKUP: {result['backup_path']}")
        print(f"RECOVERY ID: {result['recovery_id']}")
        effective=sum(bool(row.get("human_verified")) for row in project.catalog_rows())
        print(f"EFFECTIVE CHECKED NOW: {effective}")
    else:
        result=validate_recovery_plan(project,backup,safe_ids)
        print("MODE: DRY RUN")
        print(f"PLANNED: {result['planned']}")
        print(f"SAFE TO RESTORE NOW: {len(result['restore'])}")
        print(f"ALREADY CHECKED: {len(result['already_checked'])}")
        print("NO PROJECT DATA CHANGED")


if __name__=="__main__":
    main()
