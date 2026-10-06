"""Production MorphoLabel shell using the accepted module workflow and real services."""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys
import re
import threading, queue
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from app.identity import APP_NAME, APP_FULL_NAME, APP_VERSION, APP_STATUS, COPYRIGHT, CONTACT_EMAIL, PUBLIC_REPOSITORY, LICENSE_NAME, apply_window_identity, icon_image
from app.gui_crop_debug import log
from .tooltips import Tooltip
from .icons import tk_icon, TOPBAR_ICON_SIZE, CONTROL_ICON_SIZE
from .dialogs import center, info, install_auto_center

from .module_hub import ModuleHub
from .queue_center import show_queue_center
from app.extensions.api import ModuleHost
from app.extensions.builtins import module_registry
from app.ai_hardware import get_hardware_profile, format_hardware_profile
from app.setup_progress import COMPONENTS, SetupProgress
from app.first_run_setup import first_run_setup_required, run_first_run_setup, defer_first_run_setup, ai_setup_complete

BG="#f0f0f0"; ACC="#0067c0"

def _first_run_progress_state(stage,detail,current=0):
    """Compatibility mapper for component-weighted setup progress."""
    offset=0
    for item in COMPONENTS:
        if item.stage==stage:
            model=SetupProgress();model.update(stage,detail)
            value=offset+item.weight*model.fractions[stage]
            return max(float(current),value),item.name
        offset+=item.weight
    return (100,"MorphoLabel is ready") if stage=="READY" else (float(current),str(stage))

class ProductionShell(tk.Tk):
    """One durable Tk application; project selection never opens another shell."""
    def __init__(self, *, initial_module=None, module_states=None):
        super().__init__()
        self.module_key=None
        self.module_states=dict(module_states or {})
        self.module_registry=module_registry()
        self._active_module_runtime=None
        # Paint the module hub first. Large projects are opened only after the
        # user enters the current module, keeping startup fast and predictable.
        apply_window_identity(self)
        self.geometry("1600x900"); self.minsize(980,650); self.configure(bg=BG)
        self._ui_icons={}
        install_auto_center(self)
        self.style=ttk.Style(self)
        from .design import apply_styles
        apply_styles(self,self.style)
        self.root=ttk.Frame(self,padding=(8,6)); self.root.pack(fill="both",expand=True)
        self.tip=Tooltip(self)
        log("GLOBAL", "production_shell_start", "START", detail=f"module={initial_module or 'hub'}")
        self.render()
        # Public installed builds perform one explicit, visible setup before
        # ordinary work. Source/developer runs remain side-effect free.
        if first_run_setup_required():
            self.after(300,self._show_first_run_setup)
        # Successful setup already persists a qualified hardware profile.
        # Ordinary launches must not silently re-probe or overwrite it.
        if initial_module is not None:
            self.open_module(initial_module)

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


    def _module_host(self):
        return ModuleHost(
            self.root,self.module_states.setdefault(self.module_key,{}),self.show_module_hub,
            self._menus,self.ui_icon,self.control_button,self._run_background_task,self.tip,
        )

    def _create_module_runtime(self,spec):
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
            self.render()
            if self._active_module_runtime is runtime and callable(on_open):on_open()
        except Exception as exc:
            if self._active_module_runtime is runtime:self._module_failed(module_id,"open",exc,runtime)

    def show_module_hub(self):
        module_id=self.module_key or "unknown"
        self._dispose_module_runtime(module_id,self._active_module_runtime)
        self._active_module_runtime=None
        self.module_key=None
        self.render()

    def _show_first_run_setup(self):
        """Explain AI support first; download only after one explicit click."""
        if getattr(self,"_first_run_setup_active",False):return
        if ai_setup_complete():
            messagebox.showinfo("AI support","AI support is already installed and verified.",parent=self);return
        self._first_run_setup_active=True
        dialog=tk.Toplevel(self);dialog.title("AI support setup");dialog.transient(self);dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=18);frame.pack(fill="both",expand=True);frame.columnconfigure(0,weight=1)
        ttk.Label(frame,text="Set up AI features",style="PageTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(
            frame,
            text="MorphoLabel works without AI. For Landmarks and X-ray Traits prediction and training, it can install the required AI components.",
            justify="left",wraplength=900,
        ).grid(row=1,column=0,sticky="w",pady=(7,10))
        components=ttk.Frame(frame);components.grid(row=2,column=0,sticky="ew")
        status_labels={}
        for column,heading in enumerate(("Component","Used by","Purpose","Status")):
            ttk.Label(components,text=heading,style="SectionTitle.TLabel").grid(row=0,column=column,sticky="w",padx=(0,16),pady=(0,6))
        model=SetupProgress()
        for row,item in enumerate(COMPONENTS,1):
            for column,text in enumerate((item.name,item.used_by,item.purpose)):
                ttk.Label(components,text=text).grid(row=row,column=column,sticky="w",padx=(0,16),pady=4)
            label=ttk.Label(components,text=model.status[item.stage])
            label.grid(row=row,column=3,sticky="w",pady=4)
            status_labels[item.stage]=label
        ttk.Label(components,text="Downloads are several GB. AI support uses one shared engine. Project images and data are not uploaded.",
                  style="Muted.TLabel").grid(row=9,column=0,columnspan=4,sticky="w",pady=(10,0))
        stage=ttk.Label(frame,text="Nothing will be downloaded until you choose Install AI support.",style="SectionTitle.TLabel")
        stage.grid(row=3,column=0,sticky="w",pady=(14,0))
        detail=ttk.Label(frame,text="You can skip this now and install AI support later from the AI menu.",style="Muted.TLabel",justify="left",wraplength=620)
        detail.grid(row=4,column=0,sticky="w",pady=(4,8))
        bar=ttk.Progressbar(frame,mode="determinate",maximum=100,value=0,length=580)
        component_bar=ttk.Progressbar(frame,mode="determinate",maximum=100,length=580)
        component_bar.grid(row=5,column=0,sticky="ew")
        bar.grid(row=6,column=0,sticky="ew",pady=(8,0))
        summary=ttk.Label(frame,text="1 of 8 components ready · 5%")
        summary.grid(row=7,column=0,sticky="w",pady=(4,0))
        def refresh_overview():
            for key,label in status_labels.items():
                status=model.status[key]
                color="#18783a" if status=="✓ Ready" else "#b42318" if status=="⚠ Failed" else "#555555"
                label.configure(text=status,foreground=color)
            bar.configure(value=model.overall)
            component_bar.configure(value=model.component_percent)
            summary.configure(text=f"{model.ready_count} of 8 components ready · {int(model.overall)}%")
        refresh_overview()
        result_label=ttk.Label(frame,text="",justify="left",wraplength=620);result_label.grid(row=8,column=0,sticky="w",pady=(10,0))
        actions=ttk.Frame(frame);actions.grid(row=9,column=0,sticky="e",pady=(14,0))
        events=queue.Queue();working={"value":False}
        dialog.protocol("WM_DELETE_WINDOW",lambda:None);dialog.grab_set();center(self,dialog)

        def progress(stage_name,stage_detail):
            events.put(("progress",str(stage_name),str(stage_detail)))

        def worker():
            try:events.put(("done",run_first_run_setup(progress=progress)))
            except Exception as exc:events.put(("error",exc))

        def start_setup():
            if working["value"]:return
            working["value"]=True;model.retry();refresh_overview()
            for child in actions.winfo_children():child.destroy()
            result_label.configure(text="")
            stage.configure(text="Starting AI setup…")
            detail.configure(text="Preparing the required components. Downloads can resume if the connection is interrupted.")
            threading.Thread(target=worker,daemon=True,name="morpholabel-first-run-setup").start()

        def close_ready():
            self._first_run_setup_active=False
            try:dialog.grab_release()
            except tk.TclError:pass
            dialog.destroy()

        def continue_core():
            defer_first_run_setup();self._first_run_setup_active=False
            try:dialog.grab_release()
            except tk.TclError:pass
            dialog.destroy();log("GLOBAL","first_run_setup","DEFERRED",detail="user chose to continue without AI")

        def initial_actions():
            self.control_button(actions,"Continue without AI",continue_core,"Continue now and set up AI later.").pack(side="right")
            self.control_button(actions,"Install AI support",start_setup,"Install the listed AI components and test this computer.",primary=True).pack(side="right",padx=(0,6))

        def poll():
            try:
                while True:
                    kind,*value=events.get_nowait()
                    if kind=="progress":
                        stage_name,stage_detail=value
                        model.update(stage_name,stage_detail);refresh_overview()
                        component=next((item.name for item in COMPONENTS if item.stage==stage_name),"Checking AI support")
                        stage.configure(text=component);detail.configure(text=stage_detail)
                    elif kind=="error":
                        working["value"]=False;model.fail();refresh_overview()
                        stage.configure(text="AI setup is incomplete")
                        detail.configure(text="MorphoLabel can still be used without AI. Partial downloads stay local and resume only if you choose Retry or start AI setup again.")
                        log("GLOBAL","first_run_setup","ERROR",detail=str(value[0]))
                        error=str(value[0]).lower()
                        explanation="The download could not finish. Check your connection and choose Retry."
                        if "sha256" in error:explanation="The downloaded file did not pass verification. Choose Retry to replace it."
                        elif "space" in error:explanation="There is not enough disk space. Free some space and choose Retry."
                        elif "download" not in error:explanation="AI preparation could not finish. Choose Retry; if it repeats, open diagnostics from the AI menu."
                        result_label.configure(text=explanation)
                        self.control_button(actions,"Continue without AI",continue_core,"Continue now and set up AI later.").pack(side="right")
                        self.control_button(actions,"Retry",start_setup,"Retry the approved AI setup.",primary=True).pack(side="right",padx=(0,6))
                    else:
                        working["value"]=False;model.update("READY","");refresh_overview();bar.configure(value=100)
                        payload=value[0];hardware=payload.get("hardware") or {};test=payload.get("ai_self_test") or {}
                        gpu=hardware.get("gpu_model") or "No dedicated GPU detected"
                        accel="CUDA" if hardware.get("cuda_available") else "CPU"
                        training=(test.get("training_smoke") or {}).get("status") or "not run"
                        dialog.title("MorphoLabel is ready");stage.configure(text="MorphoLabel is ready")
                        detail.configure(text="AI support is installed and verified. MorphoLabel is ready to use.")
                        result_label.configure(text=f"GPU: {gpu}\nAI acceleration: {accel}\nPrediction test: PASS\nTraining test: {str(training).upper()}\n\nPerformance mode: Auto.")
                        self.control_button(actions,"Start MorphoLabel",close_ready,"Finish setup and use MorphoLabel.",primary=True).pack(side="right")
            except queue.Empty:
                if dialog.winfo_exists():self.after(100,poll)

        initial_actions();poll()

    def _warm_ai_hardware(self):
        """Compatibility hook: load the setup-qualified profile without probing hardware."""
        try:
            profile=get_hardware_profile()
            log("GLOBAL","hardware_profile","END",detail=f"source=setup-qualified; cpu={profile.cpu_model}; logical={profile.logical_cores}; gpu={profile.gpu_model}; vram_mib={profile.gpu_vram_mib}; cuda={profile.cuda_available}")
            return profile
        except Exception as exc:
            log("GLOBAL","hardware_profile","ERROR",detail=str(exc))
            return None

    def ui_icon(self,name,size):
        key=(str(name),int(size))
        if key not in self._ui_icons:self._ui_icons[key]=tk_icon(self,name,size)
        return self._ui_icons[key]

    def control_button(self,parent,text,command,help_text,primary=False,enabled=True,icon=None,icon_size=CONTROL_ICON_SIZE,**kwargs):
        from .design import action_icon
        icon=icon or action_icon(text)
        style=kwargs.pop("style","Primary.TButton" if primary else "P.TButton")
        state=kwargs.pop("state","normal" if enabled else "disabled")
        if icon:
            kwargs.setdefault("image",self.ui_icon(icon,icon_size))
            kwargs.setdefault("compound","left")
        button=ttk.Button(parent,text=text,command=command,state=state,style=style,**kwargs)
        self.tip.bind(button,help_text); return button



    def _run_background_task(self,title,initial_text,worker,on_done):
        """Run one blocking project operation off Tk with unmistakable live feedback."""
        dialog=tk.Toplevel(self);dialog.title(title);dialog.transient(self)
        frame=ttk.Frame(dialog,padding=14);frame.pack(fill="both",expand=True)
        label=ttk.Label(frame,text=initial_text,justify="left");label.pack(anchor="w")
        bar=ttk.Progressbar(frame,mode="indeterminate",length=360);bar.pack(fill="x",pady=(8,0));bar.start()
        destroy_dialog=dialog.destroy
        def close():
            try:bar.stop()
            except tk.TclError:pass
            destroy_dialog()
        dialog.destroy=close;dialog.protocol("WM_DELETE_WINDOW",close)
        events=queue.Queue();center(self,dialog);poll_state={"job":None}
        def release(event):
            if event.widget is dialog and poll_state["job"] is not None:
                try:self.after_cancel(poll_state["job"])
                except tk.TclError:pass
                poll_state["job"]=None
        dialog.bind("<Destroy>",release,add="+")
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
            poll_state["job"]=None
            if not dialog.winfo_exists():return
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
            except queue.Empty:poll_state["job"]=self.after(100,poll)
        poll();return dialog


    def _clear(self):
        self.tip.hide(); self.photo_panel=None
        for child in self.root.winfo_children(): child.destroy()
        # Each top-level view owns its grid rows. Reset weights so returning
        # from a workspace does not leave an empty weighted row under the hub.
        self.root.rowconfigure(0,weight=0);self.root.rowconfigure(1,weight=0)
        # Release widget/Variable cycles on Tk's thread before another module's
        # image worker can trigger collection of their Tcl-backed objects.
        import gc
        gc.collect()

    def _update_window_title(self):
        spec=self.module_registry.get(self.module_key) if self.module_key else None
        module_name=spec.display_name if spec is not None else "Modules"
        self.title(f"{APP_NAME} — {module_name} — {APP_FULL_NAME} — v{APP_VERSION}")

    def render(self):
        self._update_window_title()
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



    def _menus(self,row):
        button=ttk.Menubutton(row,text="Menu"); menu=tk.Menu(button,tearoff=False)
        ai_menu=tk.Menu(menu,tearoff=False)
        ai_menu.add_command(label="Set up AI support...",command=self._show_first_run_setup)
        ai_menu.add_command(label="Hardware status…",command=self.show_hardware)
        menu.add_cascade(label="AI support",menu=ai_menu)
        provider=getattr(getattr(self,"_active_module_runtime",None),"standard_menu_entries",None)
        if callable(provider):
            entries=tuple(provider() or ())
            if entries:
                models_menu=tk.Menu(menu,tearoff=False)
                category="AI models · import / export" if all(entry.get("group")=="models" for entry in entries if entry) else "Current module"
                menu.add_cascade(label=category,menu=models_menu)
                def refresh_models_menu():
                    models_menu.delete(0,"end")
                    for entry in tuple(provider() or ()):
                        if entry is None:models_menu.add_separator();continue
                        models_menu.add_command(
                            label=str(entry.get("label") or "Module action"),
                            command=entry.get("command"),
                            state=str(entry.get("state") or "normal"),
                        )
                models_menu.configure(postcommand=refresh_models_menu)
                refresh_models_menu()
        menu.add_separator()
        support=tk.Menu(menu,tearoff=False)
        support.add_command(label="Create diagnostic report…",command=self.create_diagnostic_report)
        support.add_command(label="GitHub project",command=lambda:webbrowser.open(PUBLIC_REPOSITORY))
        menu.add_cascade(label="Support",menu=support)
        menu.add_separator()
        menu.add_command(label="About MorphoLabel...",command=self.show_about)
        button.configure(menu=menu);button.pack(side="right",padx=2)
        self.tip.bind(button,"AI setup, diagnostics, project links and About MorphoLabel.")
        queues=ttk.Button(row,text="Queues",image=self.ui_icon("queues",TOPBAR_ICON_SIZE),compound="left",
                          command=lambda:self._show_queue_center(),style="Stage.TButton")
        queues.pack(side="right",padx=(2,6))
        self.tip.bind(queues,"Open, resume or close saved annotation and review queues.")

    def _show_queue_center(self):
        return show_queue_center(self,self._queue_entries(),self.control_button)

    def _queue_entries(self):
        provider=getattr(getattr(self,"_active_module_runtime",None),"queue_entries",None)
        if callable(provider):
            return tuple(provider() or ())
        return ()



































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
        from .module_credits import module_credit_rows
        dialog=tk.Toplevel(self);dialog.title("About MorphoLabel");dialog.transient(self);dialog.resizable(False,False);apply_window_identity(dialog,short=True)
        frame=ttk.Frame(dialog,padding=20);frame.pack(fill="both",expand=True)
        brand=ttk.Frame(frame);brand.pack(fill="x")
        logo=icon_image(dialog);dialog._morpholabel_about_icon=logo
        ttk.Label(brand,image=logo).pack(side="left",anchor="n",padx=(0,18))
        content=ttk.Frame(brand);content.pack(side="left",fill="x",expand=True)
        ttk.Label(content,text=APP_NAME,style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(content,text=f"v{APP_VERSION} · {APP_STATUS}",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,8))
        ttk.Label(content,text="Open-source software for scalable and reproducible extraction of morphological data from biological images.",wraplength=500,justify="left").pack(anchor="w")
        ttk.Label(content,text="MorphoLabel combines annotation, human review and quality control into a structured workflow for large image datasets.",wraplength=500,justify="left",style="Muted.TLabel").pack(anchor="w",pady=(5,0))
        ttk.Separator(frame,orient="horizontal").pack(fill="x",pady=(14,10))
        ttk.Label(frame,text="Core application",style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(frame,text="Concept, scientific workflow and development: Oleg Artaev.").pack(anchor="w",pady=(3,0))
        ttk.Label(frame,text="Developed with the assistance of OpenAI Codex.",style="Muted.TLabel").pack(anchor="w",pady=(2,10))
        ttk.Label(frame,text="Modules",style="SectionTitle.TLabel").pack(anchor="w")
        credits=ttk.Frame(frame);credits.pack(fill="x",pady=(4,8))
        for name,author,scope,ai in module_credit_rows(self.module_registry,self):
            module_box=ttk.LabelFrame(credits,text=name,padding=(10,7));module_box.pack(fill="x",pady=(0,6))
            ttk.Label(module_box,text=scope,wraplength=600,justify="left").pack(anchor="w")
            ttk.Label(module_box,text=ai,style="Muted.TLabel",wraplength=600,justify="left").pack(anchor="w",pady=(3,0))
            ttk.Label(module_box,text=f"Author: {author}",style="Muted.TLabel").pack(anchor="w",pady=(3,0))
        ttk.Separator(frame,orient="horizontal").pack(fill="x",pady=(4,8))
        ttk.Label(frame,text=f"{COPYRIGHT} · {LICENSE_NAME}",style="Muted.TLabel").pack(anchor="w")
        ttk.Label(frame,text="Redistributed derivative works must retain the Apache-2.0 license and applicable NOTICE attribution.",style="Muted.TLabel",justify="left",wraplength=620).pack(anchor="w",pady=(3,0))
        ttk.Label(frame,text="For scientific software or models substantially based on MorphoLabel, please identify MorphoLabel as the source and cite it.",style="Muted.TLabel",justify="left",wraplength=620).pack(anchor="w",pady=(3,0))
        ttk.Label(frame,text=CONTACT_EMAIL).pack(anchor="w",pady=(8,0))
        link=ttk.Label(frame,text=PUBLIC_REPOSITORY,foreground=ACC,cursor="hand2");link.pack(anchor="w",pady=(2,0))
        link.bind("<Button-1>",lambda _e:webbrowser.open(PUBLIC_REPOSITORY))
        actions=ttk.Frame(frame);actions.pack(fill="x",pady=(12,0))
        self.control_button(actions,"Close",dialog.destroy,"Close About MorphoLabel.").pack(side="right")
        center(self,dialog)

    def show_hardware(self):
        try:
            h=get_hardware_profile()
            text=format_hardware_profile(h)
            summary=getattr(self._active_module_runtime,"hardware_summary",None)
            if callable(summary):
                try:
                    extra=summary(h)
                    if extra:text+="\n\n"+extra
                except Exception:
                    pass
            info(self,"Hardware",text)
        except Exception as exc: messagebox.showerror("Hardware",str(exc),parent=self)




def run():
    ProductionShell().mainloop()

if __name__ == "__main__": run()
