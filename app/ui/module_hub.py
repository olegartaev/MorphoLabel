"""MorphoLabel module hub shown before any scientific workspace opens."""
from __future__ import annotations
from pathlib import Path
from tkinter import ttk
from app.identity import APP_NAME, APP_VERSION, APP_STATUS, icon_image


class ModuleHub:
    def __init__(self,shell,parent):
        self.shell=shell
        self.parent=parent
        self.logo=None

    def render(self):
        host=ttk.Frame(self.parent,padding=(42,34))
        host.pack(fill="both",expand=True)
        host.columnconfigure(0,weight=1)

        brand=ttk.Frame(host)
        brand.grid(row=0,column=0,sticky="n",pady=(4,24))
        self.logo=icon_image(brand)
        ttk.Label(brand,image=self.logo).pack()
        ttk.Label(brand,text=APP_NAME,style="HubTitle.TLabel").pack(pady=(12,2))
        ttk.Label(brand,text="Open scientific tools for biological morphology annotation.",style="PageSubtitle.TLabel").pack()
        ttk.Label(brand,text=f"v{APP_VERSION} · {APP_STATUS}",style="Muted.TLabel").pack(pady=(4,0))

        modules=ttk.Frame(host)
        modules.grid(row=1,column=0,sticky="n")
        card=ttk.LabelFrame(modules,text="Available module",padding=(18,14))
        card.grid(row=0,column=0,sticky="ew")
        card.columnconfigure(0,weight=1)
        ttk.Label(card,text="Landmarks & measurements",style="ModuleTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(
            card,
            text="Crop → landmark annotation and AI review → measurements → export",
            style="Muted.TLabel",
        ).grid(row=1,column=0,sticky="w",pady=(3,10))
        remembered=getattr(self.shell,"_remembered_project_path",None)
        if remembered:
            ttk.Label(
                card,
                text=f"Last project: {Path(remembered).name}",
                style="Muted.TLabel",
            ).grid(row=2,column=0,sticky="w",pady=(0,9))
        self.shell.control_button(
            card,
            "Open module",
            self.shell.open_primary_module,
            "Open the Landmarks & measurements module.",
            primary=True,
        ).grid(row=3,column=0,sticky="ew")

        planned=ttk.LabelFrame(host,text="Planned modules",padding=(14,9))
        planned.grid(row=2,column=0,sticky="n",pady=(16,0))
        ttk.Label(planned,text="X-ray counts",style="Muted.TLabel").grid(row=0,column=0,padx=(0,18))
        ttk.Label(planned,text="Scales & meristics",style="Muted.TLabel").grid(row=0,column=1)

        footer=ttk.Frame(host)
        footer.grid(row=3,column=0,sticky="n",pady=(18,0))
        self.shell.control_button(
            footer,
            "About MorphoLabel",
            self.shell.show_about,
            "Version, author, license and project links.",
        ).pack(side="left")
