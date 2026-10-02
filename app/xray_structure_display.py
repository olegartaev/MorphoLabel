"""Project-persistent display preferences for X-ray structure markers.

The base marker language intentionally mirrors Landmarks: one selected colour,
one other colour, one symbol, one size, and optional halo. Semantic start/stop
roles use small outer colour arcs so multiple meanings do not stack markers.
"""
from __future__ import annotations

from app.ui.landmark_display import (
    DEFAULT_HALO, DEFAULT_LABEL_SIZE, DEFAULT_OTHER, DEFAULT_SELECTED,
    DEFAULT_SIZE, DEFAULT_SYMBOL, HALO_LABELS, HALO_NAMES,
    SYMBOL_LABELS, SYMBOL_NAMES, draw_label, draw_marker,
)

ROLE_PALETTE=("#56b4e9","#e69f00","#009e73","#cc79a7","#d55e00","#0072b2","#f0e442","#8e6cff")
DISPLAY_DESIGN_VERSION=3


def _color(value,fallback):
    text=str(value or "").strip().lower()
    if len(text)==7 and text.startswith("#"):
        try:int(text[1:],16);return text
        except ValueError:pass
    return fallback


def normalize_xray_structure_display(value=None,structures=()):
    value=value if isinstance(value,dict) else {}
    structures=list(structures or ())
    try:size=int(value.get("size",DEFAULT_SIZE))
    except (TypeError,ValueError):size=DEFAULT_SIZE
    try:label_size=int(value.get("label_size",DEFAULT_LABEL_SIZE))
    except (TypeError,ValueError):label_size=DEFAULT_LABEL_SIZE
    symbol=str(value.get("symbol",DEFAULT_SYMBOL))
    if symbol not in SYMBOL_NAMES:symbol=DEFAULT_SYMBOL
    halo=str(value.get("halo",DEFAULT_HALO))
    if halo not in HALO_NAMES:halo=DEFAULT_HALO

    # Keep old per-structure colours only as semantic role colours. Base points
    # now follow the same selected/other colour language as Landmarks.
    legacy_colors=value.get("colors") if isinstance(value.get("colors"),dict) else {}
    raw_role=value.get("role_colors") if isinstance(value.get("role_colors"),dict) else legacy_colors
    role_colors={}
    for index,structure in enumerate(structures):
        ident=str(structure.get("id") or "")
        role_colors[ident]=_color(raw_role.get(ident),ROLE_PALETTE[index%len(ROLE_PALETTE)])
    return {
        "selected_color":_color(value.get("selected_color"),DEFAULT_SELECTED),
        "other_color":_color(value.get("other_color"),DEFAULT_OTHER),
        "size":max(3,min(12,size)),
        "symbol":symbol,
        "label_size":max(8,min(24,label_size)),
        "halo":halo,
        "role_colors":role_colors,
        "design_version":DISPLAY_DESIGN_VERSION,
    }


def load_xray_structure_display(project,structures=()):
    return normalize_xray_structure_display(project.get_ui_state("xray_structure_display",{}),structures)


def save_xray_structure_display(project,value,structures=()):
    settings=normalize_xray_structure_display(value,structures)
    project.set_ui_state("xray_structure_display",settings)
    return settings


def marker_style(settings,structure,index=0,selected=False):
    return {
        "color":settings.get("selected_color",DEFAULT_SELECTED) if selected else settings.get("other_color",DEFAULT_OTHER),
        "symbol":settings.get("symbol",DEFAULT_SYMBOL),
        "size":int(settings.get("size",DEFAULT_SIZE)),
        "label_size":int(settings.get("label_size",DEFAULT_LABEL_SIZE)),
        "halo":settings.get("halo",DEFAULT_HALO),
    }


def role_color(settings,structure,index=0):
    ident=str(structure.get("id") or "")
    return settings.get("role_colors",{}).get(ident,ROLE_PALETTE[int(index)%len(ROLE_PALETTE)])


def draw_xray_role_badges(canvas,x,y,*,colors,size,tags=()):
    """Draw compact semantic-role arcs around one physical marker."""
    colors=[str(color) for color in (colors or ()) if color]
    if not colors:return
    tags=tuple(tags) if isinstance(tags,(tuple,list)) else (tags,)
    common=tags+("structure_overlay",);r=max(4,int(size))+6
    canvas.create_oval(x-r,y-r,x+r,y+r,fill="",outline="#101418",width=4,tags=common)
    count=len(colors);gap=8.0;usable=360.0-gap*count;span=max(18.0,usable/count)
    for index,color in enumerate(colors):
        start=90.0+index*(span+gap)
        canvas.create_arc(x-r,y-r,x+r,y+r,start=start,extent=span,style="arc",outline=color,width=3,tags=common)


def draw_xray_marker(canvas,x,y,*,color,size,symbol,label="",label_size=10,halo="none",tags=()):
    """Draw exactly the same base marker language used by Landmarks."""
    common=tuple(tags) if isinstance(tags,(tuple,list)) else (tags,)
    common=common+("structure_overlay",)
    draw_marker(canvas,x,y,color=color,size=size,symbol=symbol,halo=halo,tags=common)
    if label:
        offset=int(size)+4
        draw_label(canvas,x+offset,y-offset,text=str(label),color=color,font_size=label_size,halo=halo,tags=common)
