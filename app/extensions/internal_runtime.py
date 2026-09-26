"""Narrow adapter for built-ins that reuse the original core workspace."""
from __future__ import annotations

from app.modules.landmarks import LandmarksRuntime


def create_internal_runtime(spec, shell):
    """Construct a built-in runtime while keeping private shell callbacks internal."""
    if spec.source == "builtin" and spec.module_id == "landmarks":
        runtime = spec.factory()
        if not isinstance(runtime, LandmarksRuntime):
            raise TypeError("built-in landmarks factory did not return LandmarksRuntime")
        return runtime._bind_core(shell._render_landmarks_workspace, shell._open_landmarks_workspace)
    return None
