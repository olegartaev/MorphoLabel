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

CYAN="#49b8d6"
ORANGE="#f28e2b"
PURPLE="#8b5cf6"
PLATE="#eaf7fb"

def _ctx(size):
    aa=4;side=int(size)*aa;im=Image.new("RGBA",(side,side),(0,0,0,0));d=ImageDraw.Draw(im);s=side/32
    p=lambda v:int(round(v*s));w=lambda v:max(1,p(v));return im,d,p,w

def _line(d,p,pts,fill=OUTLINE,width=2):
    d.line([(p(x),p(y)) for x,y in pts],fill=fill,width=max(1,p(width)),joint="curve")

def _dot(d,p,x,y,fill=BLUE,r=2.2,shape="circle"):
    b=(p(x-r),p(y-r),p(x+r),p(y+r))
    if shape=="circle":d.ellipse(b,fill=fill,outline=OUTLINE,width=max(1,p(.8)))
    elif shape=="square":d.rectangle(b,fill=fill,outline=OUTLINE,width=max(1,p(.8)))
    elif shape=="diamond":d.polygon([(p(x),p(y-r-1)),(p(x+r+1),p(y)),(p(x),p(y+r+1)),(p(x-r-1),p(y))],fill=fill,outline=OUTLINE)
    elif shape=="triangle":d.polygon([(p(x),p(y-r-1)),(p(x+r+1),p(y+r)),(p(x-r-1),p(y+r))],fill=fill,outline=OUTLINE)

def _plate(d,p,x0=3,y0=4,x1=29,y1=28):
    d.rounded_rectangle((p(x0),p(y0),p(x1),p(y1)),radius=p(3),fill=PLATE,outline=CYAN,width=max(1,p(1.4)))
    d.rounded_rectangle((p(x0+2),p(y0+2),p(x1-2),p(y1-2)),radius=p(2),outline="#b8dce8",width=max(1,p(.8)))

def _fish_skeleton(d,p,*,cx=16,cy=16,scale=1.0,accent=BLUE):
    """Tiny taxon-specific cue for the current X-ray module; architecture stays taxon-neutral."""
    q=lambda x:cx+(x-16)*scale
    r=lambda y:cy+(y-16)*scale
    # skull and tail outline
    d.ellipse((p(q(5)),p(r(12)),p(q(10)),p(r(18))),fill="#f8fbfd",outline=OUTLINE,width=max(1,p(1.2)))
    d.polygon([(p(q(26)),p(r(16))),(p(q(30)),p(r(11))),(p(q(29)),p(r(16))),(p(q(30)),p(r(21)))],fill="#d7edf4",outline=OUTLINE)
    # spine / vertebral centres
    _line(d,p,[(q(9),r(15)),(q(27),r(16))],OUTLINE,1.2)
    for x,y in ((10,15),(13,15.2),(16,15.4),(19,15.6),(22,15.8),(25,16)):
        d.ellipse((p(q(x-.8)),p(r(y-.8)),p(q(x+.8)),p(r(y+.8))),fill="#ffffff",outline=accent,width=max(1,p(.75)))
    # ribs and fin supports
    for x in (12,15,18,21):
        _line(d,p,[(q(x),r(16)),(q(x-1.2),r(21))],MUTED,.9)
    _line(d,p,[(q(18),r(14.6)),(q(20),r(10))],MUTED,1)
    _line(d,p,[(q(21),r(16)),(q(22),r(22))],MUTED,1)
    d.ellipse((p(q(6.2)),p(r(14)),p(q(7.2)),p(r(15))),fill=accent)

def _crop_brackets(d,p,color=BLUE):
    for pts in [((4,10),(4,5),(10,5)),((22,5),(28,5),(28,10)),((4,22),(4,27),(10,27)),((22,27),(28,27),(28,22))]:
        _line(d,p,pts,color,2.1)

def _table(d,p,x0=16,y0=8,x1=29,y1=25):
    d.rounded_rectangle((p(x0),p(y0),p(x1),p(y1)),radius=p(1.5),fill="#ffffff",outline=OUTLINE,width=max(1,p(1.1)))
    for y in (13.5,19):_line(d,p,[(x0,y),(x1,y)],MUTED,.8)
    _line(d,p,[(22.5,y0),(22.5,y1)],MUTED,.8)

def render_xray_icon(name,size=XRAY_ICON_SIZE):
    if name not in XRAY_ICON_NAMES:raise KeyError(name)
    im,d,p,w=_ctx(size)
    if name=="xray":
        _plate(d,p);_fish_skeleton(d,p,accent=CYAN)
    elif name=="xray_project":
        _plate(d,p);_fish_skeleton(d,p,cx=18,cy=17,scale=.78,accent=BLUE)
        d.rounded_rectangle((p(3),p(3),p(14),p(10)),radius=p(1.5),fill=YELLOW,outline=OUTLINE,width=w(.9))
        _line(d,p,[(6,6.5),(11,6.5)],OUTLINE,.8)
    elif name=="xray_crops":
        _plate(d,p);_fish_skeleton(d,p,scale=.8,accent=CYAN);_crop_brackets(d,p,ORANGE)
    elif name=="xray_structures":
        _plate(d,p);_fish_skeleton(d,p,scale=.82,accent=CYAN)
        _dot(d,p,12,15,ORANGE,2.1,"circle");_dot(d,p,19,16,GREEN,2.3,"triangle");_dot(d,p,24,16,PURPLE,2.2,"diamond")
    elif name=="xray_results":
        _plate(d,p,2,5,17,27);_fish_skeleton(d,p,cx=9.5,cy=16,scale=.45,accent=CYAN);_table(d,p)
        _line(d,p,[(25,5),(27,7),(30,3)],GREEN,2)
    elif name=="xray_export":
        _plate(d,p,3,6,20,27);_fish_skeleton(d,p,cx=11.5,cy=17,scale=.48,accent=CYAN)
        _line(d,p,[(20,23),(29,14)],GREEN,2.4);d.polygon([(p(29),p(14)),(p(24),p(15)),(p(28),p(19))],fill=GREEN)
    elif name in {"count","count_to","count_between","position"}:
        for x in (7,12,17,22,27):_dot(d,p,x,17,CYAN,1.8)
        _line(d,p,[(6,10),(28,10)],MUTED,1.1)
        if name=="count":
            d.rounded_rectangle((p(5),p(5),p(13),p(11)),radius=p(1),fill=YELLOW,outline=OUTLINE,width=w(.8))
        elif name=="count_to":
            _line(d,p,[(23,6),(23,27)],RED,2)
        elif name=="count_between":
            _line(d,p,[(8,6),(8,27)],RED,2);_line(d,p,[(24,6),(24,27)],RED,2)
        else:
            _line(d,p,[(17,5),(17,11)],ORANGE,2.4);d.polygon([(p(17),p(12)),(p(14),p(8)),(p(20),p(8))],fill=ORANGE)
    elif name=="presence":
        _fish_skeleton(d,p,cx=12,cy=16,scale=.55,accent=CYAN);_line(d,p,[(19,17),(23,21),(30,9)],GREEN,3)
    elif name=="distance":
        _dot(d,p,7,22,CYAN,2.3);_dot(d,p,25,9,ORANGE,2.3);_line(d,p,[(8,21),(24,10)],BLUE,2);_line(d,p,[(6,26),(27,26)],MUTED,1)
    elif name=="angle":
        _line(d,p,[(7,24),(16,9),(28,24)],CYAN,2.3);d.arc((p(10),p(14),p(22),p(27)),210,330,fill=ORANGE,width=w(2))
    elif name=="derived":
        d.rounded_rectangle((p(4),p(6),p(13),p(16)),radius=p(2),fill=PALE_BLUE,outline=BLUE,width=w(1));d.text((p(6),p(6)),"ƒ",fill=BLUE)
        _line(d,p,[(15,16),(28,16)],OUTLINE,1.8);_line(d,p,[(23,11),(28,16),(23,21)],GREEN,2)
    return im.resize((int(size),int(size)),Image.Resampling.LANCZOS)

def tk_xray_icon(master,name,size=XRAY_ICON_SIZE):
    return ImageTk.PhotoImage(render_xray_icon(name,size),master=master)
