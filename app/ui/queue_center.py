"""Shared queue browser used by all MorphoLabel modules.

Queue callbacks own persistence semantics. This dialog only presents them
consistently and never edits scientific data itself.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from .dialogs import center


def show_queue_center(parent, entries, button_factory):
    entries=tuple(entries or ())
    dialog=tk.Toplevel(parent)
    dialog.title("Queues")
    dialog.transient(parent)
    dialog.resizable(False,False)
    frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
    ttk.Label(frame,text="Queues",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
    ttk.Label(
        frame,
        text="Saved review and annotation queues. Open a queue to continue it, or close the queue without deleting scientific annotations.",
        style="Muted.TLabel",wraplength=620,justify="left",
    ).grid(row=1,column=0,sticky="w",pady=(3,10))

    def run(callback):
        dialog.destroy()
        if callable(callback):callback()

    if not entries:
        empty=ttk.LabelFrame(frame,text="No saved queues",padding=(12,10))
        empty.grid(row=2,column=0,sticky="ew")
        ttk.Label(empty,text="There is no unfinished queue in this module.",style="Muted.TLabel").pack(anchor="w")
    else:
        for index,entry in enumerate(entries,2):
            row=ttk.LabelFrame(frame,text=str(entry.get("title") or "Queue"),padding=(10,8))
            row.grid(row=index,column=0,sticky="ew",pady=(0,7));row.columnconfigure(0,weight=1)
            ttk.Label(row,text=str(entry.get("detail") or ""),style="Muted.TLabel",wraplength=430,justify="left").grid(row=0,column=0,sticky="w")
            actions=ttk.Frame(row);actions.grid(row=0,column=1,sticky="e",padx=(14,0))
            button_factory(actions,"Open",lambda cb=entry.get("open"):run(cb),"Open this saved queue.",icon="next").pack(side="left")
            button_factory(actions,"Close queue",lambda cb=entry.get("close"):run(cb),"Close this queue. Saved annotations and scientific results are kept.",icon="close").pack(side="left",padx=(5,0))
    button_factory(frame,"Close",dialog.destroy,"Close the queue list.",icon="close").grid(row=max(3,len(entries)+2),column=0,sticky="e",pady=(4,0))
    dialog.update_idletasks();center(parent,dialog)
    return dialog
