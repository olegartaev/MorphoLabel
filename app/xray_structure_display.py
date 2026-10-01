"""Project-persistent display preferences for X-ray structure markers."""
from __future__ import annotations

DEFAULT_SIZE=8
DEFAULT_LABEL_SIZE=11
DEFAULT_PALETTE=("#00e5ff","#ff2bd6","#ffd400","#6dff5c","#ff7043","#b388ff","#00ff95","#ff4d6d")
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
    raw_symbols=value.get("symbols") if isinstance(value.get("symbols"),dict) else {}
    colors={};symbols={}
    for index,structure in enumerate(structures):
        ident=str(structure.get("id") or "")
        fallback=DEFAULT_PALETTE[index%len(DEFAULT_PALETTE)]
        colors[ident]=_color(raw_colors.get(ident),fallback)
        symbol=str(raw_symbols.get(ident) or structure.get("shape") or "circle")
        if symbol=="ring":symbol="target"
        if symbol not in SYMBOL_NAMES:symbol="circle"
        symbols[ident]=symbol
    return {
        "size":max(4,min(18,size)),
        "label_size":max(8,min(24,label_size)),
        "colors":colors,
        "symbols":symbols,
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


def _oval(canvas,x,y,r,**kwargs):
    return canvas.create_oval(x-r,y-r,x+r,y+r,**kwargs)


def _polygon_points(symbol,x,y,r):
    if symbol=="diamond":return (x,y-r,x-r,y,x,y+r,x+r,y)
    if symbol=="triangle":return (x,y-r,x-r,y+r,x+r,y+r)
    return (x-r,y-r,x+r,y-r,x+r,y+r,x-r,y+r)


def draw_xray_marker(canvas,x,y,*,color,size,symbol,label="",label_size=11,selected=False,tags=()):
    """High-contrast marker visible on black, white and gray radiographs."""
    tags=tuple(tags) if isinstance(tags,(tuple,list)) else (tags,)
    r=max(4,int(size))
    common=tags+("structure_overlay",)
    if symbol=="cross":
        for width,stroke in ((7,"#000000"),(5,"#ffffff"),(2,color)):
            canvas.create_line(x-r,y-r,x+r,y+r,fill=stroke,width=width,tags=common)
            canvas.create_line(x-r,y+r,x+r,y-r,fill=stroke,width=width,tags=common)
    elif symbol in {"diamond","square","triangle"}:
        pts=_polygon_points(symbol,x,y,r)
        canvas.create_polygon(*pts,fill="",outline="#000000",width=7,tags=common)
        canvas.create_polygon(*pts,fill="",outline="#ffffff",width=5,tags=common)
        canvas.create_polygon(*pts,fill=color,outline=color,width=2,tags=common)
    elif symbol=="filled_circle":
        _oval(canvas,x,y,r+3,fill="#000000",outline="#000000",tags=common)
        _oval(canvas,x,y,r+2,fill="#ffffff",outline="#ffffff",tags=common)
        _oval(canvas,x,y,r,fill=color,outline=color,tags=common)
    else:
        _oval(canvas,x,y,r+2,fill="",outline="#000000",width=7,tags=common)
        _oval(canvas,x,y,r+1,fill="",outline="#ffffff",width=5,tags=common)
        _oval(canvas,x,y,r,fill="",outline=color,width=2,tags=common)
        if symbol=="target":_oval(canvas,x,y,max(2,r//3),fill=color,outline=color,tags=common)
    if selected:
        _oval(canvas,x,y,r+7,fill="",outline="#000000",width=5,tags=common)
        _oval(canvas,x,y,r+7,fill="",outline="#fff200",width=2,tags=common)
    if label:
        lx=x+r+5;ly=y-r-4;font=("Segoe UI",int(label_size),"bold")
        for dx,dy in ((-2,0),(2,0),(0,-2),(0,2),(-2,-2),(2,-2),(-2,2),(2,2)):
            canvas.create_text(lx+dx,ly+dy,text=str(label),anchor="sw",fill="#000000",font=font,tags=common)
        for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)):
            canvas.create_text(lx+dx,ly+dy,text=str(label),anchor="sw",fill="#ffffff",font=font,tags=common)
        canvas.create_text(lx,ly,text=str(label),anchor="sw",fill=color,font=font,tags=common)
