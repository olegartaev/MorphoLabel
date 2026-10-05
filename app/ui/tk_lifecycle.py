"""Release one Tk callback while preserving other users of a shared event."""
import tkinter as tk


def unbind_callback(widget, sequence, binding):
    # Tkinter in Python 3.11/early 3.12 clears the entire event even when a
    # function ID is supplied to unbind(). Durable shells share these events.
    script = widget.bind(sequence)
    prefix = f'if {{"[{binding} '
    remaining = "\n".join(line for line in script.split("\n") if not line.startswith(prefix))
    widget.bind(sequence, remaining)
    widget.deletecommand(binding)


def trace_for_widget(widget, variable, mode, callback):
    """Keep a Variable trace alive only while its owning widget exists."""
    binding = variable.trace_add(mode, callback)
    def release(event):
        if event.widget is widget:
            try:variable.trace_remove(mode, binding)
            except tk.TclError:pass
    widget.bind("<Destroy>", release, add="+")
    return binding
