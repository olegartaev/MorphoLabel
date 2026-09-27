"""Small, generic toolbar icons for the MorphoLabel production UI.

The symbols deliberately avoid taxon-specific silhouettes: MorphoLabel may annotate
fish, plants, insects, museum objects, or any other image-based morphology.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

TOPBAR_ICON_SIZE=24
CONTROL_ICON_SIZE=18

OUTLINE="#465d73"
MUTED="#a9b8c7"
PALE="#dfe7ef"
PALE_BLUE="#d9e9fa"
BLUE="#2f80ed"
RED="#ee514f"
GREEN="#35a853"
YELLOW="#f1b433"

ICON_NAMES=frozenset({
    "modules","project","crop","landmarks","measurements","export",
    "missing","delete","clear","verify","display","exclude","restore",
})

def _renderer(size:int):
    if int(size)<12:raise ValueError("toolbar icons must be at least 12 px")
    aa=4;side=int(size)*aa
    image=Image.new("RGBA",(side,side),(0,0,0,0));draw=ImageDraw.Draw(image)
    scale=side/32.0
    p=lambda value:int(round(float(value)*scale))
    box=lambda values:tuple(p(value) for value in values)
    width=lambda value:max(1,p(value))
    return image,draw,p,box,width

def _line(draw,p,points,fill=OUTLINE,width=2):
    draw.line([(p(x),p(y)) for x,y in points],fill=fill,width=max(1,p(width)),joint="curve")

def _blob(draw,p,box,fill=PALE,outline=OUTLINE,width=2):
    x0,y0,x1,y1=box
    points=[(x0+2,y0+8),(x0+6,y0+3),(x0+13,y0+4),(x0+18,y0+1),(x0+24,y0+5),(x0+26,y0+11),(x0+22,y0+17),(x0+14,y0+19),(x0+7,y0+17),(x0+2,y0+13)]
    scaled=[(p(x),p(y)) for x,y in points]
    draw.polygon(scaled,fill=fill)
    draw.line(scaled+[scaled[0]],fill=outline,width=max(1,p(width)),joint="curve")

def _dot(draw,p,x,y,color,r=2.4,outline=OUTLINE):
    draw.ellipse((p(x-r),p(y-r),p(x+r),p(y+r)),fill=color,outline=outline,width=max(1,p(1)))

def _dash(draw,p,a,b,fill=OUTLINE,width=1.4,segments=4):
    x0,y0=a;x1,y1=b
    for i in range(segments):
        start=i/segments;end=min(1.0,start+0.55/segments)
        draw.line((p(x0+(x1-x0)*start),p(y0+(y1-y0)*start),p(x0+(x1-x0)*end),p(y0+(y1-y0)*end)),fill=fill,width=max(1,p(width)))

def _arrow(draw,p,a,b,color=BLUE,width=2,double=False):
    x0,y0=a;x1,y1=b
    _line(draw,p,[a,b],color,width)
    def head(tip,tail):
        tx,ty=tip;bx,by=tail;dx=tx-bx;dy=ty-by
        length=(dx*dx+dy*dy)**0.5 or 1.0;ux,uy=dx/length,dy/length;px,py=-uy,ux
        base=(tx-ux*4.2,ty-uy*4.2)
        draw.polygon([(p(tx),p(ty)),(p(base[0]+px*2.6),p(base[1]+py*2.6)),(p(base[0]-px*2.6),p(base[1]-py*2.6))],fill=color)
    head(b,a)
    if double:head(a,b)

def _image_card(draw,p,x0,y0,x1,y1,outline=OUTLINE,fill="#f7fafc"):
    draw.rounded_rectangle((p(x0),p(y0),p(x1),p(y1)),radius=p(2),fill=fill,outline=outline,width=max(1,p(1.8)))
    draw.ellipse((p(x1-7),p(y0+4),p(x1-4),p(y0+7)),fill=MUTED)
    draw.polygon([(p(x0+3),p(y1-4)),(p(x0+8),p(y0+8)),(p(x0+12),p(y1-7)),(p(x1-3),p(y1-4))],fill=PALE_BLUE)

def render_icon(name:str,size:int=TOPBAR_ICON_SIZE):
    """Return a supersampled transparent RGBA Pillow image."""
    if name not in ICON_NAMES:raise KeyError(f"Unknown toolbar icon: {name}")
    image,draw,p,box,width=_renderer(size)

    if name=="modules":
        for x,y in ((6,6),(18,6),(6,18),(18,18)):
            draw.rounded_rectangle(box((x,y,x+8,y+8)),radius=p(1.5),fill=PALE_BLUE,outline=OUTLINE,width=width(1.5))
    elif name=="project":
        _image_card(draw,p,9,5,27,20,outline=MUTED,fill="#f4f7fa")
        _image_card(draw,p,5,10,24,27)
    elif name=="crop":
        _blob(draw,p,(5,7,27,26),fill=PALE)
        for points in [((4,10),(4,4),(10,4)),((22,4),(28,4),(28,10)),((4,22),(4,28),(10,28)),((22,28),(28,28),(28,22))]:
            _line(draw,p,points,BLUE,2.6)
    elif name=="landmarks":
        _blob(draw,p,(3,6,29,25),fill="#eef3f7")
        _dash(draw,p,(9,16),(16,9),MUTED);_dash(draw,p,(16,9),(24,16),MUTED);_dash(draw,p,(9,16),(16,23),MUTED);_dash(draw,p,(16,23),(24,16),MUTED)
        for x,y,c in ((16,8,BLUE),(8,16,RED),(24,16,GREEN),(16,24,YELLOW)):_dot(draw,p,x,y,c)
    elif name=="measurements":
        _blob(draw,p,(3,6,29,25),fill="#eef3f7")
        _arrow(draw,p,(9,23),(24,8),BLUE,2.4,True)
        _dot(draw,p,9,23,BLUE,1.8);_dot(draw,p,24,8,BLUE,1.8)
    elif name=="export":
        draw.rounded_rectangle(box((5,5,21,27)),radius=p(2),fill="#f9fbfd",outline=OUTLINE,width=width(1.8))
        for y in (11,15,19):
            _line(draw,p,[(9,y),(17,y)],MUTED,1.2)
        _line(draw,p,[(19,16),(28,16)],GREEN,2.6)
        draw.polygon([(p(28),p(16)),(p(23),p(12)),(p(23),p(20))],fill=GREEN)
    elif name=="missing":
        _blob(draw,p,(4,7,28,25),fill="#eef3f7")
        cx,cy=20,9
        for start in range(0,360,90):
            import math
            a=math.radians(start);b=math.radians(start+52)
            draw.arc(box((cx-3,cy-3,cx+3,cy+3)),start=start,end=start+52,fill=BLUE,width=width(1.5))
    elif name=="delete":
        _blob(draw,p,(3,7,27,25),fill="#eef3f7");_dot(draw,p,19,9,RED)
        _line(draw,p,[(22,20),(29,27)],RED,2.8);_line(draw,p,[(29,20),(22,27)],RED,2.8)
    elif name=="clear":
        _blob(draw,p,(3,7,27,25),fill="#eef3f7")
        for x,y in ((9,16),(17,10),(24,16),(16,24)):
            draw.ellipse(box((x-2.1,y-2.1,x+2.1,y+2.1)),outline=MUTED,width=width(1.4))
        _line(draw,p,[(23,6),(25,3)],RED,2);_line(draw,p,[(27,7),(30,6)],RED,2)
    elif name=="verify":
        _blob(draw,p,(3,7,27,25),fill="#eef3f7")
        for x,y,c in ((9,16,BLUE),(17,10,RED),(24,16,GREEN),(16,24,YELLOW)):_dot(draw,p,x,y,c,1.8)
        _line(draw,p,[(20,23),(23,26),(29,18)],GREEN,2.7)
    elif name=="display":
        draw.ellipse(box((5,6,27,26)),fill="#eef3f7",outline=OUTLINE,width=width(1.7))
        for x,y,c in ((11,11,RED),(19,10,YELLOW),(23,16,GREEN),(12,21,BLUE)):_dot(draw,p,x,y,c,1.7,outline=c)
        draw.ellipse(box((20,21,27,27)),fill=(0,0,0,0),outline=OUTLINE,width=width(1.5))
    elif name=="exclude":
        _image_card(draw,p,4,6,25,25,outline=OUTLINE,fill="#f4f7fa")
        _line(draw,p,[(21,20),(28,27)],RED,2.8);_line(draw,p,[(28,20),(21,27)],RED,2.8)
    elif name=="restore":
        _image_card(draw,p,5,7,24,25,outline=OUTLINE,fill="#f4f7fa")
        _line(draw,p,[(26,20),(26,12),(18,12)],BLUE,2.4)
        draw.polygon([(p(18),p(12)),(p(22),p(8)),(p(22),p(16))],fill=BLUE)

    return image.resize((int(size),int(size)),Image.Resampling.LANCZOS)

def tk_icon(master,name:str,size:int=TOPBAR_ICON_SIZE):
    """Create a Tk image; callers keep the returned reference for widget lifetime."""
    from PIL import ImageTk
    return ImageTk.PhotoImage(render_icon(name,size),master=master)
