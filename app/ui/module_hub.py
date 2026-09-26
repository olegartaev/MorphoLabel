"""MorphoLabel module hub shown before any scientific workspace opens."""
from __future__ import annotations
from pathlib import Path
from tkinter import ttk
from app.identity import APP_NAME, APP_VERSION, APP_STATUS, icon_image


class ModuleHub:
    def __init__(self,shell,parent,registry):
        self.shell=shell
        self.parent=parent
        self.registry=registry
        self.logo=None

    def render(self):
        host=ttk.Frame(self.parent,padding=(42,34))
        host.pack(fill="both",expand=True)
        host.columnconfigure(0,weight=1)

        brand=ttk.Frame(host)
        brand.grid(row=0,column=0,sticky="n",pady=(4,24))
        self.logo=icon_image(brand)
        # Keep the Tcl image owned by the durable shell, not by this temporary
        # ModuleHub renderer object.
        self.shell._morpholabel_hub_icon=self.logo
        ttk.Label(brand,image=self.logo).pack()
        ttk.Label(brand,text=APP_NAME,style="HubTitle.TLabel").pack(pady=(12,2))
        ttk.Label(brand,text="Open scientific tools for biological morphology annotation.",style="PageSubtitle.TLabel").pack()
        ttk.Label(brand,text=f"v{APP_VERSION} · {APP_STATUS}",style="Muted.TLabel").pack(pady=(4,0))

        modules=ttk.Frame(host)
        modules.grid(row=1,column=0,sticky="n")
        for index,spec in enumerate(self.registry.available()):
            card=ttk.LabelFrame(modules,text="Available module",padding=(18,14))
            card.grid(row=index,column=0,sticky="ew",pady=(0,8))
            card.columnconfigure(0,weight=1)
            ttk.Label(card,text=spec.display_name,style="ModuleTitle.TLabel").grid(row=0,column=0,sticky="w")
            ttk.Label(card,text=spec.description,style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(3,10))
            remembered=getattr(self.shell,"_remembered_project_path",None)
            if remembered:
                ttk.Label(card,text=f"Last project: {Path(remembered).name}",style="Muted.TLabel").grid(row=2,column=0,sticky="w",pady=(0,9))
            self.shell.control_button(card,"Open module",lambda key=spec.module_id:self.shell.open_module(key),
                                      f"Open {spec.display_name}.",primary=True).grid(row=3,column=0,sticky="ew")

        planned=ttk.LabelFrame(host,text="Planned modules",padding=(14,9))
        planned.grid(row=2,column=0,sticky="n",pady=(16,0))
        for index,spec in enumerate(self.registry.planned()):
            ttk.Label(planned,text=spec.display_name,style="Muted.TLabel").grid(row=0,column=index,padx=(0,18))

        footer=ttk.Frame(host)
        footer.grid(row=3,column=0,sticky="n",pady=(18,0))
        self.shell.control_button(
            footer,
            "About MorphoLabel",
            self.shell.show_about,
            "Version, author, license and project links.",
        ).pack(side="left")
