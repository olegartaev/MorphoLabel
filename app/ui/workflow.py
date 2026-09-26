"""Shared responsive workflow dock used by SIMM workspaces."""
from __future__ import annotations

from tkinter import ttk


def columns_for_width(width: int, card_count: int, card_widths=None) -> int:
    """Choose columns from the cards' real requested widths."""
    count = max(1, int(card_count or 1))
    width = max(0, int(width or 0))
    required = [max(1, int(value)) for value in (card_widths or (300,) * count)]
    if len(required) != count:
        raise ValueError("one requested width is required for each workflow card")
    gap = 4
    if width >= sum(required) + gap * (count - 1):
        return count
    if count > 1:
        widest_pair = max(
            sum(required[index:index + 2])
            for index in range(0, count, 2)
        )
        if width >= widest_pair + gap:
            return min(2, count)
    return 1


class WorkflowDock(ttk.Frame):
    """Responsive card dock with one stable help affordance.

    The scientific section owns the controls inside each card.  This class only
    owns layout, spacing and responsive wrapping.
    """

    def __init__(self, parent, shell, *, help_factory=None, title="Workflow"):
        super().__init__(parent, style="WorkflowDock.TFrame", padding=(0, 2, 0, 0))
        self.shell = shell
        self._cards = []
        self._layout_after = None
        self._last_columns = None

        header = ttk.Frame(self, style="WorkflowDock.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=title, style="WorkflowDockTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        if help_factory is not None:
            help_factory(header).grid(row=0, column=1, sticky="e")

        self.cards_host = ttk.Frame(self, style="WorkflowDock.TFrame")
        self.cards_host.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.bind("<Configure>", self._schedule_layout, add="+")

    def add_card(self, title, *, icon="", help_text=""):
        header = ttk.Frame(self.cards_host)
        if icon:
            style = "WorkflowCheck.TLabel" if icon in {"✓", "✔"} else "WorkflowIcon.TLabel"
            ttk.Label(header, text=icon, style=style).pack(side="left", padx=(0, 6))
        ttk.Label(header, text=title, style="WorkflowCardTitle.TLabel").pack(side="left")
        card = ttk.LabelFrame(
            self.cards_host,
            labelwidget=header,
            padding=(7, 5),
            style="WorkflowCard.TLabelframe",
        )
        if help_text:
            self.shell.tip.bind(card, help_text)
            self.shell.tip.bind(header, help_text)
        self._cards.append(card)
        self._schedule_layout()
        return card

    def _schedule_layout(self, _event=None):
        if self._layout_after is not None:
            try:
                self.after_cancel(self._layout_after)
            except Exception:
                pass
        self._layout_after = self.after_idle(self._layout_cards)

    def _layout_cards(self):
        self._layout_after = None
        if not self._cards:
            return
        width = self.winfo_width() or self.cards_host.winfo_width() or 1000
        columns = columns_for_width(width, len(self._cards), [card.winfo_reqwidth() for card in self._cards])
        if columns == self._last_columns and all(card.winfo_manager() == "grid" for card in self._cards):
            return
        self._last_columns = columns

        for card in self._cards:
            card.grid_forget()
        for index in range(max(columns, len(self._cards))):
            # Clear the old uniform group too. A column that used to share the
            # four-card row must not keep consuming width after a narrow resize.
            self.cards_host.columnconfigure(index, weight=0, uniform="")
        for column in range(columns):
            self.cards_host.columnconfigure(column, weight=1, uniform="workflow")
        for index, card in enumerate(self._cards):
            row, column = divmod(index, columns)
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 4, 0),
                pady=(0 if row == 0 else 4, 0),
            )
def build_help_button(section, parent, title, text):
    """Create the shared compact workflow-help action."""
    button = section.what_to_do(parent, title, text)
    button.configure(text="Help")
    return button
