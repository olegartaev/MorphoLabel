"""Presentation-only tokens and helpers shared by all MorphoLabel modules.

No project, annotation, model or queue state is owned by this module.
"""
from __future__ import annotations

from datetime import datetime
from tkinter import ttk

SURFACE = "#f3f6f9"
PAPER = "#ffffff"
INK = "#253746"
MUTED = "#586b7a"
ACCENT = "#246b9b"
BORDER = "#d6dfe7"
CANVAS = "#202020"


def apply_styles(root, style):
    # The native Windows theme ignores several colour maps. Clam makes the
    # selected stage and primary action legible on Windows as well as Linux.
    from tkinter import font as tkfont
    family="Segoe UI" if "Segoe UI" in tkfont.families(root) else "DejaVu Sans"
    tkfont.nametofont("TkDefaultFont",root=root).configure(family=family,size=9)
    style.theme_use("clam")
    style.configure(".", background=SURFACE, foreground=INK, font=(family, 9))
    style.configure("TFrame", background=SURFACE)
    style.configure("TLabel", background=SURFACE, foreground=INK)
    style.configure("TButton", padding=(8, 4), width=0, background=PAPER, bordercolor=BORDER, relief="flat")
    style.map("TButton", background=[("pressed", "#d9e8f3"), ("active", "#eaf1f6")], foreground=[("disabled", "#8995a0")])
    for name in ("P.TButton", "Icon.TButton", "Nav.TButton", "ReviewAction.TButton"):
        style.configure(name, padding=(7, 4), font=(family, 9), background=PAPER, foreground=INK)
    for name in ("Primary.TButton", "NavPrimary.TButton", "CropNext.TButton", "CropApply.TButton"):
        style.configure(name, padding=(8, 4), font=(family, 9, "bold"), background="#e1eef7", foreground="#174f75", bordercolor="#9ebdd2")
        style.map(name, background=[("pressed", "#c4deee"), ("active", "#d2e6f3")], foreground=[("disabled", "#8995a0"), ("!disabled", "#174f75")])
    style.configure("Stage.TButton", padding=(9, 4), foreground=MUTED, background=SURFACE, bordercolor=SURFACE)
    style.configure("StageActive.TButton", padding=(9, 4), font=(family, 9, "bold"), foreground="#174f75", background="#dcebf5", bordercolor="#9ebdd2")
    style.map("StageActive.TButton", background=[("active", "#cce2f0"), ("!disabled", "#dcebf5")], foreground=[("!disabled", "#174f75")])
    style.configure("Topbar.TFrame", padding=(0, 1))
    style.configure("Toolbar.TFrame", padding=(4, 3))
    style.configure("WorkflowDockTitle.TLabel", font=(family, 9, "bold"), foreground=MUTED)
    style.configure("WorkflowCard.TLabelframe", bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("WorkflowCardTitle.TLabel", font=(family, 9, "bold"), foreground=INK)
    style.configure("SectionTitle.TLabel", font=(family, 9, "bold"), foreground=INK)
    style.configure("PageTitle.TLabel", font=(family, 16, "bold"), foreground=INK)
    style.configure("PageSubtitle.TLabel", font=(family, 10), foreground=MUTED)
    style.configure("HubTitle.TLabel", font=(family, 24, "bold"), foreground=INK)
    style.configure("ModuleTitle.TLabel", font=(family, 12, "bold"), foreground=INK)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("StatusChip.TLabel", padding=(4, 2), foreground=MUTED)
    style.configure("Prediction.TLabel", foreground=ACCENT, padding=(4, 2))
    style.configure("Attention.TFrame", background="#fff2d2")
    style.configure("AttentionTitle.TLabel", background="#fff2d2", foreground="#694d12", font=(family, 9, "bold"))
    style.configure("AttentionText.TLabel", background="#fff2d2", foreground=INK)
    style.configure("AttentionStep.TLabel", background="#fff2d2", foreground="#694d12")
    style.configure("Treeview", background=PAPER, fieldbackground=PAPER, rowheight=26, bordercolor=BORDER)
    style.configure("Treeview.Heading", font=(family, 9, "bold"), background="#e8eef3", padding=(5, 5))
    style.map("Treeview", background=[("selected", "#dcebf5")], foreground=[("selected", "#174f75")])


def action_icon(text):
    """One visual meaning per action; explicit caller icons take priority."""
    label=str(text).strip().casefold().replace("…", "").rstrip(".")
    if label in {"help", "quick guide"}: return "help"
    if label.startswith("models"): return "models"
    if label.startswith("export") or label == "open export": return "export"
    if label.startswith("review"): return "review_worst"
    if label in {"check results", "final data qc"}: return "complex_qc"
    if label.startswith("repeat"): return "landmark_repeat"
    if label.startswith("display"): return "display"
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
            row_height=max(row_height,height);x+=requested+4
        right_width=sum(child.winfo_reqwidth()+4 for child in right)
        if right and x and x+right_width>width:y+=row_height+2;row_height=0
        rx=max(0,width-right_width)
        for child in reversed(right):
            if child.winfo_manager()=="pack":child.pack_forget()
            requested=child.winfo_reqwidth();height=child.winfo_reqheight()
            child.place(x=rx,y=y,width=requested,height=height);rx+=requested+4;row_height=max(row_height,height)
        wanted=y+row_height+2
        if wanted!=self._row_height:self._row_height=wanted;self.configure(height=max(1,wanted))
