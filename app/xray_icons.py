"""X-ray icons for MorphoLabel.

The top-level workflow icons use the same restrained palette and line weights as
MorphoLabel, but each has a distinct anatomical silhouette so the five X-ray
stages are recognisable at a glance.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageTk
from app.ui.icons import OUTLINE, MUTED, PALE, PALE_BLUE, BLUE, GREEN, RED, YELLOW

XRAY_ICON_SIZE=30
TRAIT_ICON_SIZE=26
XRAY_ICON_NAMES=frozenset({
    "xray","xray_project","xray_crops","xray_structures","xray_results","xray_export",
    "count","count_to","count_between","position","presence","distance","angle","derived",
})

XRAY_DARK="#31485b"
XRAY_MID="#73899a"
XRAY_PAPER="#f8fbfd"
XRAY_FILM="#e6f0f6"
ACCENT_ORANGE="#e88727"


def _ctx(size):
    if int(size)<12:raise ValueError("X-ray icons must be at least 12 px")
    aa=4;side=int(size)*aa;im=Image.new("RGBA",(side,side),(0,0,0,0));d=ImageDraw.Draw(im);s=side/32
    p=lambda v:int(round(float(v)*s));w=lambda v:max(1,p(v));return im,d,p,w


def _line(d,p,pts,fill=OUTLINE,width=2):
    d.line([(p(x),p(y)) for x,y in pts],fill=fill,width=max(1,p(width)),joint="curve")


def _node(d,p,x,y,fill="#ffffff",outline=XRAY_DARK,r=1.35,width=.8):
    d.ellipse((p(x-r),p(y-r),p(x+r),p(y+r)),fill=fill,outline=outline,width=max(1,p(width)))


def _film(d,p,x0=2.5,y0=3,x1=29.5,y1=28.5,accent=BLUE):
    d.rounded_rectangle((p(x0),p(y0),p(x1),p(y1)),radius=p(2.6),fill=XRAY_PAPER,outline=XRAY_DARK,width=max(1,p(1.4)))
    d.rounded_rectangle((p(x0+2),p(y0+2),p(x1-2),p(y1-2)),radius=p(1.6),fill=XRAY_FILM,outline=accent,width=max(1,p(.75)))
    _line(d,p,[(x0+5,y0+4),(x1-5,y0+4)],XRAY_MID,.55)


def _fish_body(d,p,cx=16,cy=16,scale=1.0,fill="#f3f7fa",outline=XRAY_MID):
    q=lambda x:cx+(x-16)*scale;r=lambda y:cy+(y-16)*scale
    pts=[
        (q(4),r(16)),(q(7),r(11.2)),(q(13),r(9.5)),(q(20.5),r(10.3)),
        (q(25.5),r(13.2)),(q(29.2),r(10.5)),(q(28.1),r(15.8)),
        (q(29.2),r(21.2)),(q(25.5),r(18.5)),(q(20.5),r(21.3)),
        (q(13),r(22.3)),(q(7),r(20.6)),
    ]
    scaled=[(p(x),p(y)) for x,y in pts]
    d.polygon(scaled,fill=fill)
    d.line(scaled+[scaled[0]],fill=outline,width=max(1,p(.8)),joint="curve")


def _fish_skeleton(d,p,cx=16,cy=16,scale=1.0,accent=BLUE,body=True):
    q=lambda x:cx+(x-16)*scale;r=lambda y:cy+(y-16)*scale
    if body:_fish_body(d,p,cx,cy,scale)
    # skull: recognisable wedge + orbit rather than a generic circle
    skull=[(q(5.0),r(15.8)),(q(7.2),r(12.8)),(q(10.0),r(13.7)),(q(10.3),r(17.5)),(q(7.4),r(19.0))]
    d.polygon([(p(x),p(y)) for x,y in skull],fill="#ffffff",outline=XRAY_DARK)
    _node(d,p,q(7.1),r(14.7),fill=accent,outline=accent,r=.65,width=.4)
    # vertebral column with explicit centra
    _line(d,p,[(q(9.4),r(16.0)),(q(25.5),r(16.0))],XRAY_DARK,1.1)
    for x in (10.4,12.8,15.2,17.6,20.0,22.4,24.8):
        _node(d,p,q(x),r(16),fill="#ffffff",outline=accent,r=1.05,width=.65)
    # neural / haemal spines and ribs
    for x in (12.3,15.0,17.7,20.4):
        _line(d,p,[(q(x),r(15.4)),(q(x+.5),r(12.0))],XRAY_MID,.75)
        _line(d,p,[(q(x),r(16.6)),(q(x-.9),r(20.1))],XRAY_MID,.8)
    for x in (13.7,16.4,19.1):
        _line(d,p,[(q(x),r(16.8)),(q(x+1.6),r(21.0))],XRAY_MID,.6)
    # caudal fin rays
    for yy in (11.8,14.0,16.0,18.0,20.2):
        _line(d,p,[(q(25.2),r(16)),(q(29),r(yy))],XRAY_MID,.7)


def _folder(d,p):
    d.rounded_rectangle((p(3),p(8),p(29),p(27)),radius=p(2),fill=XRAY_PAPER,outline=XRAY_DARK,width=max(1,p(1.3)))
    d.polygon([(p(3),p(10)),(p(3),p(6)),(p(13),p(6)),(p(16),p(10))],fill=PALE_BLUE,outline=XRAY_DARK)
    _line(d,p,[(4,11),(28,11)],MUTED,.7)


def _crop_brackets(d,p,color=BLUE):
    for pts in [((4.5,11),(4.5,5),(10.5,5)),((21.5,5),(27.5,5),(27.5,11)),((4.5,21),(4.5,27),(10.5,27)),((21.5,27),(27.5,27),(27.5,21))]:
        _line(d,p,pts,color,2.5)


def _structure_badges(d,p):
    _node(d,p,12.0,16.0,fill=BLUE,outline="#ffffff",r=2.1,width=.7)
    d.polygon([(p(18.5),p(12.8)),(p(21.1),p(18.1)),(p(15.9),p(18.1))],fill=GREEN,outline="#ffffff")
    d.rectangle((p(22.4),p(13.8),p(27.0),p(18.4)),fill=ACCENT_ORANGE,outline="#ffffff",width=max(1,p(.7)))


def _table(d,p,x0=15.5,y0=7,x1=29,y1=25):
    d.rounded_rectangle((p(x0),p(y0),p(x1),p(y1)),radius=p(1.2),fill="#ffffff",outline=XRAY_DARK,width=max(1,p(1.1)))
    d.rectangle((p(x0+1),p(y0+1),p(x1-1),p(y0+5)),fill=PALE_BLUE)
    for y in (13.2,18.7):_line(d,p,[(x0,y),(x1,y)],MUTED,.65)
    _line(d,p,[(21.8,y0),(21.8,y1)],MUTED,.65)
    _line(d,p,[(24.0,11),(27.0,11)],GREEN,1.1)
    _line(d,p,[(24.0,16),(27.0,16)],BLUE,1.1)


def _document(d,p,x0=5,y0=4,x1=23,y1=28):
    d.rounded_rectangle((p(x0),p(y0),p(x1),p(y1)),radius=p(1.6),fill="#ffffff",outline=XRAY_DARK,width=max(1,p(1.2)))
    d.polygon([(p(x1-5),p(y0)),(p(x1),p(y0+5)),(p(x1-5),p(y0+5))],fill=PALE_BLUE,outline=XRAY_DARK)
    _line(d,p,[(x0+4,y0+10),(x1-4,y0+10)],MUTED,.75)
    _line(d,p,[(x0+4,y0+14),(x1-4,y0+14)],MUTED,.75)

def _export_arrow(d,p):
    _line(d,p,[(24,23),(24,11)],GREEN,1.8)
    d.polygon([(p(24),p(8)),(p(20.8),p(13)),(p(27.2),p(13))],fill=GREEN)
    _line(d,p,[(19,21),(19,25),(29,25),(29,21)],XRAY_DARK,1.1)


def render_xray_icon(name,size=XRAY_ICON_SIZE):
    if name not in XRAY_ICON_NAMES:raise KeyError(name)
    im,d,p,w=_ctx(size)

    # Main workflow icons: different silhouette + shared visual language.
    if name=="xray":
        # Module identity: a clean radiograph with the skeleton as the only focal object.
        _film(d,p);_fish_skeleton(d,p,scale=.92,accent=BLUE)
    elif name=="xray_project":
        # Project: folder sits behind a small radiograph; anatomy must remain visible.
        _folder(d,p)
        _film(d,p,11.0,9.0,30.0,27.5,accent=BLUE)
        _fish_skeleton(d,p,cx=20.5,cy=18.2,scale=.52,accent=BLUE)
    elif name=="xray_crops":
        # Crops: skeleton/radiograph plus the same corner-bracket language as MorphoLabel.
        _film(d,p);_fish_skeleton(d,p,scale=.78,accent=XRAY_DARK)
        _crop_brackets(d,p,BLUE)
    elif name=="xray_structures":
        # Structures: skeleton is central; coloured markers sit on anatomical positions.
        _film(d,p);_fish_skeleton(d,p,scale=.80,accent=XRAY_DARK)
        _node(d,p,12.4,16.0,fill=BLUE,outline="#ffffff",r=2.0,width=.7)
        d.polygon([(p(19.0),p(12.5)),(p(21.5),p(17.7)),(p(16.5),p(17.7))],fill=GREEN,outline="#ffffff")
        d.rectangle((p(22.8),p(15.0),p(27.0),p(19.2)),fill=ACCENT_ORANGE,outline="#ffffff",width=max(1,p(.7)))
    elif name=="xray_results":
        # Results: mini radiograph/skeleton feeding into a compact scientific table.
        _film(d,p,2.5,4.0,15.2,27.5,accent=BLUE)
        _fish_skeleton(d,p,cx=8.8,cy=16.2,scale=.34,accent=BLUE)
        _table(d,p,14.5,6.5,29.5,26.0)
        _line(d,p,[(22.5,11.2),(27.0,11.2)],GREEN,1.1)
        _line(d,p,[(22.5,16.3),(27.0,16.3)],BLUE,1.1)
    elif name=="xray_export":
        # Export: report containing the skeleton plus the shared outward-action cue.
        _document(d,p,3.0,4.0,23.0,28.0)
        _fish_skeleton(d,p,cx=12.0,cy=18.0,scale=.45,accent=BLUE,body=False)
        _line(d,p,[(20.5,17.0),(29.0,17.0)],GREEN,2.4)
        d.polygon([(p(30.0),p(17.0)),(p(25.2),p(13.5)),(p(25.2),p(20.5))],fill=GREEN)

    # Trait-method icons: scientific diagrams, compact and deliberately quieter.
    elif name in {"count","count_to","count_between","position"}:
        _line(d,p,[(5,17),(28,17)],XRAY_MID,.8)
        for x in (7,12,17,22,27):_node(d,p,x,17,outline=BLUE,r=1.25,width=.7)
        if name=="count":
            _line(d,p,[(7,8.5),(27,8.5)],XRAY_DARK,1.0)
            _line(d,p,[(7,6.5),(7,10.5)],XRAY_DARK,1.0);_line(d,p,[(27,6.5),(27,10.5)],XRAY_DARK,1.0)
        elif name=="count_to":
            _line(d,p,[(23,6),(23,27)],RED,1.8)
        elif name=="count_between":
            _line(d,p,[(8,6),(8,27)],RED,1.8);_line(d,p,[(24,6),(24,27)],RED,1.8)
        else:
            _line(d,p,[(17,5.5),(17,12)],XRAY_DARK,1.6)
            d.polygon([(p(17),p(13)),(p(14),p(9)),(p(20),p(9))],fill=XRAY_DARK)
    elif name=="presence":
        _fish_body(d,p,10.5,16,.45,fill=XRAY_FILM,outline=XRAY_MID);_fish_skeleton(d,p,10.5,16,.38,accent=BLUE,body=False)
        _line(d,p,[(19.5,17),(23.5,21),(30,10)],GREEN,2.5)
    elif name=="distance":
        _node(d,p,7,23,fill=BLUE,outline=BLUE,r=1.8);_node(d,p,25,9,fill=BLUE,outline=BLUE,r=1.8)
        _line(d,p,[(8.5,21.7),(23.5,10.3)],XRAY_DARK,1.4)
        _line(d,p,[(7,27),(25,27)],MUTED,.8)
    elif name=="angle":
        _line(d,p,[(6,24),(16,9),(28,24)],XRAY_DARK,1.8)
        d.arc((p(10),p(14),p(22),p(27)),210,330,fill=BLUE,width=w(1.7))
    elif name=="derived":
        d.rounded_rectangle((p(4),p(7),p(12),p(15)),radius=p(.8),fill="#ffffff",outline=XRAY_DARK,width=w(1))
        d.rounded_rectangle((p(4),p(18),p(12),p(26)),radius=p(.8),fill="#ffffff",outline=XRAY_DARK,width=w(1))
        _line(d,p,[(13,11),(20,16),(13,22)],MUTED,1.2)
        _line(d,p,[(20,16),(29,16)],GREEN,2)
        d.polygon([(p(29),p(16)),(p(25),p(13)),(p(25),p(19))],fill=GREEN)

    return im.resize((int(size),int(size)),Image.Resampling.LANCZOS)


def tk_xray_icon(master,name,size=XRAY_ICON_SIZE):
    return ImageTk.PhotoImage(render_xray_icon(name,size),master=master)
