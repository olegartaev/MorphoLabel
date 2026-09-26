"""Small shared, text-first visual language for quality reports."""
import tkinter as tk
from tkinter import ttk

PALETTE={
 "dark_green":"#0b5d3b", "green":"#247a3d", "yellow":"#806000",
 "orange":"#a84b00", "red":"#a61b1b", "neutral":"#333333",
}
def level_for_status(status):
 value=(status or "").casefold()
 if "persistent weak" in value or "clearly worse" in value or value=="worse":return "red"
 if "currently weak" in value or "needs improvement" in value:return "orange"
 if "within human" in value:return "dark_green"
 if "very close" in value:return "green"
 if "mixed" in value or "close" in value or "watch" in value:return "yellow"
 if "improved" in value or "normal" in value or "very good" in value:return "green"
 return "neutral"
def status_label(parent, text, *, level=None, **kwargs):
 """Colour is supplemental: every item always displays its explicit status."""
 return ttk.Label(parent,text=text,foreground=PALETTE[level or level_for_status(text)],**kwargs)
def report_dialog(parent,title,body,status=None):
 dialog=tk.Toplevel(parent);dialog.title(title);dialog.transient(parent);dialog.resizable(False,False)
 frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
 ttk.Label(frame,text=body,justify="left").pack(fill="both",expand=True)
 if status:status_label(frame,status).pack(anchor="w",pady=(10,0))
 ttk.Button(frame,text="Close",command=dialog.destroy).pack(fill="x",pady=(12,0))
 return dialog
