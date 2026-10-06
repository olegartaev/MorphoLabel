"""Project settings scroll independently of the full-height project catalog."""
import tkinter as tk
from tkinter import font, ttk


def project_columns(parent):
    body = ttk.Frame(parent)
    body.pack(fill="both", expand=True)
    body.rowconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)
    width = font.nametofont("TkDefaultFont").measure("0" * 48) + 40
    sidebar = ttk.Frame(body, width=width)
    sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    sidebar.grid_propagate(False)
    sidebar.rowconfigure(0, weight=1)
    sidebar.columnconfigure(0, weight=1)
    canvas = tk.Canvas(sidebar, highlightthickness=0,
                       background=ttk.Style(parent).lookup("TFrame", "background") or "#f0f0f0")
    canvas.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(sidebar, orient="vertical", command=canvas.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scroll.set)
    settings = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=settings, anchor="nw")

    def layout(_event=None):
        canvas.itemconfigure(window, width=max(1, canvas.winfo_width()))
        canvas.configure(scrollregion=canvas.bbox("all"))

    canvas.bind("<Configure>", layout)
    settings.bind("<Configure>", layout)
    catalog = ttk.Frame(body, width=1, height=1)
    catalog.grid(row=0, column=1, sticky="nsew")
    catalog.grid_propagate(False)
    return settings, catalog, canvas


def bind_settings_navigation(settings, canvas):
    """Keep all settings reachable with wheel or keyboard, without root bindings."""
    def wheel(event):
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def reveal(event):
        widget = event.widget
        top = widget.winfo_rooty() - settings.winfo_rooty()
        bottom = top + widget.winfo_height()
        visible = canvas.canvasy(0)
        height = canvas.winfo_height()
        total = max(1, settings.winfo_height())
        if top < visible:
            canvas.yview_moveto(top / total)
        elif bottom > visible + height:
            canvas.yview_moveto((bottom - height) / total)

    def bind(widget):
        widget.bind("<MouseWheel>", wheel, add="+")
        widget.bind("<FocusIn>", reveal, add="+")
        for child in widget.winfo_children():
            bind(child)

    bind(settings)


def wrapped_label(parent, text, style="Muted.TLabel", **kwargs):
    label = ttk.Label(parent, text=str(text), style=style, wraplength=280, **kwargs)
    label.pack(anchor="w", fill="x", pady=(2, 5))
    label.bind("<Configure>", lambda event: label.configure(wraplength=max(80, event.width)))
    return label
