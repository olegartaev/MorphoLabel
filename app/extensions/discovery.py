"""Load only explicitly installed Python entry points, once per registry."""
from __future__ import annotations

from importlib.metadata import entry_points
from threading import Thread

from .api import BackendSpec, ModuleSpec

LOAD_TIMEOUT_SECONDS = 5


def discover(registry, group: str, expected_type):
    try:
        candidates = entry_points().select(group=group)
    except Exception as exc:
        registry.diagnostics.append(f"{group}: enumeration failed: {type(exc).__name__}: {exc}")
        return registry
    for entry in sorted(candidates, key=lambda item: (item.name, item.value)):
        result = []

        def load(entry=entry, result=result):
            try:
                provider = entry.load()
                spec = provider() if callable(provider) and not isinstance(provider, expected_type) else provider
                result.append((spec, None))
            except Exception as exc:
                result.append((None, exc))

        worker = Thread(target=load, daemon=True, name=f"morpholabel-extension-{entry.name}")
        worker.start()
        worker.join(LOAD_TIMEOUT_SECONDS)
        if worker.is_alive():
            registry.diagnostics.append(f"{group}:{entry.name}: load exceeded {LOAD_TIMEOUT_SECONDS}s; extension disabled")
            continue
        try:
            spec, error = result[0]
            if error is not None:
                raise error
            if not isinstance(spec, expected_type):
                raise TypeError(f"provider must return {expected_type.__name__}")
            registry.register(spec)
        except Exception as exc:
            registry.diagnostics.append(f"{group}:{entry.name}: {type(exc).__name__}: {exc}")
    return registry


def discover_modules(registry):
    return discover(registry, "morpholabel.modules", ModuleSpec)


def discover_backends(registry):
    return discover(registry, "morpholabel.ai_backends", BackendSpec)
