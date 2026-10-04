"""Shared, canvas-first workflow dock. Scientific sections retain their controls."""
from __future__ import annotations
from tkinter import ttk
from .icons import ICON_NAMES, WORKFLOW_ICON_SIZE


def columns_for_width(width: int, card_count: int, card_widths=None) -> int:
    count=max(1,int(card_count or 1));width=max(0,int(width or 0))
    required=[max(1,int(v)) for v in (card_widths or (300,)*count)]
    if len(required)!=count:raise ValueError('one requested width is required for each workflow card')
    # Each wide-mode column retains its own minimum requested width.
    if width>=sum(required)+18*(count-1):return count
    return 1


class WorkflowDock(ttk.Frame):
    """All cards on wide windows; stage tabs on narrow windows.

    Only placement and visibility change. Existing widgets, variables and
    commands live for the whole section lifetime, including hidden cards.
    """
    def __init__(self,parent,shell,*,help_factory=None,title='Workflow'):
        super().__init__(parent,style='WorkflowDock.TFrame',padding=(0,1,0,0))
        self.shell=shell;self._cards=[];self._card_headers=[];self._tabs=[];self._layout_after=None;self._last_columns=None;self._selected_card=0;self._last_selection=None;self._collapsed=False
        header=ttk.Frame(self,style='WorkflowDock.TFrame');header.grid(row=0,column=0,sticky='ew',pady=(0,1));header.columnconfigure(0,weight=1)
        self.toggle=ttk.Button(header,text=title+' ▾',style='Stage.TButton',command=self._toggle)
        self.toggle.grid(row=0,column=0,sticky='w');self._title=title
        shell.tip.bind(self.toggle,'Hide or show workflow controls to make more room for the image.')
        if help_factory is not None:help_factory(header).grid(row=0,column=1,sticky='e')
        self.tab_host=ttk.Frame(self,style='WorkflowDock.TFrame');self.tab_host.grid(row=1,column=0,sticky='ew',pady=(0,2))
        self.cards_host=ttk.Frame(self,style='WorkflowDock.TFrame');self.cards_host.grid(row=2,column=0,sticky='ew')
        self.columnconfigure(0,weight=1);self.bind('<Configure>',self._schedule_layout,add='+')

    def add_card(self,title,*,icon='',help_text=''):
        header=ttk.Frame(self.cards_host)
        if icon:
            if icon in ICON_NAMES:
                ttk.Label(header,image=self.shell.ui_icon(icon, max(26,WORKFLOW_ICON_SIZE-4))).pack(side='left',padx=(0,5))
            else:ttk.Label(header,text=icon,style='WorkflowIcon.TLabel').pack(side='left',padx=(0,6))
        ttk.Label(header,text=title,style='WorkflowCardTitle.TLabel').pack(side='left')
        card=ttk.LabelFrame(self.cards_host,labelwidget=header,padding=(8,5),style='WorkflowCard.TLabelframe')
        if help_text:self.shell.tip.bind(card,help_text);self.shell.tip.bind(header,help_text)
        index=len(self._cards);self._cards.append(card);self._card_headers.append(header)
        label=title.split('. ',1)[-1]
        short={'Repeatability':'Repeatability','Training data':'Examples','Train model':'Train','Predict & review':'Predict & review'}.get(label,label)
        tab=ttk.Button(self.tab_host,text=f'{index+1}. {short}',style='Stage.TButton',command=lambda value=index:self._select_card(value))
        tab.pack(side='left',padx=(0,3));self._tabs.append(tab)
        if label=='Training data' and index==1:self._selected_card=1
        self._schedule_layout();return card

    def _select_card(self,index):
        self._selected_card=int(index);self._last_columns=None;self._layout_cards()

    def _toggle(self):
        self._collapsed=not self._collapsed
        self.toggle.configure(text=self._title+(' ▸' if self._collapsed else ' ▾'))
        self._last_columns=None;self._layout_cards()

    def _schedule_layout(self,_event=None):
        if self._layout_after is not None:
            try:self.after_cancel(self._layout_after)
            except Exception:pass
        self._layout_after=self.after_idle(self._layout_cards)

    def _layout_cards(self):
        self._layout_after=None
        if not self._cards:return
        if self._collapsed:
            self.tab_host.grid_remove();self.cards_host.grid_remove();return
        self.cards_host.grid()
        width=self.winfo_width() or self.cards_host.winfo_width() or 1000
        columns=columns_for_width(width,len(self._cards),[max(card.winfo_reqwidth(),header.winfo_reqwidth()+20) for card,header in zip(self._cards,self._card_headers)])
        compact=columns<len(self._cards)
        if compact:self.tab_host.grid()
        else:self.tab_host.grid_remove()
        if columns==self._last_columns and self._last_selection==self._selected_card:return
        self._last_columns=columns;self._last_selection=self._selected_card
        for card,header in zip(self._cards,self._card_headers):
            card.grid_forget()
            card.configure(labelwidget="" if compact else header)
        for index in range(max(1,len(self._cards))):self.cards_host.columnconfigure(index,weight=0,uniform='',minsize=0)
        self.cards_host.rowconfigure(0,minsize=0)
        if compact:
            self.cards_host.columnconfigure(0,weight=1)
            self._cards[self._selected_card].grid(row=0,column=0,sticky='nsew')
        else:
            # Equal-height cards, separated by whitespace rather than divider bars.
            self.update_idletasks()
            target_height=max(card.winfo_reqheight() for card in self._cards)
            self.cards_host.rowconfigure(0,minsize=target_height)
            for index,card in enumerate(self._cards):
                self.cards_host.columnconfigure(index,weight=1,uniform='workflow_stage',minsize=card.winfo_reqwidth())
                card.grid(row=0,column=index,sticky='nsew',padx=(0 if index==0 else 5,0))
        for index,tab in enumerate(self._tabs):tab.configure(style='StageActive.TButton' if index==self._selected_card else 'Stage.TButton')


def add_command_separator(parent, *, padx=6):
    """Visually separate command groups without adding another boxed panel."""
    separator=ttk.Separator(parent,orient="vertical")
    separator.pack(side="left",fill="y",padx=padx,pady=2)
    return separator


def build_help_button(section,parent,title,text):
    button=section.what_to_do(parent,title,text);button.configure(text='Help');return button
