"""Shared delayed tooltip behavior for production UI controls."""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import ttk


def work_area(root):
    """Return the usable work area of the monitor containing the SIMM window."""
    if sys.platform.startswith("win"):
        try:
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long),
                ]
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_ulong),
                ]
            user32 = ctypes.windll.user32
            monitor = user32.MonitorFromWindow(int(root.winfo_id()), 2)  # MONITOR_DEFAULTTONEAREST
            if monitor:
                info = MONITORINFO();info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    rect=info.rcWork
                    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
            rect = RECT()
            if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        except Exception:
            pass
    try:
        left = int(root.winfo_vrootx())
        top = int(root.winfo_vrooty())
        return left, top, left + int(root.winfo_vrootwidth()), top + int(root.winfo_vrootheight())
    except tk.TclError:
        return 0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight())


def clamp_popup(x, y, width, height, bounds, *, above_y=None, margin=8):
    """Keep a popup fully inside the usable desktop; prefer above when below would overflow."""
    left, top, right, bottom = (int(value) for value in bounds)
    width, height = max(1, int(width)), max(1, int(height))
    x, y = int(x), int(y)
    if y + height + margin > bottom and above_y is not None:
        y = int(above_y) - height
    max_x = max(left + margin, right - width - margin)
    max_y = max(top + margin, bottom - height - margin)
    return (
        max(left + margin, min(x, max_x)),
        max(top + margin, min(y, max_y)),
    )


def place_popup(window, root, x, y, *, above_y=None):
    """Place an already-built popup within the usable monitor work area."""
    try:
        window.update_idletasks()
        width = window.winfo_reqwidth()
        height = window.winfo_reqheight()
        px, py = clamp_popup(x, y, width, height, work_area(root), above_y=above_y)
        window.geometry(f"+{px}+{py}")
    except tk.TclError:
        return


class Tooltip:
 def __init__(self,root):
  self.root=root;self.job=None;self.window=None;root.bind("<Destroy>",self._root_destroyed,add="+")
 def bind(self,widget,text): widget.bind("<Enter>",lambda _e:self._wait(widget,text),add="+");widget.bind("<Leave>",lambda _e:self.hide(),add="+")
 def _root_destroyed(self,event):
  if event.widget is self.root:self.job=None;self.window=None
 def _wait(self,w,text):
  self.hide()
  try:self.job=self.root.after(1200,lambda:self._show(w,text))
  except tk.TclError:self.job=None
 def _show(self,w,text):
  self.job=None
  try:
   if not w.winfo_exists():return
   self.window=tk.Toplevel(self.root);self.window.overrideredirect(True);self.window.attributes("-topmost",True)
   ttk.Label(self.window,text=text,background="#fffff2",padding=(7,4),wraplength=280).pack()
   place_popup(
    self.window,self.root,
    w.winfo_rootx()+6,
    w.winfo_rooty()+w.winfo_height()+4,
    above_y=w.winfo_rooty()-4,
   )
  except tk.TclError:self.window=None
 def hide(self):
  if self.job:
   try:self.root.after_cancel(self.job)
   except tk.TclError:pass
   self.job=None
  if self.window:
   try:self.window.destroy()
   except tk.TclError:pass
   self.window=None
