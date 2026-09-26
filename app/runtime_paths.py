"""Single source of truth for source, frozen-resource and per-user application paths."""
from __future__ import annotations
import os
import sys
from pathlib import Path
APP_DIRNAME = "MorphoLabel"
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
def source_root() -> Path:
    return Path(__file__).resolve().parents[1]
def resource_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return source_root()
def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)
def local_app_data_root() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"
def app_state_dir(*, create: bool = False) -> Path:
    path = local_app_data_root() / APP_DIRNAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
