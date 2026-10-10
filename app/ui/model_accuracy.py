"""Human-readable Landmark model accuracy comparison UI."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from app.ai_batch import backend_for_model
from app.human_baseline import (
    evaluate_model_against_repeatability,
    human_repeatability_metrics,
    repeatability_report_state,
)
from .dialogs import center


def _fmt(value):
    return "—" if value is None else f"{float(value):.3f}%"


def _ratio(human_value, ai_value):
    if human_value in (None, 0) or ai_value is None:
        return None
    return float(ai_value) / float(human_value)


def _ratio_text(value):
    return "—" if value is None else f"{float(value):.2f}×"


class LandmarkAccuracyDialog(tk.Toplevel):
    """Readable all-landmark and GM-only comparison for one saved model."""

    def __init__(self, shell, project, model_id, human, model):
        super().__init__(shell)
        self.shell = shell
        self.project = project
        self.model_id = str(model_id)
        self.human = human
        self.model = model
        self.scope = tk.StringVar(value="all")
        self.sort_column = "ai"
        self.sort_descending = True
        self._accuracy_rows = []
        self.title(f"Landmark accuracy — {self.model_id}")
        self.transient(shell)
        self.geometry("980x650")
        self.minsize(820,520)

        outer=ttk.Frame(self,padding=16);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Landmark accuracy",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text=f"Model {self.model_id} compared with two blind manual annotations of the same frozen images.",
            style="PageSubtitle.TLabel",
        ).pack(anchor="w",pady=(2,10))

        choices=ttk.Frame(outer);choices.pack(fill="x")
        ttk.Label(choices,text="Show:",style="SectionTitle.TLabel").pack(side="left")
        ttk.Radiobutton(choices,text="All landmarks",variable=self.scope,value="all",command=self.refresh).pack(side="left",padx=(8,2))
        ttk.Radiobutton(choices,text="GM landmarks only",variable=self.scope,value="gm",command=self.refresh).pack(side="left",padx=(8,2))

        self.cards=ttk.Frame(outer);self.cards.pack(fill="x",pady=(10,8))
        for col in range(3):self.cards.columnconfigure(col,weight=1)
        self.human_value=self._card(0,"Human repeatability","P90 manual-to-manual displacement (% of configuration span)")
        self.ai_value=self._card(1,"AI ↔ human","P90 AI-to-manual displacement (% of configuration span)")
        self.relative_value=self._card(2,"Relative size","AI-to-manual P90 / manual-to-manual P90")

        note=ttk.Label(
            outer,
            text=(
                "Human repeatability and AI ↔ human disagreement are related but not identical error quantities; "
                "the ratio is context, not a formal accuracy score. Lower P90 means tighter point placement. "
                "GM-only excludes landmarks whose scheme role is CLASSICAL. Configuration span is the greatest distance between two present landmarks in the reference configuration. GM-only comparisons use the GM landmark configuration."
            ),
            style="Muted.TLabel",justify="left",wraplength=920,
        )
        note.pack(fill="x",pady=(0,10))

        table_frame=ttk.Frame(outer);table_frame.pack(fill="both",expand=True)
        table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        columns=("abbr","name","role","human","ai","ratio")
        self.table=ttk.Treeview(table_frame,columns=columns,show="headings",selectmode="browse")
        labels={"abbr":"Landmark","name":"Name","role":"Use","human":"Human P90","ai":"AI ↔ human P90","ratio":"Relative"}
        widths={"abbr":90,"name":260,"role":90,"human":110,"ai":135,"ratio":90}
        self._column_labels=labels
        for col in columns:
            self.table.heading(col,text=labels[col],command=lambda key=col:self.sort_by(key))
            self.table.column(col,width=widths[col],anchor="w",stretch=col=="name")
        scroll=ttk.Scrollbar(table_frame,orient="vertical",command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")

        self.scope_note=ttk.Label(outer,text="",style="Muted.TLabel",justify="left")
        self.scope_note.pack(anchor="w",pady=(7,0))

        actions=ttk.Frame(outer);actions.pack(fill="x",pady=(12,0))
        ttk.Button(actions,text="Close",command=self.destroy,style="Primary.TButton").pack(side="right")
        self.refresh()
        center(shell,self)

    def sort_by(self,column):
        if self.sort_column==column:
            self.sort_descending=not self.sort_descending
        else:
            self.sort_column=column
            self.sort_descending=column in {"human","ai","ratio"}
        self._render_sorted_rows()

    def _render_sorted_rows(self):
        columns=("abbr","name","role","human","ai","ratio")
        index={"abbr":1,"name":2,"role":3,"human":4,"ai":5,"ratio":6}
        numeric={"human","ai","ratio"}
        def key(item):
            value=item[index[self.sort_column]]
            if self.sort_column in numeric:return float("-inf") if value is None else float(value)
            return str(value or "").casefold()
        rows=sorted(self._accuracy_rows,key=key,reverse=self.sort_descending)
        self.table.delete(*self.table.get_children())
        for ident,abbr,name,role,h,a,ratio in rows:
            use_label={"GM":"GM","CLASSICAL":"Linear measurements","BOTH":"Both"}.get(role,role)
            self.table.insert("", "end", values=(abbr,name,use_label,_fmt(h),_fmt(a),_ratio_text(ratio)))
        for column in columns:
            arrow=" ↓" if column==self.sort_column and self.sort_descending else " ↑" if column==self.sort_column else ""
            self.table.heading(column,text=self._column_labels[column]+arrow,command=lambda key=column:self.sort_by(key))

    def _card(self,column,title,subtitle):
        box=ttk.LabelFrame(self.cards,text=title,padding=(12,8));box.grid(row=0,column=column,sticky="ew",padx=(0 if column==0 else 5,0))
        value=ttk.Label(box,text="—",font=("Segoe UI",16,"bold"));value.pack(anchor="w")
        ttk.Label(box,text=subtitle,style="Muted.TLabel",wraplength=260,justify="left").pack(anchor="w",pady=(2,0))
        return value

    def _aggregate(self,payload,scope):
        scopes=payload.get("aggregate_by_scope") or {}
        if scope in scopes:return scopes[scope] or {}
        return payload.get("aggregate") or {} if scope=="all" else {}

    def refresh(self):
        scope=self.scope.get()
        human_agg=self._aggregate(self.human,scope);ai_agg=self._aggregate(self.model,scope)
        hp90=human_agg.get("p90_error_percent");ap90=ai_agg.get("p90_error_percent");ratio=_ratio(hp90,ap90)
        self.human_value.configure(text=_fmt(hp90))
        self.ai_value.configure(text=_fmt(ap90))
        self.relative_value.configure(text=_ratio_text(ratio))

        self.table.delete(*self.table.get_children())
        human_source=((self.human.get("per_landmark_by_scope") or {}).get(scope) if scope!="all" else None) or self.human.get("per_landmark") or {}
        ai_source=((self.model.get("per_landmark_by_scope") or {}).get(scope) if scope!="all" else None) or self.model.get("per_landmark") or {}
        human_rows={int(k):v for k,v in human_source.items()}
        ai_rows={int(k):v for k,v in ai_source.items()}
        rows=[]
        for schema_row in self.project.schema:
            ident=int(schema_row["id"]);role=str(schema_row.get("role") or "BOTH").upper()
            if scope=="gm" and role not in {"GM","BOTH"}:continue
            h=human_rows.get(ident,{}).get("p90_error_percent")
            a=ai_rows.get(ident,{}).get("p90_error_percent")
            rows.append((ident,schema_row.get("abbr") or str(ident),schema_row.get("name") or "",role,h,a,_ratio(h,a)))
        self._accuracy_rows=rows
        self._render_sorted_rows()
        if scope=="gm":
            gm_count=sum(str(row.get("role") or "BOTH").upper() in {"GM","BOTH"} for row in self.project.schema)
            total=len(self.project.schema)
            self.scope_note.configure(text=f"GM-only uses {gm_count} of {total} landmarks (roles GM + BOTH). Landmarks used only for linear measurements are excluded. Normalization uses the GM landmark configuration.")
        else:
            self.scope_note.configure(text=f"All {len(self.project.schema)} landmarks are shown. Switch to GM-only to exclude landmarks used only for linear measurements.")


def open_landmark_accuracy(shell, project, model_id):
    """Run the same-image comparison off Tk, then open the detailed view."""
    state=repeatability_report_state(project)
    report=state.get("report")
    if report is None:
        messagebox.showinfo(
            "Landmark accuracy",
            state.get("message") or "Complete Human repeatability first. MorphoLabel needs two blind manual annotations of the same images before model accuracy can be compared fairly.",
            parent=shell,
        )
        return None
    run_id=report.get("run_id")
    if not run_id:
        messagebox.showinfo("Landmark accuracy","The current Human repeatability report has no usable run ID. Start a new Human repeatability sample.",parent=shell)
        return None

    def worker(progress):
        progress("Reading the two blind manual annotations…")
        human=human_repeatability_metrics(project,run_id)
        progress("Running the selected model on the same frozen images…")
        _,backend=backend_for_model(project,str(model_id))
        model=evaluate_model_against_repeatability(project,run_id,str(model_id),backend=backend)
        return human,model

    def done(value):
        human,model=value
        LandmarkAccuracyDialog(shell,project,model_id,human,model)

    return shell._run_background_task("Landmark accuracy","Preparing same-image comparison…",worker,done)
