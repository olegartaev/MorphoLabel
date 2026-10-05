"""Landmark-owned workflow, project and scientific actions."""
from __future__ import annotations
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from app.project_storage import Project
from app.gui_crop_debug import log
from app.ui.context import UIContext
from app.ui.section_registry import visible_sections
from app.ui.icons import TOPBAR_ICON_SIZE, CONTROL_ICON_SIZE
from app.ui.dialogs import center
from app.ui.tk_lifecycle import unbind_callback
from app.ui.photo_list_panel import PhotoListPanel
from app.ui.design import build_context_row, sidebar_width_for_window, dialog_width_for_columns, FlowRow
from app.ui.landmark_sidebar import LandmarkSidebar
from app.ui.preferences import last_project, remember_project
from app.ui.project_section import ProjectSection
from app.ui.crop_section import CropSection
from app.ui.landmarks_section import LandmarksSection
from app.ui.measurements_section import MeasurementsSection
from app.ui.export_section import ExportSection
from app.calibration_workflow import CalibrationWorkflow
from app.measurements_ui import MeasurementsWindow
from app.ai_package import export_model_package, import_model_package


class LandmarksRuntime(tk.Misc):
    """Ordinary module controller using the host's existing Tk interpreter.

    Misc supplies Tk/dialog APIs to the existing views without a second window
    or a duplicate application shell. All scientific callbacks belong here.
    """
    def __init__(self):
        self._host = None
        self._closed = False
        self._jobs = set()
        self._tclCommands = []
        self.current_view = None
        self.photo_panel = None
        self._selection_token = 0
        self._align_selected_top_once = False

    @property
    def project(self):
        return self.context.project

    def render(self, host=None):
        if self._closed:
            return
        first = self._host is None
        if host is not None:
            self._host = host
        if first:
            host = self._host
            self.master = host.container.winfo_toplevel()
            self.tk = self.master.tk
            self._w = self.master._w
            self.children = self.master.children
            self.root = host.container
            self.tip = host.tooltip
            self.ui_icon = host.ui_icon
            self.control_button = host.control_button
            self._menus = host.build_standard_menu
            self.show_module_hub = host.show_module_hub
            self.context = host.state.setdefault('context', UIContext(host.state.get('project')))
            self._remembered_project_path = self.context.project.root if self.context.project is not None else host.state.get('remembered_project') or last_project()
            if self.context.project is not None:
                remember_project(self.context.project.root)
            if host.state.get('closed_queue_navigation'):
                self._closed_queue_navigation = set(host.state['closed_queue_navigation'])
            self._enter_binding = self.bind('<Return>', self._enter_next, add='+')
        else:
            self._clear()
        self._render_landmarks_workspace()
        if first and self.context.project is None:
            self.after_idle(self._open_landmarks_workspace)

    def _clear(self):
        self.tip.hide()
        self.photo_panel = None
        self.current_view = None
        for child in self.root.winfo_children():
            child.destroy()
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=0)
        import gc
        gc.collect()

    def after(self, ms, func=None, *args):
        if func is None:
            return super().after(ms)
        if self._closed:
            return None
        job = None
        def invoke():
            self._jobs.discard(job)
            if not self._closed:
                func(*args)
        job = super().after(ms, invoke)
        self._jobs.add(job)
        return job

    def after_cancel(self, job):
        self._jobs.discard(job)
        return super().after_cancel(job)

    def _run_background_task(self, title, initial_text, worker, on_done):
        def done(result):
            if not self._closed:
                on_done(result)
        return self._host.run_background_task(title, initial_text, worker, done)

    def standard_menu_entries(self):
        return ()

    def queue_entries(self):
        return tuple(self._landmark_queue_entries())

    def hardware_summary(self, hardware):
        if self.project is None:
            return ''
        from app.performance_engine import performance_diagnostic
        return performance_diagnostic(self.project, hardware)['summary']

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._host is None:
            return
        self._host.state['context'] = self.context
        self._host.state['remembered_project'] = self._remembered_project_path
        self._host.state['closed_queue_navigation'] = set(self.__dict__.get('_closed_queue_navigation', ()))
        unbind_callback(self, '<Return>', self._enter_binding)
        for job in tuple(self._jobs):
            self.after_cancel(job)
        for widget in tuple(self.children.values()):
            if getattr(widget, 'master', None) is self:
                widget.destroy()
        self.current_view = None
        self.photo_panel = None
        self._host = None

    def _open_landmarks_workspace(self):
        if self.context.project:
            self.render();return
        remembered=self._remembered_project_path
        if remembered:
            self._open_project_path_async(Path(remembered),"Opening last project")
        else:
            self.context.section="project";self.render()


    def _open_project_path_async(self,path,title="Open project"):
        def worker(progress):
            progress("Opening project…");project=Project.open(Path(path))
            progress("Reading image catalog…");rows=project.catalog_rows()
            return project,rows
        return self._run_background_task(title,"Opening project…",worker,lambda result:self._attach_project(result[0],result[1]))


    def _load_existing_project_async(self,project,title="Open project"):
        def worker(progress):
            progress("Reading image catalog…");rows=project.catalog_rows()
            return project,rows
        return self._run_background_task(title,"Reading image catalog…",worker,lambda result:self._attach_project(result[0],result[1]))


    def _enter_next(self,event):
        if event.widget.winfo_class() in {"Entry","TEntry","TCombobox","Text","Spinbox","TSpinbox"}: return
        if self.context.project and self.context.section not in {"project","export"} and self._workflow_navigation_visible(self._active_batch_summary()):
            handler=getattr(getattr(self,"current_view",None),"on_enter",None)
            if handler:handler()
            else:self._nav_image(1)
        return "break"


    def _render_landmarks_workspace(self):
        """Render the module-owned workspace using the existing scientific views."""
        self.context.refresh(); self._nav()
        if not self.context.project:
            self.section_host=ttk.Frame(self.root); self.section_host.grid(row=1,column=0,sticky="nsew")
            self.root.rowconfigure(1,weight=1); self.root.columnconfigure(0,weight=1); self._section(); return
        if self.context.section in {"project", "export"}:
            self.section_host=ttk.Frame(self.root); self.section_host.grid(row=1,column=0,sticky="nsew")
            self.root.rowconfigure(1,weight=1); self.root.columnconfigure(0,weight=1); self._section(); return
        workspace=ttk.Frame(self.root); workspace.grid(row=1,column=0,sticky="nsew")
        self.root.rowconfigure(1,weight=1); self.root.columnconfigure(0,weight=1)
        panes=ttk.Panedwindow(workspace,orient="horizontal"); panes.grid(row=0,column=0,sticky="nsew")
        workspace.rowconfigure(0,weight=1); workspace.columnconfigure(0,weight=1)
        sidebar_host=ttk.Frame(panes); self.main=ttk.Frame(panes)
        panes.add(sidebar_host,weight=0); panes.add(self.main,weight=1)
        self.workspace_panes=panes
        self.main.rowconfigure(1,weight=1); self.main.columnconfigure(0,weight=1)
        self._status(); self._sidebar(sidebar_host); self._restore_sidebar_sash()
        self.section_host=ttk.Frame(self.main); self.section_host.grid(row=1,column=0,sticky="nsew")
        self._section()
        if self._align_selected_top_once:
            self._align_selected_top_once=False
            self.after_idle(self._align_selected_after_layout)


    def _nav(self):
        row=FlowRow(self.root,style="Topbar.TFrame"); row.grid(row=0,column=0,sticky="ew",pady=(0,4))
        home=ttk.Button(row,text="Modules",image=self.ui_icon("modules",TOPBAR_ICON_SIZE),compound="left",command=self.show_module_hub,style="Modules.TButton")
        home.pack(side="left",padx=(8,12),pady=(1,1));self.tip.bind(home,"Return to the MorphoLabel module hub.")
        ttk.Separator(row,orient="vertical").pack(side="left",fill="y",padx=(0,12),pady=4)
        sections=visible_sections(self.context.crop_enabled()) if self.context.project else visible_sections(True)
        for spec in sections:
            active=spec.key == self.context.section
            button=ttk.Button(row,text=spec.label,image=self.ui_icon(spec.key,TOPBAR_ICON_SIZE),compound="left",command=lambda key=spec.key:self.select(key),style="StageActive.TButton" if active else "Stage.TButton",state="normal" if self.context.project or spec.key=="project" else "disabled")
            button.pack(side="left",padx=(0,3)); self.tip.bind(button,f"Open the {spec.label} section.")
        self._menus(row)


    def _open_core_saved_queue(self,section,image_id):
        if not self.context.project:return False
        self.resume_queue_navigation()
        if image_id and not self.context.select_image(str(image_id)):return False
        self.context.section=str(section)
        self._align_selected_top_once=True
        self.render()
        return True


    def _open_landmark_ai_review_queue(self,batch_id):
        from app.landmark_ai_review import activate_review_session
        session=activate_review_session(self.context.project,batch_id)
        if not session:return False
        return self._open_core_saved_queue("landmarks",session.get("current_image_id"))


    def _close_core_queue(self,kind,batch_id=None):
        project=self.context.project
        if not project:return False
        if kind=="landmark_attention":
            from app.landmark_attention_queue import clear
            clear(project)
        elif kind=="crop":
            project.set_ui_state("crop_active_batch",{})
        elif kind=="landmark_ai_review":
            from app.landmark_ai_review import close_review_session
            close_review_session(project,batch_id)
        elif kind=="landmark_suspicious":
            from app.landmark_suspicious_review import clear
            clear(project)
        elif kind=="landmark":
            from app.landmark_ai_workflow import load_state
            stage=str((load_state(project) or {}).get("stage") or "")
            project.set_ui_state("landmark_training_queue_closed",{"stage":stage,"closed":True})
        self.render()
        return True


    def _landmark_queue_entries(self):
        project=self.context.project
        if not project:return ()
        entries=[]
        from app.landmark_attention_queue import display_summary as attention_summary,banner_copy
        attention=attention_summary(project)
        if attention:
            copy=banner_copy(attention);issue=dict(attention)
            entries.append({
                "title":"Attention queue",
                "detail":f"{copy['title']} · {attention.get('remaining',0)} remaining",
                "open":lambda item=issue:self.open_landmark_attention(item),
                "close":lambda:self._close_core_queue("landmark_attention"),
            })
        state=project.get_ui_state("crop_active_batch",{}) or {};ids=[str(v) for v in state.get("ids") or ()]
        if ids:
            pos=max(0,min(len(ids)-1,int(state.get("position",0) or 0)));target=ids[pos]
            entries.append({
                "title":"Crop batch",
                "detail":f"{pos+1} / {len(ids)} · saved Crop navigation",
                "open":lambda image_id=target:self._open_core_saved_queue("crop",image_id),
                "close":lambda:self._close_core_queue("crop"),
            })
        from app.crop_queues import saved_batches,close_saved_batch
        for saved in saved_batches(project,"crop_active_batch"):
            queue_id=saved["queue_id"]
            entries.append({"title":"Crop batch","detail":f"{len(saved.get('ids',()))} images · saved {saved.get('batch_type','Crop')} queue",
                "open":lambda ident=queue_id:self._open_saved_crop_queue(ident),
                "close":lambda ident=queue_id:(close_saved_batch(project,"crop_active_batch",ident),self.render())})
        for key,title in (("landmark_attention_queue","Attention queue"),("landmark_suspicious_review","Final data QC")):
            for saved in saved_batches(project,key):
                queue_id=saved["queue_id"]
                entries.append({"title":title,"detail":"Saved unfinished review",
                    "open":lambda k=key,ident=queue_id:self._open_saved_review_queue(k,ident),
                    "close":lambda k=key,ident=queue_id:(close_saved_batch(project,k,ident),self.render())})
        from app.landmark_ai_review import pending_review_sessions,review_summary
        for review in pending_review_sessions(project):
            summary=review_summary(project,review,review.get("current_image_id")) or {}
            batch_id=review.get("batch_id")
            entries.append({
                "title":"AI review",
                "detail":f"{summary.get('remaining',len(review.get('image_ids') or ())) } remaining",
                "open":lambda ident=batch_id:self._open_landmark_ai_review_queue(ident),
                "close":lambda ident=batch_id:self._close_core_queue("landmark_ai_review",ident),
            })
        from app.landmark_suspicious_review import summary as suspicious_summary
        suspicious=suspicious_summary(project)
        if suspicious:
            target=str(suspicious.get("image_id") or "")
            entries.append({
                "title":"Final data QC",
                "detail":f"{suspicious.get('position',0)} / {suspicious.get('total',0)}",
                "open":lambda image_id=target:self._open_core_saved_queue("landmarks",image_id),
                "close":lambda:self._close_core_queue("landmark_suspicious"),
            })
        from app.landmark_ai_workflow import load_state
        workflow=load_state(project);stage=workflow.get("stage")
        key="initial_image_ids" if stage=="INITIAL_TRAINING" else "improvement_image_ids" if stage=="MODEL_IMPROVEMENT" else None
        workflow_ids=[str(v) for v in workflow.get(key,())] if key else []
        closed_state=project.get_ui_state("landmark_training_queue_closed",{}) or {}
        workflow_closed=bool(closed_state.get("closed") and str(closed_state.get("stage") or "")==str(stage or ""))
        workflow_nav_key=(str(project.root),"landmarks","landmark",None)
        workflow_nav_closed=workflow_nav_key in self.__dict__.get("_closed_queue_navigation",set())
        if workflow_ids and not workflow_closed and not workflow_nav_closed:
            target=str(workflow.get("current_image_id") or workflow_ids[0])
            entries.append({
                "title":"Landmark training batch",
                "detail":f"{len(workflow_ids)} images · {stage.replace('_',' ').title()}",
                "open":lambda image_id=target:self._open_core_saved_queue("landmarks",image_id),
                "close":lambda:self._close_core_queue("landmark"),
            })
        return entries

    def _open_saved_crop_queue(self,queue_id):
        from app.crop_queues import open_saved_batch
        state=open_saved_batch(self.project,"crop_active_batch",queue_id)
        if not state or not state.get("ids"):return False
        ids=state["ids"];position=max(0,min(len(ids)-1,int(state.get("position",0))))
        return self._open_core_saved_queue("crop",ids[position])

    def _open_saved_review_queue(self,key,queue_id):
        from app.crop_queues import open_saved_batch
        state=open_saved_batch(self.project,key,queue_id)
        if not state:return False
        if key=="landmark_attention_queue":return self.open_landmark_attention()
        issues=state.get("issues",());position=max(0,min(len(issues)-1,int(state.get("position",0))))
        return bool(issues and self._open_core_saved_queue("landmarks",issues[position]["image_id"]))


    @staticmethod
    def _workflow_navigation_visible(batch):
        return batch is not None


    def _status(self):
        """Reserve the right-side navigation before flexible descriptive status text."""
        bar=ttk.Frame(self.main,padding=(2,1)); bar.grid(row=0,column=0,sticky="ew");bar.columnconfigure(0,weight=1);self.status_bar=bar
        left=ttk.Frame(bar);left.grid(row=0,column=0,sticky="ew");self.status_left=left
        self.status_navigation=None;self.status_queue_title=None;self.status_previous=None;self.status_index=None;self.status_next=None
        self._status_context_full=""
        context_fields,context_values=build_context_row(left,("Sample","Specimen"));context_fields.pack(side="left",padx=(0,7))
        self.status_locality=context_values["Sample"];self.status_context=context_values["Specimen"];self.status_context.configure(text="No images")
        self.status_count_host=ttk.Frame(left);self.status_count_host.pack(side="right")
        self.status_counts={}
        status_help={
            "Total":"Images currently included in this project view.",
            "Images":"Images currently included in the Landmarks workflow.",
            "Human verified":"Images whose current landmark set has been explicitly confirmed by a person.",
            "Reviewed":"Crops with a persisted explicit human-review observation for the current Crop.",
            "Review needed":"Existing Crop frames without a provable explicit human-review observation. Legacy Crop can remain scientifically usable and train-ready without being counted as reviewed.",
            "AI pending":"Current AI Crop proposals still awaiting human review.",
            "Train ready":"Crop frames eligible for training under the established scientific eligibility rules; this can include legacy accepted frames.",
            "Uncropped":"Included images that do not yet have a Crop frame.",
            "Training set":"Verified, complete images currently eligible for model training. This is the full set used when training starts.",
            "New/changed":"Training-set images whose current Crop or landmarks are not yet represented by the active model lineage.",
            "Incomplete":"Images where one or more required landmarks are not yet placed or explicitly marked missing.",
        }
        display_labels={"Incomplete":"Unresolved"}
        for key,value in self._section_counts().items():
            label=ttk.Label(self.status_count_host,text=f"{display_labels.get(key,key)}: {value}",style="StatusChip.TLabel"); label.pack(side="left",padx=(0,2)); self.status_counts[key]=label
            if key in status_help:self.tip.bind(label,status_help[key])
        self._update_status()


    def build_queue_navigation(self,parent):
        """One shared queue strip, mounted immediately above the working image."""
        navigation=ttk.Frame(parent,style="Attention.TFrame",padding=(6,4))
        self.status_navigation=navigation
        self.status_queue_title=ttk.Label(navigation,text="Review queue",style="AttentionTitle.TLabel",anchor="w")
        self.status_queue_title.pack(side="left",fill="x",expand=True)
        actions=ttk.Frame(navigation,style="Attention.TFrame");actions.pack(side="right")
        self.status_previous=self.control_button(actions,"Previous",lambda:self._nav_image(-1),"Show the previous queue item.",style="Nav.TButton",icon="previous")
        self.status_previous.pack(side="left",padx=(0,3))
        self.status_index=None
        self.status_next=self.control_button(actions,"Next",lambda:self._nav_image(1),"Show the next queue item.",style="Nav.TButton",icon="next")
        self.status_next.pack(side="left",padx=(3,3))
        self.control_button(
            actions,"Close queue",self.close_queue_navigation,
            "Close this queue navigation. Scientific annotations, models and training data are kept.",
            icon="close",
        ).pack(side="left",padx=(3,0))
        self._update_queue_navigation()
        return navigation


    def _update_queue_navigation(self):
        navigation=getattr(self,"status_navigation",None)
        if navigation is None or not navigation.winfo_exists():return
        batch=self._active_batch_summary()
        if not self._workflow_navigation_visible(batch):
            navigation.pack_forget();return
        navigation.pack(fill="x",pady=(4,0))
        kind=batch.get("kind") if batch else None
        attention_stage=batch.get("stage") if kind=="landmark_attention" else None
        queue_titles={
            "landmark":"Annotation batch",
            "landmark_ai_review":"AI review",
            "landmark_suspicious":"QC review",
            "landmark_attention":"Attention queue",
            "crop":"Crop batch",
        }
        title=queue_titles.get(kind,"Review queue");position_text=str(batch.get("text") or "").strip()
        self.status_queue_title.configure(text=f"{title} · {position_text}" if position_text else title)
        landmark_confirm=bool(self.context.section=="landmarks" and (kind in {"landmark","landmark_ai_review","landmark_suspicious"} or (kind=="landmark_attention" and attention_stage=="landmarks")))
        crop_confirm=bool(self.context.section=="crop" and ((kind=="landmark_attention" and attention_stage=="crop") or (batch and kind!="landmark_attention")))
        attention_retry=bool(self.context.section=="landmarks" and kind=="landmark_attention" and attention_stage=="prediction")
        confirm=landmark_confirm or crop_confirm or attention_retry
        next_text="Retry AI" if attention_retry else "Verify & Next" if landmark_confirm else "Confirm & Next" if crop_confirm else "Next"
        self.status_next.configure(
            text=next_text,
            style="NavPrimary.TButton" if confirm else "Nav.TButton",
            image=self.ui_icon("verify" if landmark_confirm or crop_confirm else "predict" if attention_retry else "next",CONTROL_ICON_SIZE),
            compound="left",
        )
        if landmark_confirm:
            source=batch.get("source") if batch else None
            if kind=="landmark_ai_review":help_text="Verify this reviewed AI landmark set and continue to the next unverified prediction."
            elif kind=="landmark_suspicious" and source=="Complex QC":help_text="Verify or re-verify this final landmark set and continue to the next Complex QC outlier."
            elif kind=="landmark_suspicious":help_text="Verify this landmark set after checking the flagged placement and continue."
            else:help_text="Verify this completed landmark set and continue to the next training image."
            self.tip.bind(self.status_next,help_text)
        elif attention_retry:self.tip.bind(self.status_next,"Retry AI landmark prediction for this queued image.")
        elif crop_confirm:self.tip.bind(self.status_next,"Confirm this Crop and continue this queue.")
        else:self.tip.bind(self.status_next,"Show the next queue item.")


    def _refresh_status_context(self):
        """Context values use the same bold-key / normal-value language as X-ray."""
        label=getattr(self,"status_context",None)
        if label is None or not label.winfo_exists():return
        label.configure(text=getattr(self,"_status_context_full",""))


    def _sidebar(self,parent):
        if self.context.section == "landmarks":
            self.photo_panel=LandmarkSidebar(parent,self.context,self._selected_image,self.tip,self._select_landmark,on_exclusion=self._photo_exclusion_changed)
        else:
            self.photo_panel=PhotoListPanel(parent,self.context,self._selected_image,self.tip,on_exclusion=self._photo_exclusion_changed)
        self.photo_panel.pack(fill="both",expand=True)
        self.photo_panel.refresh()


    def _restore_sidebar_sash(self, attempt=0):
        panes=getattr(self,"workspace_panes",None)
        if panes is None or not self.context.project:return
        width=panes.winfo_width()
        if width < 650 and attempt < 8:
            panes.bind("<Configure>",self._restore_sidebar_on_configure,add="+"); return
        try:
            responsive_default=sidebar_width_for_window(width,self.photo_panel.winfo_reqwidth())
            maximum=max(250,min(480,int(width*.29),max(250,width-560)))
            saved=self.context.project.get_ui_state("workspace_sidebar_sash",None)
            target=responsive_default if saved is None else int(saved)
            panes.sashpos(0,max(250,min(maximum,target)))
            panes.bind("<ButtonRelease-1>",self._save_sidebar_sash,add="+")
        except Exception:
            return


    def _restore_sidebar_on_configure(self,_event=None):
        self._restore_sidebar_sash()


    def _save_sidebar_sash(self,_event=None):
        try:
            self.context.project.set_ui_state("workspace_sidebar_sash",int(self.workspace_panes.sashpos(0)))
        except Exception:
            return


    def _select_landmark(self, ident):
        view=getattr(self,"current_view",None)
        if view and hasattr(view,"select_landmark"): view.select_landmark(ident)


    def _selected_image(self, preserve_list=True):
        """Paint list selection now; start asynchronous image work only after Tk becomes idle."""
        self._update_status()
        self._selection_token += 1
        token=self._selection_token
        # This is the target-request identity; it exists before after_idle starts a canvas load.
        self.selection_request_epoch=token
        def begin():
            if token != self._selection_token or not self.winfo_exists(): return
            view=getattr(self,"current_view",None)
            if view and hasattr(view,"on_image_selected"): view.on_image_selected()
            elif view and hasattr(view,"canvas"):
                canvas=view.canvas
                if hasattr(canvas,"load_current"): canvas.load_current()
                elif hasattr(canvas,"render"): canvas.render()
        self.after_idle(begin)


    def _update_status(self):
        if not hasattr(self,"status_context"): return
        row=self.context.current() or {}; name=row.get("original_name","No images"); sample=row.get("locality",row.get("sample_id",""))
        self._status_context_full=str(name or "No images")
        self.status_context.configure(text=self._status_context_full)
        self.status_locality.configure(text=str(sample or "—"))
        self._update_queue_navigation()
        display_labels={"Incomplete":"Unresolved"};counts=self._section_counts()
        for key,label in getattr(self,"status_counts",{}).items():
            label.configure(text=f"{display_labels.get(key,key)}: {counts.get(key,0)}")


    def _align_selected_after_layout(self):
        """Apply section-switch alignment only after panes and section geometry have settled."""
        if not self.winfo_exists():return False
        try:self.update_idletasks()
        except tk.TclError:return False
        return self._sync_photo_panel_current(align_top=True,refresh_rows=False)


    def _sync_photo_panel_current(self, *, align_top=False, refresh_rows=True):
        panel=getattr(self,"photo_panel",None)
        target=getattr(panel,"photos",panel)
        sync=getattr(target,"sync_current",None)
        if sync:
            sync(reveal=True,align_top=align_top,refresh_rows=refresh_rows)
            return True
        return False


    def open_landmark_attention(self, issue=None):
        """Open one persisted attention item without rebuilding the whole workspace."""
        self.__dict__.pop("_closed_queue_navigation",None)
        if not self.context.project:return False
        if issue is None:
            from app.landmark_attention_queue import current as current_attention
            issue=current_attention(self.context.project)
        if not issue:
            self._update_status();return False
        desired_section="crop" if issue.get("stage")=="crop" else "landmarks"
        same_workspace=bool(
            self.context.section==desired_section
            and getattr(self,"current_view",None) is not None
            and getattr(self,"photo_panel",None) is not None
        )
        if not self.context.select_image(issue["image_id"]):return False
        self.context.section=desired_section
        if same_workspace:
            # Queue navigation changes only the selected record. Rebuilding the
            # whole workspace here used to recompute catalogue-wide counters,
            # recreate widgets and re-decode the sidebar on every image.
            self._sync_photo_panel_current(align_top=True,refresh_rows=False)
            self._selected_image(False)
            view=getattr(self,"current_view",None)
            refresh_banner=getattr(view,"refresh_attention_banner",None)
            if refresh_banner:refresh_banner()
        else:
            self._align_selected_top_once=True
            self.render()
        def show_reason():
            view=getattr(self,"current_view",None)
            if self.context.section=="landmarks" and view is not None and hasattr(view,"_inline_status"):
                view._inline_status(issue.get("reason") or "Check this image")
            self._update_status()
        self.after_idle(show_reason)
        return True


    def _queue_navigation_key(self,batch):
        return (str(self.context.project.root),self.context.section,batch.get("kind"),batch.get("source"))


    def close_queue_navigation(self):
        batch=self._active_batch_summary()
        if not batch:return False
        kind=batch.get("kind")
        if kind=="landmark_attention":
            return self._close_core_queue("landmark_attention")
        if kind=="crop":
            return self._close_core_queue("crop")
        if kind=="landmark_ai_review":
            return self._close_core_queue("landmark_ai_review",batch.get("batch_id"))
        if kind=="landmark_suspicious":
            return self._close_core_queue("landmark_suspicious")
        if kind=="landmark":
            closed=self.__dict__.setdefault("_closed_queue_navigation",set())
            closed.add(self._queue_navigation_key(batch))
            self.render();return True
        return False


    def resume_queue_navigation(self):
        self.__dict__.pop("_closed_queue_navigation",None)
        if self.context.project:self.context.project.set_ui_state("landmark_training_queue_closed",{})


    def _active_batch_summary(self):
        batch=self._persisted_batch_summary()
        if batch and self._queue_navigation_key(batch) in self.__dict__.get("_closed_queue_navigation",set()):return None
        return batch


    def _persisted_batch_summary(self):
        """Finite batch position from persisted IDs only; never the catalogue index."""
        if not self.context.project:return None
        from app.ui.batch_status import position_and_remaining,compact
        current=(self.context.current() or {}).get('image_id')
        from app.landmark_attention_queue import display_summary as attention_summary
        attention=attention_summary(self.context.project)
        if attention and current==attention.get('image_id'):
            label={"crop":"Crop","prediction":"Retry AI","landmarks":"Landmarks"}.get(attention.get("stage"),"Review")
            return {"kind":"landmark_attention","stage":attention.get("stage"),"text":f"{attention.get('position',0)}/{attention.get('total',0)} · {label}","source":"Prediction attention"}
        if self.context.section=='crop':
            state=self.context.project.get_ui_state('crop_active_batch',{});ids=list(state.get('ids',()))
            if current in ids:
                counts=self.context.project.crop_batch_counts(ids);status=position_and_remaining(ids,current,())
                return {'kind':'crop','text':compact({**status,'remaining':counts['Remaining']})}
        if self.context.section=='landmarks':
            from app.landmark_suspicious_review import active as suspicious_active, summary as suspicious_summary
            suspicious=suspicious_active(self.context.project)
            if suspicious:
                summary=suspicious_summary(self.context.project)
                if summary and current==summary.get('image_id'):
                    return {'kind':'landmark_suspicious','text':compact(summary),'source':summary.get('source')}
            from app.landmark_ai_review import active_review_session,review_summary
            review=active_review_session(self.context.project)
            if review and current in review.get('image_ids',()):
                summary=review_summary(self.context.project,review,current)
                return {'kind':'landmark_ai_review','text':compact(summary),'batch_id':review.get('batch_id')}
            from app.landmark_ai_workflow import load_state
            state=load_state(self.context.project);stage=state.get('stage');ids=list(state.get('initial_image_ids' if stage=='INITIAL_TRAINING' else 'improvement_image_ids' if stage=='MODEL_IMPROVEMENT' else '',()))
            closed=self.context.project.get_ui_state("landmark_training_queue_closed",{}) or {}
            if current in ids and not (closed.get("closed") and str(closed.get("stage") or "")==str(stage or "")):
                # Context rows are authoritative on first render and delta-updated per edited image.
                # Never re-run annotation_status over an active batch during a point gesture.
                rows={row.get('image_id'):row for row in self.context.rows}
                done=[ident for ident in ids if rows.get(ident,{}).get('human_verified')]
                return {'kind':'landmark','text':compact(position_and_remaining(ids,current,done))}
        return None


    def _section_counts(self):
        if not self.context.project: return {"Total":0}
        if self.context.section == "crop": return self.context.crop_counts()
        if self.context.section == "landmarks": return self.context.landmark_counts()
        if self.context.section == "measurements": return {"Total":len(self.context.rows)}
        return self.context.counts()


    def _nav_image(self,step):
        row=self.context.current() or {}; section=self.context.section
        log(row.get("image_id",""),"NAV_CLICK","START",detail=f"section={section}; step={int(step)}; selected={row.get('image_id')}")
        view=getattr(self,"current_view",None)
        from app.landmark_attention_queue import active as active_attention_queue
        attention_handler=getattr(view,"navigate_attention_queue",None)
        if active_attention_queue(self.context.project) and attention_handler:
            handled=attention_handler(step)
            if handled:
                log(row.get("image_id",""),"NAV_FINISHED","END",detail=f"section={section}; step={int(step)}; attention=1")
                return
        # Finite-batch views exclusively own their scientific commit before navigation.
        handler=(getattr(view,"navigate_training_batch",None) if section=="landmarks" else getattr(view,"navigate_batch",None) if section=="crop" else None)
        if handler:
            handled=handler(step)
            log(row.get("image_id",""),"NAV_FINISHED" if handled else "NAV_BLOCKED","END",detail=f"section={section}; step={int(step)}")
            if handled:return
        if self.photo_panel:
            self.photo_panel.navigate(step); return
        self.context.navigate(step); self._selected_image(False)


    def _section(self):
        if self.context.project and self.context.section in {"landmarks","measurements"} and not self.context.project.schema:
            ttk.Label(self.section_host,text="Landmark scheme needs attention. Edit the scheme in Project before using this section.",padding=18,font=("Segoe UI",11)).pack(anchor="nw")
            self.current_view=None;return
        sections={"project":ProjectSection,"crop":CropSection,"landmarks":LandmarksSection,"measurements":MeasurementsSection,"export":ExportSection}
        self.current_view=sections[self.context.section](self,self.section_host); self.current_view.render()


    def select(self,key):
        if not self.context.project and key != "project": return
        if self.context.project and key != "project" and (not self.context.project.schema or self.context.project.schema_error):
            messagebox.showwarning("Landmark scheme required", "A landmark scheme must be created/applied before continuing.\n\nIn Project, choose Create scheme… or Edit scheme… and apply a valid scheme.", parent=self)
            if self.context.section != "project":
                self.context.section="project";self.render()
            return
        if key == "crop" and not self.context.crop_enabled(): key="landmarks"
        image_id=(self.context.current() or {}).get("image_id")
        self._align_selected_top_once=(key!=self.context.section)
        self.context.section=key
        if image_id:self.context.select_image(image_id)
        self.render()


    def _restore_last_project(self):
        remembered=last_project()
        if not remembered: return None
        try:
            project=Project.open(remembered)
            log("GLOBAL","ui_preference_project_open","END",path=str(project.root),detail="last project restored in ProductionShell")
            return project
        except Exception as exc:
            log("GLOBAL","ui_preference_project_open","ERROR",path=str(remembered),detail=str(exc))
            return None


    def _attach_project(self, project, prepared_rows=None):
        self._remembered_project_path=project.root
        self.context=UIContext(project=project,section="project")
        self._host.state["context"]=self.context
        if prepared_rows is None:self.context.refresh(force=True)
        else:
            self.context.rows=list(prepared_rows);self.context._catalog_valid=True;self.context.invalidate_counts();self.context.selected=0
        remember_project(project.root)
        log("GLOBAL","project_opened_in_shell","END",path=str(project.root),detail=f"images={len(self.context.rows)}")
        self.render()


    def open_project(self,path=None):
        if path is not None:
            return self._open_project_path_async(Path(path),"Open project")
        folder=filedialog.askdirectory(parent=self,title="Select project folder")
        if not folder:return
        self._open_project_path_async(Path(folder),"Open project")


    def new_project(self):
        name=simpledialog.askstring("New project","Project name:",parent=self)
        if not name:return
        source=filedialog.askdirectory(title="Folder with original photographs",parent=self)
        destination=filedialog.askdirectory(title="Folder where the project will be created",parent=self)
        if not all((source,destination)):return
        layout,subfolder=self._source_layout(Path(source))
        def worker(progress):
            progress("Creating project and scanning source photographs…")
            project=Project.create(name,Path(source),Path(destination),source_layout=layout,source_image_subfolder=subfolder,progress=progress)
            progress("Reading image catalog…");rows=project.catalog_rows()
            return project,rows
        self._run_background_task("New project","Creating project…",worker,lambda result:self._attach_project(result[0],result[1]))


    def _source_layout(self, source):
        direct=messagebox.askyesno("Original image layout","Are original photographs directly inside sample folders?\n\nYes = sample/image\nNo = sample/subfolder/image",parent=self)
        layout="direct" if direct else "subfolder"; subfolder=""
        if layout=="subfolder": subfolder=simpledialog.askstring("Source subfolder","Subfolder containing original photographs:",initialvalue="orig",parent=self) or "orig"
        return layout,subfolder


    def open_schema(self):
        project=self.context.project
        if not project: return
        from app.schema_editor import SchemaEditor
        def applied():
            self.context.refresh(force=True);self.context.invalidate_counts();self.render()
        dialog=SchemaEditor(self,project.schema_path,project=project,on_apply=applied); center(self,dialog)
        dialog.bind("<Destroy>",lambda event,d=dialog: self._schema_closed(event,d), add="+")


    def _schema_closed(self,event,dialog):
        if self._closed or event.widget is not dialog or not self.winfo_exists() or not self.context.project:return
        root=Path(self.context.project.root);section=self.context.section
        def worker(progress):
            progress("Reloading landmark scheme…");project=Project.open(root)
            progress("Refreshing image catalog…");rows=project.catalog_rows()
            return project,rows
        def done(result):
            project,rows=result
            current=self.context.project
            if current is None or Path(current.root)!=root:return
            self.context.project=project;self.context.rows=list(rows);self.context._catalog_valid=True
            self.context.invalidate_counts();self.context.selected=min(self.context.selected,max(0,len(rows)-1));self.context.section=section
            self.after_idle(self.render)
        self._run_background_task("Landmark scheme","Reloading landmark scheme…",worker,done)


    def add_samples(self):
        project=self.context.project
        def worker(progress):
            progress("Scanning source photo folders…");total=project.scan_originals()
            progress("Refreshing image catalog…");rows=project.catalog_rows()
            return total,rows
        def done(result):
            total,rows=result;self.context.rows=list(rows);self.context._catalog_valid=True;self.context.invalidate_counts();self.context.selected=min(self.context.selected,max(0,len(rows)-1))
            messagebox.showinfo("Rescan catalog",f"Source photo folder scanned safely. Existing project work was preserved. Catalog images: {total}.",parent=self);self.render()
        self._run_background_task("Rescan catalog","Scanning source photo folders…",worker,done)


    def relink_source(self):
        folder=filedialog.askdirectory(parent=self,title="Root photo folder")
        if not folder:return
        project=self.context.project
        def worker(progress):
            progress("Relinking source photographs…");result=project.relink(folder)
            progress("Refreshing image catalog…");rows=project.catalog_rows()
            return result,rows
        def done(payload):
            result,rows=payload;self.context.rows=list(rows);self.context._catalog_valid=True;self.context.invalidate_counts()
            messagebox.showinfo("Root photo folder",f"Matched {result['matched']} of {result['total']} catalog images.",parent=self);self.render()
        self._run_background_task("Root photo folder","Relinking source photographs…",worker,done)


    def open_calibration(self):
        dialog=CalibrationWorkflow(self,self.context.project); center(self,dialog); return dialog


    def open_measurements(self):
        view=getattr(self,"current_view",None)
        callback=getattr(view,"refresh_definitions",self.render)
        select_callback=getattr(view,"select_measurement",None)
        dialog=MeasurementsWindow(self,self.context.project,on_saved=callback,on_selection=select_callback); center(self,dialog); return dialog

    def import_measurement_definitions(self):
        from app.measurements_ui import transfer_measurement_definitions
        return transfer_measurement_definitions(self,self.project,"import",self.render)

    def export_measurement_definitions(self):
        from app.measurements_ui import transfer_measurement_definitions
        return transfer_measurement_definitions(self,self.project,"export")

    def add_measurement(self):
        dialog=self.open_measurements()
        if dialog:dialog.after_idle(dialog.add)
        return dialog


    def show_models(self,kind=None):
        if not self.context.project:return
        if kind=="landmark":return self._show_landmark_models()
        kinds=(kind,) if kind else ("crop","landmark")
        landmark_only=kinds==("landmark",)
        dialog=tk.Toplevel(self);dialog.title("Models");dialog.transient(self)
        frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        columns=("active","model","dataset","split","iou","boundary","rotation") if kinds==("crop",) else ("active","model","parent","dataset","p90","best_epoch","manual_p90","ai_p90","human_ratio","manual_status","created")
        table_frame=ttk.Frame(frame);table_frame.grid(row=0,column=0,sticky="nsew");table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        table=ttk.Treeview(table_frame,columns=columns,show="headings")
        labels={"active":"Active","model":"Model","dataset":"Dataset N","split":"Train / Val","iou":"Validation IoU","boundary":"Boundary MAE %","rotation":"Rotation MAE °","parent":"Parent","p90":"Validation P90 %","best_epoch":"Best epoch","manual_p90":"Manual P90 %","ai_p90":"AI P90 %","human_ratio":"AI / manual","manual_status":"Interpretation","created":"Created"}
        widths={"active":65,"model":160,"dataset":80,"split":90,"iou":105,"boundary":115,"rotation":115,"parent":125,"p90":105,"best_epoch":80,"manual_p90":95,"ai_p90":85,"human_ratio":90,"manual_status":155,"created":125}
        model_width=dialog_width_for_columns((widths[col] for col in columns),dialog.winfo_screenwidth(),chrome=105)
        dialog.geometry(f"{model_width}x{440 if landmark_only else 420}");dialog.minsize(min(model_width,760 if landmark_only else 660),260)
        for col in columns:table.heading(col,text=labels[col]);table.column(col,width=widths[col],anchor="w",stretch=col=="model")
        scroll=ttk.Scrollbar(table_frame,orient="vertical",command=table.yview);table.configure(yscrollcommand=scroll.set);table.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")
        import json
        if landmark_only:
            from app.human_baseline import repeatability_report_state, comparison_for_model, repeatability_reference_frame_issue, repeatability_reference_frame_issue_message, redo_repeatability_image
            from app.landmark_qc import stored_control_landmark_quality_profile, evaluate_control_set, persist_control_landmark_quality_profile
            from app.project_storage import landmark_model_schema_compatible
            human_state=repeatability_report_state(self.context.project)
            human_report=human_state.get("report")
        else:
            human_state={"ready":False,"report":None,"message":""};human_report=None;current_schema=None
        def manifest_count(item):
            path=item.get("dataset_manifest_path")
            if not path:return "—"
            try:
                data=json.loads((self.context.project.data_root/path).read_text(encoding="utf-8"));return str(len(data.get("images",data.get("selected_images",()))))
            except (OSError,ValueError,TypeError):return "—"
        def landmark_details(item,metrics):
            payload={}
            try:
                model_path=self.context.project.data_root/(item.get("path") or "")/"model.json";payload=json.loads(model_path.read_text(encoding="utf-8")) if model_path.is_file() else {}
            except (OSError,ValueError,TypeError):pass
            result=payload.get("result",{});engineering=result.get("engineering_validation",payload.get("engineering_validation",{})) or {}
            p90=engineering.get("p90_error_percent",metrics.get("p90_error_percent"));best=result.get("best_epoch",payload.get("best_epoch",metrics.get("best_epoch")))
            manual_p90=ai_p90=ratio=status=None
            if human_report is not None:
                manual_p90=((human_report.get("human") or {}).get("aggregate") or {}).get("p90_error_percent")
                profile=stored_control_landmark_quality_profile(self.context.project,item["model_id"],image_ids=human_report.get("image_ids",())) if landmark_model_schema_compatible(self.context.project,item) else None
                if profile is not None:
                    ai_p90=(profile.get("aggregate") or {}).get("p90_error_percent")
                    comparison=comparison_for_model(human_report,profile);ratio=(comparison.get("ratios") or {}).get("p90");status=comparison.get("grade")
            return p90,best,manual_p90,ai_p90,ratio,status
        def populate():
            nonlocal human_state,human_report
            if landmark_only:
                human_state=repeatability_report_state(self.context.project);human_report=human_state.get("report")
            selected=(table.item(table.selection()[0],"values")[1] if table.selection() else None)
            table.delete(*table.get_children())
            with self.context.project.transaction() as c: current=c.execute("SELECT model_id,kind,active,metrics_json,dataset_manifest_path,parent_model_id,path,created_at FROM models WHERE kind IN ({}) ORDER BY kind,created_at DESC".format(",".join("?"*len(kinds))),kinds).fetchall()
            for row in current:
                item=dict(row);metrics=json.loads(item.get("metrics_json") or "{}")
                if item["kind"]=="crop":
                    total=metrics.get("training_examples",metrics.get("training_count","—"));val=metrics.get("validation_count",len(metrics.get("validation_indices",[])));train=metrics.get("train_count",len(metrics.get("train_indices",[])));values=("✓" if item["active"] else "",item["model_id"],total,f"{train} / {val}" if train or val else "—","—" if metrics.get("validation_iou") is None else f"{metrics['validation_iou']:.3f}","—" if not metrics.get("boundary_mae_percent") else f"{sum(metrics['boundary_mae_percent'])/len(metrics['boundary_mae_percent']):.2f}%","—" if metrics.get("rotation_mae_degrees") is None else f"{metrics['rotation_mae_degrees']:.2f}")
                else:
                    p90,best,manual_p90,ai_p90,ratio,status=landmark_details(item,metrics);values=("✓" if item["active"] else "",item["model_id"],item.get("parent_model_id") or "—",manifest_count(item),"—" if p90 is None else f"{float(p90):.3f}","—" if best is None else str(best),"—" if manual_p90 is None else f"{float(manual_p90):.3f}","—" if ai_p90 is None else f"{float(ai_p90):.3f}","—" if ratio is None else f"{float(ratio):.2f}×",status or "Not evaluated",item.get("created_at") or "—")
                iid=table.insert("","end",values=values)
                if selected==item["model_id"]:table.selection_set(iid)
        populate()
        if landmark_only:
            ttk.Label(frame,text="Human P90: your repeat-placement error. AI P90: model error on the same images. AI/Human 1.00× ≈ your Human Repeatability. Validation P90 uses each model's own split. Lower is better.",style="Muted.TLabel",wraplength=1120).grid(row=1,column=0,sticky="w",pady=(7,0))
        actions=ttk.Frame(frame);actions.grid(row=2 if landmark_only else 1,column=0,sticky="ew",pady=(8,0))
        if kinds==("crop",):
            use=self.control_button(actions,"Use selected",lambda:None,"Use this saved model for new Crop predictions.")
            use.configure(state="disabled")
            def refresh_use(_event=None): use.configure(state="normal" if table.selection() else "disabled")
            def set_crop_active():
                selected=table.selection()
                if not selected:return
                model_id=table.item(selected[0],"values")[1]
                try:
                    self.context.project.set_active_model("crop",model_id)
                    populate();refresh_use();self.render()
                except Exception as exc:messagebox.showerror("Set active Crop model",str(exc),parent=dialog)
            use.configure(command=set_crop_active);table.bind("<<TreeviewSelect>>",refresh_use,add="+")
        if landmark_only:
            def selected_model_id():
                selected=table.selection()
                return None if not selected else str(table.item(selected[0],"values")[1])
            def set_active():
                model_id=selected_model_id()
                if not model_id:return
                try:
                    from app.landmark_training_workflow import activate_landmark_model
                    activate_landmark_model(self.context.project,model_id)
                    self.context.invalidate_counts()
                    populate();self.render()
                except Exception as exc:messagebox.showerror("Set active Landmark model",str(exc),parent=dialog)
            def compare_manual():
                nonlocal human_state,human_report
                model_id=selected_model_id()
                if not model_id:return
                human_state=repeatability_report_state(self.context.project);human_report=human_state.get("report")
                if human_report is None:
                    messagebox.showinfo("Compare with manual",human_state.get("message") or "Complete Human Repeatability first to compare AI with human placement.",parent=dialog);populate();return
                issue=repeatability_reference_frame_issue(self.context.project,human_report["run_id"],reference_pass=1)
                if issue:
                    text=repeatability_reference_frame_issue_message(issue)
                    repairable=issue.get("kind") in {"legacy_changed","frozen_changed","size_changed"}
                    if not repairable:
                        messagebox.showerror("Compare with manual",text,parent=dialog);return
                    position=int(issue["position"]);total=int(issue["total"]);image_id=str(issue["image_id"])
                    answer=messagebox.askyesno("Repair Human repeatability",text+f"\n\nRepair only image {position}/{total} now?\nThe other {max(0,total-1)} image(s) will stay unchanged.",parent=dialog,default="yes")
                    if not answer:return
                    try:
                        _run,result=redo_repeatability_image(self.context.project,human_report["run_id"],position)
                    except Exception as exc:
                        messagebox.showerror("Repair Human repeatability",str(exc),parent=dialog);return
                    populate();dialog.destroy()
                    view=getattr(self,"current_view",None)
                    if view is not None and hasattr(view,"open_repeat"):
                        self.after_idle(view.open_repeat)
                    else:
                        messagebox.showinfo("Repair Human repeatability",f"Image {result['position']}/{result['total']} reset.\nID: {result['image_id']}\n\nOpen Landmarks → Human repeatability... and complete Annotation 1 and Annotation 2 for this one image.",parent=self)
                    return
                image_ids=tuple(map(str,human_report.get("image_ids",())))
                human_p90=((human_report.get("human") or {}).get("aggregate") or {}).get("p90_error_percent")
                if not image_ids or human_p90 in (None,0):
                    messagebox.showinfo("Compare with manual","The latest Human repeatability report does not contain a usable P90 comparison set.",parent=dialog);return
                def worker(progress):
                    progress("Running selected model on the frozen Human repeatability images…")
                    from app.ai_batch import backend_for_model
                    from app.human_baseline import evaluate_model_on_repeatability_run
                    _,backend=backend_for_model(self.context.project,model_id)
                    result=evaluate_model_on_repeatability_run(self.context.project,human_report["run_id"],model_id,backend=backend,reference_pass=1)
                    profile=persist_control_landmark_quality_profile(self.context.project,result)
                    return profile,comparison_for_model(human_report,profile)
                def done(value):
                    profile,comparison=value;populate()
                    ai_p90=(profile.get("aggregate") or {}).get("p90_error_percent");ratio=(comparison.get("ratios") or {}).get("p90");grade=comparison.get("grade","Unavailable")
                    if ai_p90 is None or ratio is None:
                        messagebox.showinfo("AI vs manual",f"Model: {model_id}\n\nThe same-image comparison did not contain enough comparable landmarks to calculate P90.",parent=dialog);return
                    delta=(float(ratio)-1.0)*100.0;difference=f"Difference: {delta:+.0f}%"
                    explanation="AI error is below measured human repeatability on this control set." if delta<0 else "AI error is higher than measured human repeatability on this control set." if delta>0 else "AI error matches measured human repeatability on this control set."
                    messagebox.showinfo("AI vs manual",f"Model: {model_id}\n\nHuman repeatability P90: {float(human_p90):.3f}%\nAI P90 on same images: {float(ai_p90):.3f}%\n\nAI / Human: {float(ratio):.2f}×\n{difference}\nStatus: {grade}\n\n{explanation}\nLower is better. Comparison uses the same control images.",parent=dialog)
                self._run_background_task("Compare with manual","Preparing same-image comparison…",worker,done)
            set_button=self.control_button(actions,"Set active",set_active,"Use the selected compatible finalized Landmark model for prediction.")
            set_button.pack(side="left")
            compare_button=self.control_button(actions,"Compare with manual",compare_manual,"Compare the selected model with your Human Repeatability on the exact same images.")
            compare_button.pack(side="left",padx=(6,0))
        self.control_button(actions,"Close",dialog.destroy,"Close this model list.").pack(side="right")
        if kinds==("crop",): use.pack(side="right",padx=(0,8))
        center(self,dialog)


    def _show_landmark_models(self):
        """Friendly Landmark model list with accuracy details kept one click away."""
        if not self.context.project:return
        import json
        dialog=tk.Toplevel(self);dialog.title("Landmark models");dialog.transient(self);dialog.geometry("1060x570");dialog.minsize(860,470)
        outer=ttk.Frame(dialog,padding=16);outer.pack(fill="both",expand=True);outer.rowconfigure(2,weight=1);outer.columnconfigure(0,weight=1)

        header=ttk.Frame(outer);header.grid(row=0,column=0,sticky="ew")
        ttk.Label(header,text="Landmark models",style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Choose the model used for prediction. Accuracy details compares any saved model with your own Human Repeatability on the same images.",
            style="PageSubtitle.TLabel",wraplength=960,justify="left",
        ).pack(anchor="w",pady=(2,10))

        note=ttk.Label(
            outer,
            text="Validation P90 comes from that model's held-out training split. It is useful for model development, but it is not directly comparable across different datasets. Use Accuracy details for the same-image human comparison.",
            style="Muted.TLabel",wraplength=960,justify="left",
        )
        note.grid(row=1,column=0,sticky="ew",pady=(0,10))

        table_frame=ttk.Frame(outer);table_frame.grid(row=2,column=0,sticky="nsew");table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        columns=("active","model","parent","dataset","validation","created")
        table=ttk.Treeview(table_frame,columns=columns,show="headings",selectmode="browse")
        labels={"active":"Active","model":"Model","parent":"Parent","dataset":"Training images","validation":"Validation P90","created":"Created"}
        widths={"active":65,"model":190,"parent":180,"dataset":110,"validation":120,"created":170}
        for col in columns:
            table.heading(col,text=labels[col]);table.column(col,width=widths[col],anchor="w",stretch=col=="model")
        table.tag_configure("active",foreground="#188038")
        scroll=ttk.Scrollbar(table_frame,orient="vertical",command=table.yview);table.configure(yscrollcommand=scroll.set)
        table.grid(row=0,column=0,sticky="nsew");scroll.grid(row=0,column=1,sticky="ns")

        details=tk.StringVar(value="Select a model to see its details.")
        ttk.Label(outer,textvariable=details,style="Muted.TLabel",wraplength=960,justify="left").grid(row=3,column=0,sticky="ew",pady=(8,0))

        records={}
        def manifest_count(item):
            path=item.get("dataset_manifest_path")
            if not path:return "—"
            try:
                data=json.loads((self.context.project.data_root/path).read_text(encoding="utf-8"))
                return str(len(data.get("images",data.get("selected_images",()))))
            except (OSError,ValueError,TypeError):return "—"

        def model_details(item,metrics):
            payload={}
            try:
                model_path=self.context.project.data_root/(item.get("path") or "")/"model.json"
                payload=json.loads(model_path.read_text(encoding="utf-8")) if model_path.is_file() else {}
            except (OSError,ValueError,TypeError):pass
            result=payload.get("result",{});engineering=result.get("engineering_validation",payload.get("engineering_validation",{})) or {}
            p90=engineering.get("p90_error_percent",metrics.get("p90_error_percent"))
            best=result.get("best_epoch",payload.get("best_epoch",metrics.get("best_epoch")))
            return p90,best

        def populate():
            selected_id=selected_model_id()
            table.delete(*table.get_children());records.clear()
            with self.context.project.transaction() as c:
                current=c.execute("SELECT model_id,active,metrics_json,dataset_manifest_path,parent_model_id,path,created_at FROM models WHERE kind='landmark' ORDER BY created_at DESC,model_id DESC").fetchall()
            selected_item=None
            for row in current:
                item=dict(row);metrics=json.loads(item.get("metrics_json") or "{}");p90,best=model_details(item,metrics);item["_best_epoch"]=best;item["_p90"]=p90;records[item["model_id"]]=item
                values=("✓" if item["active"] else "",item["model_id"],item.get("parent_model_id") or "Bootstrap",manifest_count(item),"—" if p90 is None else f"{float(p90):.3f}%",item.get("created_at") or "—")
                iid=table.insert("","end",values=values,tags=("active",) if item["active"] else ())
                if selected_id==item["model_id"]:selected_item=iid
            if selected_item:table.selection_set(selected_item);table.focus(selected_item)
            elif table.get_children():
                first=table.get_children()[0];table.selection_set(first);table.focus(first)
            refresh_selection()

        def selected_model_id():
            selected=table.selection()
            return None if not selected else str(table.item(selected[0],"values")[1])

        def refresh_selection(_event=None):
            model_id=selected_model_id();item=records.get(model_id or "")
            if not item:
                details.set("Select a model to see its details.");set_button.configure(state="disabled");accuracy_button.configure(state="disabled");return
            best=item.get("_best_epoch");active="Active model" if item.get("active") else "Saved model"
            details.set(f"{active} · Parent: {item.get('parent_model_id') or 'Bootstrap / first model'} · Best epoch: {'—' if best is None else best}")
            set_button.configure(state="disabled" if item.get("active") else "normal")
            accuracy_button.configure(state="normal")

        def set_active():
            model_id=selected_model_id()
            if not model_id:return
            try:
                from app.landmark_training_workflow import activate_landmark_model
                activate_landmark_model(self.context.project,model_id)
                self.context.invalidate_counts();populate();self.render()
            except Exception as exc:messagebox.showerror("Set active Landmark model",str(exc),parent=dialog)

        def accuracy():
            model_id=selected_model_id()
            if not model_id:return
            from app.ui.model_accuracy import open_landmark_accuracy
            open_landmark_accuracy(self,self.context.project,model_id)

        actions=ttk.Frame(outer);actions.grid(row=4,column=0,sticky="ew",pady=(12,0))
        set_button=self.control_button(actions,"Set active",set_active,"Use the selected saved model for future Landmark predictions.",style="Primary.TButton")
        set_button.pack(side="left")
        accuracy_button=self.control_button(actions,"Accuracy details…",accuracy,"Compare Human Repeatability with AI landmark placement on the same images, including a GM-only view.")
        accuracy_button.configure(image=self.ui_icon("landmark_repeat",CONTROL_ICON_SIZE),compound="left")
        accuracy_button.pack(side="left",padx=(7,0))
        self.control_button(actions,"Close",dialog.destroy,"Close this model list.").pack(side="right")
        table.bind("<<TreeviewSelect>>",refresh_selection,add="+")
        populate();center(self,dialog);return dialog


    def _photo_exclusion_changed(self,image_id):
        """Synchronize one exclusion with every live workflow membership.

        Scientific annotations/history are preserved. Exclusion only removes
        the image from active work queues, counters and future eligibility.
        Restoring an image never silently re-inserts it into a finite queue.
        """
        project=self.context.project
        if not project:return
        image_id=str(image_id);current_id=(self.context.current() or {}).get("image_id")
        excluded=bool(project.image_exclusion(image_id).get("excluded"))
        suspicious_target=ai_target=crop_target=stage_target=attention_target=None
        crop_member_removed=False

        if excluded:
            from app.human_baseline import invalidate_runs_for_excluded_image
            invalidate_runs_for_excluded_image(project,image_id)
            from app.landmark_suspicious_review import remove_image as remove_suspicious_image
            from app.landmark_ai_review import remove_image_from_reviews
            from app.landmark_attention_queue import remove_image as remove_attention_image
            try:
                _state,suspicious_target=remove_suspicious_image(project,image_id)
                ai_target=remove_image_from_reviews(project,image_id)
                attention_issue=remove_attention_image(project,image_id)
                attention_target=attention_issue.get("image_id") if attention_issue else None
            except Exception as exc:
                messagebox.showwarning("Exclude image",f"The image was excluded, but a review queue could not be updated:\n{exc}",parent=self)

            from app.crop_batch_state import remove_crop_batch_member
            active=project.get_ui_state("crop_active_batch",{}) or {}
            crop_member_removed=image_id in set(active.get("ids",()))
            if crop_member_removed:
                _state,crop_target,_empty=remove_crop_batch_member(project,image_id,current_id)

            from app.landmark_ai_workflow import repair_excluded_stage_members
            try:
                stage_state=repair_excluded_stage_members(project)
                candidate=stage_state.get("current_image_id")
                if current_id==image_id and candidate and candidate!=image_id:
                    stage_target=str(candidate)
            except ValueError as exc:messagebox.showwarning("Landmark batch",str(exc),parent=self)

        view=getattr(self,"current_view",None)
        if self.context.section=="crop" and view is not None and getattr(view,"canvas",None) is not None:
            view._pending_crop_action=None

        self.context.refresh_landmark_state(image_id);self.context.invalidate_counts();self.context.refresh(force=True)
        panel=getattr(self,'photo_panel',None)

        target=None
        if excluded and image_id==current_id:
            if self.context.section=="landmarks":target=attention_target or suspicious_target or ai_target or stage_target
            elif self.context.section=="crop":target=attention_target or crop_target
            if target is None:
                target=next((row.get("image_id") for row in self.context.rows if not row.get("excluded") and row.get("image_id")!=image_id),None)
        elif self.context.section=="crop" and crop_target:
            target=crop_target

        if target:self.context.select_image(target)
        if excluded and image_id==current_id and attention_target:
            self.open_landmark_attention();return
        if panel and target is None and not panel.show_excluded.get() and (self.context.current() or {}).get('excluded'):
            next_row=next((row for row in self.context.rows if not row.get('excluded')),None)
            if next_row:self.context.select_image(next_row["image_id"])
        self.render()


    def show_model_transfer(self):
        if not self.context.project: return
        dialog=tk.Toplevel(self); dialog.title("Import / export AI models"); dialog.transient(self); dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=16); frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="Move trained AI between projects or computers.",style="SectionTitle.TLabel").pack(anchor="w",pady=(0,4))
        ttk.Label(frame,text="Model ZIP files contain AI and its settings. Research images stay in the project.",wraplength=520,style="Muted.TLabel").pack(anchor="w",pady=(0,8))
        for kind,label in (("crop","Crop model"),("landmark","Landmark model")):
            card=ttk.LabelFrame(frame,text=label,padding=12); card.pack(fill="x",pady=5)
            model=self.context.project.active_model(kind) or {}
            ttk.Label(card,text=f"Current model: {model.get('model_id','None')}").pack(anchor="w")
            ttk.Label(card,text="Finds specimen frames." if kind=="crop" else "Places anatomical landmarks. Use the same landmark definitions when transferring.",wraplength=490).pack(anchor="w",pady=(2,6))
            self.control_button(card,"Import model…",lambda k=kind:self._import_model(k),"Open a trained model ZIP file.").pack(side="left")
            export=self.control_button(card,"Export active…",lambda k=kind:self._export_model(k),"Save the active model as a ZIP file for another project or computer.")
            export.configure(state="normal" if model else "disabled");export.pack(side="left",padx=5)
        self.control_button(frame,"Close",dialog.destroy,"Close this transfer window.").pack(anchor="e",pady=(8,0)); center(self,dialog)


    def _export_model(self,kind):
        from app.model_transfer import model_package_filename, registered_active_model
        target=filedialog.asksaveasfilename(parent=self,title=f"Export {kind.title()} model",initialfile=model_package_filename(registered_active_model(self.context.project,kind),"landmarks_"+kind+"_model"),defaultextension=".zip",filetypes=[("MorphoLabel model package","*.zip")])
        if target:
            try: export_model_package(self.context.project,kind,target); messagebox.showinfo("AI Model Transfer",f"Saved: {target}",parent=self)
            except Exception as exc: messagebox.showerror("AI Model Transfer",str(exc),parent=self)


    def _import_model(self,kind):
        from app.model_transfer import model_package_filename, registered_active_model
        source=filedialog.askopenfilename(parent=self,title=f"Import {kind.title()} model",initialfile=model_package_filename(registered_active_model(self.context.project,kind),"landmarks_"+kind+"_model"),filetypes=[("MorphoLabel model package","*.zip")])
        if source:
            try:
                model=import_model_package(self.context.project,source,kind);self.context.project.set_active_model(kind,model);self.context.refresh(force=True)
                text=f"Imported and activated {kind} model: {model}"
                if kind=="crop":
                    from app.crop_training import rotation_supported
                    if not rotation_supported(self.context.project,model):text+="\n\nThis older model predicts crop bounds only. Rotation requires manual review or training a new model from confirmed crops with their angles."
                messagebox.showinfo("AI Model Transfer",text,parent=self);self.render()
            except Exception as exc: messagebox.showerror("AI Model Transfer",str(exc),parent=self)
