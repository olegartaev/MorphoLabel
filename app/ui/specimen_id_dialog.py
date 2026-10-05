"""A small keyboard-friendly dialog for a specimen's visible identifier."""
import tkinter as tk
from tkinter import simpledialog, ttk


class SpecimenIDDialog(simpledialog.Dialog):
    def __init__(self,parent,initial_value,on_save):
        self.initial_value=initial_value;self.on_save=on_save
        super().__init__(parent,title="Specimen ID")

    def body(self,master):
        ttk.Label(master,text="Specimen ID",style="SectionTitle.TLabel").pack(anchor="w",pady=(4,6))
        ttk.Label(master,text="Letters and numbers are allowed, e.g. A12 or 12-B.").pack(anchor="w",pady=(0,8))
        self.value=tk.StringVar(master=self,value=self.initial_value)
        self.entry=ttk.Entry(master,textvariable=self.value,width=42)
        self.entry.pack(fill="x");self.entry.selection_range(0,"end")
        self.error=ttk.Label(master,text="",foreground="#b42318",wraplength=340)
        self.error.pack(anchor="w",pady=(6,0))
        return self.entry

    def buttonbox(self):
        actions=ttk.Frame(self,padding=(10,0,10,10));actions.pack(fill="x")
        ttk.Button(actions,text="Save",style="Primary.TButton",command=self.ok).pack(side="right")
        ttk.Button(actions,text="Cancel",command=self.cancel).pack(side="right",padx=(0,6))
        self.bind("<Return>",self.ok);self.bind("<Escape>",self.cancel)

    def validate(self):
        try:self.on_save(self.value.get())
        except Exception as exc:
            self.error.configure(text=str(exc));self.entry.selection_range(0,"end");return False
        return True
