"""Read-only current Project readiness summary for landmark-AI training."""
from __future__ import annotations

import math

from .landmark_dataset import v2_human_final_eligible_image_ids
from .landmark_ai_workflow import control_set_summary
from .project_storage import schema_hash

_HUMAN = {"manual", "corrected", "corrected_by_human", "reviewed_by_human", "missing"}


def _resolved(row):
    if row.get("state") == "missing":
        return True
    return all(
        isinstance(row.get(key), (int, float)) and math.isfinite(row[key])
        for key in ("x_standardized", "y_standardized")
    )


def _ai_assisted(row):
    return row.get("provenance") == "machine" or any(
        row.get(key) is not None
        for key in ("model_id", "predicted_x", "predicted_y", "prediction_run_id")
    )


def training_status(project):
    """Return a read-only readiness snapshot from current Project SQLite metadata."""
    required = {int(item["id"]) for item in project.schema}
    with project.transaction() as connection:
        catalog = [
            dict(row)
            for row in connection.execute(
                "SELECT image_id, excluded FROM images WHERE COALESCE(active, 1)=1"
            )
        ]
        points = [dict(row) for row in connection.execute("SELECT * FROM landmarks")]
        reviews = {
            row["image_id"]: bool(row["human_verified"])
            for row in connection.execute("SELECT image_id, human_verified FROM image_review")
        }
        model = connection.execute(
            "SELECT model_id, created_at FROM models WHERE kind='landmark' AND active=1"
        ).fetchone()
    by_image = {}
    for row in points:
        by_image.setdefault(row["image_id"], {})[int(row["landmark_id"])] = row
    human_verified = fully_manual = ai_verified = ai_unreviewed = 0
    for image in catalog:
        if image.get("excluded"):
            continue
        image_id = image["image_id"]
        rows = by_image.get(image_id, {})
        has_landmarks = bool(rows)
        verified = bool(reviews.get(image_id))
        required_rows = [rows.get(identifier) for identifier in required]
        resolved = bool(required) and all(row is not None and _resolved(row) for row in required_rows)
        manual = resolved and all(row.get("provenance") in _HUMAN for row in required_rows)
        assisted = any(_ai_assisted(row) for row in rows.values())
        if verified and has_landmarks:
            human_verified += 1
        if manual:
            fully_manual += 1
        if assisted and verified:
            ai_verified += 1
        if assisted and not verified:
            ai_unreviewed += 1
    control = control_set_summary(project)
    return {
        "control_set_checked": control["verified"],
        "control_set_total": control["total"],
        "human_verified_landmark_images": human_verified,
        "fully_manual_images": fully_manual,
        "ai_assisted_human_verified_images": ai_verified,
        "ai_predicted_not_reviewed_images": ai_unreviewed,
        "training_eligible_landmark_images": len(v2_human_final_eligible_image_ids(project)),
        "active_landmark_model_id": model["model_id"] if model else None,
        "last_training_at": model["created_at"] if model else None,
        "schema_sha256": schema_hash(project.schema_path),
    }


def format_training_status(status):
    model = status["active_landmark_model_id"] or "None"
    trained = status["last_training_at"] or "Unavailable"
    return "\n".join((
        f"Control Set: {status['control_set_checked']} / {status['control_set_total']}",
        f"AI predicted but not reviewed images: {status['ai_predicted_not_reviewed_images']}",
        f"Training-eligible landmark images: {status['training_eligible_landmark_images']}",
        f"Active landmark model: {model}",
        f"Last training: {trained}",
        f"Current schema SHA-256: {status['schema_sha256']}",
    ))
