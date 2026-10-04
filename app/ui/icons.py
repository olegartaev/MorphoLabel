"""MorphoLabel's taxon-neutral, drawn icon family (no external font/assets)."""
from __future__ import annotations
from PIL import Image, ImageDraw

TOPBAR_ICON_SIZE=26
CONTROL_ICON_SIZE=28
WORKFLOW_ICON_SIZE=32
OUTLINE='#344f63'; MUTED='#8295a3'; PALE='#e5ebf0'; PALE_BLUE='#dfedf6'
BLUE='#246b9b'; RED='#bd4850'; GREEN='#27815c'; YELLOW='#bc872a'
ICON_NAMES=frozenset({
    'modules','project','crop','landmarks','structures','measurements','export',
    'missing','delete','clear','clear_type','verify','display','exclude','restore','review_worst','complex_qc',
    'help','models','train','predict','previous','next','close','flip_horizontal','flip_vertical',
    'crop_training','crop_train','crop_apply','landmark_repeat','landmark_training','landmark_train','landmark_apply',
    'measurement_calibrate','measurement_define','measurement_export','export_landmarks','export_measurements',
})


def render_icon(name: str, size: int=TOPBAR_ICON_SIZE):
    if name not in ICON_NAMES: raise KeyError(f'Unknown UI icon: {name}')
    if int(size)<12: raise ValueError('UI icons must be at least 12 px')
    side=int(size)*4; scale=side/32
    im=Image.new('RGBA',(side,side)); d=ImageDraw.Draw(im)
    p=lambda n:round(n*scale)
    box=lambda coords:tuple(p(n) for n in coords)
    def line(points,color=OUTLINE,width=1.9):
        pts=[(p(x),p(y)) for x,y in points];w=max(1,p(width))
        d.line(pts,fill=color,width=w,joint='curve')
        r=w/2
        for x,y in (pts[0],pts[-1]):d.ellipse((x-r,y-r,x+r,y+r),fill=color)
    def rect(coords,fill=PALE_BLUE,color=OUTLINE,width=1.8,r=2):
        d.rounded_rectangle(box(coords),radius=p(r),fill=fill,outline=color,width=max(1,p(width)))
    def dot(x,y,color=BLUE,r=2):d.ellipse(box((x-r,y-r,x+r,y+r)),fill=color)
    def arrow(a,b,color=BLUE,width=2):
        line([a,b],color,width);dx=b[0]-a[0];dy=b[1]-a[1];length=(dx*dx+dy*dy)**.5 or 1
        u,v=dx/length,dy/length
        line([(b[0]-u*4-v*3,b[1]-v*4+u*3),b,(b[0]-u*4+v*3,b[1]-v*4-u*3)],color,width)
    def check(cx=16,cy=17):line([(cx-6,cy),(cx-1,cy+5),(cx+8,cy-6)],GREEN,2.8)
    def card(x=5,y=5,w=22,h=22):
        rect((x,y,x+w,y+h),fill='#f8fbfd');dot(x+w-5,y+5,MUTED,1.4)
        line([(x+4,y+h-5),(x+9,y+h-11),(x+14,y+h-6),(x+w-4,y+h-9)],MUTED,1.4)
    def brackets():
        for pts in (((5,11),(5,5),(11,5)),((21,5),(27,5),(27,11)),((5,21),(5,27),(11,27)),((21,27),(27,27),(27,21))):line(pts,BLUE,2.2)
    def points(offset=0):
        pts=[(7+offset,22),(14+offset,10),(23+offset,19)]
        line(pts,MUTED,1.3)
        for x,y in pts:dot(x,y,BLUE,2.6)
    def chip():
        rect((9,9,23,23),fill=PALE_BLUE,color=BLUE)
        for x in (12,16,20):
            line([(x,5),(x,9)],OUTLINE,1.5);line([(x,23),(x,27)],OUTLINE,1.5)
            line([(5,x),(9,x)],OUTLINE,1.5);line([(23,x),(27,x)],OUTLINE,1.5)
        line([(12,18),(16,13),(20,18)],BLUE,1.4)
        for x,y in ((12,18),(16,13),(20,18)):dot(x,y,BLUE,1.4)
    def table():
        rect((5,5,22,27),fill='#f8fbfd')
        for y in (12,19):line([(6,y),(21,y)],MUTED,1)
        line([(12,6),(12,26)],MUTED,1)
    def ruler():
        rect((4,18,28,27),fill='#f8fbfd')
        for x in (8,12,16,20,24):line([(x,19),(x,22 if x%8 else 24)],BLUE,1.4)

    if name=='modules':
        for x,y in ((5,5),(18,5),(5,18),(18,18)):rect((x,y,x+9,y+9),r=2)
    elif name in {'project','crop_training','landmark_training'}:
        rect((9,4,28,23),fill=PALE,color=MUTED);card(4,9,20,19)
        if name=='landmark_training':
            dot(9,22);dot(15,15);dot(21,20)
    elif name=='crop':card(7,7,18,18);brackets()
    elif name in {'landmarks','export_landmarks'}:points()
    elif name=='structures':
        line([(5,17),(27,17)],MUTED,1.5)
        for x in (7,14,21):rect((x-2,12,x+2,22),fill='#f8fbfd',color=BLUE,width=1.5,r=1)
        line([(26,6),(26,26)],YELLOW,2.2)
    elif name in {'measurements','export_measurements','measurement_define'}:
        arrow((7,23),(25,9));arrow((25,9),(7,23));dot(7,23);dot(25,9)
        line([(4,20),(10,26)],MUTED,1.3);line([(22,6),(28,12)],MUTED,1.3)
    elif name in {'export','measurement_export'}:table();arrow((19,17),(29,17),BLUE,2.3)
    elif name=='missing':
        d.ellipse(box((7,7,25,25)),outline=MUTED,width=p(1.7))
        line([(11,16),(21,16)],MUTED,2.4)
    elif name=='delete':
        line([(7,9),(25,9)],RED,2);line([(12,6),(20,6)],RED,2)
        rect((9,10,23,27),fill=None,color=RED,r=2)
        for x in (13,19):line([(x,14),(x,23)],RED,1.6)
    elif name in {'clear','clear_type'}:
        d.polygon([tuple(map(p,xy)) for xy in ((7,20),(18,7),(27,15),(16,28))],fill=PALE_BLUE)
        line([(7,20),(18,7),(27,15),(16,28),(7,20)],OUTLINE,1.8)
        line([(12,14),(22,22)],BLUE,1.8);line([(6,28),(27,28)],MUTED,1.4)
        if name=='clear_type':dot(7,6,BLUE,2.7)
    elif name=='verify':check()
    elif name=='display':
        dot(7,9,BLUE,2.8);dot(14,9,YELLOW,2.8);dot(10,19,GREEN,2.8)
        line([(19,8),(28,8)],OUTLINE,2);line([(23.5,8),(23.5,25)],OUTLINE,2)
    elif name=='exclude':
        card(4,5,19,20);d.ellipse(box((18,18,30,30)),fill='#ffffff',outline=RED,width=p(2))
        line([(21,24),(27,24)],RED,2)
    elif name=='restore':card(5,8,20,19);arrow((27,13),(17,13));line([(27,13),(27,6),(21,6)],BLUE)
    elif name=='review_worst':
        line([(3,17),(8,10),(16,7),(24,10),(29,17),(24,24),(16,27),(8,24),(3,17)],OUTLINE,1.8)
        d.ellipse(box((11,12,21,22)),fill=PALE_BLUE,outline=BLUE,width=p(2));dot(16,17,BLUE,2)
    elif name=='complex_qc':
        line([(16,4),(27,8),(25,20),(16,28),(7,20),(5,8),(16,4)],OUTLINE,1.9);check(15,16)
    elif name=='help':
        d.ellipse(box((5,5,27,27)),outline=BLUE,width=p(1.8))
        d.arc(box((12,9,21,18)),180,445,fill=BLUE,width=p(2));line([(16,18),(16,20)],BLUE,2);dot(16,24,BLUE,1.3)
    elif name=='models':
        rect((7,4,27,23),fill=PALE,color=MUTED);rect((4,9,24,28),fill='#f8fbfd')
        for y,n in ((15,12),(20,18),(25,15)):line([(8,y),(n,y)],BLUE,1.8)
    elif name in {'train','crop_train','landmark_train'}:chip()
    elif name in {'predict','crop_apply','landmark_apply'}:
        card(11,5,17,23);arrow((3,16),(15,16),BLUE,2.4);dot(19,13);dot(23,20)
    elif name=='landmark_repeat':
        rect((3,7,14,26),fill='#f8fbfd');rect((18,7,29,26),fill='#f8fbfd')
        for x in (8,23):dot(x,13,BLUE,1.8);dot(x+2,20,BLUE,1.8)
        line([(14,4),(18,4)],MUTED,1.6);line([(14,29),(18,29)],MUTED,1.6)
    elif name=='measurement_calibrate':ruler();arrow((6,10),(26,10));arrow((26,10),(6,10))
    elif name in {'previous','next'}:
        line([(21,7),(12,16),(21,25)] if name=='previous' else [(11,7),(20,16),(11,25)],BLUE,2.7)
    elif name=='close':line([(9,9),(23,23)],OUTLINE,2.3);line([(23,9),(9,23)],OUTLINE,2.3)
    elif name in {'flip_horizontal','flip_vertical'}:
        horizontal=name=='flip_horizontal'
        if horizontal:
            line([(16,5),(16,27)],MUTED,1.2);arrow((13,16),(4,16));arrow((19,16),(28,16))
        else:
            line([(5,16),(27,16)],MUTED,1.2);arrow((16,13),(16,4));arrow((16,19),(16,28))
    return im.resize((int(size),int(size)),Image.Resampling.LANCZOS)


def tk_icon(master,name: str,size: int=TOPBAR_ICON_SIZE):
    from PIL import ImageTk
    return ImageTk.PhotoImage(render_icon(name,size),master=master)
