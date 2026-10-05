"""Small, versioned extension boundary for scientific modules and AI backends."""

from .api import EXTENSION_API_VERSION, BackendContext, BackendSpec, ModuleHost, ModuleRuntime, ModuleSpec
from .registry import BackendRegistry, ModuleRegistry
from .api import StructureBackend, StructureBackendContext

__all__ = (
    "EXTENSION_API_VERSION", "BackendContext", "BackendSpec", "ModuleHost",
    "ModuleRuntime", "ModuleSpec", "BackendRegistry", "ModuleRegistry",
    "StructureBackend", "StructureBackendContext",
)
