"""Programmatic X-ray module icons matching MorphoLabel's compact visual language."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageTk
from app.ui.icons import OUTLINE, MUTED, PALE_BLUE, BLUE, GREEN, RED, YELLOW

XRAY_ICON_SIZE=26
TRAIT_ICON_SIZE=28
XRAY_ICON_NAMES=frozenset({
    "xray","xray_project","xray_crops","xray_structures","xray_results","xray_export",
    "count","count_to","count_between","position","presence","distance","angle","derived",
})

def _ctx(size):
    aa=4;side=int(size)*aa;im=Image.new("RGBA",(side,side),(0,0,0,0));d=ImageDraw.Draw(im);s=side/32
    p=lambda v:int(round(v*s));w=lambda v:max(1,p(v));return im,d,p,w
def _line(d,p,pts,fill=OUTLINE,width=2):d.line([(p(x),p(y)) for x,y in pts],fill=fill,width=max(1,p(width)),joint="curve")
def _dot(d,p,x,y,fill=BLUE,r=2.2,shape="circle"):
    b=(p(x-r),p(y-r),p(x+r),p(y+r))
    if shape=="circle":d.ellipse(b,fill=fill,outline=OUTLINE,width=max(1,p(.8)))
    elif shape=="square":d.rectangle(b,fill=fill,outline=OUTLINE,width=max(1,p(.8)))
    elif shape=="diamond":d.polygon([(p(x),p(y-r-1)),(p(x+r+1),p(y)),(p(x),p(y+r+1)),(p(x-r-1),p(y))],fill=fill,outline=OUTLINE)
    elif shape=="triangle":d.polygon([(p(x),p(y-r-1)),(p(x+r+1),p(y+r)),(p(x-r-1),p(y+r))],fill=fill,outline=OUTLINE)
def _xray_card(d,p):
    d.rounded_rectangle((p(4),p(5),p(28),p(27)),radius=p(2),fill="#f7fafc",outline=OUTLINE,width=max(1,p(1.5)))
    for x in (9,13,17,21,25):_dot(d,p,x,16,MUTED,1.5)
    _line(d,p,[(7,10),(25,10)],MUTED,1);_line(d,p,[(7,22),(25,22)],MUTED,1)

def render_xray_icon(name,size=XRAY_ICON_SIZE):
    if name not in XRAY_ICON_NAMES:raise KeyError(name)
    im,d,p,w=_ctx(size)
    if name=="xray":
        _xray_card(d,p);d.ellipse((p(7),p(12),p(10),p(15)),fill=BLUE);d.ellipse((p(22),p(17),p(25),p(20)),fill=GREEN)
    elif name=="xray_project":
        _xray_card(d,p);d.rounded_rectangle((p(3),p(4),p(13),p(11)),radius=p(1),fill=PALE_BLUE,outline=OUTLINE,width=w(1))
    elif name=="xray_crops":
        _xray_card(d,p)
        for pts in [((4,11),(4,5),(10,5)),((22,5),(28,5),(28,11)),((4,21),(4,27),(10,27)),((22,27),(28,27),(28,21))]:_line(d,p,pts,BLUE,2)
    elif name=="xray_structures":
        _xray_card(d,p);_dot(d,p,9,16,"#f28e2b",2.2,"circle");_dot(d,p,16,16,"#22a06b",2.4,"triangle");_dot(d,p,23,16,"#3b82f6",2.3,"diamond")
    elif name=="xray_results":
        d.rectangle((p(5),p(6),p(24),p(26)),fill="#f8fbfd",outline=OUTLINE,width=w(1.4))
        for y in (12,18):_line(d,p,[(5,y),(24,y)],MUTED,1)
        for x in (11,18):_line(d,p,[(x,6),(x,26)],MUTED,1)
        _line(d,p,[(24,8),(29,8)],GREEN,2);_line(d,p,[(27,5),(27,11)],GREEN,2)
    elif name=="xray_export":
        d.rectangle((p(5),p(5),p(21),p(27)),fill="#f8fbfd",outline=OUTLINE,width=w(1.4));_line(d,p,[(9,11),(17,11)],MUTED,1);_line(d,p,[(9,16),(17,16)],MUTED,1)
        _line(d,p,[(19,21),(28,12)],GREEN,2.2);d.polygon([(p(28),p(12)),(p(23),p(13)),(p(27),p(17))],fill=GREEN)
    elif name in {"count","count_to","count_between","position"}:
        xs=(7,12,17,22,27)
        for x in xs:_dot(d,p,x,17,BLUE,1.8)
        if name=="count":_line(d,p,[(6,8),(28,8)],MUTED,1.4)
        elif name=="count_to":_line(d,p,[(23,7),(23,27)],RED,2);_line(d,p,[(6,9),(21,9)],MUTED,1.3)
        elif name=="count_between":_line(d,p,[(8,7),(8,27)],RED,2);_line(d,p,[(24,7),(24,27)],RED,2)
        else:_line(d,p,[(17,6),(17,11)],YELLOW,2.6);d.polygon([(p(17),p(12)),(p(14),p(8)),(p(20),p(8))],fill=YELLOW)
    elif name=="presence":
        _dot(d,p,12,16,BLUE,4);_line(d,p,[(18,16),(22,21),(29,10)],GREEN,3)
    elif name=="distance":
        _dot(d,p,7,22,BLUE,2.3);_dot(d,p,25,9,BLUE,2.3);_line(d,p,[(8,21),(24,10)],BLUE,2);_line(d,p,[(6,25),(27,25)],MUTED,1)
    elif name=="angle":
        _line(d,p,[(7,24),(16,10),(27,24)],BLUE,2.2);d.arc((p(10),p(14),p(22),p(26)),210,330,fill=YELLOW,width=w(2))
    elif name=="derived":
        d.text((p(5),p(6)),"ƒ",fill=BLUE);_line(d,p,[(15,16),(28,16)],OUTLINE,1.8);_line(d,p,[(23,11),(28,16),(23,21)],GREEN,2)
    return im.resize((int(size),int(size)),Image.Resampling.LANCZOS)

def tk_xray_icon(master,name,size=XRAY_ICON_SIZE):return ImageTk.PhotoImage(render_xray_icon(name,size),master=master)
