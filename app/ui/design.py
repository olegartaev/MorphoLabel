"""Presentation-only tokens and helpers shared by all MorphoLabel modules.

No project, annotation, model or queue state is owned by this module.
"""
from __future__ import annotations

from datetime import datetime
import sys
from tkinter import ttk

# Neutral fallbacks are used outside Windows.  On Windows, ttk's native theme
# owns control chrome and colours so MorphoLabel looks like an ordinary desktop
# application rather than a custom web-like skin.
SURFACE = "#f0f0f0"
PAPER = "#ffffff"
INK = "#202020"
MUTED = "#606060"
ACCENT = "#256d9e"
BORDER = "#c8c8c8"
CANVAS = "#202020"


def _native_theme(style):
    themes=set(style.theme_names())
    if sys.platform.startswith("win"):
        for candidate in ("vista","xpnative","winnative"):
            if candidate in themes:
                style.theme_use(candidate)
                return candidate
    if "clam" in themes:
        style.theme_use("clam")
        return "clam"
    return style.theme_use()


def apply_styles(root, style):
    """Apply one compact desktop style without replacing native Windows chrome."""
    from tkinter import font as tkfont
    family="Segoe UI" if "Segoe UI" in tkfont.families(root) else "DejaVu Sans"
    tkfont.nametofont("TkDefaultFont",root=root).configure(family=family,size=9)
    native_windows=_native_theme(style) in {"vista","xpnative","winnative"}

    # Keep standard Windows controls standard.  Custom colours are deliberately
    # limited to semantic states such as the yellow review queue.
    style.configure(".",font=(family,9))
    if not native_windows:
        style.configure("TFrame",background=SURFACE)
        style.configure("TLabel",background=SURFACE,foreground=INK)
        style.configure("TButton",background=SURFACE,foreground=INK)
        style.configure("Treeview",background=PAPER,fieldbackground=PAPER,foreground=INK)
        style.configure("Treeview.Heading",background="#e9e9e9",foreground=INK)

    style.configure("TButton",padding=(9,5),width=0)
    for name in ("P.TButton","Icon.TButton","Nav.TButton","ReviewAction.TButton"):
        style.configure(name,padding=(9,5),font=(family,9))
    for name in ("Primary.TButton","NavPrimary.TButton","CropNext.TButton","CropApply.TButton"):
        style.configure(name,padding=(9,5),font=(family,9,"bold"))
    style.configure("Marker.TButton",padding=(7,4),font=(family,9))
    style.configure("MarkerActive.TButton",padding=(7,4),font=(family,9,"bold"))
    style.configure("MarkerStatus.TButton",padding=(7,4),font=(family,9))

    style.configure("Stage.TButton",padding=(8,4),font=(family,9))
    style.configure("StageActive.TButton",padding=(8,4),font=(family,9,"bold"))
    style.configure("Topbar.TFrame",padding=(0,1))
    style.configure("Toolbar.TFrame",padding=(3,2))
    style.configure("WorkflowDock.TFrame",padding=0)
    style.configure("WorkflowDockTitle.TLabel",font=(family,9,"bold"),foreground=MUTED)
    style.configure("WorkflowCard.TLabelframe",padding=(8,5),borderwidth=1,relief="groove")
    style.configure("WorkflowCardTitle.TLabel",font=(family,9,"bold"))
    style.configure("SectionTitle.TLabel",font=(family,9,"bold"))
    style.configure("PageTitle.TLabel",font=(family,15,"bold"))
    style.configure("PageSubtitle.TLabel",font=(family,9),foreground=MUTED)
    style.configure("HubTitle.TLabel",font=(family,22,"bold"))
    style.configure("ModuleTitle.TLabel",font=(family,12,"bold"))
    style.configure("Muted.TLabel",foreground=MUTED)
    style.configure("StatusChip.TLabel",padding=(2,1),foreground=MUTED)
    style.configure("Prediction.TLabel",foreground=MUTED,padding=(2,1))
    style.configure("ProjectIdentity.TLabelframe",borderwidth=2,relief="groove",padding=(8,6))
    style.configure("ProjectIdentityTitle.TLabel",font=(family,9,"bold"))
    style.configure("ContextKey.TLabel",font=(family,9,"bold"))
    style.configure("ContextValue.TLabel",font=(family,9))

    # Queue colour is semantic, not decoration: it must remain visually distinct
    # from ordinary Previous/Next navigation.
    style.configure("Attention.TFrame",background="#fff2cc")
    style.configure("AttentionTitle.TLabel",background="#fff2cc",foreground="#5f4a00",font=(family,9,"bold"))
    style.configure("AttentionText.TLabel",background="#fff2cc",foreground=INK)
    style.configure("AttentionStep.TLabel",background="#fff2cc",foreground="#5f4a00")

    style.configure("Treeview",rowheight=24)
    style.configure("Treeview.Heading",font=(family,9,"bold"),padding=(5,4))
    if not native_windows:
        style.map("Treeview",background=[("selected","#d9e8f5")],foreground=[("selected",INK)])


def sidebar_width_for_window(total_width: int, requested_width: int=0) -> int:
    """Readable list width capped near the reviewed ~28% desktop proportion."""
    width=max(1,int(total_width or 0))
    available=max(250,width-560)
    ceiling=max(250,min(480,int(width*.29),available))
    floor=min(ceiling,max(280,min(350,int(requested_width or 0)+12 if requested_width else 330)))
    responsive=min(ceiling,max(floor,int(width*.27)))
    return int(responsive)


def dialog_width_for_columns(column_widths, screen_width: int, *, chrome: int=70, margin: int=80) -> int:
    """Choose a model-list width that exposes all normal columns when the screen permits."""
    required=sum(max(1,int(value)) for value in column_widths)+max(40,int(chrome))
    available=max(620,int(screen_width or 0)-max(40,int(margin)))
    return max(620,min(required,available))


def action_icon(text):
    """One visual meaning per action; explicit caller icons take priority."""
    label=str(text).strip().casefold().replace("…", "").rstrip(".")
    if label in {"help", "quick guide"}: return "help"
    if label.startswith("models"): return "models"
    if label in {"start first batch","add next batch","start batch","continue batch"}: return "batch_add"
    if label == "train" or label.startswith("train "): return "train"
    if label.startswith("predict current"): return "predict_current"
    if label.startswith("predict next"): return "predict_batch"
    if label.startswith("predict all"): return "predict_all"
    if label.startswith("export") or label == "open export": return "export"
    if label.startswith("review"): return "review_worst"
    if label.startswith("accept all"): return "accept_all"
    if label in {"check results", "final data qc"}: return "complex_qc"
    if label.startswith("repeat"): return "landmark_repeat"
    if label.startswith("display"): return "display"
    if label in {"verify specimen","verify image","confirm & next","verify & next","apply crop","apply crops"}: return "verify"
    if label=="previous": return "previous"
    if label in {"next","next unfinished","continue"}: return "next"
    if label=="close queue": return "close"
    if label in {"exclude", "restore"}: return label
    return None


def prediction_stamp(model_id, timestamp):
    """Show recorded model and prediction time, never the active model/time."""
    model=str(model_id or "").strip()
    if not model: return ""
    stamp=str(timestamp or "").strip()
    if stamp:
        try:
            stamp=datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass  # Preserve unusual legacy timestamps instead of inventing one.
    return f"AI prediction · {model}"+(f" · {stamp}" if stamp else " · time not recorded")


def structure_prediction_text(project, specimen_id, pass_no=1):
    """Read the latest seed event in this exact specimen/schema/pass history."""
    if not specimen_id: return ""
    run=project.annotation_run(specimen_id, pass_no, "human", False)
    if not run or str(run.get("status") or "").startswith("stale"): return ""
    events=project.annotation_events(specimen_id, pass_no, "human")
    for event in reversed(events):
        if event.get("action") != "model_seed": continue
        text=prediction_stamp((event.get("payload") or {}).get("model_id"), event.get("created_at"))
        if not text: return ""
        # This is provenance of the original suggestion, not an assertion that
        # the current coordinates are still the model output.
        edited=any(int(e.get("event_id") or 0)>int(event.get("event_id") or 0) and e.get("action") not in {"verify", "model_seed"} for e in events)
        return text+(" · human reviewed" if run.get("status")=="verified" else " · edited" if edited else "")
    return ""


class ElidedLabel(ttk.Label):
    """Shrink long non-critical context without displacing neighbouring actions."""
    def __init__(self, parent, **kwargs):
        self.full_text=str(kwargs.pop("text", ""))
        super().__init__(parent, text=self.full_text, width=1, **kwargs)
        self.bind("<Configure>", self._fit, add="+")

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs: self.full_text=str(kwargs.pop("text"))
        result=super().configure(cnf, **kwargs)
        self._fit()
        return result

    config=configure

    def _fit(self, _event=None):
        import tkinter.font as tkfont
        font=tkfont.nametofont("TkDefaultFont", root=self)
        width=max(8, self.winfo_width()-4)
        shown=self.full_text
        if font.measure(shown)>width:
            lo,hi=0,len(shown)
            while lo<hi:
                mid=(lo+hi+1)//2
                if font.measure(shown[:mid]+"…")<=width: lo=mid
                else: hi=mid-1
            shown=shown[:lo].rstrip()+"…"
        super().configure(text=shown)


class FlowRow(ttk.Frame):
    """Wrap intact control groups instead of clipping a long marker toolbar."""
    def __init__(self,parent,**kwargs):
        super().__init__(parent,**kwargs)
        self.grid_propagate(False);self.pack_propagate(False)
        self._layout_job=None
        self._row_height=0
        self.bind("<Configure>",self.relayout,add="+")

    def relayout(self,_event=None):
        if self._layout_job is None:self._layout_job=self.after_idle(self._layout)

    def _layout(self):
        self._layout_job=None
        width=max(1,self.winfo_width());x=0;y=0;row_height=0
        children=self.winfo_children()
        left=[];right=[]
        for child in children:
            if getattr(child,"_flow_hidden",False):
                child.place_forget();child.pack_forget();continue
            if child.winfo_manager()=="pack":child._flow_side=child.pack_info().get("side","left")
            (right if getattr(child,"_flow_side","left")=="right" else left).append(child)
        for child in left:
            requested=child.winfo_reqwidth();height=child.winfo_reqheight()
            if x and x+requested>width:
                y+=row_height+2;x=0;row_height=0
            if child.winfo_manager()=="pack":child.pack_forget()
            child.place(x=x,y=y,width=requested,height=height)
            row_height=max(row_height,height);x+=requested+6
        right_width=sum(child.winfo_reqwidth()+6 for child in right)
        if right and x and x+right_width>width:y+=row_height+2;row_height=0
        rx=max(0,width-right_width)
        for child in reversed(right):
            if child.winfo_manager()=="pack":child.pack_forget()
            requested=child.winfo_reqwidth();height=child.winfo_reqheight()
            child.place(x=rx,y=y,width=requested,height=height);rx+=requested+6;row_height=max(row_height,height)
        wanted=y+row_height+2
        if wanted!=self._row_height:self._row_height=wanted;self.configure(height=max(1,wanted))
