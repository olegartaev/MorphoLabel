# Extension API v1

MorphoLabel has two small extension points. Scientific modules add a workspace to
the Module Hub. AI backends supply inference implementations for existing model
packages. Each module owns its scientific project, annotations, crop provenance, dataset
snapshots, model lineage, QC, measurements and exports. The shell retains only
opaque module session state and shared UI/application services.

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
The public host exposes an empty `container`, `show_module_hub()`, and a `state`
dictionary retained across runtime lifecycles. Each module defines the contents
of its own dictionary, including its own project/data type. The shell never
interprets it or opens scientific projects on the module's behalf. Modules may
use `build_standard_menu`, `ui_icon`, `control_button`, `run_background_task`
and `tooltip` for shared application UI. Menu and queue actions come from the
runtime's optional `standard_menu_entries()` and `queue_entries()` methods.
An optional `ModuleSpec.recent_project` supplies the hub's recent-project label.
Extensions must not import `ProductionShell` or call its private methods.
`close()` releases callbacks/views when leaving or switching modules. Optional
`on_open()` runs after the first `render(host)`; failures return to the hub.

```python
# my_package/plugin.py
from tkinter import ttk
from app.extensions import EXTENSION_API_VERSION, ModuleSpec

class MyWorkspace:
    def render(self, host):
        ttk.Label(host.container, text="My scientific workspace").pack()
        ttk.Button(host.container, text="Modules", command=host.show_module_hub).pack()
        self.project = host.state.setdefault("project", {"annotations": []})
        # This module defines its own open/create project actions.

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
contract and owns its Landmark Project/UIContext. X-ray traits owns XRayProject
through the same lifecycle. Scales & meristics remains planned metadata.

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

## X-ray Structure AI

The existing backend registry also accepts `BackendSpec(task="xray_structure")`.
The built-in `resnet18_heatmap_v1` remains the default. Register another spec in
`backend_registry()` (or use an isolated registry in tests); installed providers
use the same `morpholabel.ai_backends` entry point. Its factory receives
`StructureBackendContext` (progress only) and returns `StructureBackend` with
`train(payload, timeout)` and `predict_many(payload, timeout)` methods.

Training receives a prepared dataset manifest, work directory, optional parent
checkpoint and execution settings. It returns checkpoint/metadata paths and
metrics. Metadata names the registered backend and retains the portable
structures/input_size/thresholds contract. Prediction receives prepared image
paths, checkpoint/metadata and execution settings; it returns one result per
image with structure_id and normalized x/y/score points. Providers never receive
a Project/database and cannot save annotations. The X-ray module selects human
truth, splits by plate, records memberships/lineage/schema digests, saves drafts
and provenance, compares traits and manages packages.

`train_structure_model(..., backend_id="my_provider")` selects a provider.
Continued training defaults to the parent's provider; a different provider
requires an explicit fresh lineage (`parent_model_id=""`). Prediction and human
comparison dispatch from the stored backend identity. Unavailable/wrong-task
providers, incompatible parent/schema and mismatched artifact identities are
rejected. Optional `registry=` arguments support isolated tests. Portable model
packages retain `morpholabel-xray-structure-model-v1`, artifact names, checksums,
privacy filtering and imported lineage provenance; no scientific schema change
or project migration is required.
