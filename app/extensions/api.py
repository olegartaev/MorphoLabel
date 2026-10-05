"""Public contracts for installed MorphoLabel extensions (API version 1)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from tkinter import Misc
    from app.project_storage import Project

EXTENSION_API_VERSION = 1
ModuleStatus = Literal["available", "planned", "unavailable"]


@dataclass(frozen=True)
class ModuleHost:
    """Generic application services and opaque, module-owned session state.

    The host retains the state dictionary across runtime lifecycles but never
    interprets its contents. Modules define their own project type and actions.
    """

    container: Misc
    state: dict[str, object]
    show_module_hub: Callable[[], None]
    build_standard_menu: Callable[["Misc"], object] | None = None
    ui_icon: Callable[..., object] | None = None
    control_button: Callable[..., object] | None = None
    run_background_task: Callable[..., object] | None = None
    tooltip: object | None = None


class ModuleRuntime(Protocol):
    def render(self, host: ModuleHost) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    display_name: str
    description: str
    version: str
    api_version: int
    order: int
    status: ModuleStatus
    factory: Callable[[], ModuleRuntime] | None
    source: str
    recent_project: Callable[[], Path | None] | None = None


@dataclass(frozen=True)
class BackendContext:
    """Inputs supplied by core when opening an existing landmark model package."""

    project: Project
    model: dict
    artifact: Path
    metadata: dict
    input_size: tuple[int, int]
    performance: dict


@dataclass(frozen=True)
class BackendSpec:
    backend_id: str
    display_name: str
    task: str
    version: str
    api_version: int
    factory: Callable[..., object]
    source: str


@dataclass(frozen=True)
class StructureBackendContext:
    """Application progress only; providers never receive scientific storage."""

    progress: Callable[..., object] | None = None


@runtime_checkable
class StructureBackend(Protocol):
    """Compute from prepared artifacts; the X-ray module saves scientific truth.

    train returns checkpoint/metadata paths and metrics. predict_many returns
    one result per input image, with structure_id and normalized x/y/score points.
    Payloads contain prepared manifest/images, model artifacts and execution
    settings, never a project/database. Portable artifacts keep model.pth and
    model.json envelope names; their implementation is provider-owned.
    """

    def train(self, payload: dict, timeout: int) -> dict: ...
    def predict_many(self, payload: dict, timeout: int) -> dict: ...
