"""Internal adapter for the existing core Landmarks workspace.

External modules receive only ModuleHost and never need this bridge.
"""


class LandmarksRuntime:
    def render(self, host):
        host._render_core()

    def on_open(self, host):
        host._open_core()

    def close(self):
        pass
