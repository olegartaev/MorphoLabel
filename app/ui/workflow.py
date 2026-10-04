"""Shared, canvas-first workflow dock. Scientific sections retain their controls."""
from __future__ import annotations
from tkinter import ttk
from .icons import ICON_NAMES, WORKFLOW_ICON_SIZE


def columns_for_width(width: int, card_count: int, card_widths=None) -> int:
    """Compatibility helper retained for callers/tests from the former card layout."""
    count=max(1,int(card_count or 1));width=max(0,int(width or 0))
    required=[max(1,int(v)) for v in (card_widths or (300,)*count)]
    if len(required)!=count:raise ValueError('one requested width is required for each workflow card')
    if width>=sum(required)+18*(count-1):return count
    return 1


class WorkflowDock(ttk.Frame):
    """Compact workflow presented as real tabs.

    Only one stage is open at a time, so the active stage is unambiguous and
    the image keeps the largest possible working area. Stage widgets stay
    alive for the whole section lifetime, including when another tab is open.
    """
    def __init__(self,parent,shell,*,help_factory=None,title='Workflow'):
        super().__init__(parent,style='WorkflowDock.TFrame',padding=(0,1,0,0))
        self.shell=shell;self._cards=[];self._tabs=[];self._tab_images=[];self._selected_card=0
        self._collapsed=False;self._last_columns=1;self._last_selection=0
        header=ttk.Frame(self,style='WorkflowDock.TFrame');header.grid(row=0,column=0,sticky='ew',pady=(0,1));header.columnconfigure(0,weight=1)
        self.toggle=ttk.Button(header,text=title+' ▾',style='Stage.TButton',command=self._toggle)
        self.toggle.grid(row=0,column=0,sticky='w');self._title=title
        shell.tip.bind(self.toggle,'Hide or show workflow controls to make more room for the image.')
        if help_factory is not None:help_factory(header).grid(row=0,column=1,sticky='e')
        self.notebook=ttk.Notebook(self,style='Workflow.TNotebook')
        self.notebook.grid(row=1,column=0,sticky='ew')
        self.notebook.bind('<<NotebookTabChanged>>',self._tab_changed,add='+')
        self.columnconfigure(0,weight=1)

    def add_card(self,title,*,icon='',help_text=''):
        index=len(self._cards);label=title.split('. ',1)[-1]
        short={'Repeatability':'Repeatability','Training data':'Examples','Train model':'Train','Predict & review':'Predict & review'}.get(label,label)
        card=ttk.Frame(self.notebook,padding=(8,6),style='WorkflowDock.TFrame')
        image=''
        if icon:
            image=self.shell.ui_icon(icon if icon in ICON_NAMES else 'modules',max(24,WORKFLOW_ICON_SIZE-6))
        self._cards.append(card);self._tabs.append(card);self._tab_images.append(image)
        options={'text':f'{index+1}. {short}','compound':'left'}
        if image:options['image']=image
        self.notebook.add(card,**options)
        if help_text:self.shell.tip.bind(card,help_text)
        if label=='Training data' and index==1:
            self._selected_card=index;self.notebook.select(card)
        self._last_selection=self._selected_card
        return card

    def _tab_changed(self,_event=None):
        try:self._selected_card=int(self.notebook.index('current'))
        except Exception:return
        self._last_selection=self._selected_card

    def _select_card(self,index):
        index=max(0,min(len(self._cards)-1,int(index))) if self._cards else 0
        self._selected_card=index;self._last_selection=index
        if self._cards:self.notebook.select(self._cards[index])

    def _toggle(self):
        self._collapsed=not self._collapsed
        self.toggle.configure(text=self._title+(' ▸' if self._collapsed else ' ▾'))
        self._layout_cards()

    def _schedule_layout(self,_event=None):
        self.after_idle(self._layout_cards)

    def _layout_cards(self):
        if self._collapsed:
            self.notebook.grid_remove();return
        self.notebook.grid()
        if self._cards:self.notebook.select(self._cards[self._selected_card])


def add_command_separator(parent, *, padx=6):
    """Keep command-group spacing without drawing vertical divider bars."""
    spacer=ttk.Frame(parent,width=1)
    spacer.pack(side='left',padx=padx)
    return spacer


def build_help_button(section,parent,title,text):
    button=section.what_to_do(parent,title,text);button.configure(text='Help');return button
