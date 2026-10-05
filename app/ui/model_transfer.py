"""Visible Project cards for module-owned portable model actions."""
from tkinter import ttk
from .design import FlowRow


def model_transfer_card(parent,title,model,import_command,export_command):
    card=ttk.LabelFrame(parent,text=title,padding=8)
    label=ttk.Label(card,text=f"Current model: {(model or {}).get('model_id') or 'None'}",style="Muted.TLabel",wraplength=220)
    label.pack(anchor="w",fill="x")
    label.bind("<Configure>",lambda e:label.configure(wraplength=max(100,e.width)))
    actions=FlowRow(card);actions.pack(fill="x",pady=(5,0))
    ttk.Button(actions,text="Import model…",command=import_command).pack(side="left")
    ttk.Button(actions,text="Export active…",command=export_command,state="normal" if model else "disabled").pack(side="left",padx=(4,0))
    return card
