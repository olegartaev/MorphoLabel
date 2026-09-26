"""Deterministic registries; external loading errors are diagnostics, not startup errors."""
from __future__ import annotations

from .api import BackendSpec, EXTENSION_API_VERSION, ModuleSpec


class _Registry:
    kind = "extension"
    id_field = ""

    def __init__(self):
        self._items = {}
        self.diagnostics: list[str] = []

    def register(self, spec):
        identifier = getattr(spec, self.id_field)
        if not identifier or not isinstance(identifier, str):
            raise ValueError(f"{self.kind} id must be a nonempty string")
        if identifier in self._items:
            raise ValueError(f"duplicate {self.kind} id: {identifier}")
        if spec.api_version != EXTENSION_API_VERSION:
            self.diagnostics.append(f"{self.kind} {identifier}: incompatible API {spec.api_version}; expected {EXTENSION_API_VERSION}")
            return False
        self._validate(spec)
        self._items[identifier] = spec
        return True

    def _validate(self, spec):
        pass

    def get(self, identifier):
        return self._items.get(identifier)

    def all(self):
        return tuple(sorted(self._items.values(), key=self._sort_key))

    def _sort_key(self, spec):
        return (getattr(spec, self.id_field),)


class ModuleRegistry(_Registry):
    kind = "module"
    id_field = "module_id"

    def _validate(self, spec: ModuleSpec):
        if spec.status not in ("available", "planned", "unavailable"):
            raise ValueError(f"invalid module status: {spec.status}")
        if spec.status == "available" and not callable(spec.factory):
            raise ValueError(f"available module {spec.module_id} needs a factory")

    def _sort_key(self, spec):
        return (spec.order, spec.module_id)

    def available(self):
        return tuple(spec for spec in self.all() if spec.status == "available")

    def planned(self):
        return tuple(spec for spec in self.all() if spec.status == "planned")


class BackendRegistry(_Registry):
    kind = "backend"
    id_field = "backend_id"

    def _validate(self, spec: BackendSpec):
        if not callable(spec.factory):
            raise ValueError(f"backend {spec.backend_id} needs a factory")

    def for_task(self, task):
        return tuple(spec for spec in self.all() if spec.task == task)
