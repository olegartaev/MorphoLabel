"""Validate recoverable UI state without changing stored scientific records."""
import json
import logging

_MAPPING_KEYS = {
    "crop_active_batch", "landmark_attention_queue", "landmark_ai_workflow",
    "landmark_ai_review", "landmark_suspicious_review", "landmark_training_queue_closed",
    "xray_crop_active_batch", "xray_structure_active_batch", "xray_current_selection",
    "xray_result_review_queue", "landmark_prediction_review_sessions", "landmark_display", "xray_structure_display",
}
_LIST_FIELDS = {"ids", "image_ids", "specimen_ids", "completed_ids", "prepared_ids", "control_image_ids",
                "initial_image_ids", "improvement_image_ids", "improvement_history_ids"}
_MAP_FIELDS = {"proposals", "failure_reasons", "stage_created_at", "review_meta", "payload"}
_INT_FIELDS = {"position", "current_position", "version", "format_version", "pass_no",
               "control_target", "initial_target", "improvement_target"}
_BOOL_FIELDS = {"active", "closed", "full_prediction_done", "complete", "finished", "completion_announced"}

def _mapping(value):
    if not isinstance(value, dict):return False
    for key, field in value.items():
        if key in _LIST_FIELDS and (not isinstance(field, list) or any(not isinstance(item, str) for item in field)):return False
        if key in _MAP_FIELDS and not isinstance(field, dict):return False
        if key == "review_meta" and not all(isinstance(item,dict) for item in field.values()):return False
        if key == "proposals" and not all(
            isinstance(item,dict) or (isinstance(item,list) and len(item)==4 and all(type(number) in (int,float) for number in item))
            for item in field.values()
        ):return False
        if key == "landmark_ids" and (not isinstance(field,list) or not all(type(item) is int for item in field)):return False
        if key in _INT_FIELDS and field is not None and type(field) is not int:return False
        if key in _BOOL_FIELDS and type(field) is not bool:return False
        if key in {"sessions", "items", "issues"} and (not isinstance(field,list) or not all(_mapping(item) for item in field)):return False
        if key == "completed" and (not isinstance(field,list) or not all(isinstance(item,(str,int)) for item in field)):return False
        if key in {"stage", "current_stage", "current_image_id", "current_reason", "unfinished_image_id", "batch_id", "queue_id"} and field is not None and not isinstance(field, str):return False
    return True

def decode_ui_state(key, raw, default=None, logger_name=__name__):
    """Shape checks apply to declared queues and explicitly typed defaults only."""
    try:
        value = json.loads(raw)
        if key in _MAPPING_KEYS or isinstance(default, dict):
            if not _mapping(value):raise ValueError("expected mapping with typed fields")
        elif key.endswith("_saved") and key[:-6] in _MAPPING_KEYS:
            if not isinstance(value, list) or not all(_mapping(item) for item in value):raise ValueError("expected saved queue list")
        elif isinstance(default, (list, bool, str)) and not isinstance(value, type(default)):
            raise ValueError("unexpected UI state type")
        return value
    except (ValueError, TypeError):
        logging.getLogger(logger_name).warning("Ignoring malformed UI state: %s", key)
        return default
