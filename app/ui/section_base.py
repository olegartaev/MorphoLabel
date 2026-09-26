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
