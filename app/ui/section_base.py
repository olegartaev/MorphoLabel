"""Small common base for independently readable production UI sections."""

def _attention_banner_model(project,stages):
    from app.landmark_attention_queue import banner_copy, display_summary
    issue=display_summary(project) if project else None
    if not issue or issue.get("stage") not in set(stages):
        return None
    generation=str(issue.get("generation_id") or "")
    if generation and project.get_ui_state("attention_banner_dismissed_generation_id",None)==generation:
        return None
    copy=banner_copy(issue)
    return {
        "generation_id":generation,
        "remaining":int(issue.get("remaining") or 0),
        "title":copy["title"],
        "message":copy["message"],
    }


class SectionView:
    def __init__(self, shell, parent):
        self.shell=shell; self.context=shell.context; self.parent=parent; self._attention_banner_state=None
    def frame(self, **kwargs):
        from tkinter import ttk
        return ttk.Frame(self.parent, **kwargs)
    def button(self, parent, text, command, help_text, **kwargs):
        return self.shell.control_button(parent,text,command,help_text,**kwargs)
    def workflow_dock(self, parent, *, help_title, help_text):
        from .workflow import WorkflowDock, build_help_button
        return WorkflowDock(
            parent,
            self.shell,
            help_factory=lambda host: build_help_button(self, host, help_title, help_text),
        )
    def attention_banner(self, parent, command, *, stages):
        """Show one compact reminder for the active saved review queue."""
        from tkinter import ttk
        project=getattr(self.context,"project",None)
        model=_attention_banner_model(project,stages)
        if model:
            key=(str(project.root),self.context.section,"landmark_attention","Prediction attention")
            if key in self.shell.__dict__.get("_closed_queue_navigation",set()):model=None
        if not model:
            self._attention_banner_state=None
            return None
        box=ttk.Frame(parent,style="Attention.TFrame",padding=(10,7));box.pack(fill="x",pady=(3,0))
        ttk.Label(box,text="⚠",style="AttentionTitle.TLabel").pack(side="left",anchor="n",padx=(0,8))
        text=ttk.Frame(box,style="Attention.TFrame");text.pack(side="left",fill="x",expand=True)
        title_label=ttk.Label(text,style="AttentionTitle.TLabel");title_label.pack(anchor="w")
        message_label=ttk.Label(text,style="AttentionText.TLabel",wraplength=900,justify="left");message_label.pack(anchor="w")
        state={"box":box,"title":title_label,"message":message_label,"stages":set(stages),"generation_id":model.get("generation_id")}
        self._attention_banner_state=state
        def apply(value):
            left=int(value["remaining"]);noun="image" if left==1 else "images"
            title_label.configure(text=f"{value['title']} — {left} {noun} left")
            message_label.configure(text=value["message"])
            state["generation_id"]=value.get("generation_id")
        apply(model)
        def dismiss():
            generation=state.get("generation_id")
            if generation:
                project.set_ui_state("attention_banner_dismissed_generation_id",generation)
            self._attention_banner_state=None
            box.destroy()
        self.button(box,"Hide reminder",dismiss,"Hide this reminder. The review queue stays saved.",icon="close").pack(side="right",padx=(6,0))
        self.button(box,"Continue",command,"Open the saved review queue. Nothing is verified automatically.",style="Primary.TButton").pack(side="right",padx=(12,0))
        return box

    def refresh_attention_banner(self):
        """Update only banner text during fast queue navigation."""
        state=self._attention_banner_state
        if not state:return False
        box=state.get("box")
        if box is None or not box.winfo_exists():
            self._attention_banner_state=None;return False
        model=_attention_banner_model(getattr(self.context,"project",None),state.get("stages",()))
        if not model:
            box.destroy();self._attention_banner_state=None;return False
        left=int(model["remaining"]);noun="image" if left==1 else "images"
        state["title"].configure(text=f"{model['title']} — {left} {noun} left")
        state["message"].configure(text=model["message"])
        state["generation_id"]=model.get("generation_id")
        return True

    def what_to_do(self, parent, title, text, help_text="Open a short guide for this workspace."):
        """One compact, shared workflow guide button for production sections."""
        import tkinter as tk
        from tkinter import ttk
        from .dialogs import center
        def show():
            dialog=tk.Toplevel(self.shell);dialog.title(title);dialog.transient(self.shell);dialog.resizable(False,False)
            frame=ttk.Frame(dialog,padding=16);frame.pack(fill="both",expand=True)
            ttk.Label(frame,text=title,font=("Segoe UI",11,"bold")).pack(anchor="w")
            blocks=[part.strip() for part in str(text).split("\n\n") if part.strip()]
            for index,block in enumerate(blocks):
                style="Muted.TLabel" if index==0 and not block[:2].rstrip(".").isdigit() else None
                ttk.Label(frame,text=block,justify="left",wraplength=540,style=style or "TLabel").pack(anchor="w",pady=((8 if index==0 else 5),0))
            self.button(frame,"Close",dialog.destroy,"Close this guide.").pack(anchor="e",pady=(14,0))
            center(self.shell,dialog)
        return self.button(parent,"Help",show,help_text)
