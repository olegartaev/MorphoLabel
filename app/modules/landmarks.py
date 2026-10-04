"""Internal adapter for the existing core Landmarks workspace.

External modules receive only ModuleHost and never need this bridge.
"""


class LandmarksRuntime:
    """Zero-argument built-in runtime; private core callbacks are bound internally."""

    def __init__(self):
        self._render_core = None
        self._open_core = None
        self._queue_entries_core = None
        self._model_transfer_core = None
        self._host = None

    def _bind_core(self, render_core, open_core, queue_entries_core=None, model_transfer_core=None):
        self._render_core = render_core
        self._open_core = open_core
        self._queue_entries_core = queue_entries_core
        self._model_transfer_core = model_transfer_core
        return self

    def render(self, host):
        if self._render_core is None:
            raise RuntimeError("Landmarks core runtime is not bound")
        self._host = host
        self._render_core()

    def on_open(self):
        if self._open_core is None:
            raise RuntimeError("Landmarks core runtime is not bound")
        self._open_core()

    def queue_entries(self):
        if not callable(self._queue_entries_core):
            return ()
        return tuple(self._queue_entries_core() or ())

    def standard_menu_entries(self):
        if not callable(self._model_transfer_core):
            return ()
        available = bool(self._host is not None and self._host.project is not None)
        return ({
            "label": "AI model transfer...",
            "command": self._model_transfer_core,
            "state": "normal" if available else "disabled",
        },)

    def close(self):
        self._host = None
