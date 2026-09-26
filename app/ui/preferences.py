"""User-level non-scientific UI preferences for the durable ProductionShell."""
from __future__ import annotations
import json
import os
from pathlib import Path
from app.gui_crop_debug import log

_PATH = Path(os.environ.get("APPDATA", Path.home())) / "SIMM" / "ui_preferences.json"

def _read() -> dict:
    try:
        if not _PATH.is_file():
            return {}
        value = json.loads(_PATH.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("preference document must be a JSON object")
        return value
    except Exception as exc:
        log("GLOBAL", "ui_preference_read", "ERROR", path=str(_PATH), detail=str(exc))
        return {}

def last_project() -> Path | None:
    raw = _read().get("last_project")
    if not raw:
        return None
    try:
        path = Path(str(raw)).expanduser().resolve(strict=True)
        if not path.is_dir() or not os.access(path, os.R_OK):
            raise OSError("stored project directory is not readable")
    except Exception as exc:
        log("GLOBAL", "ui_preference_last_project", "ERROR", path=str(raw), detail=str(exc))
        return None
    log("GLOBAL", "ui_preference_last_project", "END", path=str(path), detail="stored project path is readable")
    return path

def remember_project(path: Path | str) -> bool:
    try:
        normalized = Path(path).expanduser().resolve(strict=True)
        if not normalized.is_dir() or not os.access(normalized, os.R_OK):
            raise OSError("project directory is not readable")
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        data = _read()
        data["last_project"] = str(normalized)
        temporary = _PATH.with_suffix(_PATH.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, _PATH)
        log("GLOBAL", "ui_preference_write", "END", path=str(_PATH), detail=f"last_project={normalized}")
        return True
    except Exception as exc:
        log("GLOBAL", "ui_preference_write", "ERROR", path=str(_PATH), detail=str(exc))
        return False