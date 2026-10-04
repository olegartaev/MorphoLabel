"""MorphoLabel module hub shown before any scientific workspace opens."""
from __future__ import annotations
from pathlib import Path
from tkinter import ttk
from app.identity import APP_NAME, APP_VERSION, APP_STATUS, icon_image
from .icons import WORKFLOW_ICON_SIZE
from app.xray_icons import tk_xray_icon


class ModuleHub:
    def __init__(self,shell,parent,registry):
        self.shell=shell;self.parent=parent;self.registry=registry;self.logo=None;self._module_icons=[]

    def render(self):
        host=ttk.Frame(self.parent,padding=(32,26));host.pack(fill="both",expand=True);host.columnconfigure(0,weight=1)
        brand=ttk.Frame(host);brand.grid(row=0,column=0,sticky="n",pady=(8,24))
        self.logo=icon_image(brand);self.shell._morpholabel_hub_icon=self.logo
        ttk.Label(brand,image=self.logo).pack(side="left",padx=(0,22))
        copy=ttk.Frame(brand);copy.pack(side="left")
        ttk.Label(copy,text=APP_NAME,style="HubTitle.TLabel").pack(anchor="w")
        ttk.Label(copy,text="From biological images to reviewed morphological data.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(3,8))
        ttk.Label(copy,text=f"v{APP_VERSION} · {APP_STATUS}",style="Muted.TLabel").pack(anchor="w")
        modules=ttk.Frame(host);modules.grid(row=1,column=0,sticky="n")
        modules.columnconfigure(0,weight=1,uniform="module_cards");modules.columnconfigure(1,weight=1,uniform="module_cards")
        self._module_icons=[]
        for index,spec in enumerate(self.registry.available()):
            card=ttk.LabelFrame(modules,text="Available module",padding=(16,14))
            card.grid(row=index//2,column=index%2,sticky="nsew",padx=(0 if index%2==0 else 12,0),pady=(0,10))
            card.columnconfigure(0,weight=1);card.rowconfigure(1,weight=1)
            header=ttk.Frame(card);header.grid(row=0,column=0,sticky="w")
            if spec.module_id=="xray_counts":
                icon=tk_xray_icon(header,"xray",WORKFLOW_ICON_SIZE)
            else:
                icon=self.shell.ui_icon({"landmarks":"landmarks"}.get(spec.module_id,"modules"),WORKFLOW_ICON_SIZE)
            self._module_icons.append(icon)
            ttk.Label(header,image=icon).pack(side="left",padx=(0,8))
            ttk.Label(header,text=spec.display_name,style="ModuleTitle.TLabel").pack(side="left")
            ttk.Label(card,text=spec.description,style="Muted.TLabel",wraplength=300,justify="left").grid(row=1,column=0,sticky="nw",pady=(8,8))
            remembered=getattr(self.shell,"_remembered_project_path",None)
            recent=f"Last project: {Path(remembered).name}" if remembered else "Last project: —"
            ttk.Label(card,text=recent,style="Muted.TLabel",wraplength=300).grid(row=2,column=0,sticky="w",pady=(0,8))
            self.shell.control_button(card,"Open module",lambda key=spec.module_id:self.shell.open_module(key),f"Open {spec.display_name}.",primary=True).grid(row=3,column=0,sticky="ew")
        planned=ttk.Frame(host);planned.grid(row=2,column=0,sticky="n",pady=(10,0))
        names=[spec.display_name for spec in self.registry.planned()]
        if names:ttk.Label(planned,text="Planned: "+" · ".join(names),style="Muted.TLabel").pack()
        footer=ttk.Frame(host);footer.grid(row=3,column=0,sticky="n",pady=(20,0))
        self.shell.control_button(footer,"About MorphoLabel",self.shell.show_about,"Version, module authors, license and project link.").pack(side="left")
