"""Shared, canvas-first workflow dock. Scientific sections retain their controls."""
from __future__ import annotations
from tkinter import ttk
from tkinter import font as tkfont
import tkinter as tk
from .icons import ICON_NAMES, WORKFLOW_ICON_SIZE


def columns_for_width(width: int, card_count: int, card_widths=None) -> int:
    """Compatibility helper retained for callers/tests from the former card layout."""
    count=max(1,int(card_count or 1));width=max(0,int(width or 0))
    required=[max(1,int(v)) for v in (card_widths or (300,)*count)]
    if len(required)!=count:raise ValueError('one requested width is required for each workflow card')
    if width>=sum(required)+18*(count-1):return count
    return 1


class WorkflowDock(ttk.Frame):
    """Compact workflow presented as real tabs with stage-specific hover help."""
    def __init__(self,parent,shell,*,help_factory=None,title='Workflow'):
        super().__init__(parent,style='WorkflowDock.TFrame',padding=(0,1,0,0))
        self.shell=shell;self._cards=[];self._tabs=[];self._tab_images=[];self._tab_help=[];self._selected_card=0
        self._collapsed=False;self._last_columns=1;self._last_selection=0;self._hover_tab=None;self._tab_labels=[]
        header=ttk.Frame(self,style='WorkflowDock.TFrame');header.grid(row=0,column=0,sticky='ew',pady=(0,1));header.columnconfigure(0,weight=1)
        self.toggle=ttk.Button(header,text=title+' ▾',style='Stage.TButton',command=self._toggle)
        self.toggle.grid(row=0,column=0,sticky='w');self._title=title
        shell.tip.bind(self.toggle,'Hide or show workflow controls to make more room for the image.')
        if help_factory is not None:help_factory(header).grid(row=0,column=1,sticky='e')
        self.notebook=ttk.Notebook(self,style='Workflow.TNotebook')
        self.notebook.grid(row=1,column=0,sticky='ew')
        self.notebook.bind('<<NotebookTabChanged>>',self._tab_changed,add='+')
        self.notebook.bind('<Motion>',self._tab_motion,add='+')
        self.notebook.bind('<Leave>',lambda _e:self._clear_tab_hover(),add='+')
        self.notebook.bind('<Destroy>',lambda _e:self._clear_tab_hover(),add='+')
        self.notebook.bind('<Configure>',self._fit_tab_labels,add='+')
        self.columnconfigure(0,weight=1)

    def add_card(self,title,*,icon='',help_text=''):
        index=len(self._cards);label=title.split('. ',1)[-1]
        short={'Repeatability':'Repeatability','Training data':'Start examples','Train model':'Train','Predict & review':'Predict & review'}.get(label,label)
        card=ttk.Frame(self.notebook,style='WorkflowDock.TFrame')
        card.columnconfigure(0,weight=1);card.rowconfigure(0,weight=1)
        viewport=tk.Canvas(card,highlightthickness=0,background=ttk.Style(self).lookup('WorkflowDock.TFrame','background') or '#f0f0f0')
        viewport.grid(row=0,column=0,sticky='ew')
        scroll=ttk.Scrollbar(card,orient='vertical',command=viewport.yview);scroll.grid(row=0,column=1,sticky='ns')
        viewport.configure(yscrollcommand=scroll.set)
        content=ttk.Frame(viewport,padding=(8,6),style='WorkflowDock.TFrame')
        window=viewport.create_window((0,0),window=content,anchor='nw')
        def layout(_event=None):
            width=max(1,viewport.winfo_width());height=max(1,content.winfo_reqheight())
            limit=180 if self.winfo_toplevel().winfo_height()>=850 else 100
            viewport.configure(height=min(height,limit),scrollregion=(0,0,width,height))
            viewport.itemconfigure(window,width=width)
        viewport.bind('<Configure>',layout);content.bind('<Configure>',layout)
        def wheel(event):
            viewport.yview_scroll(-1 if event.delta>0 else 1,'units');return 'break'
        def reveal(event):
            top=event.widget.winfo_rooty()-content.winfo_rooty();bottom=top+event.widget.winfo_height()
            visible=viewport.canvasy(0);height=viewport.winfo_height();total=max(1,content.winfo_height())
            if top<visible:viewport.yview_moveto(top/total)
            elif bottom>visible+height:viewport.yview_moveto((bottom-height)/total)
        def bind_navigation(widget):
            if not getattr(widget,'_workflow_navigation_bound',False):
                if not isinstance(widget,(ttk.Combobox,ttk.Spinbox,ttk.Treeview)):
                    widget.bind('<MouseWheel>',wheel,add='+')
                widget.bind('<FocusIn>',reveal,add='+')
                widget._workflow_navigation_bound=True
            for child in widget.winfo_children():bind_navigation(child)
        content.bind('<Map>',lambda _event:bind_navigation(content),add='+')
        image=''
        if icon:image=self.shell.ui_icon(icon if icon in ICON_NAMES else 'modules',max(24,WORKFLOW_ICON_SIZE-6))
        self._cards.append(card);self._tabs.append(card);self._tab_images.append(image);self._tab_help.append(str(help_text or ''))
        options={'text':f'{index+1}. {short}','compound':'left'}
        compact={'Human Repeatability':'Repeatability','Start examples':'Examples','Predict & review':'Predict'}.get(short,short)
        self._tab_labels.append((options['text'],f'{index+1}. {compact}'))
        if image:options['image']=image
        self.notebook.add(card,**options)
        if label=='Training data' and index==1:
            self._selected_card=index;self.notebook.select(card)
        self._last_selection=self._selected_card
        return content

    def _fit_tab_labels(self,event):
        style=ttk.Style(self)
        font=tkfont.Font(master=self,font=style.lookup('Workflow.TNotebook.Tab','font') or 'TkDefaultFont')
        needed=sum(font.measure(full)+48 for full,_compact in self._tab_labels)
        for index,(full,compact) in enumerate(self._tab_labels):
            text=compact if needed>event.width else full
            if self.notebook.tab(index,'text')!=text:self.notebook.tab(index,text=text)

    def _tab_motion(self,event):
        element=str(self.notebook.identify(event.x,event.y) or '')
        if not element or element=='client':
            self._clear_tab_hover();return
        try:index=int(self.notebook.index(f'@{event.x},{event.y}'))
        except Exception:
            self._clear_tab_hover();return
        if index==self._hover_tab:return
        self._clear_tab_hover();self._hover_tab=index
        text=self._tab_help[index] if 0<=index<len(self._tab_help) else ''
        if text:self.shell.tip.schedule(self.notebook,text,(event.x_root+8,event.y_root+20,event.y_root-6))

    def _clear_tab_hover(self):
        self._hover_tab=None
        try:self.shell.tip.hide(self.notebook)
        except Exception:pass

    def _tab_changed(self,_event=None):
        self._clear_tab_hover()
        try:self._selected_card=int(self.notebook.index('current'))
        except Exception:return
        self._last_selection=self._selected_card

    def _select_card(self,index):
        index=max(0,min(len(self._cards)-1,int(index))) if self._cards else 0
        self._selected_card=index;self._last_selection=index
        if self._cards:self.notebook.select(self._cards[index])

    def _toggle(self):
        self._clear_tab_hover();self._collapsed=not self._collapsed
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
    """Visually separate command groups without adding another boxed panel."""
    separator=ttk.Separator(parent,orient='vertical')
    separator.pack(side='left',fill='y',padx=padx,pady=2)
    return separator


def build_help_button(section,parent,title,text):
    button=section.what_to_do(parent,title,text);button.configure(text='Help');return button
