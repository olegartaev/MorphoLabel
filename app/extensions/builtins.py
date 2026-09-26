"""Register built-ins through the same public API as installed extensions."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .api import BackendContext, BackendSpec, EXTENSION_API_VERSION, ModuleSpec
from .discovery import discover_backends, discover_modules
from .registry import BackendRegistry, ModuleRegistry
from app.modules.landmarks import LandmarksRuntime


def module_registry():
    registry = ModuleRegistry()
    for spec in (
        ModuleSpec("landmarks", "Landmarks & measurements", "Crop → landmark annotation and AI review → measurements → export", "1", EXTENSION_API_VERSION, 10, "available", LandmarksRuntime, "builtin"),
        ModuleSpec("xray_counts", "X-ray counts", "X-ray counts workflow", "1", EXTENSION_API_VERSION, 20, "planned", None, "builtin"),
        ModuleSpec("scales_meristics", "Scales & meristics", "Scales and meristics workflow", "1", EXTENSION_API_VERSION, 30, "planned", None, "builtin"),
    ):
        registry.register(spec)
    return discover_modules(registry)


def _rtmpose_provider(context: BackendContext):
    from app.rtmpose_backend import RTMPoseBackend, RTMPoseModelSpec
    from app.project_storage import schema_hash

    artifact = context.artifact
    info = context.metadata
    checkpoint = artifact / "best_engineering_validation.pth"
    if not checkpoint.is_file():
        checkpoint = Path(info.get("result", {}).get("checkpoint_path", ""))
    config = artifact / "config.py"
    if not checkpoint.is_file() or not config.is_file():
        raise ValueError("landmark model checkpoint or config is unavailable")
    performance = context.performance
    spec = RTMPoseModelSpec(
        str(context.model["model_id"]), schema_hash(context.project.schema_path), config,
        checkpoint, context.input_size, performance["device"], int(performance["batch_size"]),
    )
    return RTMPoseBackend(spec)


@lru_cache(maxsize=1)
def backend_registry():
    registry = BackendRegistry()
    registry.register(BackendSpec("rtmpose", "RTMPose", "landmark", "1", EXTENSION_API_VERSION, _rtmpose_provider, "builtin"))
    return discover_backends(registry)
