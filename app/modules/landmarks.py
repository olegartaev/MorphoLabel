"""Internal adapter for the existing core Landmarks workspace.

External modules receive only ModuleHost and never need this bridge.
"""


class LandmarksRuntime:
    """Zero-argument built-in runtime; private core callbacks are bound internally."""

    def __init__(self):
        self._render_core = None
        self._open_core = None

    def _bind_core(self, render_core, open_core):
        self._render_core = render_core
        self._open_core = open_core
        return self

    def render(self, _host):
        if self._render_core is None:
            raise RuntimeError("Landmarks core runtime is not bound")
        self._render_core()

    def on_open(self):
        if self._open_core is None:
            raise RuntimeError("Landmarks core runtime is not bound")
        self._open_core()

    def close(self):
        pass
