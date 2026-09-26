"""Persistent finite review of suspicious landmark placements."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

_STATE_KEY = "landmark_suspicious_review"
_FORMAT_VERSION = 2
_COMPLEX_QC_SOURCE = "Complex QC"


def _normalize_issue(item):
    ids = item.get("landmark_ids") or ()
    if not ids:
        ids = (item.get("landmark_id"), item.get("other_landmark_id"), item.get("first_landmark_id"), item.get("second_landmark_id"))
    landmark_ids = tuple(sorted({int(value) for value in ids if value is not None}))
    return {
        "image_id": str(item["image_id"]),
        "kind": str(item.get("kind") or "warning"),
        "message": str(item.get("message") or "Check landmark placement"),
        "landmark_ids": list(landmark_ids),
        "payload": dict(item),
    }


def start(project, issues, *, source="landmark_batch"):
    normalized = [_normalize_issue(item) for item in issues if item.get("image_id")]
    state = {
        "format_version": _FORMAT_VERSION,
        "generation_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": bool(normalized),
        "source": str(source),
        "issues": normalized,
        "position": 0,
        "completed": [],
    }
    project.set_ui_state(_STATE_KEY, state)
    return state


def state(project):
    value = project.get_ui_state(_STATE_KEY, {}) or {}
    return value if isinstance(value, dict) else {}


def active(project):
    value = state(project)
    # Old Complex-QC queues predate generation metadata and may survive across
    # code/algorithm changes. Never resume them implicitly; a fresh Complex QC
    # scan will replace the persisted state when Review all is pressed.
    if value.get("source") == _COMPLEX_QC_SOURCE and int(value.get("format_version") or 0) != _FORMAT_VERSION:
        return None
    issues = list(value.get("issues") or ())
    position = int(value.get("position") or 0)
    if not value.get("active") or not issues or not (0 <= position < len(issues)):
        return None
    return value


def current(project):
    value = active(project)
    if not value:
        return None
    return dict(value["issues"][int(value["position"])])


def summary(project):
    value = active(project)
    if not value:
        return None
    total = len(value["issues"])
    position = int(value["position"]) + 1
    return {
        "position": position,
        "total": total,
        "remaining": max(0, total - position + 1),
        "image_id": value["issues"][position - 1]["image_id"],
        "source": value.get("source"),
    }


def move(project, step):
    value = active(project)
    if not value:
        return None, False
    issues = list(value["issues"])
    position = int(value["position"])
    target = position + int(step)
    if target < 0:
        target = 0
    if target >= len(issues):
        value["active"] = False
        value["position"] = len(issues) - 1
        project.set_ui_state(_STATE_KEY, value)
        return value, True
    value["position"] = target
    project.set_ui_state(_STATE_KEY, value)
    return value, False


def complete_current(project):
    value = active(project)
    if not value:
        return None, False
    position = int(value["position"])
    completed = set(int(v) for v in value.get("completed") or ())
    completed.add(position)
    value["completed"] = sorted(completed)
    project.set_ui_state(_STATE_KEY, value)
    return move(project, 1)


def remove_image(project,image_id):
    """Remove one image from a persisted suspicious/Complex-QC queue.

    Exclusion is workflow membership, not a review decision: the image is
    dropped without being marked completed or accepted.  If it was current,
    the queue advances to the next surviving item at the same position.
    """
    value=state(project)
    issues=list(value.get("issues") or ())
    if not issues:
        return value,None
    image_id=str(image_id)
    old_position=max(0,min(int(value.get("position") or 0),len(issues)-1))
    completed={int(v) for v in value.get("completed") or ()}
    kept=[];new_completed=[];new_position=0
    for old_index,issue in enumerate(issues):
        if str(issue.get("image_id"))==image_id:
            continue
        new_index=len(kept)
        kept.append(issue)
        if old_index in completed:new_completed.append(new_index)
        if old_index<old_position:new_position+=1
    if not kept:
        value.update({"active":False,"issues":[],"position":0,"completed":[]})
        project.set_ui_state(_STATE_KEY,value)
        return value,None
    new_position=min(new_position,len(kept)-1)
    value.update({"issues":kept,"position":new_position,"completed":new_completed,"active":True})
    project.set_ui_state(_STATE_KEY,value)
    return value,str(kept[new_position]["image_id"])


def clear(project):
    project.set_ui_state(_STATE_KEY, {"active": False, "issues": [], "position": 0, "completed": []})
