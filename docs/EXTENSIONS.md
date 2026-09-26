# Extension API v1

MorphoLabel has two small extension points. Scientific modules add a workspace to
the Module Hub. AI backends supply inference implementations for existing model
packages. The core `Project`, annotations, crop provenance, dataset snapshots,
model lineage, QC, measurements and exports remain authoritative.

Only installed Python entry points are discovered. MorphoLabel does not scan
arbitrary source folders or install extension dependencies. Discovery runs when
the module registry is built at shell startup; the backend registry is built on
first use and cached. An entry point that fails to load is recorded in
`registry.diagnostics` and does not prevent other extensions from loading.
Extensions with `api_version != 1` are disabled. Duplicate IDs are rejected.
Providers have five seconds to load their metadata; a slower provider is
disabled for that registry instance and reported in diagnostics.

## Scientific modules

An entry point in `morpholabel.modules` returns an immutable `ModuleSpec`.
`status` is `available`, `planned`, or `unavailable`. Available modules supply
a zero-argument `factory` returning an object with `render(host)` and `close()`.
The public host exposes `container` (an empty Tk parent), `project` (the current
core project or `None`), `show_module_hub()`, `open_project(path=None)`, and
`new_project()`. The open/new actions use MorphoLabel's normal project dialogs
and loading workflow; `open_project(path)` may be used when the extension has
already selected a project path. The extension must not import
`ProductionShell` or call its private methods. `close()` is called when leaving
or switching modules. An optional `on_open()` hook may defer the first render, as the built-in
Landmarks adapter does while loading a remembered project.

Core owns every `Project` and all scientific persistence. Modules may request
or open a core project through the host, but must not silently replace the
canonical project storage or scientific records.

```python
# my_package/plugin.py
from tkinter import ttk
from app.extensions import EXTENSION_API_VERSION, ModuleSpec

class MyWorkspace:
    def render(self, host):
        ttk.Label(host.container, text="My scientific workspace").pack()
        ttk.Button(host.container, text="Modules", command=host.show_module_hub).pack()
        ttk.Button(host.container, text="Open project", command=host.open_project).pack()
        ttk.Button(host.container, text="New project", command=host.new_project).pack()

    def close(self):
        pass

def get_module():
    return ModuleSpec(
        module_id="my_module", display_name="My module",
        description="A scientific workspace", version="1.0",
        api_version=EXTENSION_API_VERSION, order=100, status="available",
        factory=MyWorkspace, source="my_package",
    )
```

```toml
[project.entry-points."morpholabel.modules"]
my_module = "my_package.plugin:get_module"
```

The built-in Landmarks & measurements module uses this same registration
contract. X-ray counts and Scales & meristics are registered as planned
metadata and have no runtime factory yet.

## AI backends

An entry point in `morpholabel.ai_backends` returns a `BackendSpec`. The
registry is task-neutral: `factory(context)` may return any object appropriate
for the declared task. The current landmark inference consumer verifies that
the returned object implements `app.ai.LandmarkBackend` and rejects providers
for other tasks. Future scientific consumers define and validate their own
backend protocol. `BackendContext` currently supplies the core project, model
metadata, artifact directory, model JSON, input size and performance settings.
The existing `RTMPoseBackend` is registered as the built-in `rtmpose` provider.
No AI packages or model weights are installed by the extension API.

```python
# my_package/backend.py
from app.extensions import BackendSpec, EXTENSION_API_VERSION
from .implementation import MyLandmarkBackend  # implements app.ai.LandmarkBackend

def get_backend():
    return BackendSpec(
        backend_id="my_backend", display_name="My backend", task="landmark",
        version="1.0", api_version=EXTENSION_API_VERSION,
        factory=lambda context: MyLandmarkBackend(context), source="my_package",
    )
```

```toml
[project.entry-points."morpholabel.ai_backends"]
my_backend = "my_package.backend:get_backend"
```

Provider identity is read from existing `model.json` `backend_id`/`backend` or
project model metrics `backend`. If absent, it defaults to `rtmpose`. A package
that names another installed provider can use it without changing core
dispatch. This is a non-destructive metadata choice; no package format
migration is required. Backend predictions still pass through the core
`LandmarkAIService` and cannot replace human-corrected annotations.
