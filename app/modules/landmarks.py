"""Internal adapter for the existing core Landmarks workspace.

External modules receive only ModuleHost and never need this bridge.
"""


class LandmarksRuntime:
    def __init__(self, render_core, open_core):
        self._render_core = render_core
        self._open_core = open_core

    def render(self, _host):
        self._render_core()

    def on_open(self):
        self._open_core()

    def close(self):
        pass
