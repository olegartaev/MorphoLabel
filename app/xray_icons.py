"""X-ray icons for MorphoLabel.

The top-level workflow icons use the same restrained palette and line weights as
MorphoLabel, but each has a distinct anatomical silhouette so the five X-ray
stages are recognisable at a glance.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont, ImageTk
from app.ui.icons import OUTLINE, MUTED, PALE_BLUE, BLUE, GREEN, RED, render_icon

XRAY_ICON_SIZE=26
TRAIT_ICON_SIZE=20
XRAY_ICON_NAMES=frozenset({
    "xray","xray_project","xray_crops","xray_structures","xray_results","xray_export",
    "count","count_to","count_between","position","presence","distance","angle","derived","counted_element","reference_mark","annotation_setup","trait_setup",
    "flip_horizontal","flip_vertical","delete_crop","clear_crops",
    "structure_apply","structure_previous","structure_next","clear_marker_set","clear_all_markers",
})

XRAY_DARK="#31485b"
XRAY_MID="#73899a"
XRAY_PAPER="#f8fbfd"
XRAY_FILM="#e6f0f6"
ACCENT_ORANGE="#ffb000"  # same ventral-side orange used on the X-ray crop canvas
VISIBILITY_ICON_SIZE=32
VISIBILITY_STATES=("complete","partial","not_visible","absent")


def render_visibility_icon(state,size=VISIBILITY_ICON_SIZE):
    """Readable biological visibility states; absent is deliberately not an eye."""
    state=str(state)
    if state not in VISIBILITY_STATES:raise KeyError(f"Unknown visibility state: {state}")
    im,d,p,w=_ctx(size)

    def eye(outline=XRAY_DARK,iris=BLUE,fill="#ffffff"):
        # Almond silhouette with separate lids, iris and pupil remains legible at 24–40 px.
        upper=[(4.0,16.0),(7.5,11.4),(12.0,8.9),(16.0,8.1),(20.0,8.9),(24.5,11.4),(28.0,16.0)]
        lower=[(28.0,16.0),(24.4,20.5),(20.0,23.1),(16.0,23.9),(12.0,23.1),(7.6,20.5),(4.0,16.0)]
        d.polygon([(p(x),p(y)) for x,y in upper+lower[1:]],fill=fill)
        _line(d,p,upper,outline,1.5);_line(d,p,lower,outline,1.5)
        d.ellipse((p(11.2),p(11.2),p(20.8),p(20.8)),fill="#dceaf3",outline=iris,width=w(1.2))
        d.ellipse((p(14.2),p(14.2),p(17.8),p(17.8)),fill=iris)
        d.ellipse((p(15.0),p(14.8),p(15.9),p(15.7)),fill="#ffffff")

    if state=="complete":
        eye(iris=GREEN)
        d.ellipse((p(21),p(20),p(30),p(29)),fill="#ffffff",outline=GREEN,width=w(1.2))
        _line(d,p,[(23.0,24.4),(25.0,26.4),(28.2,22.4)],GREEN,1.7)
    elif state=="partial":
        eye(iris=ACCENT_ORANGE)
        # translucent-looking occluder on the right half, plus a crisp boundary.
        d.polygon([(p(16),p(8.4)),(p(28.3),p(15.9)),(p(16),p(23.6))],fill="#f6dfb5")
        _line(d,p,[(16,8.6),(16,23.4)],ACCENT_ORANGE,1.5)
        for y in (11.5,15.2,18.9,22.0):_line(d,p,[(18.0,y),(24.5,y+2.2)],ACCENT_ORANGE,.75)
    elif state=="not_visible":
        eye(outline=MUTED,iris=MUTED,fill="#f7f8f9")
        # Eye-with-slash is reserved only for "cannot be judged".
        _line(d,p,[(6.0,27.0),(27.0,6.0)],RED,3.0)
        _line(d,p,[(7.0,28.0),(28.0,7.0)],"#ffffff",.8)
    else:  # absent
        # Absence is a vacant anatomical slot, not poor visibility: no eye glyph.
        d.rounded_rectangle((p(6),p(7),p(26),p(25)),radius=p(4),fill="#ffffff",outline=XRAY_MID,width=w(1.4))
        d.rounded_rectangle((p(9),p(10),p(23),p(22)),radius=p(3),fill="#f3f5f7",outline="#c7d0d7",width=w(.8))
        _line(d,p,[(11,12),(21,20)],RED,2.3);_line(d,p,[(21,12),(11,20)],RED,2.3)
        # small broken baseline reinforces "nothing present" rather than "hidden".
        _line(d,p,[(7,28),(13,28)],MUTED,1.1);_line(d,p,[(19,28),(25,28)],MUTED,1.1)

    return im.resize((int(size),int(size)),Image.Resampling.LANCZOS)


def tk_visibility_icon(master,state,size=VISIBILITY_ICON_SIZE):
    return ImageTk.PhotoImage(render_visibility_icon(state,size),master=master)


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


def _folder(d,p):
    d.rounded_rectangle((p(3),p(8),p(29),p(27)),radius=p(2),fill=XRAY_PAPER,outline=XRAY_DARK,width=max(1,p(1.3)))
    d.polygon([(p(3),p(10)),(p(3),p(6)),(p(13),p(6)),(p(16),p(10))],fill=PALE_BLUE,outline=XRAY_DARK)
    _line(d,p,[(4,11),(28,11)],MUTED,.7)


def _crop_brackets(d,p,color=BLUE):
    for pts in [((4.5,11),(4.5,5),(10.5,5)),((21.5,5),(27.5,5),(27.5,11)),((4.5,21),(4.5,27),(10.5,27)),((21.5,27),(27.5,27),(27.5,21))]:
        _line(d,p,pts,color,2.5)


def _fish_skeleton_icon(d,p):
    """Large lateral fish skeleton silhouette for the Crops stage."""
    # skull / opercular block
    skull=[(5.0,16.0),(7.2,11.8),(10.5,12.7),(11.8,16.0),(10.3,19.3),(7.0,20.0)]
    d.polygon([(p(x),p(y)) for x,y in skull],fill="#f8fbfd",outline=XRAY_DARK)
    d.ellipse((p(7.0),p(13.5),p(8.4),p(14.9)),fill=BLUE)
    # strong axial column
    _line(d,p,[(10.5,16),(26.0,16)],XRAY_DARK,1.6)
    for x in (12.5,15.0,17.5,20.0,22.5,25.0):
        d.ellipse((p(x-1.0),p(15.0),p(x+1.0),p(17.0)),fill="#ffffff",outline=XRAY_DARK,width=max(1,p(.6)))
    # readable dorsal/ventral processes and ribs
    for x in (13.3,16.3,19.3,22.3):
        _line(d,p,[(x,15.4),(x+1.0,11.3)],XRAY_MID,.75)
        _line(d,p,[(x,16.6),(x-1.3,21.0)],XRAY_MID,.85)
    # tail rays
    for y in (11.5,13.7,16.0,18.3,20.5):
        _line(d,p,[(25.5,16),(29.0,y)],XRAY_MID,.75)


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

def _vertebra(d,p,cx=16,cy=16,scale=1.0,accent=XRAY_DARK):
    """Lateral teleost vertebra with a broad centrum and posteriorly inclined neural/haemal spines."""
    q=lambda x:cx+x*scale;r=lambda y:cy+y*scale
    # A broad amphicoelous centrum: flared ends, narrow waist.
    body=[
        (q(-6.8),r(-3.4)),(q(-5.0),r(-4.8)),(q(-2.2),r(-3.1)),
        (q(2.2),r(-3.1)),(q(5.0),r(-4.8)),(q(6.8),r(-3.4)),
        (q(6.8),r(3.4)),(q(5.0),r(4.8)),(q(2.2),r(3.1)),
        (q(-2.2),r(3.1)),(q(-5.0),r(4.8)),(q(-6.8),r(3.4)),
    ]
    d.polygon([(p(x),p(y)) for x,y in body],fill="#fdfefe",outline=accent)
    # End plates / concavity cues.
    _line(d,p,[(q(-5.1),r(-3.4)),(q(-5.8),r(0)),(q(-5.1),r(3.4))],XRAY_MID,.65)
    _line(d,p,[(q(5.1),r(-3.4)),(q(5.8),r(0)),(q(5.1),r(3.4))],XRAY_MID,.65)
    # Neural arch and spine.
    _line(d,p,[(q(-1.8),r(-3.1)),(q(-.2),r(-6.2)),(q(2.6),r(-3.0))],accent,.9)
    _line(d,p,[(q(.2),r(-6.2)),(q(4.7),r(-12.0))],accent,1.15)
    # Haemal arch and spine.
    _line(d,p,[(q(-1.8),r(3.1)),(q(-.2),r(6.2)),(q(2.6),r(3.0))],accent,.9)
    _line(d,p,[(q(.2),r(6.2)),(q(4.5),r(11.8))],accent,1.15)
    # Short zygapophyses.
    _line(d,p,[(q(-4.0),r(-3.3)),(q(-7.6),r(-5.8))],XRAY_MID,.7)
    _line(d,p,[(q(4.0),r(-3.3)),(q(7.2),r(-5.4))],XRAY_MID,.7)

def _vertebral_segment(d,p,cx=16,cy=16,scale=1.0,count=2,accent=XRAY_DARK):
    """Short fish vertebral-column fragment with clearly repeated centra."""
    spacing=11.0*scale;start=cx-spacing*(count-1)/2
    for index in range(count):_vertebra(d,p,start+spacing*index,cy,scale,accent)

def _preview_vertebra(d,cx,cy,scale=1.0,kind="caudal",outline=XRAY_DARK,body_fill="#ffffff",highlight=None):
    """Larger lateral vertebra for explanatory illustrations; abdominal and caudal forms differ."""
    s=float(scale);edge=highlight or outline
    body=[(-20,-8),(-15,-12),(-7,-8),(7,-8),(15,-12),(20,-8),(20,8),(15,12),(7,8),(-7,8),(-15,12),(-20,8)]
    pts=[(cx+x*s,cy+y*s) for x,y in body]
    d.polygon(pts,fill=body_fill,outline=edge,width=max(1,int(2*s)))
    d.line([(cx-15*s,cy-8*s),(cx-18*s,cy),(cx-15*s,cy+8*s)],fill="#73899a",width=max(1,int(s)))
    d.line([(cx+15*s,cy-8*s),(cx+18*s,cy),(cx+15*s,cy+8*s)],fill="#73899a",width=max(1,int(s)))
    # Neural arch and posteriorly inclined neural spine.
    w=max(1,int(2*s))
    d.line([(cx-5*s,cy-8*s),(cx,cy-18*s),(cx+7*s,cy-8*s)],fill=outline,width=w)
    d.line([(cx+1*s,cy-18*s),(cx+12*s,cy-36*s)],fill=outline,width=w)
    if kind=="caudal":
        # Caudal vertebra: haemal arch + haemal spine.
        d.line([(cx-5*s,cy+8*s),(cx,cy+18*s),(cx+7*s,cy+8*s)],fill=outline,width=w)
        d.line([(cx+1*s,cy+18*s),(cx+11*s,cy+35*s)],fill=outline,width=w)
    else:
        # Abdominal vertebra: paired rib/parapophysis cue instead of a haemal arch.
        d.line([(cx-6*s,cy+6*s),(cx-13*s,cy+25*s)],fill=outline,width=w)
        d.line([(cx+2*s,cy+7*s),(cx-3*s,cy+28*s)],fill=outline,width=max(1,int(1.5*s)))

def _count_to_indices(side,ref_index,total):
    """Indices contributing to a count-to trait; through includes the reference element."""
    side=str(side or "before")
    if side=="from":return set(range(ref_index,total))
    if side=="through":return set(range(ref_index+1))
    return set(range(ref_index))


def render_rule_preview(method_id,side="before",object_label="Vertebrae",reference_label="Reference",reference_label2="Second reference",size=(430,150)):
    """Large explanatory counting-rule illustration built from anatomical vertebra silhouettes."""
    width,height=(int(size[0]),int(size[1]));aa=2
    im=Image.new("RGBA",(width*aa,height*aa),(0,0,0,0));d=ImageDraw.Draw(im)
    S=lambda v:int(round(v*aa))
    font=ImageFont.load_default(size=S(11))
    font_small=ImageFont.load_default(size=S(9))
    d.rounded_rectangle((S(1),S(1),S(width-1),S(height-1)),radius=S(8),fill="#f8fafc",outline="#c8d3dc",width=S(1))

    if method_id=="derived":
        d.text((S(16),S(14)),"Calculated trait",font=font,fill="#27313a")
        d.rounded_rectangle((S(24),S(52),S(width-24),S(112)),radius=S(7),fill="#ffffff",outline="#c8d3dc",width=S(1))
        d.text((S(42),S(72)),"Value is calculated from other traits",font=font,fill="#31485b")
        return im.resize((width,height),Image.Resampling.LANCZOS)

    xs=[58,132,206,280,354];cy=78;ref_index=3
    counted=set(range(len(xs)))
    if method_id=="count_to":counted=_count_to_indices(side,ref_index,len(xs))
    elif method_id=="count_between":counted={1,2,3}
    elif method_id=="position":counted={2}
    elif method_id in {"presence","distance","angle"}:counted={2}

    if method_id=="count":caption=f"Count all {object_label}"
    elif method_id=="count_to":
        relation={"before":"before","from":"starting with","through":"through"}.get(side,"before")
        caption=f"Count {object_label} {relation} {reference_label}"
    elif method_id=="count_between":caption=f"Count {object_label} from {reference_label} to {reference_label2}"
    elif method_id=="position":caption=f"Record the position of {reference_label}"
    elif method_id=="presence":caption=f"Record whether {object_label} is present"
    elif method_id=="distance":caption="Measure between the selected marks"
    elif method_id=="angle":caption="Measure the angle defined by the selected marks"
    else:caption=f"Mark {object_label}"
    d.text((S(16),S(10)),caption,font=font,fill="#27313a")

    if counted:
        x0=min(xs[i] for i in counted)-30;x1=max(xs[i] for i in counted)+30
        d.rounded_rectangle((S(x0),S(40),S(x1),S(116)),radius=S(8),fill="#e7f2fa")

    for i,x in enumerate(xs):
        body_fill="#eef7fd" if i in counted else "#ffffff"
        edge="#1976e9" if i in counted else "#31485b"
        # When the reference is the first caudal vertebra, show the biological transition:
        # abdominal vertebrae before it have ribs; the reference and following vertebrae have haemal spines.
        kind="abdominal" if (method_id=="count_to" and i<ref_index) else "caudal"
        if method_id!="count_to":kind="caudal"
        ref_edge="#20a447" if (method_id=="count_to" and i==ref_index) else edge
        _preview_vertebra(d,S(x),S(cy),scale=aa*.60,kind=kind,outline="#31485b",body_fill=body_fill,highlight=ref_edge)

    if method_id=="count_to":
        rx=xs[ref_index]
        d.polygon([(S(rx),S(34)),(S(rx-7),S(44)),(S(rx+7),S(44))],fill="#20a447")
        d.text((S(rx-46),S(118)),reference_label,font=font_small,fill="#188038")
        if counted:
            x0=min(xs[i] for i in counted)-25;x1=max(xs[i] for i in counted)+25
            d.line((S(x0),S(128),S(x1),S(128)),fill="#1976e9",width=S(2))
            d.text((S(x0),S(131)),"count these",font=font_small,fill="#1976e9")
    elif method_id=="count_between":
        for idx in (1,4):
            rx=xs[idx];d.polygon([(S(rx),S(34)),(S(rx-7),S(44)),(S(rx+7),S(44))],fill="#20a447")
    elif method_id=="position":
        rx=xs[2];d.polygon([(S(rx),S(34)),(S(rx-7),S(44)),(S(rx+7),S(44))],fill="#20a447")

    return im.resize((width,height),Image.Resampling.LANCZOS)

def render_xray_icon(name,size=XRAY_ICON_SIZE):
    common={
        "xray_project":"project", "xray_crops":"crop", "xray_structures":"structures",
        "xray_export":"export", "xray_results":"measurement_export",
        "delete_crop":"delete", "clear_crops":"clear", "structure_apply":"verify",
        "structure_previous":"previous", "structure_next":"next",
        "clear_marker_set":"clear_type", "clear_all_markers":"clear",
    }
    if name in common:return render_icon(common[name],size)
    if name not in XRAY_ICON_NAMES:raise KeyError(name)
    im,d,p,w=_ctx(size)

    # Main workflow icons: different silhouette + shared visual language.
    if name=="xray":
        # Module identity: an immediately readable lateral fish skeleton, not an electronics-like symbol.
        _fish_skeleton_icon(d,p)
    elif name=="xray_project":
        _folder(d,p);_vertebra(d,p,20.0,18.0,.62,XRAY_DARK)
    elif name=="xray_crops":
        _fish_skeleton_icon(d,p);_crop_brackets(d,p,BLUE)
    elif name=="xray_structures":
        _vertebra(d,p,15.5,16,.76,XRAY_DARK)
        _line(d,p,[(7.6,8.0),(7.6,24.0)],ACCENT_ORANGE,2.0)
        d.polygon([(p(24.5),p(7.5)),(p(27.5),p(13.0)),(p(21.5),p(13.0))],fill=GREEN,outline="#ffffff")
    elif name=="xray_results":
        _vertebra(d,p,8.2,17.0,.50,XRAY_DARK);_table(d,p,14.0,5.5,29.5,26.5)
    elif name=="xray_export":
        _document(d,p,2.5,3.5,22.5,28.5);_vertebra(d,p,11.5,18.0,.48,XRAY_DARK)
        _line(d,p,[(20.0,17.0),(29.0,17.0)],GREEN,2.4)
        d.polygon([(p(30.0),p(17.0)),(p(25.2),p(13.5)),(p(25.2),p(20.5))],fill=GREEN)

    elif name=="counted_element":
        _vertebra(d,p,16,16,.78,BLUE)
    elif name=="reference_mark":
        _vertebra(d,p,15.2,17,.66,XRAY_DARK)
        d.polygon([(p(23),p(5)),(p(19),p(11)),(p(27),p(11))],fill=GREEN)
        _line(d,p,[(23,11),(23,26)],GREEN,1.8)

    elif name=="annotation_setup":
        # Step 1: repeated anatomical elements plus a distinct start/stop boundary.
        _vertebra(d,p,8.0,17.0,.48,BLUE)
        _vertebra(d,p,15.5,17.0,.48,BLUE)
        _vertebra(d,p,23.0,17.0,.48,XRAY_DARK)
        _line(d,p,[(26.5,6.0),(26.5,27.0)],GREEN,2.0)
        d.polygon([(p(26.5),p(5.0)),(p(22.5),p(10.0)),(p(30.5),p(10.0))],fill=GREEN)
    elif name=="flip_horizontal":
        _line(d,p,[(5,16),(27,16)],MUTED,1.0)
        d.polygon([(p(4),p(16)),(p(10),p(11)),(p(10),p(21))],fill=BLUE)
        d.polygon([(p(28),p(16)),(p(22),p(11)),(p(22),p(21))],fill=BLUE)
        _line(d,p,[(16,7),(16,25)],XRAY_DARK,1.2)
    elif name=="flip_vertical":
        _line(d,p,[(16,5),(16,27)],MUTED,1.0)
        d.polygon([(p(16),p(4)),(p(11),p(10)),(p(21),p(10))],fill=ACCENT_ORANGE)
        d.polygon([(p(16),p(28)),(p(11),p(22)),(p(21),p(22))],fill=ACCENT_ORANGE)
        _line(d,p,[(7,16),(25,16)],XRAY_DARK,1.2)

    elif name=="structure_apply":
        d.ellipse((p(5),p(5),p(27),p(27)),fill="#eef9f2",outline=GREEN,width=w(1.5))
        _line(d,p,[(9,16),(14,21),(24,10)],GREEN,3.1)
    elif name=="structure_previous":
        _line(d,p,[(25,8),(12,16),(25,24)],BLUE,2.6)
        _line(d,p,[(11,7),(11,25)],XRAY_MID,1.2)
    elif name=="structure_next":
        _line(d,p,[(7,8),(20,16),(7,24)],BLUE,2.6)
        d.ellipse((p(19),p(18),p(30),p(29)),fill="#eef9f2",outline=GREEN,width=w(1.0))
        _line(d,p,[(21,24),(24,27),(28,21)],GREEN,2.1)
    elif name=="clear_marker_set":
        _node(d,p,9,9,fill="#ffffff",outline=BLUE,r=2.5,width=1.0)
        _node(d,p,16,16,fill="#ffffff",outline=ACCENT_ORANGE,r=2.5,width=1.0)
        _node(d,p,23,23,fill="#ffffff",outline=GREEN,r=2.5,width=1.0)
        d.polygon([(p(5),p(25)),(p(10),p(29)),(p(18),p(20)),(p(13),p(16))],fill="#f6f8fa",outline=XRAY_DARK)
        _line(d,p,[(11,27),(18,20)],RED,1.8)
    elif name=="clear_all_markers":
        for x,y,c in ((8,9,BLUE),(16,12,ACCENT_ORANGE),(24,9,GREEN),(11,22,"#cc79a7"),(22,22,BLUE)):
            _node(d,p,x,y,fill="#ffffff",outline=c,r=2.2,width=.9)
        _line(d,p,[(5,27),(27,5)],RED,3.0)
        d.polygon([(p(4),p(22)),(p(8),p(27)),(p(13),p(22)),(p(9),p(18))],fill="#f6f8fa",outline=XRAY_DARK)

    elif name=="delete_crop":
        d.rounded_rectangle((p(5),p(7),p(24),p(25)),radius=p(1.8),fill="#f8fbfd",outline=BLUE,width=w(1.5))
        _crop_brackets(d,p,BLUE)
        _line(d,p,[(20,9),(28,17)],RED,2.5);_line(d,p,[(28,9),(20,17)],RED,2.5)
    elif name=="clear_crops":
        d.rounded_rectangle((p(4),p(6),p(19),p(18)),radius=p(1.4),fill="#f8fbfd",outline=MUTED,width=w(1.1))
        d.rounded_rectangle((p(9),p(11),p(24),p(23)),radius=p(1.4),fill="#f8fbfd",outline=BLUE,width=w(1.3))
        d.rounded_rectangle((p(14),p(16),p(29),p(28)),radius=p(1.4),fill="#f8fbfd",outline=XRAY_DARK,width=w(1.1))
        _line(d,p,[(5,27),(27,5)],RED,2.6)
        d.polygon([(p(5),p(24)),(p(8),p(27)),(p(12),p(23)),(p(9),p(20))],fill=ACCENT_ORANGE,outline="#ffffff")

    elif name=="trait_setup":
        # Step 2: anatomical annotations are combined into an output trait.
        _vertebra(d,p,7.5,12.0,.38,BLUE)
        _vertebra(d,p,7.5,22.0,.38,XRAY_DARK)
        _line(d,p,[(12.0,12.0),(16.0,16.0),(12.0,22.0)],MUTED,1.5)
        _line(d,p,[(16.0,16.0),(20.0,16.0)],GREEN,2.0)
        d.polygon([(p(20.5),p(16.0)),(p(16.5),p(13.0)),(p(16.5),p(19.0))],fill=GREEN)
        _table(d,p,20.5,7.5,30.0,25.5)

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
        _vertebra(d,p,11.0,17.0,.58,XRAY_DARK)
        _line(d,p,[(18.5,17),(22.5,21),(29.5,10)],GREEN,2.5)
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

def tk_rule_preview(master,method_id,side="before",object_label="Vertebrae",reference_label="Reference",reference_label2="Second reference",size=(430,150)):
    return ImageTk.PhotoImage(render_rule_preview(method_id,side,object_label,reference_label,reference_label2,size),master=master)
