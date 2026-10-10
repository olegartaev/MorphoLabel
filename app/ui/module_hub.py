"""MorphoLabel module hub shown before any scientific workspace opens."""
from __future__ import annotations
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageOps
from app.identity import APP_NAME, APP_VERSION, APP_STATUS, COPYRIGHT, LICENSE_NAME, icon_image
from app.runtime_paths import resource_path
from .icons import WORKFLOW_ICON_SIZE
from app.xray_icons import tk_xray_icon


_MODULE_COVER_FILES={
    "landmarks":"landmarks.png",
    "xray_counts":"xray_traits.png",
}
_MODULE_COVER_DISPLAY_SIZE=(460,500)
_HUB_MAX_SIZE=(1244,866)


def _module_cover(master,module_id,size=_MODULE_COVER_DISPLAY_SIZE):
    filename=_MODULE_COVER_FILES.get(str(module_id))
    if not filename:return None
    path=resource_path("app","resources","module_covers",filename)
    if not path.is_file():return None
    with Image.open(path) as image:
        image.load()
        rendered=ImageOps.contain(image.convert("RGB"),size,Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(rendered,master=master)


class ModuleHub:
    def __init__(self,shell,parent,registry):
        self.shell=shell;self.parent=parent;self.registry=registry;self.logo=None;self._module_icons=[];self._module_covers=[]

    def render(self):
        stage=ttk.Frame(self.parent);stage.pack(fill="both",expand=True)
        host=ttk.Frame(stage,padding=(24,16));host.columnconfigure(0,weight=1);host.rowconfigure(1,weight=1)
        def resize_hub(event):
            host.place(relx=.5,rely=.5,anchor="center",width=min(event.width,_HUB_MAX_SIZE[0]),height=min(event.height,_HUB_MAX_SIZE[1]))
        stage.bind("<Configure>",resize_hub)
        self.content=host
        brand=ttk.Frame(host);brand.grid(row=0,column=0,sticky="n",pady=(0,14))
        self.logo=icon_image(brand);self.shell._morpholabel_hub_icon=self.logo
        ttk.Label(brand,image=self.logo).pack(side="left",padx=(0,22))
        copy=ttk.Frame(brand);copy.pack(side="left")
        ttk.Label(copy,text=APP_NAME,style="HubTitle.TLabel").pack(anchor="w")
        ttk.Label(copy,text="Large-scale biological image annotation with human review and optional AI assistance",style="PageSubtitle.TLabel",wraplength=730,justify="left").pack(anchor="w",pady=(3,8))
        ttk.Label(copy,text=f"v{APP_VERSION} · {APP_STATUS}",style="Muted.TLabel").pack(anchor="w")
        modules=ttk.Frame(host);modules.grid(row=1,column=0,sticky="nsew");modules.rowconfigure(0,weight=1)
        modules.columnconfigure(0,weight=1,uniform="module_cards");modules.columnconfigure(1,weight=1,uniform="module_cards")
        self._module_icons=[];self._module_covers=[]
        for index,spec in enumerate(self.registry.available()):
            bg="#fff8e8" if spec.module_id=="xray_counts" else "#eaf7fd"
            border="#edcf99" if spec.module_id=="xray_counts" else "#afd8ee"
            card=tk.Frame(modules,bg=bg,highlightbackground=border,highlightthickness=1)
            card.grid(row=index//2,column=index%2,sticky="nsew",padx=(0 if index%2==0 else 12,0),pady=(0,10))
            card.columnconfigure(0,weight=1);card.rowconfigure(2,weight=1)
            header=tk.Frame(card,bg=bg);header.grid(row=0,column=0,sticky="ew",padx=20,pady=(16,8))
            if spec.module_id=="xray_counts":
                icon=tk_xray_icon(header,"xray",WORKFLOW_ICON_SIZE)
            else:
                icon=self.shell.ui_icon({"landmarks":"landmarks"}.get(spec.module_id,"modules"),WORKFLOW_ICON_SIZE)
            self._module_icons.append(icon)
            tk.Label(header,image=icon,bg=bg).pack(side="left",padx=(0,8))
            title=tk.Label(header,text=spec.display_name,font=("Segoe UI",17,"bold"),bg=bg,fg="#141b3a",anchor="w",justify="left",wraplength=380)
            title.pack(side="left",fill="x",expand=True)
            header.bind("<Configure>",lambda e,label=title:label.configure(wraplength=max(180,e.width-48)))
            artwork=tk.Canvas(card,width=440,height=400,bg=bg,cursor="hand2",takefocus=True,highlightthickness=0)
            artwork.grid(row=2,column=0,sticky="nsew",padx=14,pady=(8,8))
            cover=_module_cover(artwork,spec.module_id)
            if cover is not None:
                self._module_covers.append(cover)
                artwork._cover=cover
            def resize(event,label=artwork,key=spec.module_id):
                size=(max(1,event.width),max(1,event.height))
                if getattr(label,"_cover_size",None)==size:return
                cover=_module_cover(label,key,size)
                if cover is not None:
                    label.delete("all");label.create_image(event.width/2,event.height/2,image=cover,anchor="center")
                    label._cover=cover;label._cover_size=size
            artwork.bind("<Configure>",resize)
            artwork.bind("<Button-1>",lambda _e,key=spec.module_id:self.shell.open_module(key))
            artwork.bind("<Return>",lambda _e,key=spec.module_id:self.shell.open_module(key))
            self.shell.tip.bind(artwork,f"Open {spec.display_name}.")
            descriptions={"xray_counts":"Mark and count anatomical structures in X-ray images.\nTurn annotations into reviewed trait tables.",
                          "landmarks":"Place landmarks for geometric morphometrics (GM)\nand measure biological structures."}
            description=descriptions.get(spec.module_id,spec.description)
            tk.Label(card,text=description,bg=bg,fg="#34546b",font=("Segoe UI",11),wraplength=420,justify="left").grid(row=1,column=0,sticky="w",padx=20)
            remembered=spec.recent_project() if callable(spec.recent_project) else None
            recent=f"Last project: {Path(remembered).name}" if remembered else "Start a new project or open an existing one"
            tk.Label(card,text=recent,bg=bg,fg="#536579",font=("Segoe UI",9),wraplength=420).grid(row=3,column=0,sticky="w",padx=20,pady=(0,8))
            accent="#bb6619" if spec.module_id=="xray_counts" else "#197bb5"
            active="#9c5110" if spec.module_id=="xray_counts" else "#116497"
            caption=f"Open {spec.display_name}"
            button=tk.Button(card,text=caption,command=lambda key=spec.module_id:self.shell.open_module(key),
                font=("Segoe UI",10,"bold"),bg=accent,fg="white",activebackground=active,activeforeground="white",
                relief="flat",borderwidth=0,pady=10,cursor="hand2",highlightthickness=2,highlightbackground=bg,highlightcolor="#162c40")
            button.grid(row=4,column=0,sticky="ew",padx=20,pady=(0,16))
            button.bind("<Return>",lambda _e,b=button:b.invoke())
            button.bind("<Enter>",lambda _e,b=button,color=active:b.configure(bg=color))
            button.bind("<Leave>",lambda _e,b=button,color=accent:b.configure(bg=color))
            self.shell.tip.bind(button,f"Open {spec.display_name}.")
        footer=ttk.Frame(host);footer.grid(row=2,column=0,sticky="n",pady=(8,0))
        self.shell.control_button(footer,"About MorphoLabel",self.shell.show_about,"Version, module authors, license and project link.").pack()
        ttk.Label(footer,text=f"{COPYRIGHT} · {LICENSE_NAME}",style="Muted.TLabel").pack(pady=(5,0))
