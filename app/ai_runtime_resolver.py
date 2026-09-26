"""Portable resolution of the isolated SIMM AI runtime."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _configured(project=None):
    values = []
    env = os.environ.get("SIMM_AI_RUNTIME")
    if env:
        values.append(env)
    if project is not None:
        try:
            config = project.config
            for key in ("ai_runtime_path", "runtime_python", "ai_runtime"):
                if config.get(key):
                    values.append(config[key])
        except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return values


def _artifact_runtimes(project=None):
    if project is None:
        return []
    roots = []
    try:
        data_root = Path(project.data_root)
        roots.extend((data_root / "ai" / "models", data_root / "models" / "landmark"))
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


def _discovered(repo_root: Path):
    values = []
    # Keep discovery generic: verified runtimes in sibling SIMM workspaces are
    # candidates, without making any one legacy path mandatory.
    for parent in (repo_root.parent, Path.cwd().parent):
        try:
            values.extend(str(path) for path in parent.glob("*/ai_runtime/Scripts/python.exe"))
        except OSError:
            continue
    return values


def resolve_ai_runtime(*, project=None, explicit=None, configured=None, runner_path=None):
    """Return ``(python_executable, current_runner)`` using portable priority."""
    root = _repo_root()
    runner = Path(runner_path) if runner_path is not None else root / "ai_runtime" / "rtmpose_runner.py"
    values = []
    if explicit is not None:
        values.append(explicit)
    values.extend(_configured(project))
    if configured is not None:
        values.append(configured)
    values.append(root / "ai_runtime" / "Scripts" / "python.exe")
    values.extend(_artifact_runtimes(project))
    values.extend(_discovered(root))
    seen = set()
    for value in values:
        path = Path(value).expanduser()
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path, runner
    # Preserve a controlled missing-runtime error at the call site.
    return Path(values[0]) if values else root / "ai_runtime" / "Scripts" / "python.exe", runner


def validate_ai_runtime(runtime_python, runner_path, *, require_cuda=False, timeout=15):
    """Execute the runner info operation and return its JSON capability record."""
    runtime_python, runner_path = Path(runtime_python), Path(runner_path)
    if not runtime_python.is_file() or not runner_path.is_file():
        raise RuntimeError(f"AI runtime files are unavailable: {runtime_python}, {runner_path}")
    result = subprocess.run([str(runtime_python), str(runner_path), "info"], input="{}", text=True,
                            capture_output=True, check=False, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"AI runtime info failed (return code {result.returncode}): {result.stderr}")
    try:
        info = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
    except (ValueError, StopIteration) as exc:
        raise RuntimeError("AI runtime info returned invalid JSON") from exc
    if require_cuda and not info.get("cuda_available"):
        raise RuntimeError("AI runtime does not report CUDA availability")
    return info
