"""Shared standardized-image canvas interaction; storage is adapter supplied."""
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk
from .ui.landmark_display import normalize_display_settings, draw_marker, draw_label, label_text
POINT_CURRENT="#ffb000";POINT_NORMAL="#00e5ff";POINT_RADIUS=5;POINT_MIN_RADIUS=3;POINT_MAX_RADIUS=12;FIT_WIDTH=1050;FIT_HEIGHT=720
def build_landmark_tree(parent, callback):
 frame=ttk.Frame(parent);tree=ttk.Treeview(frame,columns=("status","id","role","abbr","name"),show="headings",selectmode="browse")
 for col,head,width,stretch in (("status","",28,False),("id","#",34,False),("role","Use",42,False),("abbr","Abbr",58,False),("name","Landmark",180,True)):tree.heading(col,text=head);tree.column(col,width=width,minwidth=width,stretch=stretch,anchor="w")
 scroll=ttk.Scrollbar(frame,orient="vertical",command=tree.yview);tree.configure(yscrollcommand=scroll.set);tree.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y");tree.tag_configure("present",foreground="#188038");tree.tag_configure("missing",foreground="#c88700");tree.tag_configure("unresolved",foreground="#d93025");tree.tag_configure("review_warning",background="#fde8e8");tree.bind("<<TreeviewSelect>>",callback);return frame,tree
class LandmarkAnnotationSurface:
 def __init__(self,parent,adapter,canvas=None,marker_radius=POINT_RADIUS,display_settings=None):
  self.adapter=adapter;self.canvas=canvas or tk.Canvas(parent,bg="#262626",highlightthickness=0);self.owns_canvas=canvas is None;self.zoom=1.;self.pan=[0.,0.];self.dragging=None;self.drag_pending=None;self.right_anchor=None;self.photo=None;self._photo_key=None;self.highlight_ids=set()
  settings=normalize_display_settings(display_settings or {"size":marker_radius});self.display_settings=settings;self.marker_radius=settings["size"]
  self.canvas.bind("<Button-1>",self.left_down);self.canvas.bind("<B1-Motion>",self.left_drag);self.canvas.bind("<ButtonRelease-1>",self.left_up);self.canvas.bind("<Button-3>",self.right_down);self.canvas.bind("<B3-Motion>",self.right_drag);self.canvas.bind("<MouseWheel>",self.wheel);self.canvas.bind("<Configure>",lambda _e:self.render())
 def load(self,image,schema,points,current=None,highlight_ids=None):self.image=image;self.schema=tuple(schema);self.points=dict(points);self.highlight_ids={int(value) for value in (highlight_ids or ())};self.current=current or self._next() or self.schema[0]["id"];self.zoom=min(1.,FIT_WIDTH/image.width,FIT_HEIGHT/image.height);self.pan=[0.,0.];self._photo_key=None;self.dragging=self.drag_pending=None;self.render();self.adapter.selected(self.current)
 def set_display_settings(self,value):
  self.display_settings=normalize_display_settings(value);self.marker_radius=self.display_settings["size"];self.render()
 def set_marker_size(self,value):
  settings=dict(self.display_settings);settings["size"]=value;self.set_display_settings(settings)
 def image_point(self,x,y):return ((x-self.pan[0])/self.zoom,(y-self.pan[1])/self.zoom)
 def screen_point(self,x,y):return (self.pan[0]+x*self.zoom,self.pan[1]+y*self.zoom)
 def _next(self):return next((r["id"] for r in self.schema if r["id"] not in self.points),None)
 def render(self):
  if not hasattr(self,"image"):return
  size=(max(1,round(self.image.width*self.zoom)),max(1,round(self.image.height*self.zoom)));key=(id(self.image),size)
  if key!=self._photo_key:
   self.photo=ImageTk.PhotoImage(self.image.resize(size),master=self.canvas);self._photo_key=key
  self.canvas.delete("all");self.canvas.create_image(*self.pan,anchor="nw",image=self.photo)
  for ident,p in self.points.items():
   if p.get("state")!="present":continue
   x,y=self.screen_point(p["x"],p["y"]);selected=ident==self.current;highlighted=int(ident) in self.highlight_ids;settings=self.display_settings;color=settings["selected_color"] if selected or highlighted else settings["other_color"];r=settings["size"]
   if highlighted:self.canvas.create_oval(x-r-6,y-r-6,x+r+6,y+r+6,outline=settings["selected_color"],width=3)
   draw_marker(self.canvas,x,y,color=color,size=r,symbol=settings["symbol"],halo=settings["halo"])
   draw_label(self.canvas,x+r+3,y-r-3,text=label_text(self.schema,ident,settings["label"]),color=color,font_size=settings["label_size"],halo=settings["halo"])
  self.adapter.redrawn(self.current)
 def hit_test(self,event):
  hits=[]
  for ident,p in self.points.items():
   if p.get("state")!="present":continue
   x,y=self.screen_point(p["x"],p["y"]);d=((event.x-x)**2+(event.y-y)**2)**.5
   if d<=max(12,self.marker_radius*2+2):hits.append((d,ident))
  return min(hits)[1] if hits else None
 def left_down(self,e):
  hit=self.hit_test(e)
  if hit is not None:
   self.current=hit;self.dragging=hit
   point=self.points.get(hit) or {};self.drag_pending=(point.get("x"),point.get("y"))
   self.adapter.selected(hit);self.render();return
  ident=self._next()
  if ident is None:return
  self.current=ident;x,y=self.image_point(e.x,e.y);self.adapter.place(ident,x,y);self.points=self.adapter.points();self.current=self._next() or ident;self.adapter.selected(self.current);self.render()
 def left_drag(self,e):
  if self.dragging is None:return
  x,y=self.image_point(e.x,e.y);self.drag_pending=(x,y)
  point=dict(self.points.get(self.dragging) or {});point.update({"landmark_id":self.dragging,"state":"present","x":x,"y":y});self.points[self.dragging]=point
  self.render()
 def left_up(self,_e):
  if self.dragging is None:return
  ident,pending=self.dragging,self.drag_pending;self.dragging=self.drag_pending=None
  if pending is not None:self.adapter.place(ident,*pending)
  self.points=self.adapter.points();self.adapter.finish_drag(ident);self.render()
 def right_down(self,e):self.right_anchor=(e.x,e.y)
 def right_drag(self,e):
  if self.right_anchor:self.pan[0]+=e.x-self.right_anchor[0];self.pan[1]+=e.y-self.right_anchor[1];self.right_anchor=(e.x,e.y);self.render()
 def wheel(self,e):
  old=self.zoom;self.zoom=max(.05,min(4.,old*(1.15 if e.delta>0 else 1/1.15)));self.pan[0]=e.x-(e.x-self.pan[0])*self.zoom/old;self.pan[1]=e.y-(e.y-self.pan[1])*self.zoom/old;self.render()
 def current_is_missing(self):
  point=self.points.get(self.current) or {};return point.get("state")=="missing"
 def toggle_missing(self):
  ident=self.current
  if self.current_is_missing():
   if hasattr(self.adapter,'unmark_missing'):self.adapter.unmark_missing(ident)
   else:self.adapter.remove(ident)
   self.points=self.adapter.points();self.current=ident
  else:
   self.adapter.missing(ident);self.points=self.adapter.points();self.current=self._next() or ident
  self.adapter.selected(self.current);self.render()
 def missing(self):return self.toggle_missing()
 def remove(self):self.adapter.remove(self.current);self.points=self.adapter.points();self.adapter.selected(self.current);self.render()
 def clear_all(self):self.adapter.clear_all();self.points=self.adapter.points();self.current=self._next() or self.current;self.adapter.selected(self.current);self.render()
class RepeatSessionAdapter:
 def __init__(self,project,session_id,header,before_edit=None,after_edit=None):
  self.project=project;self.session_id=session_id;self.header=header;self.before_edit=before_edit or (lambda:None);self.after_edit=after_edit or (lambda:None);self.on_selected=lambda _id:None;self.on_redrawn=lambda _id:None
 def points(self):
  from .operator_qc import _load
  return {p["landmark_id"]:p for p in _load(self.project,self.session_id)["repeat"]}
 def _edit(self,operation):
  self.before_edit();operation();self.after_edit()
 def place(self,i,x,y):
  from .operator_qc import set_repeat_landmark
  self._edit(lambda:set_repeat_landmark(self.project,self.session_id,i,x,y))
 def remove(self,i):
  from .operator_qc import remove_repeat_landmark
  self._edit(lambda:remove_repeat_landmark(self.project,self.session_id,i))
 def clear_all(self):
  from .operator_qc import clear_repeat_landmarks
  self._edit(lambda:clear_repeat_landmarks(self.project,self.session_id))
 def unmark_missing(self,i):
  from .operator_qc import unmark_repeat_landmark
  result={'restored':False}
  self._edit(lambda:result.update(restored=unmark_repeat_landmark(self.project,self.session_id,i)))
  return result['restored']
 def missing(self,i):
  from .operator_qc import set_repeat_landmark
  self._edit(lambda:set_repeat_landmark(self.project,self.session_id,i,None,None,state="missing"))
 def finish_drag(self,_i):pass
 def selected(self,i):self.on_selected(i)
 def redrawn(self,i):self.on_redrawn(i)