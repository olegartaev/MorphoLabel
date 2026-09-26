"""Public contracts for installed MorphoLabel extensions (API version 1)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from tkinter import Misc
    from app.ai import LandmarkBackend
    from app.project_storage import Project

EXTENSION_API_VERSION = 1
ModuleStatus = Literal["available", "planned", "unavailable"]


@dataclass(frozen=True)
class ModuleHost:
    """Documented host surface; the container is empty when render is called."""

    container: Misc
    project: Project | None
    show_module_hub: Callable[[], None]
    _render_core: Callable[[], None] | None = None
    _open_core: Callable[[], None] | None = None


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
    factory: Callable[[BackendContext], LandmarkBackend]
    source: str
