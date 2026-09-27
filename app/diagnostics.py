"""Privacy-conscious support diagnostics for MorphoLabel."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .runtime_paths import app_state_dir, is_frozen, source_root
from .version import __version__


_EVENT = re.compile(
    r"^(?P<time>\S+) thread=(?P<thread>\S+) image_id=(?P<image>\S*) "
    r"op=(?P<op>\S+) state=(?P<state>\S+) elapsed_s=(?P<elapsed>[0-9.]+)"
)


def diagnostics_dir(*, create=False) -> Path:
    path = app_state_dir(create=create) / "diagnostics"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _token(value) -> str | None:
    if value in (None, ""):
        return None
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]


def _queue_summary(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key in {"stage", "batch_type", "position", "current_position", "finished", "completion_announced"}:
            result[key] = item
        elif key in {"current_image_id"}:
            result[key] = _token(item)
        elif key == "ids" or key.endswith("_ids"):
            values = list(item or ()) if isinstance(item, (list, tuple, set, frozenset)) else []
            result[key] = {"count": len(values), "members": [_token(entry) for entry in values]}
    return result


def _model_summary(project, kind):
    try:
        model = project.active_model_readonly(kind) or {}
    except Exception:
        return None
    if not model:
        return None
    return {
        "model": _token(model.get("model_id")),
        "dataset": _token(model.get("dataset_id")),
        "parent": _token(model.get("parent_model_id")),
        "created_at": model.get("created_at"),
    }


def _project_summary(project):
    if project is None:
        return None
    try:
        rows = list(project.catalog_rows())
    except Exception:
        rows = []
    try:
        config = project.config
    except Exception:
        config = {}
    result = {
        "project": _token(getattr(project, "root", None)),
        "format_version": config.get("format_version"),
        "schema_sha256": config.get("schema_sha256"),
        "images": len(rows),
        "excluded": sum(bool(row.get("excluded")) for row in rows),
        "active_models": {
            "crop": _model_summary(project, "crop"),
            "landmark": _model_summary(project, "landmark"),
        },
    }
    for name, method in (
        ("crop_counts", "crop_section_counts"),
        ("landmark_counts", "landmark_counts"),
    ):
        try:
            result[name] = getattr(project, method)()
        except Exception:
            result[name] = None
    try:
        result["crop_active_batch"] = _queue_summary(project.get_ui_state("crop_active_batch", {}) or {})
    except Exception:
        result["crop_active_batch"] = {}
    try:
        from .landmark_ai_workflow import STATE_KEY
        result["landmark_workflow"] = _queue_summary(project.get_ui_state(STATE_KEY, {}) or {})
    except Exception:
        result["landmark_workflow"] = {}
    return result


def collect_summary(shell=None):
    context = getattr(shell, "context", None)
    project = getattr(context, "project", None)
    current = None
    if context is not None:
        try:
            current = context.current()
        except Exception:
            current = None
    registry = getattr(shell, "module_registry", None)
    module_diagnostic_count = len(getattr(registry, "diagnostics", ())) if registry is not None else 0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "morpholabel_version": __version__,
        "frozen": is_frozen(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "module": getattr(shell, "module_key", None),
        "section": getattr(context, "section", None),
        "current_image": _token((current or {}).get("image_id")),
        "project": _project_summary(project),
        "module_diagnostic_count": module_diagnostic_count,
    }


def _known_replacements(shell=None):
    values = []
    for label, value in (
        ("<USER_HOME>", Path.home()),
        ("<APP_STATE>", app_state_dir()),
        ("<EXECUTABLE_DIR>", Path(sys.executable).resolve().parent),
        ("<CODE_ROOT>", source_root()),
    ):
        values.append((str(value), label))
    project = getattr(getattr(shell, "context", None), "project", None)
    if project is not None:
        for label, value in (
            ("<PROJECT_ROOT>", getattr(project, "root", None)),
            ("<SOURCE_ROOT>", getattr(project, "source_root", None)),
        ):
            if value:
                values.append((str(value), label))
    return sorted(((raw, label) for raw, label in values if raw), key=lambda pair: len(pair[0]), reverse=True)


def _sanitize_text(text, shell=None):
    result = str(text)
    for raw, label in _known_replacements(shell):
        result = re.sub(re.escape(raw), label, result, flags=re.IGNORECASE)
    return result


def record_exception(exc_type, exc_value, tb, *, shell=None) -> Path:
    root = diagnostics_dir(create=True)
    target = root / "latest_exception.txt"
    trace = "".join(traceback.format_exception(exc_type, exc_value, tb))
    target.write_text(_sanitize_text(trace, shell), encoding="utf-8")
    meta = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "error_type": getattr(exc_type, "__name__", str(exc_type)),
        "message": _sanitize_text(str(exc_value), shell),
    }
    (root / "latest_exception.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _safe_event_tail(path: Path, *, max_lines=1200):
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    except OSError:
        return ""
    safe = []
    for line in lines:
        match = _EVENT.match(line)
        if not match:
            continue
        data = match.groupdict()
        image = data["image"]
        image = image if image == "GLOBAL" else (_token(image) or "-")
        safe.append(
            f'{data["time"]} thread={data["thread"]} image={image} '
            f'op={data["op"]} state={data["state"]} elapsed_s={data["elapsed"]}'
        )
    return "\n".join(safe) + ("\n" if safe else "")


def create_diagnostic_bundle(*, shell=None) -> Path:
    root = diagnostics_dir(create=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = root / f"MorphoLabel-diagnostic-{stamp}.zip"
    summary = collect_summary(shell)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("summary.json", json.dumps(summary, indent=2, sort_keys=True))
        latest = root / "latest_exception.txt"
        if latest.is_file():
            archive.writestr("latest_exception.txt", _sanitize_text(latest.read_text(encoding="utf-8", errors="replace"), shell))
        latest_meta = root / "latest_exception.json"
        if latest_meta.is_file():
            archive.write(latest_meta, "latest_exception.json")
        hardware = app_state_dir() / "hardware_profile.json"
        if hardware.is_file():
            try:
                payload = json.loads(hardware.read_text(encoding="utf-8"))
                archive.writestr("hardware_profile.json", json.dumps(payload, indent=2, sort_keys=True))
            except (OSError, json.JSONDecodeError):
                pass
        try:
            from .gui_crop_debug import LOG
            events = _safe_event_tail(Path(LOG))
        except Exception:
            events = ""
        if events:
            archive.writestr("recent_events.log", events)
        archive.writestr(
            "README.txt",
            "This MorphoLabel support bundle intentionally excludes photographs, SQLite databases, "
            "raw project paths and filenames. Image/model identifiers are hashed.\n",
        )
    return target
