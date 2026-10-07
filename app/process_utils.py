"""Small cross-platform subprocess helpers for MorphoLabel-owned background work."""
from __future__ import annotations

import subprocess
import sys

def terminate_process_tree(process):
    """Stop only this owned subprocess and its multiprocessing children."""
    if process.poll() is not None:return
    if sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, check=False, timeout=10, **hidden_window_kwargs())
    else:process.terminate()
    try:process.wait(timeout=2)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)


def hidden_window_kwargs():
    """Return Windows-only Popen kwargs that keep internal console windows hidden.

    MorphoLabel captures stdout/stderr itself, so an extra console window is
    never useful to the user.  Non-Windows platforms receive no extra kwargs.
    """
    if not sys.platform.startswith("win"):
        return {}
    kwargs = {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if flags:
        kwargs["creationflags"] = flags
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is not None:
        startupinfo = startupinfo_type()
        use_show = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        if use_show:
            startupinfo.dwFlags |= use_show
        if hasattr(startupinfo, "wShowWindow"):
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs
