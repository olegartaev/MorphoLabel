"""User-level non-scientific UI preferences for the durable ProductionShell."""
from __future__ import annotations
import json
import os
from pathlib import Path
from app.gui_crop_debug import log
from app.runtime_paths import app_state_dir

_FILENAME = "ui_preferences.json"

def preference_path() -> Path:
    return app_state_dir() / _FILENAME

def legacy_preference_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home()))
    return root / "SIMM" / _FILENAME

def _read_from(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("preference document must be a JSON object")
    return value

def _read() -> dict:
    current = preference_path()
    legacy = legacy_preference_path()
    for path in (current, legacy):
        try:
            value = _read_from(path)
            if value:
                return value
        except Exception as exc:
            log("GLOBAL", "ui_preference_read", "ERROR", path=str(path), detail=str(exc))
    return {}

def _last_project_value(key: str, event: str) -> Path | None:
    raw = _read().get(str(key))
    if not raw:
        return None
    try:
        path = Path(str(raw)).expanduser().resolve(strict=True)
        if not path.is_dir() or not os.access(path, os.R_OK):
            raise OSError("stored project directory is not readable")
    except Exception as exc:
        log("GLOBAL", event, "ERROR", path=str(raw), detail=str(exc))
        return None
    log("GLOBAL", event, "END", path=str(path), detail="stored project path is readable")
    return path

def last_project() -> Path | None:
    return _last_project_value("last_project","ui_preference_last_project")

def last_xray_project() -> Path | None:
    return _last_project_value("last_xray_project","ui_preference_last_xray_project")

def _remember_project_value(key: str, path: Path | str) -> bool:
    target = preference_path()
    try:
        normalized = Path(path).expanduser().resolve(strict=True)
        if not normalized.is_dir() or not os.access(normalized, os.R_OK):
            raise OSError("project directory is not readable")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _read()
        data[str(key)] = str(normalized)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        log("GLOBAL", "ui_preference_write", "END", path=str(target), detail=f"{key}={normalized}")
        return True
    except Exception as exc:
        log("GLOBAL", "ui_preference_write", "ERROR", path=str(target), detail=str(exc))
        return False

def remember_project(path: Path | str) -> bool:
    return _remember_project_value("last_project",path)

def remember_xray_project(path: Path | str) -> bool:
    return _remember_project_value("last_xray_project",path)
