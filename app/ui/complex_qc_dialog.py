"""Compact UI for project-wide Complex QC."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app.complex_qc import scan_complex_qc
from app.landmark_suspicious_review import start as start_suspicious_review
from .dialogs import center


def _method_summary(result):
    methods=result.get("methods") or {}
    basic=methods.get("basic") or {}
    established=methods.get("established") or {}
    distance=methods.get("distance") or {}
    measurements=methods.get("measurements") or {}
    gm=methods.get("gm") or {}
    parts=[
        f"Geometry: {basic.get('issues',0)} issue(s)" if basic.get("used") else "Geometry: skipped",
        f"Identity: {established.get('candidate_images',0)} candidate(s)" if established.get("used") else "Identity: skipped",
        f"Distance: {distance.get('landmarks',0)} landmarks" if distance.get("used") else "Distance: not enough data",
        f"Measurements: {measurements.get('definitions',0)}" if measurements.get("used") else "Measurements: skipped",
        f"GM PCA: {gm.get('landmarks',0)} landmarks" if gm.get("used") else "GM PCA: "+str(gm.get("reason") or "skipped"),
    ]
    return " · ".join(parts)


def open_complex_qc(section):
    project=section.context.project
    dialog=tk.Toplevel(section.shell);dialog.title("Complex QC");dialog.transient(section.shell);dialog.geometry("920x560");dialog.minsize(760,440)
    frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True);frame.rowconfigure(4,weight=1);frame.columnconfigure(0,weight=1)

    ttk.Label(frame,text="Complex QC",font=("Segoe UI",12,"bold")).grid(row=0,column=0,sticky="w")
    ttk.Label(
        frame,
        text="Post-verification audit of final human-verified landmark sets. Unverified AI predictions are handled by Review worst.",
        style="Muted.TLabel",
    ).grid(row=1,column=0,sticky="w",pady=(2,0))
    ttk.Label(
        frame,
        text="Outlier ≠ error. High-priority cases come first; Verify & Next re-confirms the final landmark set after inspection or correction.",
        style="Muted.TLabel",
    ).grid(row=2,column=0,sticky="w",pady=(0,9))

    summary=tk.StringVar(master=dialog,value="Preparing scan…")
    methods=tk.StringVar(master=dialog,value="")
    status=ttk.Frame(frame);status.grid(row=3,column=0,sticky="ew",pady=(0,8));status.columnconfigure(0,weight=1)
    ttk.Label(status,textvariable=summary,font=("Segoe UI",9,"bold")).grid(row=0,column=0,sticky="w")
    ttk.Label(status,textvariable=methods,style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(2,0))
    progress=ttk.Progressbar(status,mode="indeterminate",length=240);progress.grid(row=0,column=1,rowspan=2,sticky="e",padx=(12,0))

    table_frame=ttk.Frame(frame);table_frame.grid(row=4,column=0,sticky="nsew");table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
    columns=("priority","image","signals","landmarks")
    table=ttk.Treeview(table_frame,columns=columns,show="headings",selectmode="browse")
    labels={"priority":"Priority","image":"Image","signals":"Why flagged","landmarks":"Inspect first"}
    widths={"priority":80,"image":250,"signals":330,"landmarks":170}
    for name in columns:
        table.heading(name,text=labels[name]);table.column(name,width=widths[name],anchor="w",stretch=name in {"image","signals"})
    table.tag_configure("high",font=("Segoe UI",9,"bold"))
    scroll=ttk.Scrollbar(table_frame,orient="vertical",command=table.yview);table.configure(yscrollcommand=scroll.set)
    table.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")

    detail=tk.StringVar(master=dialog,value="")
    ttk.Label(frame,textvariable=detail,style="Muted.TLabel",wraplength=880,justify="left").grid(row=5,column=0,sticky="ew",pady=(8,0))

    actions=ttk.Frame(frame);actions.grid(row=6,column=0,sticky="ew",pady=(10,0));actions.columnconfigure(0,weight=1)
    all_button=section.button(actions,"Review flagged — worst first",lambda:None,"Review final verified images flagged by Complex QC, strongest suspicion first.",primary=True,enabled=False,icon='complex_qc')
    all_button.grid(row=0,column=0,sticky="ew")

    state={"result":None,"items":{},"running":False}
    events=queue.Queue()

    def select_issue(_event=None):
        selection=table.selection()
        issue=state["items"].get(selection[0]) if selection else None
        detail.set("" if not issue else issue.get("details") or issue.get("message") or "")

    table.bind("<<TreeviewSelect>>",select_issue)

    def begin_review(issues):
        issues=list(issues)
        if not issues:return
        start_suspicious_review(project,issues,source="Complex QC")
        section.context.refresh(force=True)
        first=issues[0]["image_id"]
        try:section.context.selected=next(i for i,row in enumerate(section.context.rows) if row.get("image_id")==first)
        except StopIteration:
            messagebox.showerror("Complex QC","The selected image is no longer in the active catalogue.",parent=dialog);return
        dialog.destroy();section.shell.render();section.shell.after_idle(lambda:section.shell._selected_image(False))

    def review_all():
        result=state.get("result") or {};begin_review(result.get("queue") or ())

    all_button.configure(command=review_all)

    def render_result(result):
        state["result"]=result;state["items"]={};table.delete(*table.get_children())
        flagged=int(result.get("flagged") or 0);high=int(result.get("high") or 0);scanned=int(result.get("scanned") or 0);review_total=int(result.get("review_total") or 0)
        summary.set(f"Scanned {scanned} verified images · Flagged {flagged} · High priority {high}")
        methods.set(_method_summary(result))
        abbrs={int(row["id"]):str(row.get("abbr") or row["id"]) for row in project.schema}
        for index,issue in enumerate(result.get("queue") or ()):
            iid=f"qc_{index}"
            landmarks=", ".join(abbrs.get(int(value),str(value)) for value in issue.get("landmark_ids") or ())
            values=(issue.get("priority","Review"),issue.get("display_name") or issue["image_id"],issue.get("message") or "",landmarks or "—")
            table.insert("","end",iid=iid,values=values,tags=("high",) if issue.get("priority")=="High" else ())
            state["items"][iid]=issue
        all_button.configure(state="normal" if review_total else "disabled")
        detail.set("Select a row to see why it was flagged." if review_total else "No unresolved QC outliers were found across the verified final data.")

    def run_scan():
        if state["running"]:return
        state["running"]=True;all_button.configure(state="disabled")
        table.delete(*table.get_children());state["items"]={};summary.set("Scanning verified final data…");methods.set("");detail.set("")
        progress.configure(mode="indeterminate");progress.start()
        def worker():
            try:
                result=scan_complex_qc(project,progress=lambda stage,done,total:events.put(("progress",stage,done,total)))
                events.put(("done",result))
            except Exception as exc:events.put(("error",exc))
        threading.Thread(target=worker,daemon=True,name="production-complex-qc").start()


    def poll():
        try:
            while True:
                kind,*payload=events.get_nowait()
                if kind=="progress":
                    stage,done,total=payload;summary.set(stage+"…" if not total else f"{stage}: {done} / {total}")
                elif kind=="error":
                    state["running"]=False;progress.stop()
                    messagebox.showerror("Complex QC",str(payload[0]),parent=dialog);summary.set("Scan failed. Close and reopen Complex QC to retry.");return
                else:
                    state["running"]=False;progress.stop();progress.configure(mode="determinate",value=0)
                    render_result(payload[0])
        except queue.Empty:
            if dialog.winfo_exists():dialog.after(100,poll)

    center(section.shell,dialog);run_scan();poll()
    return dialog
