"""Project-persistent display preferences for X-ray structure markers."""
from __future__ import annotations

DEFAULT_SIZE=7
DEFAULT_LABEL_SIZE=10
LEGACY_DEFAULT_PALETTE=("#00e5ff","#ff2bd6","#ffd400","#6dff5c","#ff7043","#b388ff","#00ff95","#ff4d6d")
DEFAULT_PALETTE=("#56b4e9","#e69f00","#009e73","#cc79a7","#d55e00","#0072b2","#f0e442","#8e6cff")
DISPLAY_DESIGN_VERSION=2
SYMBOL_LABELS={
    "Circle":"circle",
    "Filled circle":"filled_circle",
    "Target":"target",
    "Cross":"cross",
    "Diamond":"diamond",
    "Square":"square",
    "Triangle":"triangle",
}
SYMBOL_NAMES={value:key for key,value in SYMBOL_LABELS.items()}


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
    raw_colors=value.get("colors") if isinstance(value.get("colors"),dict) else {}
    if not raw_colors and isinstance(value.get("role_colors"),dict):raw_colors=value.get("role_colors")
    legacy_defaults=bool(raw_colors) and int(value.get("design_version",1) or 1)<DISPLAY_DESIGN_VERSION
    raw_symbols=value.get("symbols") if isinstance(value.get("symbols"),dict) else {}
    global_symbol=str(value.get("symbol") or "")
    colors={};symbols={}
    for index,structure in enumerate(structures):
        ident=str(structure.get("id") or "")
        fallback=DEFAULT_PALETTE[index%len(DEFAULT_PALETTE)]
        raw=raw_colors.get(ident)
        if legacy_defaults and str(raw or "").lower()==LEGACY_DEFAULT_PALETTE[index%len(LEGACY_DEFAULT_PALETTE)].lower():raw=fallback
        colors[ident]=_color(raw,fallback)
        symbol=str(raw_symbols.get(ident) or global_symbol or structure.get("shape") or "circle")
        if symbol=="ring":symbol="target"
        if symbol not in SYMBOL_NAMES:symbol="circle"
        symbols[ident]=symbol
    return {
        "size":max(4,min(18,size)),
        "label_size":max(8,min(24,label_size)),
        "colors":colors,
        "symbols":symbols,
        "design_version":DISPLAY_DESIGN_VERSION,
    }


def load_xray_structure_display(project,structures=()):
    return normalize_xray_structure_display(project.get_ui_state("xray_structure_display",{}),structures)


def save_xray_structure_display(project,value,structures=()):
    settings=normalize_xray_structure_display(value,structures)
    project.set_ui_state("xray_structure_display",settings)
    return settings


def marker_style(settings,structure,index=0):
    ident=str(structure.get("id") or "")
    return {
        "color":settings.get("colors",{}).get(ident,DEFAULT_PALETTE[int(index)%len(DEFAULT_PALETTE)]),
        "symbol":settings.get("symbols",{}).get(ident,"circle"),
        "size":int(settings.get("size",DEFAULT_SIZE)),
        "label_size":int(settings.get("label_size",DEFAULT_LABEL_SIZE)),
    }


def role_color(settings,structure,index=0):
    return marker_style(settings,structure,index)["color"]


def _oval(canvas,x,y,r,**kwargs):
    return canvas.create_oval(x-r,y-r,x+r,y+r,**kwargs)


def _polygon_points(symbol,x,y,r):
    if symbol=="diamond":return (x,y-r,x-r,y,x,y+r,x+r,y)
    if symbol=="triangle":return (x,y-r,x-r,y+r,x+r,y+r)
    return (x-r,y-r,x+r,y-r,x+r,y+r,x-r,y+r)


def draw_xray_role_badges(canvas,x,y,*,colors,size,tags=()):
    """One shared point can carry several semantic roles without stacking markers."""
    colors=[str(color) for color in (colors or ()) if color]
    if not colors:return
    tags=tuple(tags) if isinstance(tags,(tuple,list)) else (tags,)
    common=tags+("structure_overlay",);r=max(4,int(size))+6
    canvas.create_oval(x-r,y-r,x+r,y+r,fill="",outline="#101418",width=5,tags=common)
    count=len(colors);gap=8.0;usable=360.0-gap*count;span=max(18.0,usable/count)
    for index,color in enumerate(colors):
        start=90.0+index*(span+gap)
        canvas.create_arc(x-r,y-r,x+r,y+r,start=start,extent=span,style="arc",outline=color,width=3,tags=common)


def draw_xray_marker(canvas,x,y,*,color,size,symbol,label="",label_size=11,selected=False,tags=()):
    """Compact high-contrast marker for grayscale radiographs."""
    tags=tuple(tags) if isinstance(tags,(tuple,list)) else (tags,)
    r=max(4,int(size));common=tags+("structure_overlay",)
    if symbol=="cross":
        for width,stroke in ((4,"#101418"),(2,color)):
            canvas.create_line(x-r,y-r,x+r,y+r,fill=stroke,width=width,tags=common)
            canvas.create_line(x-r,y+r,x+r,y-r,fill=stroke,width=width,tags=common)
    elif symbol in {"diamond","square","triangle"}:
        pts=_polygon_points(symbol,x,y,r)
        canvas.create_polygon(*pts,fill="",outline="#101418",width=4,tags=common)
        canvas.create_polygon(*pts,fill="",outline=color,width=2,tags=common)
    elif symbol=="filled_circle":
        _oval(canvas,x,y,r+1,fill="#101418",outline="#101418",tags=common)
        _oval(canvas,x,y,r-1,fill=color,outline=color,tags=common)
        _oval(canvas,x,y,max(1,r//4),fill="#ffffff",outline="#ffffff",tags=common)
    else:
        _oval(canvas,x,y,r+1,fill="",outline="#101418",width=4,tags=common)
        _oval(canvas,x,y,r,fill="",outline=color,width=2,tags=common)
        _oval(canvas,x,y,max(1,r//5),fill="#ffffff",outline="#101418",width=1,tags=common)
        if symbol=="target":_oval(canvas,x,y,max(2,r//3),fill="",outline=color,width=2,tags=common)
    if selected:
        sr=r+11
        _oval(canvas,x,y,sr,fill="",outline="#101418",width=5,tags=common)
        _oval(canvas,x,y,sr,fill="",outline="#ffffff",width=2,tags=common)
    if label:
        lx=x+r+5;ly=y-r-3;font=("Segoe UI",int(label_size),"bold")
        for dx,dy in ((-2,0),(2,0),(0,-2),(0,2)):
            canvas.create_text(lx+dx,ly+dy,text=str(label),anchor="sw",fill="#101418",font=font,tags=common)
        canvas.create_text(lx,ly,text=str(label),anchor="sw",fill="#ffffff",font=font,tags=common)

