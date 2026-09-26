"""Resolve MorphoLabel's isolated AI runtime without scanning unrelated user directories."""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from .runtime_paths import app_state_dir, resource_path, source_root

def _configured(project=None):
    values = []
    current = os.environ.get("MORPHOLABEL_AI_RUNTIME")
    if current:
        values.append(current)
    if project is not None:
        try:
            config = project.config
            for key in ("ai_runtime_path", "runtime_python", "ai_runtime"):
                if config.get(key):
                    values.append(config[key])
        except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    legacy = os.environ.get("SIMM_AI_RUNTIME")
    if legacy:
        values.append(legacy)
    return values

def _artifact_runtimes(project=None):
    if project is None:
        return []
    try:
        data_root = Path(project.data_root)
        roots = (data_root / "ai" / "models", data_root / "models" / "landmark")
    except (AttributeError, TypeError):
        return []
    values = []
    for root in roots:
        if not root.is_dir():
            continue
        for model_json in root.glob("*/model.json"):
            try:
                meta = json.loads(model_json.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            runtime = meta.get("runtime_python") or meta.get("result", {}).get("runtime_python")
            if runtime:
                values.append(runtime)
    return values

def installed_component_runtimes():
    root = app_state_dir() / "components" / "ai"
    if not root.is_dir():
        return []
    return [folder / "Scripts" / "python.exe" for folder in sorted(root.iterdir(), key=lambda p: p.name, reverse=True) if folder.is_dir()]

def resolve_ai_runtime(*, project=None, explicit=None, configured=None, runner_path=None):
    runner = Path(runner_path) if runner_path is not None else resource_path("ai_runtime", "rtmpose_runner.py")
    values = []
    if explicit is not None:
        values.append(explicit)
    values.extend(_configured(project))
    if configured is not None:
        values.append(configured)
    values.extend(installed_component_runtimes())
    values.extend(_artifact_runtimes(project))
    values.append(source_root() / "ai_runtime" / "Scripts" / "python.exe")
    seen = set()
    for value in values:
        path = Path(value).expanduser()
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path, runner
    fallback = values[0] if values else app_state_dir() / "components" / "ai" / "missing" / "Scripts" / "python.exe"
    return Path(fallback), runner

def validate_ai_runtime(runtime_python, runner_path, *, require_cuda=False, timeout=15):
    runtime_python, runner_path = Path(runtime_python), Path(runner_path)
    if not runtime_python.is_file() or not runner_path.is_file():
        raise RuntimeError(f"AI runtime files are unavailable: {runtime_python}, {runner_path}")
    result = subprocess.run([str(runtime_python), str(runner_path), "info"], input="{}", text=True, capture_output=True, check=False, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"AI runtime info failed (return code {result.returncode}): {result.stderr}")
    try:
        info = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
    except (ValueError, StopIteration) as exc:
        raise RuntimeError("AI runtime info returned invalid JSON") from exc
    if require_cuda and not info.get("cuda_available"):
        raise RuntimeError("AI runtime does not report CUDA availability")
    return info
