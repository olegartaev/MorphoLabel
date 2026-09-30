"""Small common base for independently readable production UI sections."""
class SectionView:
    def __init__(self, shell, parent): self.shell=shell; self.context=shell.context; self.parent=parent
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
        """Explain why a persistent prediction-review queue opened this workspace."""
        from tkinter import ttk
        from app.landmark_attention_queue import display_summary, user_copy
        project=getattr(self.context,"project",None)
        current=(self.context.current() or {}).get("image_id") if project else None
        issue=display_summary(project) if project else None
        if not issue or issue.get("image_id")!=current or issue.get("stage") not in set(stages):
            return None
        copy=user_copy(issue)
        box=ttk.Frame(parent,style="Attention.TFrame",padding=(10,7));box.pack(fill="x",pady=(3,0))
        text=ttk.Frame(box,style="Attention.TFrame");text.pack(side="left",fill="x",expand=True)
        ttk.Label(text,text=f"Prediction review · {issue.get('position',0)} of {issue.get('total',0)}",style="AttentionStep.TLabel").pack(anchor="w")
        ttk.Label(text,text=copy["title"],style="AttentionTitle.TLabel").pack(anchor="w")
        ttk.Label(text,text=copy["message"],style="AttentionText.TLabel",wraplength=900,justify="left").pack(anchor="w")
        self.button(box,copy["action"],command,copy["help"],style="Primary.TButton").pack(side="right",padx=(12,0))
        return box

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
