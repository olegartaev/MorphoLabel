"""Built-in X-ray Counts module adapter."""
from __future__ import annotations


class XRayCountsRuntime:
    def __init__(self):
        from app.ui.xray_counts_module import XRayCountsView
        self._view_cls=XRayCountsView;self._view=None

    def render(self, host):
        self._view=self._view_cls(host)
        self._view.render()

    def close(self):
        if self._view is not None:
            self._view.close();self._view=None
