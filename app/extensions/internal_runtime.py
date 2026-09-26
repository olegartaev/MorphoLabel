"""Narrow adapter for built-ins that reuse the original core workspace."""
from __future__ import annotations

from app.modules.landmarks import LandmarksRuntime


def create_internal_runtime(spec, shell):
    """Construct a built-in runtime with private shell callbacks kept internal."""
    if spec.source == "builtin" and spec.module_id == "landmarks":
        return LandmarksRuntime(shell._render_landmarks_workspace, shell._open_landmarks_workspace)
    return None
