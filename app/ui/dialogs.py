"""Centered, reusable production UI dialogs."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .tooltips import work_area


def _screen_center(dialog, root=None):
    """Center a normal Tk toplevel in the usable monitor work area."""
    try:
        dialog.update_idletasks()
        owner = root or dialog.winfo_toplevel()
        left, top, right, bottom = work_area(owner)
        width = max(dialog.winfo_width(), dialog.winfo_reqwidth())
        height = max(dialog.winfo_height(), dialog.winfo_reqheight())
        x = left + max(0, (right - left - width) // 2)
        y = top + max(0, (bottom - top - height) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog._simm_centered = True
    except tk.TclError:
        return


def center(parent, dialog):
    """Backward-compatible helper: all SIMM windows now center on-screen."""
    _screen_center(dialog, parent.winfo_toplevel() if parent is not None else None)


def install_auto_center(root):
    """Center every normal SIMM Toplevel once, without affecting tooltips.

    Native file/message dialogs are handled by Windows.  Tk tooltips use
    overrideredirect and are intentionally excluded because they follow controls.
    """
    def on_map(event):
        dialog = event.widget
        if not isinstance(dialog, tk.Toplevel):
            return
        try:
            if dialog.overrideredirect() or getattr(dialog, "_simm_centered", False):
                return
        except tk.TclError:
            return
        if getattr(dialog, "_simm_center_pending", False):
            return
        dialog._simm_center_pending = True
        def apply():
            try:
                dialog._simm_center_pending = False
                if dialog.winfo_exists() and not getattr(dialog, "_simm_centered", False):
                    _screen_center(dialog, root)
            except tk.TclError:
                return
        try:
            dialog.after_idle(apply)
        except tk.TclError:
            pass

    root.bind_class("Toplevel", "<Map>", on_map, add="+")


def info(parent,title,text):
    d=tk.Toplevel(parent);d.title(title);f=ttk.Frame(d,padding=16);f.pack();ttk.Label(f,text=text,wraplength=460).pack();ttk.Button(f,text="Close",command=d.destroy).pack(pady=(10,0));center(parent,d);return d
