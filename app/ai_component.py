"""Atomic installation and activation of versioned MorphoLabel AI components."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from .io import atomic_json_write
from .runtime_paths import app_state_dir

_COMPONENT_FILE = "component.json"
_ACTIVE_FILE = "active.json"

class AIComponentError(RuntimeError):
    pass

def components_root(*, create=False) -> Path:
    root = app_state_dir() / "components" / "ai"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root

def active_record_path() -> Path:
    return components_root() / _ACTIVE_FILE

def _read_json(path: Path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AIComponentError(f"invalid AI component metadata: {path}") from exc
    if not isinstance(value, dict):
        raise AIComponentError(f"invalid AI component metadata object: {path}")
    return value

def component_manifest(component_dir: Path):
    return _read_json(Path(component_dir) / _COMPONENT_FILE)

def component_runtime(component_dir: Path) -> Path:
    component_dir = Path(component_dir)
    manifest = component_manifest(component_dir)
    return component_dir / str(manifest.get("python_relative_path") or "python.exe")

def component_root_for_runtime(runtime_python: Path) -> Path | None:
    """Return the managed component root containing this runtime, if any."""
    runtime = Path(runtime_python).resolve()
    for candidate in runtime.parents:
        manifest_path = candidate / _COMPONENT_FILE
        if not manifest_path.is_file():
            continue
        try:
            if component_runtime(candidate).resolve() == runtime:
                return candidate
        except (AIComponentError, OSError):
            continue
    return None

def component_runtime_candidates():
    root = components_root()
    if not root.is_dir():
        return []
    ordered = []
    active_path = active_record_path()
    if active_path.is_file():
        try:
            active = _read_json(active_path)
            version = str(active.get("version") or "")
            if version:
                runtime = component_runtime(root / version)
                if runtime.is_file():
                    ordered.append(runtime)
        except AIComponentError:
            pass
    for directory in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            runtime = component_runtime(directory)
        except AIComponentError:
            continue
        if runtime.is_file() and runtime not in ordered:
            ordered.append(runtime)
    return ordered

def _validate_manifest(manifest):
    required = ("component_format", "component_version", "platform", "python_relative_path")
    missing = [key for key in required if not manifest.get(key)]
    if missing:
        raise AIComponentError("AI component manifest is missing: " + ", ".join(missing))
    if int(manifest["component_format"]) != 1:
        raise AIComponentError("unsupported AI component format")
    if str(manifest["platform"]) != "windows-x64":
        raise AIComponentError("unsupported AI component platform")
    version = str(manifest["component_version"])
    if any(part in version for part in ("/", "\\", "..")):
        raise AIComponentError("unsafe AI component version")
    return version

def _validate_tree(component_dir: Path, manifest, *, run_runtime_check=True):
    runtime = component_dir / str(manifest["python_relative_path"])
    config = component_dir / str(manifest.get("bootstrap_config") or "")
    checkpoint = component_dir / str(manifest.get("bootstrap_checkpoint") or "")
    source = component_dir / str(manifest.get("mmpose_source") or "")
    if not runtime.is_file():
        raise AIComponentError("AI component Python runtime is missing")
    if not config.is_file():
        raise AIComponentError("AI component RTMPose bootstrap config is missing")
    if not (source / "tools" / "train.py").is_file():
        raise AIComponentError("AI component MMPose training source is missing")
    expected = str(manifest.get("bootstrap_checkpoint_sha256") or "").lower()
    url = str(manifest.get("bootstrap_checkpoint_url") or "")
    if not expected or len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise AIComponentError("AI component bootstrap checkpoint SHA256 is missing or invalid")
    if not url.startswith("https://download.openmmlab.com/"):
        raise AIComponentError("AI component bootstrap checkpoint URL is missing or untrusted")
    if checkpoint.is_file():
        actual = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        if actual != expected:
            raise AIComponentError("AI component bootstrap checkpoint checksum mismatch")
    if run_runtime_check:
        from .ai_runtime_resolver import validate_ai_runtime
        from .runtime_paths import resource_path
        validate_ai_runtime(runtime, resource_path("ai_runtime", "rtmpose_runner.py"))
    return runtime

def activate_component(version: str, *, run_runtime_check=True):
    root = components_root()
    directory = root / str(version)
    manifest = component_manifest(directory)
    actual = _validate_manifest(manifest)
    if actual != str(version):
        raise AIComponentError("AI component version directory does not match manifest")
    runtime = _validate_tree(directory, manifest, run_runtime_check=run_runtime_check)
    root.mkdir(parents=True, exist_ok=True)
    atomic_json_write(active_record_path(), {"version": actual})
    return runtime

def _safe_extract(archive: zipfile.ZipFile, destination: Path):
    destination = destination.resolve()
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        raw_parts = tuple(part for part in name.split("/") if part not in ("", "."))
        # Windows ZIPs created from a directory commonly contain a harmless
        # root entry named "./". It has no filename to extract and must simply
        # be ignored rather than handed to ZipFile.extractall().
        if not raw_parts:
            if name.strip("/") in ("", "."):
                continue
            raise AIComponentError(f"unsafe AI component archive path: {info.filename}")
        if name.startswith("/") or any(part == ".." for part in raw_parts):
            raise AIComponentError(f"unsafe AI component archive path: {info.filename}")
        first = raw_parts[0]
        if len(first) >= 2 and first[1] == ":":
            raise AIComponentError(f"unsafe AI component archive path: {info.filename}")
        target = destination.joinpath(*raw_parts).resolve()
        try:
            target.relative_to(destination)
        except ValueError as exc:
            raise AIComponentError(f"unsafe AI component archive path: {info.filename}") from exc
        if info.is_dir() or name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)

def install_component_archive(source, *, expected_sha256=None, activate=True, run_runtime_check=True):
    source = Path(source)
    if not source.is_file():
        raise AIComponentError(f"AI component archive is unavailable: {source}")
    if expected_sha256:
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual.lower() != str(expected_sha256).lower():
            raise AIComponentError("AI component archive checksum mismatch")
    root = components_root(create=True)
    staging = root / ".installing"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        try:
            with zipfile.ZipFile(source) as archive:
                _safe_extract(archive, staging)
        except zipfile.BadZipFile as exc:
            raise AIComponentError("invalid AI component archive") from exc
        manifest = component_manifest(staging)
        version = _validate_manifest(manifest)
        _validate_tree(staging, manifest, run_runtime_check=run_runtime_check)
        destination = root / version
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(staging, destination)
        if activate:
            return activate_component(version, run_runtime_check=run_runtime_check)
        return component_runtime(destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
