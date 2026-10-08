"""Small cross-platform subprocess helpers for MorphoLabel-owned background work."""
from __future__ import annotations

import subprocess
import sys
import time


def _terminate_windows_process_tree(pid):
    """Use owned descendant handles when taskkill is unavailable or denied."""
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while present:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            present = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(snapshot)

    owned = [pid]
    for parent in owned:
        owned.extend(child for child, owner in parents.items() if owner == parent and child not in owned)
    handles = []
    try:
        # Hold the handles before terminating so PID reuse cannot redirect a kill.
        for child in reversed(owned):
            handle = kernel.OpenProcess(0x100000 | 0x1, False, child)  # SYNCHRONIZE | TERMINATE
            if handle:
                handles.append(handle)
            elif ctypes.get_last_error() != 87:  # Already exited: ERROR_INVALID_PARAMETER
                raise ctypes.WinError(ctypes.get_last_error())
        for handle in handles:
            if (kernel.WaitForSingleObject(handle, 0) != 0
                    and not kernel.TerminateProcess(handle, 1)
                    and kernel.WaitForSingleObject(handle, 0) != 0):
                raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + 2
        for handle in handles:
            timeout = max(0, int((deadline - time.monotonic()) * 1000))
            if kernel.WaitForSingleObject(handle, timeout) != 0:
                raise subprocess.TimeoutExpired("owned Windows process tree", 2)
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)

def terminate_process_tree(process):
    """Stop only this owned subprocess and its multiprocessing children."""
    if process.poll() is not None:return
    if sys.platform.startswith("win"):
        try:
            result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                    capture_output=True, check=False, timeout=10, **hidden_window_kwargs())
        except (OSError, subprocess.TimeoutExpired):
            _terminate_windows_process_tree(process.pid)
        else:
            if result.returncode:
                _terminate_windows_process_tree(process.pid)
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
