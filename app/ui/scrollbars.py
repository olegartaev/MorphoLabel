"""Show vertical scrollbars only when a view has content to scroll.

Do not resize or move the viewport on trivial 0..1 yview changes; Tk owns its
geometry. Works with grid (restore preserved layout) and pack-managed sidebars.
"""
from __future__ import annotations


def autohide_scroll_command(scrollbar, *, geometry="grid"):
    if geometry not in {"grid", "pack"}:
        raise ValueError("Scrollbar geometry must be 'grid' or 'pack'")

    def changed(first, last):
        first_num = float(first)
        last_num = float(last)
        needs_scroll = first_num > 0.0001 or last_num < 0.9999
        manager = scrollbar.winfo_manager()
        if needs_scroll and not manager:
            if geometry == "grid":
                scrollbar.grid()
            else:
                scrollbar.pack(side="right", fill="y")
        elif not needs_scroll and manager:
            if geometry == "grid":
                scrollbar.grid_remove()
            else:
                scrollbar.pack_forget()
        scrollbar.set(first, last)

    return changed
