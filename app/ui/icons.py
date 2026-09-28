"""Compact generic UI icons for MorphoLabel.

All symbols are taxon-neutral and are drawn programmatically so installed builds
need no loose image assets.  Supersampling keeps the small 18–24 px controls
crisp on Windows.
"""
from __future__ import annotations

import math
from PIL import Image, ImageDraw

TOPBAR_ICON_SIZE=26
CONTROL_ICON_SIZE=20
WORKFLOW_ICON_SIZE=24

OUTLINE="#465d73"
MUTED="#91a1b2"
PALE="#dfe7ef"
PALE_BLUE="#d9e9fa"
BLUE="#1976e9"
RED="#ef2f35"
GREEN="#20a447"
YELLOW="#f5a623"

ICON_NAMES=frozenset({
    "modules","project","crop","landmarks","measurements","export",
    "missing","delete","clear","verify","display","exclude","restore","review_worst","complex_qc",
    "crop_training","crop_train","crop_apply",
    "landmark_repeat","landmark_training","landmark_train","landmark_apply",
    "measurement_calibrate","measurement_define","measurement_export",
    "export_landmarks","export_measurements",
})

def _renderer(size:int):
    if int(size)<12:raise ValueError("UI icons must be at least 12 px")
    aa=4;side=int(size)*aa
    image=Image.new("RGBA",(side,side),(0,0,0,0));draw=ImageDraw.Draw(image)
    scale=side/32.0
    p=lambda value:int(round(float(value)*scale))
    box=lambda values:tuple(p(value) for value in values)
    width=lambda value:max(1,p(value))
    return image,draw,p,box,width

def _line(draw,p,points,fill=OUTLINE,width=2):
    draw.line([(p(x),p(y)) for x,y in points],fill=fill,width=max(1,p(width)),joint="curve")

def _blob(draw,p,coords,fill=PALE,outline=OUTLINE,width=2):
    x0,y0,x1,y1=coords
    points=[(x0+2,y0+8),(x0+6,y0+3),(x0+13,y0+4),(x0+18,y0+1),(x0+24,y0+5),(x0+26,y0+11),(x0+22,y0+17),(x0+14,y0+19),(x0+7,y0+17),(x0+2,y0+13)]
    scaled=[(p(x),p(y)) for x,y in points]
    draw.polygon(scaled,fill=fill);draw.line(scaled+[scaled[0]],fill=outline,width=max(1,p(width)),joint="curve")

def _dot(draw,p,x,y,color,r=2.4,outline=OUTLINE):
    draw.ellipse((p(x-r),p(y-r),p(x+r),p(y+r)),fill=color,outline=outline,width=max(1,p(1)))

def _dash(draw,p,a,b,fill=OUTLINE,width=1.4,segments=4):
    x0,y0=a;x1,y1=b
    for i in range(segments):
        start=i/segments;end=min(1.0,start+0.55/segments)
        draw.line((p(x0+(x1-x0)*start),p(y0+(y1-y0)*start),p(x0+(x1-x0)*end),p(y0+(y1-y0)*end)),fill=fill,width=max(1,p(width)))

def _arrow(draw,p,a,b,color=BLUE,width=2,double=False):
    x0,y0=a;x1,y1=b;_line(draw,p,[a,b],color,width)
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

def _crop_brackets(draw,p,color=BLUE):
    for pts in [((5,11),(5,5),(11,5)),((21,5),(27,5),(27,11)),((5,21),(5,27),(11,27)),((21,27),(27,27),(27,21))]:
        _line(draw,p,pts,color,2.4)

def _landmark_triangle(draw,p,offset_x=0,color=BLUE,scale=1.0):
    pts=[(8+offset_x,22),(16+offset_x,8),(24+offset_x,22)]
    pts=[(16+(x-16)*scale,16+(y-16)*scale) for x,y in pts]
    _line(draw,p,[pts[0],pts[1],pts[2],pts[0]],color,1.8)
    for x,y in pts:_dot(draw,p,x,y,color,2.0,outline=color)

def _sparkle(draw,p,x=24,y=9,color=YELLOW):
    draw.polygon([(p(x),p(y-5)),(p(x+2),p(y-2)),(p(x+5),p(y)),(p(x+2),p(y+2)),(p(x),p(y+5)),(p(x-2),p(y+2)),(p(x-5),p(y)),(p(x-2),p(y-2))],fill=color)

def _check(draw,p,x=23,y=22):
    _line(draw,p,[(x-5,y),(x-1,y+4),(x+6,y-5)],GREEN,3.0)

def _ruler(draw,p,x0=5,y0=18,x1=27,y1=26):
    draw.rounded_rectangle((p(x0),p(y0),p(x1),p(y1)),radius=p(1),fill="#f8fbfd",outline=OUTLINE,width=max(1,p(1.5)))
    for x in range(int(x0+3),int(x1-1),4):
        _line(draw,p,[(x,y0),(x,y0+3 if x%8 else y0+5)],BLUE,1.0)

def _table(draw,p,x0=5,y0=7,x1=20,y1=25):
    draw.rectangle((p(x0),p(y0),p(x1),p(y1)),fill="#f8fbfd",outline=BLUE,width=max(1,p(1.6)))
    for y in (13,19):_line(draw,p,[(x0,y),(x1,y)],BLUE,1)
    for x in (10,15):_line(draw,p,[(x,y0),(x,y1)],BLUE,1)

def _export_up(draw,p,x=25,y=18):
    _line(draw,p,[(x,y+7),(x,y-5)],GREEN,2.2)
    draw.polygon([(p(x),p(y-7)),(p(x-4),p(y-2)),(p(x+4),p(y-2))],fill=GREEN)
    _line(draw,p,[(x-6,y+1),(x-6,y+7),(x+6,y+7),(x+6,y+1)],GREEN,1.6)

def _dotted_circle(draw,p,cx,cy,r=4,color=MUTED):
    for start in range(0,360,90):
        draw.arc((p(cx-r),p(cy-r),p(cx+r),p(cy+r)),start=start,end=start+52,fill=color,width=max(1,p(1.6)))

def render_icon(name:str,size:int=TOPBAR_ICON_SIZE):
    """Return a supersampled transparent RGBA Pillow image."""
    if name not in ICON_NAMES:raise KeyError(f"Unknown UI icon: {name}")
    image,draw,p,box,width=_renderer(size)

    if name=="modules":
        for x,y in ((6,6),(18,6),(6,18),(18,18)):
            draw.rounded_rectangle(box((x,y,x+8,y+8)),radius=p(1.5),fill=PALE_BLUE,outline=OUTLINE,width=width(1.5))
    elif name=="project":
        _image_card(draw,p,9,5,27,20,outline=MUTED,fill="#f4f7fa");_image_card(draw,p,5,10,24,27)
    elif name=="crop":
        _blob(draw,p,(5,7,27,26),fill=PALE);_crop_brackets(draw,p)
    elif name=="landmarks":
        _blob(draw,p,(3,6,29,25),fill="#eef3f7")
        _dash(draw,p,(9,16),(16,9),MUTED);_dash(draw,p,(16,9),(24,16),MUTED);_dash(draw,p,(9,16),(16,23),MUTED);_dash(draw,p,(16,23),(24,16),MUTED)
        for x,y,c in ((16,8,BLUE),(8,16,RED),(24,16,GREEN),(16,24,YELLOW)):_dot(draw,p,x,y,c)
    elif name=="measurements":
        _blob(draw,p,(3,6,29,25),fill="#eef3f7");_arrow(draw,p,(9,23),(24,8),BLUE,2.4,True);_dot(draw,p,9,23,BLUE,1.8);_dot(draw,p,24,8,BLUE,1.8)
    elif name=="export":
        draw.rounded_rectangle(box((5,5,21,27)),radius=p(2),fill="#f9fbfd",outline=OUTLINE,width=width(1.8))
        for y in (11,15,19):_line(draw,p,[(9,y),(17,y)],MUTED,1.2)
        _arrow(draw,p,(19,16),(28,16),GREEN,2.6)

    # Compact landmark/photo actions selected from the UI mockups.
    elif name=="missing":
        _dot(draw,p,7,21,BLUE,3.2,outline=BLUE)
        _arrow(draw,p,(10,19),(18,12),BLUE,2.0)
        _dotted_circle(draw,p,23,9,4,MUTED)
    elif name=="delete":
        _line(draw,p,[(8,8),(24,24)],RED,4.0);_line(draw,p,[(24,8),(8,24)],RED,4.0)
    elif name=="clear":
        _line(draw,p,[(23,6),(12,19)],OUTLINE,3.0)
        draw.polygon([(p(9),p(18)),(p(15),p(22)),(p(10),p(27)),(p(5),p(23))],fill=BLUE)
        for x,y in ((20,23),(25,25),(23,19)):_dot(draw,p,x,y,RED,1.2,outline=RED)
    elif name=="verify":
        _check(draw,p,16,16)
    elif name=="display":
        for x,y,c in ((7,9,BLUE),(15,9,RED),(11,18,GREEN)):_dot(draw,p,x,y,c,2.5,outline=c)
        _line(draw,p,[(20,8),(29,8)],OUTLINE,2.2);_line(draw,p,[(24.5,8),(24.5,25)],OUTLINE,2.2)
    elif name=="exclude":
        _image_card(draw,p,4,6,23,24,outline=OUTLINE,fill="#f4f7fa")
        draw.ellipse(box((19,18,30,29)),fill="#ffffff",outline=RED,width=width(2.3))
        _line(draw,p,[(21,27),(28,20)],RED,2.3)
    elif name=="restore":
        _image_card(draw,p,5,7,24,25,outline=OUTLINE,fill="#f4f7fa");_line(draw,p,[(26,20),(26,12),(18,12)],BLUE,2.4)
        draw.polygon([(p(18),p(12)),(p(22),p(8)),(p(22),p(16))],fill=BLUE)
    elif name=="review_worst":
        draw.polygon([(p(3),p(16)),(p(8),p(10)),(p(16),p(7)),(p(24),p(10)),(p(29),p(16)),(p(24),p(22)),(p(16),p(25)),(p(8),p(22))],fill="#f7fbff",outline=BLUE)
        draw.ellipse(box((11,11,21,21)),fill=BLUE)
        draw.ellipse(box((14,14,18,18)),fill="#ffffff")
        _sparkle(draw,p,26,7,YELLOW)
    elif name=="complex_qc":
        shield=[(16,3),(27,7),(25,20),(16,29),(7,20),(5,7)]
        draw.polygon([(p(x),p(y)) for x,y in shield],fill="#f7fbff",outline=BLUE)
        _check(draw,p,16,16)

    # Crop workflow: selected A / B / A.
    elif name=="crop_training":
        _image_card(draw,p,10,5,27,20,outline=MUTED,fill="#f4f7fa");_image_card(draw,p,5,11,23,27)
    elif name=="crop_train":
        _crop_brackets(draw,p);_sparkle(draw,p,16,16,YELLOW)
    elif name=="crop_apply":
        _crop_brackets(draw,p);draw.ellipse(box((17,17,30,30)),fill="#ffffff",outline=GREEN,width=width(1.3));_check(draw,p,23,22)

    # Landmarks workflow: selected C / A / A / A.
    elif name=="landmark_repeat":
        _landmark_triangle(draw,p,-8,BLUE,.62);_line(draw,p,[(14,13),(18,13)],OUTLINE,1.8);_line(draw,p,[(14,18),(18,18)],OUTLINE,1.8);_landmark_triangle(draw,p,8,BLUE,.62)
    elif name=="landmark_training":
        for dx,dy in ((5,3),(2,1)):_image_card(draw,p,6+dx,5+dy,27+dx,27+dy,outline=MUTED,fill="#f7fafc")
        _image_card(draw,p,5,5,25,27,outline=OUTLINE,fill="#f9fbfd");_landmark_triangle(draw,p,0,BLUE,.52)
    elif name=="landmark_train":
        _landmark_triangle(draw,p,-3,BLUE,.72);_sparkle(draw,p,25,8,YELLOW)
    elif name=="landmark_apply":
        _image_card(draw,p,4,5,24,27,outline=OUTLINE,fill="#f9fbfd");_landmark_triangle(draw,p,-3,BLUE,.48);draw.ellipse(box((18,18,30,30)),fill="#ffffff",outline=GREEN,width=width(1.2));_check(draw,p,24,23)

    # Measurements workflow: selected B / C / B.
    elif name=="measurement_calibrate":
        _ruler(draw,p,5,18,27,27);_line(draw,p,[(8,10),(24,10)],BLUE,2.0);_dot(draw,p,8,10,BLUE,2.3,outline=BLUE);_dot(draw,p,24,10,BLUE,2.3,outline=BLUE)
    elif name=="measurement_define":
        _line(draw,p,[(6,18),(24,18)],BLUE,2.2);_dot(draw,p,6,18,BLUE,2.5,outline=BLUE);_dot(draw,p,24,18,BLUE,2.5,outline=BLUE)
        draw.polygon([(p(22),p(8)),(p(29),p(8)),(p(30),p(14)),(p(26),p(18)),(p(22),p(14))],fill="#f8fbfd",outline=OUTLINE)
        _dot(draw,p,26,11,MUTED,1.0,outline=MUTED)
    elif name=="measurement_export":
        _table(draw,p,4,6,19,25);_export_up(draw,p,25,17)

    # Export cards: selected B / B.
    elif name=="export_landmarks":
        for x,y in ((6,8),(5,20),(13,15)):_dot(draw,p,x,y,BLUE,2.2,outline=BLUE)
        _line(draw,p,[(19,24),(19,8),(28,8)],OUTLINE,1.7);draw.polygon([(p(19),p(6)),(p(16.5),p(10)),(p(21.5),p(10))],fill=OUTLINE);draw.polygon([(p(30),p(8)),(p(26),p(5.5)),(p(26),p(10.5))],fill=OUTLINE)
    elif name=="export_measurements":
        _arrow(draw,p,(7,16),(25,16),BLUE,2.2,True);_dot(draw,p,6,16,BLUE,2.4,outline=BLUE);_dot(draw,p,26,16,BLUE,2.4,outline=BLUE)

    return image.resize((int(size),int(size)),Image.Resampling.LANCZOS)

def tk_icon(master,name:str,size:int=TOPBAR_ICON_SIZE):
    """Create a Tk image; callers keep the returned reference for widget lifetime."""
    from PIL import ImageTk
    return ImageTk.PhotoImage(render_icon(name,size),master=master)
