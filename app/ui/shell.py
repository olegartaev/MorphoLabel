"""Production MorphoLabel shell using the accepted module workflow and real services."""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys
import threading, queue
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from app.project_storage import Project
from app.identity import APP_NAME, APP_FULL_NAME, APP_VERSION, APP_STATUS, COPYRIGHT, CONTACT_EMAIL, PUBLIC_REPOSITORY, LICENSE_NAME, apply_window_identity, icon_image
from app.gui_crop_debug import log
from .context import UIContext
from .section_registry import visible_sections
from .tooltips import Tooltip
from .icons import tk_icon, TOPBAR_ICON_SIZE, CONTROL_ICON_SIZE
from .dialogs import center, info, install_auto_center
from .photo_list_panel import PhotoListPanel
from .landmark_sidebar import LandmarkSidebar
from .preferences import last_project, remember_project
from .project_section import ProjectSection
from .crop_section import CropSection
from .landmarks_section import LandmarksSection
from .measurements_section import MeasurementsSection
from .export_section import ExportSection
from .module_hub import ModuleHub
from app.extensions.api import ModuleHost
from app.extensions.builtins import module_registry
from app.extensions.internal_runtime import create_internal_runtime
from app.calibration_workflow import CalibrationWorkflow
from app.measurements_ui import MeasurementsWindow
from app.ai_hardware import get_hardware_profile, persist_machine_profile, format_hardware_profile
from app.ai_package import export_model_package, import_model_package
from app.first_run_setup import first_run_setup_required, run_first_run_setup

BG="#f5f7f8"; ACC="#256d9e"

class ProductionShell(tk.Tk):
    """One durable Tk application; project selection never opens another shell."""
    def __init__(self, project: Project | None = None):
        super().__init__()
        requested_project=project
        remembered_path=None if project is not None else last_project()
        self._remembered_project_path=remembered_path
        self.module_key="landmarks" if project is not None else None
        self.module_registry=module_registry()
        self._active_module_runtime=None
        # Paint the module hub first. Large projects are opened only after the
        # user enters the current module, keeping startup fast and predictable.
        self.context=UIContext(None)
        apply_window_identity(self)
        self.geometry("1600x900"); self.minsize(980,650); self.configure(bg=BG)
        self._ui_icons={}
        install_auto_center(self)
        self.style=ttk.Style(self)
        # A deliberately small design system: quiet surfaces, one accent and
        # consistent hierarchy.  Section code should use these styles instead
        # of inventing local colours/sizes.
        self.style.configure("P.TButton", padding=(10,7))
        self.style.configure("Icon.TButton", padding=(7,4), font=("Segoe UI",9))
        self.style.configure("Primary.TButton", padding=(10,6), font=("Segoe UI",9,"bold"))
        self.style.configure("ComplexQC.TButton", padding=(12,7), font=("Segoe UI",9,"bold"), foreground=ACC, background="#e7f2f8")
        self.style.map("ComplexQC.TButton", foreground=[("!disabled",ACC)], background=[("active","#d7eaf5"),("!disabled","#e7f2f8")])
        self.style.configure("CropNext.TButton", padding=(10,7), font=("Segoe UI",9,"bold"), foreground="black")
        self.style.map("CropNext.TButton", foreground=[("disabled","black"),("!disabled","black")])
        self.style.configure("Stage.TButton", padding=(10,5), font=("Segoe UI",9), foreground="#27313a")
        self.style.configure("StageActive.TButton", padding=(12,6), font=("Segoe UI",9,"bold"), foreground=ACC, background="#d9edf9", relief="sunken", borderwidth=2)
        self.style.map("StageActive.TButton", foreground=[("!disabled",ACC)], background=[("active","#c8e4f5"),("!disabled","#d9edf9")])
        self.style.configure("Topbar.TFrame", padding=(0,1))
        self.style.configure("Toolbar.TFrame", padding=(8,5))
        self.style.configure("WorkflowDock.TFrame")
        self.style.configure("WorkflowDockTitle.TLabel", font=("Segoe UI",9,"bold"), foreground="#58636d")
        self.style.configure("WorkflowCard.TLabelframe", padding=(1,1))
        self.style.configure("WorkflowCardTitle.TLabel", font=("Segoe UI",9,"bold"), foreground="#27313a")
        self.style.configure("WorkflowIcon.TLabel", font=("Segoe UI Emoji",11))
        self.style.configure("WorkflowCheck.TLabel", font=("Segoe UI Symbol",12,"bold"), foreground="#188038")
        self.style.configure("Nav.TButton", padding=(12,6), font=("Segoe UI",9,"bold"))
        self.style.configure("NavPrimary.TButton", padding=(12,6), font=("Segoe UI",9,"bold"))
        self.style.configure("SectionTitle.TLabel", font=("Segoe UI",9,"bold"), foreground="#27313a")
        self.style.configure("PageTitle.TLabel", font=("Segoe UI",16,"bold"), foreground="#20272d")
        self.style.configure("PageSubtitle.TLabel", font=("Segoe UI",10), foreground="#66727d")
        self.style.configure("HubTitle.TLabel", font=("Segoe UI",24,"bold"), foreground="#20272d")
        self.style.configure("ModuleTitle.TLabel", font=("Segoe UI",12,"bold"), foreground="#27313a")
        self.style.configure("Muted.TLabel", foreground="#66727d")
        self.style.configure("StatusChip.TLabel", padding=(5,2), foreground="#39434c")
        self.root=ttk.Frame(self,padding=(8,6)); self.root.pack(fill="both",expand=True)
        self.tip=Tooltip(self); self.photo_panel=None; self._selection_token=0; self.bind("<Return>", self._enter_next)
        requested_label=(str(requested_project.root) if requested_project is not None else str(remembered_path or "none"))
        log("GLOBAL", "production_shell_start", "START", detail=f"project={requested_label}")
        self.render()
        # Public installed builds perform one explicit, visible setup before
        # ordinary work. Source/developer runs remain side-effect free.
        if first_run_setup_required():
            self.after(300,self._show_first_run_setup)
        else:
            # Keep routine hardware discovery off Tk on subsequent launches.
            threading.Thread(target=self._warm_ai_hardware,daemon=True,name="morpholabel-hardware-profile").start()
        if requested_project is not None:
            self.after_idle(lambda p=requested_project:self._load_existing_project_async(p,"Opening project"))

    def report_callback_exception(self, exc_type, exc_value, tb):
        """Persist an unexpected Tk callback failure instead of losing it in a frozen GUI."""
        bundle=None
        try:
            from app.diagnostics import create_diagnostic_bundle, record_exception
            record_exception(exc_type, exc_value, tb, shell=self)
            bundle=create_diagnostic_bundle(shell=self)
        except Exception:
            pass
        try:
            error_text=f"{getattr(exc_type,'__name__','Error')}: {exc_value}"
            if bundle is not None:
                self._show_diagnostic_report_dialog(bundle,title="MorphoLabel error",intro=error_text)
            else:
                messagebox.showerror("MorphoLabel error",error_text,parent=self)
        except tk.TclError:
            pass

    def destroy(self):
        """Release Tk-owned views/images on the Tk thread before Tcl teardown."""
        if getattr(self, "_morpholabel_destroying", False):
            return
        self._morpholabel_destroying = True
        try:
            runtime = getattr(self, "_active_module_runtime", None)
            module_id = getattr(self, "module_key", None) or "unknown"
            if runtime is not None:
                self._dispose_module_runtime(module_id, runtime)
                self._active_module_runtime = None
            try:
                if hasattr(self, "root"):
                    self._clear()
            except tk.TclError:
                pass
            self.current_view = None
            self.photo_panel = None
            # Drop Python references while Tcl is still alive. PIL/tk image
            # destructors are not safe if cyclic GC later runs on a worker
            # thread after the interpreter has already been destroyed.
            for name in ("_morpholabel_hub_icon", "_morpholabel_about_icon", "_morpholabel_window_icon"):
                if hasattr(self, name):
                    setattr(self, name, None)
            import gc
            gc.collect()
        finally:
            super().destroy()

    def open_primary_module(self):
        """Compatibility action for opening the original built-in module."""
        return self.open_module("landmarks")

    def _module_host(self):
        return ModuleHost(self.root,self.context.project,self.show_module_hub,self.open_project,self.new_project)

    def _create_module_runtime(self,spec):
        internal=create_internal_runtime(spec,self)
        if internal is not None:return internal
        return spec.factory()

    def _dispose_module_runtime(self,module_id,runtime):
        if runtime is None:return
        try:runtime.close()
        except Exception as exc:
            self.module_registry.diagnostics.append(f"module {module_id}: close failed: {type(exc).__name__}: {exc}")

    def _module_failed(self,module_id,phase,error,runtime=None):
        self.module_registry.diagnostics.append(f"module {module_id}: {phase} failed: {type(error).__name__}: {error}")
        try:
            from app.diagnostics import record_exception
            record_exception(type(error),error,error.__traceback__,shell=self)
        except Exception:
            pass
        if self._active_module_runtime is runtime:self._active_module_runtime=None
        self.module_key=None
        self._dispose_module_runtime(module_id,runtime)
        self.render()
        try:messagebox.showerror("Module could not be opened",f"{module_id} failed during {phase}.\n\n{error}",parent=self)
        except tk.TclError:pass

    def _open_landmarks_workspace(self):
        if self.context.project:
            self.render();return
        remembered=self._remembered_project_path
        if remembered:
            self._open_project_path_async(Path(remembered),"Opening last project")
        else:
            self.context.section="project";self.render()

    def open_module(self,module_id):
        """Open any registered module through its runtime contract."""
        spec=self.module_registry.get(module_id)
        if spec is None or spec.status!="available" or spec.factory is None:
            raise ValueError(f"module is unavailable: {module_id}")
        previous=self.module_key or "unknown"
        self._dispose_module_runtime(previous,self._active_module_runtime)
        self._active_module_runtime=None
        try:runtime=self._create_module_runtime(spec)
        except Exception as exc:
            self._module_failed(module_id,"factory",exc)
            return
        self._active_module_runtime=runtime
        self.module_key=module_id
        on_open=getattr(runtime,"on_open",None)
        try:
            if callable(on_open):on_open()
            else:self.render()
        except Exception as exc:
            if self._active_module_runtime is runtime:self._module_failed(module_id,"open",exc,runtime)

    def show_module_hub(self):
        module_id=self.module_key or "unknown"
        self._dispose_module_runtime(module_id,self._active_module_runtime)
        self._active_module_runtime=None
        self.module_key=None
        self.render()

    def _show_first_run_setup(self):
        """Visible one-time setup for public installs; all blocking work stays off Tk."""
        if getattr(self,"_first_run_setup_active",False):return
        self._first_run_setup_active=True
        dialog=tk.Toplevel(self);dialog.title("Preparing MorphoLabel");dialog.transient(self);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=18);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1)
        ttk.Label(frame,text="Preparing MorphoLabel for this computer",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(
            frame,
            text=(
                "This happens once after installation. MorphoLabel will prepare its AI tools, "
                "download the verified runtime and base model if they are not already present "
                "(several GB), then test this computer.\n\n"
                "The checks include GPU/CUDA detection, a real landmark prediction and a short "
                "training test. Later, real AI jobs fine-tune batch size and worker counts on "
                "your actual images."
            ),
            style="Muted.TLabel",justify="left",wraplength=610,
        ).grid(row=1,column=0,sticky="w",pady=(7,14))
        stage=ttk.Label(frame,text="Starting setup…",style="SectionTitle.TLabel");stage.grid(row=2,column=0,sticky="w")
        detail=ttk.Label(frame,text="No project or scientific data will be changed.",style="Muted.TLabel",justify="left",wraplength=610)
        detail.grid(row=3,column=0,sticky="w",pady=(4,8))
        bar=ttk.Progressbar(frame,mode="indeterminate",length=560);bar.grid(row=4,column=0,sticky="ew");bar.start(10)
        result_label=ttk.Label(frame,text="",justify="left",wraplength=610);result_label.grid(row=5,column=0,sticky="w",pady=(10,0))
        actions=ttk.Frame(frame);actions.grid(row=6,column=0,sticky="e",pady=(14,0))
        events=queue.Queue();working={"value":False}
        dialog.protocol("WM_DELETE_WINDOW",lambda:None);dialog.grab_set();center(self,dialog)

        def progress(stage_name,stage_detail):
            events.put(("progress",str(stage_name),str(stage_detail)))

        def worker():
            try:events.put(("done",run_first_run_setup(progress=progress)))
            except Exception as exc:events.put(("error",exc))

        def start():
            if working["value"]:return
            working["value"]=True
            for child in actions.winfo_children():child.destroy()
            result_label.configure(text="")
            stage.configure(text="Preparing AI support…")
            detail.configure(text="Downloaded data is verified before it is activated.")
            bar.configure(mode="indeterminate");bar.start(10)
            threading.Thread(target=worker,daemon=True,name="morpholabel-first-run-setup").start()

        def close_ready():
            self._first_run_setup_active=False
            try:dialog.grab_release()
            except tk.TclError:pass
            dialog.destroy()

        def continue_core():
            self._first_run_setup_active=False
            try:dialog.grab_release()
            except tk.TclError:pass
            dialog.destroy()

        def poll():
            try:
                while True:
                    kind,*value=events.get_nowait()
                    if kind=="progress":
                        stage.configure(text=value[0]);detail.configure(text=value[1])
                    elif kind=="error":
                        working["value"]=False;bar.stop()
                        stage.configure(text="Setup is incomplete")
                        detail.configure(text=(
                            "MorphoLabel can still be used without AI. Any partial AI download is kept, "
                            "so Retry or the next launch can continue instead of starting over."
                        ))
                        result_label.configure(text=f"{type(value[0]).__name__}: {value[0]}")
                        self.control_button(actions,"Continue without AI",continue_core,"Open MorphoLabel core tools without completing AI setup.").pack(side="right")
                        self.control_button(actions,"Retry",start,"Retry first-time setup and resume any partial download.",primary=True).pack(side="right",padx=(0,6))
                        log("GLOBAL","first_run_setup","ERROR",detail=str(value[0]))
                    else:
                        working["value"]=False;bar.stop();payload=value[0];hardware=payload.get("hardware") or {};test=payload.get("ai_self_test") or {}
                        gpu=hardware.get("gpu_model") or "No dedicated GPU detected"
                        accel="CUDA" if hardware.get("cuda_available") else "CPU fallback"
                        training=(test.get("training_smoke") or {}).get("status") or "not run"
                        stage.configure(text="MorphoLabel is ready")
                        detail.configure(text="AI support is installed and verified. No further setup is required on ordinary launches.")
                        result_label.configure(text=(
                            f"GPU: {gpu}\nAcceleration: {accel}\n"
                            f"Inference test: PASS\nTraining test: {str(training).upper()}\n\n"
                            "Performance mode: Auto. MorphoLabel will measure the best workload settings "
                            "when AI is first used on real project images."
                        ))
                        self.control_button(actions,"Start MorphoLabel",close_ready,"Finish setup and use MorphoLabel.",primary=True).pack(side="right")
                        log("GLOBAL","first_run_setup","END",detail=f"gpu={gpu}; acceleration={accel}; training={training}")
            except queue.Empty:
                if dialog.winfo_exists():self.after(100,poll)

        start();poll()

    def _warm_ai_hardware(self):
        try:
            profile=get_hardware_profile()
            persist_machine_profile(profile)
            log("GLOBAL","hardware_profile","END",detail=f"cpu={profile.cpu_model}; logical={profile.logical_cores}; gpu={profile.gpu_model}; vram_mib={profile.gpu_vram_mib}; cuda={profile.cuda_available}")
        except Exception as exc:
            log("GLOBAL","hardware_profile","ERROR",detail=str(exc))

    def ui_icon(self,name,size):
        key=(str(name),int(size))
        if key not in self._ui_icons:self._ui_icons[key]=tk_icon(self,name,size)
        return self._ui_icons[key]

    def control_button(self,parent,text,command,help_text,primary=False,enabled=True,icon=None,icon_size=CONTROL_ICON_SIZE,**kwargs):
        style=kwargs.pop("style","P.TButton" if primary else ("Icon.TButton" if icon else "TButton"))
        state=kwargs.pop("state","normal" if enabled else "disabled")
        if icon:
            kwargs.setdefault("image",self.ui_icon(icon,icon_size))
            kwargs.setdefault("compound","left")
        button=ttk.Button(parent,text=text,command=command,state=state,style=style,**kwargs)
        self.tip.bind(button,help_text); return button

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

    def _run_background_task(self,title,initial_text,worker,on_done):
        """Run one blocking project operation off Tk with unmistakable live feedback."""
        dialog=tk.Toplevel(self);dialog.title(title);dialog.transient(self)
        frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
        label=ttk.Label(frame,text=initial_text,justify="left");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="indeterminate",length=360);bar.pack(fill="x",pady=(8,0));bar.start()
        events=queue.Queue();center(self,dialog)
        def progress(text,done=None,total=None):events.put(("progress",str(text),done,total))
        def run():
            try:events.put(("done",worker(progress)))
            except Exception as exc:
                try:
                    from app.diagnostics import record_exception
                    record_exception(type(exc),exc,exc.__traceback__)
                except Exception:
                    pass
                events.put(("error",exc))
        threading.Thread(target=run,daemon=True,name="production-background-task").start()
        def poll():
            try:
                while True:
                    kind,*value=events.get_nowait()
                    if kind=="progress":
                        text,done,total=value;label.configure(text=text)
                        if done is not None and total:
                            bar.stop();bar.configure(mode="determinate",maximum=total,value=done)
                    elif kind=="error":
                        dialog.destroy();messagebox.showerror(title,str(value[0]),parent=self);return
                    else:
                        dialog.destroy();on_done(value[0]);return
            except queue.Empty:self.after(100,poll)
        poll();return dialog

    def _enter_next(self,event):
        if event.widget.winfo_class() in {"Entry","TEntry","TCombobox","Text","Spinbox","TSpinbox"}: return
        if self.context.project and self.context.section not in {"project","export"}:
            handler=getattr(getattr(self,"current_view",None),"on_enter",None)
            if handler: handler()
            else: self._nav_image(1)
        return "break"

    def _clear(self):
        self.tip.hide(); self.photo_panel=None
        for child in self.root.winfo_children(): child.destroy()
        # Each top-level view owns its grid rows. Reset weights so returning
        # from a workspace does not leave an empty weighted row under the hub.
        self.root.rowconfigure(0,weight=0);self.root.rowconfigure(1,weight=0)

    def render(self):
        self._clear()
        if self.module_key is None:
            self.root.rowconfigure(0,weight=1);self.root.columnconfigure(0,weight=1)
            self.section_host=ttk.Frame(self.root);self.section_host.grid(row=0,column=0,sticky="nsew")
            ModuleHub(self,self.section_host,self.module_registry).render()
            self.current_view=None
            return
        if self._active_module_runtime is None:
            spec=self.module_registry.get(self.module_key)
            if spec is None or spec.status!="available" or spec.factory is None:
                raise ValueError(f"module is unavailable: {self.module_key}")
            try:self._active_module_runtime=self._create_module_runtime(spec)
            except Exception as exc:
                self._module_failed(self.module_key,"factory",exc)
                return
        runtime=self._active_module_runtime;module_id=self.module_key
        try:runtime.render(self._module_host())
        except Exception as exc:
            if self._active_module_runtime is runtime:self._module_failed(module_id,"render",exc,runtime)

    def _render_landmarks_workspace(self):
        """Private bridge used only by the built-in Landmarks adapter."""
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

    def _nav(self):
        row=ttk.Frame(self.root,style="Topbar.TFrame"); row.grid(row=0,column=0,sticky="ew",pady=(0,4))
        home=ttk.Button(row,text="Modules",image=self.ui_icon("modules",TOPBAR_ICON_SIZE),compound="left",command=self.show_module_hub,style="Stage.TButton")
        home.pack(side="left",padx=(0,8));self.tip.bind(home,"Return to the MorphoLabel module hub.")
        sections=visible_sections(self.context.crop_enabled()) if self.context.project else visible_sections(True)
        for spec in sections:
            active=spec.key == self.context.section
            button=ttk.Button(row,text=spec.label,image=self.ui_icon(spec.key,TOPBAR_ICON_SIZE),compound="left",command=lambda key=spec.key:self.select(key),style="StageActive.TButton" if active else "Stage.TButton",state="normal" if self.context.project or spec.key=="project" else "disabled")
            button.pack(side="left",padx=(0,3)); self.tip.bind(button,f"Open the {spec.label} section.")
        self._menus(row)

    def _menus(self,row):
        about=ttk.Menubutton(row,text="About"); about_menu=tk.Menu(about,tearoff=False)
        about_menu.add_command(label="About MorphoLabel...",command=self.show_about)
        about_menu.add_command(label="Create diagnostic report...",command=self.create_diagnostic_report)
        about_menu.add_command(label="GitHub project",command=lambda:webbrowser.open(PUBLIC_REPOSITORY))
        about.configure(menu=about_menu); about.pack(side="right",padx=2); self.tip.bind(about,"About MorphoLabel, license and project links.")
        ai=ttk.Menubutton(row,text="AI"); ai_menu=tk.Menu(ai,tearoff=False)
        ai_menu.add_command(label="Hardware",command=self.show_hardware)
        ai_menu.add_command(label="AI Model Transfer...",command=self.show_model_transfer,state="normal" if self.context.project else "disabled")
        ai.configure(menu=ai_menu); ai.pack(side="right",padx=2); self.tip.bind(ai,"Open hardware and model transfer tools.")

    def _status(self):
        """Reserve the right-side navigation before flexible descriptive status text."""
        bar=ttk.Frame(self.main,padding=(2,1)); bar.grid(row=0,column=0,sticky="ew");bar.columnconfigure(0,weight=1);self.status_bar=bar
        left=ttk.Frame(bar);left.grid(row=0,column=0,sticky="ew");left.columnconfigure(0,weight=1);self.status_left=left
        navigation=ttk.Frame(bar);navigation.grid(row=0,column=1,sticky="e");self.status_navigation=navigation
        self._status_context_full=""
        self.status_context=ttk.Label(left,text="",style="SectionTitle.TLabel",anchor="w",width=1);self.status_context.pack(side="left",fill="x",expand=True,padx=(0,7));self.status_context.bind("<Configure>",lambda _event:self._refresh_status_context(),add="+")
        self.status_count_host=ttk.Frame(left);self.status_count_host.pack(side="right")
        self.status_counts={}
        for key,value in self._section_counts().items():
            label=ttk.Label(self.status_count_host,text=f"{key}: {value}",style="StatusChip.TLabel"); label.pack(side="left",padx=(0,2)); self.status_counts[key]=label
        self.status_previous=self.control_button(navigation,"‹ Previous",lambda:self._nav_image(-1),"Show the previous image.",style="Nav.TButton");self.status_previous.pack(side="left")
        self.status_index=ttk.Label(navigation,text="",padding=(8,0),font=("Segoe UI",9,"bold"));self.status_index.pack(side="left")
        self.status_next=self.control_button(navigation,"Next ›",lambda:self._nav_image(1),"Show the next image. Press Enter when not typing.",style="Nav.TButton");self.status_next.pack(side="left")
        self._update_status()

    def _refresh_status_context(self):
        """Ellipsize only non-critical left text; navigation never loses its reserved column."""
        label=getattr(self,"status_context",None)
        if label is None or not label.winfo_exists(): return
        text=getattr(self,"_status_context_full","")
        # Segoe UI 9 averages approximately seven logical pixels per compact character.
        limit=max(8,int(label.winfo_width()//7))
        shown=text if len(text)<=limit else text[:max(1,limit-1)].rstrip()+"…"
        if label.cget("text")!=shown: label.configure(text=shown)
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
            minimum=max(280,min(330,int(self.photo_panel.winfo_reqwidth())+12))
            maximum=max(minimum,min(440,width-600))
            responsive_default=min(400,max(310,int(width*0.20)))
            saved=self.context.project.get_ui_state("workspace_sidebar_sash",None)
            target=responsive_default if saved is None else int(saved)
            panes.sashpos(0,max(minimum,min(maximum,target)))
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
        self._status_context_full=f"{self.context.section.title()} | {name} | {sample}"
        self._refresh_status_context()
        if hasattr(self,"status_index"):
            batch=self._active_batch_summary()
            crop_normal=self.context.section=='crop' and batch is None
            if crop_normal:self.status_navigation.grid_remove()
            else:self.status_navigation.grid()
            self.status_index.configure(text=batch.get('text') if batch else f"{self.context.selected+1 if self.context.rows else 0}")
            suspicious=bool(batch and batch.get('kind')=='landmark_suspicious')
            confirm=bool(batch and (batch.get('kind')=='landmark_ai_review' or self.context.section=='crop' or suspicious))
            next_text='Checked & Next ›' if suspicious else 'Confirm & Next ›' if confirm else 'Next ›'
            self.status_next.configure(text=next_text,style='NavPrimary.TButton' if confirm else 'Nav.TButton')
            if suspicious:self.tip.bind(self.status_next,'Mark this suspicious placement as reviewed and continue to the next flagged issue.')
            elif confirm:self.tip.bind(self.status_next,'Save this crop and continue to the next batch image.' if self.context.section=='crop' else 'Confirm this landmark set and continue to the next batch image.')
        for key,label in getattr(self,"status_counts",{}).items():
            label.configure(text=f"{key}: {self._section_counts().get(key,0)}")

    def _active_batch_summary(self):
        """Finite batch position from persisted IDs only; never the catalogue index."""
        if not self.context.project:return None
        from .batch_status import position_and_remaining,compact
        current=(self.context.current() or {}).get('image_id')
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
                    return {'kind':'landmark_suspicious','text':compact(summary)}
            from app.landmark_ai_review import active_review_session,review_summary
            review=active_review_session(self.context.project)
            if review and current in review.get('image_ids',()):
                summary=review_summary(self.context.project,review,current)
                return {'kind':'landmark_ai_review','text':compact(summary)}
            from app.landmark_ai_workflow import load_state
            state=load_state(self.context.project);stage=state.get('stage');ids=list(state.get('initial_image_ids' if stage=='INITIAL_TRAINING' else 'improvement_image_ids' if stage=='MODEL_IMPROVEMENT' else '',()))
            if current in ids:
                # Context rows are authoritative on first render and delta-updated per edited image.
                # Never re-run annotation_status over an active batch during a point gesture.
                rows={row.get('image_id'):row for row in self.context.rows}
                done=[ident for ident in ids if rows.get(ident,{}).get('human_verified')]
                return {'kind':'landmark','text':compact(position_and_remaining(ids,current,done))}
        return None
    def _section_counts(self):
        if not self.context.project: return {"Total":0}
        if self.context.section == "crop": return getattr(self.context.project,"crop_section_counts",self.context.project.crop_counts)()
        if self.context.section == "landmarks": return self.context.landmark_counts()
        if self.context.section == "measurements": return {"Total":len(self.context.rows)}
        return self.context.counts()

    def _nav_image(self,step):
        row=self.context.current() or {}; section=self.context.section
        log(row.get("image_id",""),"NAV_CLICK","START",detail=f"section={section}; step={int(step)}; selected={row.get('image_id')}")
        view=getattr(self,"current_view",None)
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
        if key == "crop" and not self.context.crop_enabled(): key="landmarks"
        image_id=(self.context.current() or {}).get("image_id")
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
        if self.module_key is None:self.module_key="landmarks"
        self._remembered_project_path=project.root
        self.context=UIContext(project=project,section="project")
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
            project=Project.create(name,Path(source),Path(destination),source_layout=layout,source_image_subfolder=subfolder)
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
        dialog=SchemaEditor(self,project.schema_path); center(self,dialog)
        dialog.bind("<Destroy>",lambda event,d=dialog: self._schema_closed(event,d), add="+")

    def _schema_closed(self,event,dialog):
        if event.widget is not dialog or not self.winfo_exists() or not self.context.project:return
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

    def show_models(self,kind=None):
        if not self.context.project:return
        kinds=(kind,) if kind else ("crop","landmark")
        landmark_only=kinds==("landmark",)
        dialog=tk.Toplevel(self);dialog.title("Models");dialog.transient(self);dialog.geometry("1220x440" if landmark_only else "980x420");dialog.minsize(760 if landmark_only else 660,260)
        frame=ttk.Frame(dialog,padding=12);frame.pack(fill="both",expand=True);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        columns=("active","model","dataset","split","iou","boundary","rotation") if kinds==("crop",) else ("active","model","parent","dataset","p90","best_epoch","manual_p90","ai_p90","human_ratio","manual_status","created")
        table_frame=ttk.Frame(frame);table_frame.grid(row=0,column=0,sticky="nsew");table_frame.rowconfigure(0,weight=1);table_frame.columnconfigure(0,weight=1)
        table=ttk.Treeview(table_frame,columns=columns,show="headings")
        labels={"active":"Active","model":"Model","dataset":"Dataset N","split":"Train / Val","iou":"Validation IoU","boundary":"Boundary MAE %","rotation":"Rotation MAE °","parent":"Parent","p90":"Validation P90 %","best_epoch":"Best epoch","manual_p90":"Manual P90 %","ai_p90":"AI P90 %","human_ratio":"AI / manual","manual_status":"Interpretation","created":"Created"}
        widths={"active":65,"model":160,"dataset":80,"split":90,"iou":105,"boundary":115,"rotation":115,"parent":125,"p90":105,"best_epoch":80,"manual_p90":95,"ai_p90":85,"human_ratio":90,"manual_status":155,"created":125}
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
            ttk.Label(frame,text="Manual P90: your repeat-placement error. AI P90: model error on the same images. AI/manual 1.00× ≈ your repeatability. Validation P90 uses each model's own split. Lower is better.",style="Muted.TLabel",wraplength=1120).grid(row=1,column=0,sticky="w",pady=(7,0))
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
                    messagebox.showinfo("Compare with manual",human_state.get("message") or "Complete Human repeatability first to compare AI with manual placement.",parent=dialog);populate();return
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
                        messagebox.showinfo("Repair Human repeatability",f"Image {result['position']}/{result['total']} reset.\nID: {result['image_id']}\n\nOpen Landmarks → Repeat... and complete Annotation 1 and Annotation 2 for this one image.",parent=self)
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
            compare_button=self.control_button(actions,"Compare with manual",compare_manual,"Compare the selected model with your Human repeatability on the exact same images.")
            compare_button.pack(side="left",padx=(6,0))
        self.control_button(actions,"Close",dialog.destroy,"Close this model list.").pack(side="right")
        if kinds==("crop",): use.pack(side="right",padx=(0,8))
        center(self,dialog)
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
        suspicious_target=ai_target=crop_target=stage_target=None
        crop_member_removed=False

        if excluded:
            from app.human_baseline import invalidate_runs_for_excluded_image
            invalidate_runs_for_excluded_image(project,image_id)
            from app.landmark_suspicious_review import remove_image as remove_suspicious_image
            from app.landmark_ai_review import remove_image_from_reviews
            try:
                _state,suspicious_target=remove_suspicious_image(project,image_id)
                ai_target=remove_image_from_reviews(project,image_id)
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
            if self.context.section=="landmarks":target=suspicious_target or ai_target or stage_target
            elif self.context.section=="crop":target=crop_target
            if target is None:
                target=next((row.get("image_id") for row in self.context.rows if not row.get("excluded") and row.get("image_id")!=image_id),None)
        elif self.context.section=="crop" and crop_target:
            target=crop_target

        if target:self.context.select_image(target)
        if panel and target is None and not panel.show_excluded.get() and (self.context.current() or {}).get('excluded'):
            next_row=next((row for row in self.context.rows if not row.get('excluded')),None)
            if next_row:self.context.select_image(next_row["image_id"])
        self.render()
    def _open_report_folder(self,bundle):
        bundle=Path(bundle)
        try:
            if not bundle.is_file():
                raise FileNotFoundError(bundle)
            folder=bundle.parent
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer",str(folder)])
            elif sys.platform=="darwin":
                subprocess.Popen(["open",str(folder)])
            else:
                subprocess.Popen(["xdg-open",str(folder)])
            return True
        except Exception as exc:
            messagebox.showerror("Open report folder",f"Could not open the report folder:\n{exc}",parent=self)
            return False

    def _show_diagnostic_report_dialog(self,bundle,*,title="Diagnostic report",intro=None):
        bundle=Path(bundle)
        if not bundle.is_file():
            raise FileNotFoundError(f"Diagnostic ZIP was not created: {bundle}")
        dialog=tk.Toplevel(self);dialog.title(title);dialog.transient(self);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=16);frame.pack(fill="both",expand=True)
        if intro:
            ttk.Label(frame,text=intro,justify="left",wraplength=650).pack(anchor="w",pady=(0,10))
        ttk.Label(
            frame,
            text="Diagnostic ZIP created. It contains no photographs or SQLite database.",
            justify="left",
            wraplength=650,
        ).pack(anchor="w")
        ttk.Label(frame,text="Report path:",style="Muted.TLabel").pack(anchor="w",pady=(10,2))
        path_entry=ttk.Entry(frame,width=88)
        path_entry.insert(0,str(bundle))
        path_entry.configure(state="readonly")
        path_entry.pack(fill="x")
        actions=ttk.Frame(frame);actions.pack(fill="x",pady=(14,0))
        def copy_path():
            self.clipboard_clear();self.clipboard_append(str(bundle));self.update_idletasks()
        self.control_button(
            actions,
            "Open report folder",
            lambda:self._open_report_folder(bundle),
            "Open the folder containing this diagnostic ZIP so it can be attached to a support message.",
            style="Primary.TButton",
        ).pack(side="left")
        self.control_button(actions,"Copy path",copy_path,"Copy the diagnostic ZIP path to the clipboard.").pack(side="left",padx=(6,0))
        self.control_button(actions,"Close",dialog.destroy,"Close this window.").pack(side="right")
        center(self,dialog)
        return dialog

    def create_diagnostic_report(self):
        try:
            from app.diagnostics import create_diagnostic_bundle
            bundle=create_diagnostic_bundle(shell=self)
            if not Path(bundle).is_file():
                raise FileNotFoundError(f"Diagnostic ZIP was not created: {bundle}")
            self._show_diagnostic_report_dialog(bundle)
            return bundle
        except Exception as exc:
            messagebox.showerror("Diagnostic report",f"Could not create diagnostic report:\n{exc}",parent=self)
            return None

    def show_about(self):
        dialog=tk.Toplevel(self);dialog.transient(self);dialog.resizable(False,False);apply_window_identity(dialog,short=True)
        frame=ttk.Frame(dialog,padding=18);frame.pack(fill="both",expand=True)
        logo=icon_image(dialog);dialog._morpholabel_about_icon=logo
        ttk.Label(frame,image=logo).grid(row=0,column=0,rowspan=4,sticky="n",padx=(0,16))
        ttk.Label(frame,text=APP_NAME,style="PageTitle.TLabel").grid(row=0,column=1,sticky="w")
        ttk.Label(frame,text=f"{APP_FULL_NAME}\nv{APP_VERSION} · {APP_STATUS}",style="PageSubtitle.TLabel",justify="left").grid(row=1,column=1,sticky="w",pady=(2,10))
        ttk.Label(frame,text=f"{COPYRIGHT}\n{CONTACT_EMAIL}",justify="left").grid(row=2,column=1,sticky="w")
        ttk.Label(frame,text=f"License: {LICENSE_NAME}\nRedistributed derivative works must retain the Apache-2.0 license and applicable NOTICE attribution.\nFor scientific software or models substantially based on MorphoLabel, please identify MorphoLabel as the source and cite it.",style="Muted.TLabel",justify="left",wraplength=560).grid(row=3,column=1,sticky="w",pady=(9,9))
        link=ttk.Label(frame,text=PUBLIC_REPOSITORY,foreground=ACC,cursor="hand2");link.grid(row=4,column=0,columnspan=2,sticky="w")
        link.bind("<Button-1>",lambda _e:webbrowser.open(PUBLIC_REPOSITORY))
        actions=ttk.Frame(frame);actions.grid(row=5,column=0,columnspan=2,sticky="e",pady=(14,0))
        self.control_button(actions,"Close",dialog.destroy,"Close About MorphoLabel.").pack(side="left")
        center(self,dialog)

    def show_hardware(self):
        try:
            h=get_hardware_profile()
            text=format_hardware_profile(h)
            if self.context.project:
                try:
                    from app.performance_engine import performance_diagnostic
                    text+="\n\n"+performance_diagnostic(self.context.project,h)["summary"]
                except Exception:
                    pass
            info(self,"Hardware",text)
        except Exception as exc: messagebox.showerror("Hardware",str(exc),parent=self)

    def show_model_transfer(self):
        if not self.context.project: return
        dialog=tk.Toplevel(self); dialog.title("AI Model Transfer"); dialog.transient(self); dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=16); frame.pack(fill="both",expand=True)
        for kind,label in (("crop","Crop model"),("landmark","Landmark model")):
            card=ttk.LabelFrame(frame,text=label,padding=12); card.pack(fill="x",pady=5)
            model=self.context.project.active_model(kind) or {}
            ttk.Label(card,text=f"Current model: {model.get('model_id','None')}").pack(anchor="w")
            ttk.Label(card,text=f"Save or load a {kind} model.").pack(anchor="w",pady=(2,6))
            self.control_button(card,"Export...",lambda k=kind:self._export_model(k),f"Save the active {kind} model as a package.").pack(side="left")
            self.control_button(card,"Import...",lambda k=kind:self._import_model(k),f"Load a {kind} model package.").pack(side="left",padx=5)
        self.control_button(frame,"Close",dialog.destroy,"Close this transfer window.").pack(anchor="e",pady=(8,0)); center(self,dialog)

    def _export_model(self,kind):
        target=filedialog.asksaveasfilename(parent=self,title=f"Export {kind.title()} model",defaultextension=".zip",filetypes=[("MorphoLabel model package","*.zip")])
        if target:
            try: export_model_package(self.context.project,kind,target); messagebox.showinfo("AI Model Transfer",f"Saved: {target}",parent=self)
            except Exception as exc: messagebox.showerror("AI Model Transfer",str(exc),parent=self)

    def _import_model(self,kind):
        source=filedialog.askopenfilename(parent=self,title=f"Import {kind.title()} model",filetypes=[("MorphoLabel model package","*.zip")])
        if source:
            try: model=import_model_package(self.context.project,source,kind); messagebox.showinfo("AI Model Transfer",f"Imported {kind} model: {model}",parent=self); self.render()
            except Exception as exc: messagebox.showerror("AI Model Transfer",str(exc),parent=self)

def run(project=None):
    ProductionShell(project).mainloop()

if __name__ == "__main__": run()
