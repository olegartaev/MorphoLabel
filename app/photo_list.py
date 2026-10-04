"""Virtualised project photo list with reliable Canvas status indicators."""
from __future__ import annotations
import tkinter as tk
from app.ui.tooltips import place_popup

class PhotoListCanvas(tk.Canvas):
 row_height=24
 def __init__(self,master,**kwargs):
  self.status_shape=str(kwargs.pop("status_shape","circle") or "circle")
  super().__init__(master,highlightthickness=0,**kwargs);self.rows=[];self._selection=();self._yscroll=None;self._tooltip=None
  self.bind("<Configure>",lambda _e:self._draw());self.bind("<Button-1>",self._click);self.bind("<MouseWheel>",self._wheel);self.bind("<Up>",lambda _e:self._move(-1));self.bind("<Down>",lambda _e:self._move(1));self.bind("<Home>",lambda _e:self._select(0));self.bind("<End>",lambda _e:self._select(len(self.rows)-1));self.bind("<Motion>",self._motion);self.bind("<Leave>",lambda _e:self._hide_tooltip());self.bind("<Destroy>",lambda event:self._hide_tooltip() if event.widget is self else None,add="+");super().configure(scrollregion=(0,0,1,1),takefocus=True)
 def configure(self,cnf=None,**kwargs):
  if "yscrollcommand" in kwargs:self._yscroll=kwargs.pop("yscrollcommand")
  return super().configure(cnf,**kwargs)
 config=configure
 def set_rows(self,rows):
  self.rows=list(rows);self._selection=();super().configure(scrollregion=(0,0,max(1,self.winfo_width()),max(1,len(self.rows)*self.row_height)));self._draw()
 def set_row(self,index,row):
  if 0<=index<len(self.rows):self.rows[index]=row;self._draw()
 def curselection(self):return self._selection
 def selection_clear(self,_first,_last=None):self._selection=();self._draw()
 def selection_set(self,index,_last=None):
  if self.rows:self._selection=(max(0,min(int(index),len(self.rows)-1)),);self._draw()
 def see(self,index,align_top=False):
  if not self.rows:return
  index=max(0,min(int(index),len(self.rows)-1));content=max(1,len(self.rows)*self.row_height);height=max(1,self.winfo_height());top=float(self.canvasy(0));bottom=top+height;y=index*self.row_height;margin=2
  if align_top:
   target=min(max(0,y-margin),max(0,content-height));super().yview_moveto(target/content)
  elif y<top+margin:super().yview_moveto(max(0,y-margin)/content)
  elif y+self.row_height>bottom-margin:super().yview_moveto(max(0,y+self.row_height-height+margin)/content)
  self._draw();self._notify_scroll()
 def yview(self,*args):
  result=super().yview(*args);self._draw();self._notify_scroll();return result
 def yview_moveto(self,fraction):super().yview_moveto(fraction);self._draw();self._notify_scroll()
 def yview_scroll(self,number,what):super().yview_scroll(number,what);self._draw();self._notify_scroll()
 def _notify_scroll(self):
  if self._yscroll:
   first,last=super().yview();self._yscroll(first,last) if callable(self._yscroll) else self.tk.call(self._yscroll,first,last)
 def _wheel(self,event):self.yview_scroll(-1 if event.delta>0 else 1,"units");return "break"
 def _click(self,event):
  self.focus_set();index=int(self.canvasy(event.y)//self.row_height)
  if 0<=index<len(self.rows):self._select(index,reveal=False)
 def _move(self,delta):
  old=self._selection[0] if self._selection else 0;self._select(max(0,min(len(self.rows)-1,old+delta)));return "break"
 def _select(self,index,reveal=True):
  if not self.rows:return
  changed=self._selection!=(index,);self._selection=(index,);
  # Direct clicks paint immediately and deliberately do not alter the scroll position.
  self._draw()
  if reveal:self.see(index)
  if changed:self.event_generate("<<ListboxSelect>>")
 def _draw(self):
  super().delete("photo_list_render")
  if not self.winfo_exists():return
  width=max(1,self.winfo_width());super().configure(scrollregion=(0,0,width,max(1,len(self.rows)*self.row_height)))
  top=max(0,int(self.canvasy(0)//self.row_height));bottom=min(len(self.rows),int(self.canvasy(self.winfo_height())//self.row_height)+2)
  for index in range(top,bottom):
   row=self.rows[index];y=index*self.row_height
   warning=bool(row.get("review_warning")) and not bool(row.get("excluded"))
   if warning:self.create_rectangle(0,y,width,y+self.row_height,fill="#fde8e8",outline="",tags="photo_list_render")
   if self._selection==(index,):
    # Keep the pale review-warning layer visible; selection is a separate outline.
    self.create_rectangle(1,y+1,width-1,y+self.row_height-1,fill="",outline="#2563eb",width=2,tags="photo_list_render")
   excluded=bool(row.get("excluded"));foreground="#808080" if excluded else "#222"
   self.create_text(6,y+self.row_height/2,text=row.get("number",""),anchor="w",fill=foreground,tags="photo_list_render")
   self.create_text(38,y+self.row_height/2,text=row.get("cal",""),anchor="center",fill="#5f6b76" if not excluded else "#9aa0a6",font=("Segoe UI",9,"bold"),tags="photo_list_render")
   if row.get("has_crop"):
    self.create_rectangle(50,y+7,60,y+17,fill="",outline="#5f6b76" if not excluded else "#9aa0a6",width=1,tags="photo_list_render")
   status_x=72
   self.create_oval(status_x-8,y+4,status_x+8,y+20,fill="white",outline="white",tags="photo_list_render")
   if excluded:
    self.create_text(status_x,y+self.row_height/2,text="×",anchor="center",fill="#6b7280",font=("Segoe UI",12,"bold"),tags="photo_list_render")
   else:
    color={"red":"#d93025","yellow":"#e6a700","green":"#188038"}.get(row.get("status"),"#d93025")
    if self.status_shape=="square":
     self.create_rectangle(status_x-6,y+6,status_x+6,y+18,fill="white",outline=color,width=3,tags="photo_list_render")
    else:
     self.create_oval(status_x-5,y+7,status_x+5,y+17,fill=color,outline=color,tags="photo_list_render")
   self.create_text(86,y+self.row_height/2,text=row.get("text",""),anchor="w",fill=foreground,tags="photo_list_render")
  self._notify_scroll()
 def _hide_tooltip(self):
  if self._tooltip is not None:
   self._tooltip.destroy();self._tooltip=None
 def _motion(self,event):
  index=int(self.canvasy(event.y)//self.row_height)
  text=self.rows[index].get("tooltip","") if 0<=index<len(self.rows) else ""
  if not text:self._hide_tooltip();return
  if self._tooltip is not None and getattr(self._tooltip,"_text",None)==text:return
  self._hide_tooltip();tip=tk.Toplevel(self);tip.overrideredirect(True);tip.attributes("-topmost",True);tip._text=text
  tk.Label(tip,text=text,bg="#ffffe0",relief="solid",borderwidth=1,padx=5,pady=3).pack()
  place_popup(tip,self,event.x_root+12,event.y_root+12,above_y=event.y_root-8);self._tooltip=tip

