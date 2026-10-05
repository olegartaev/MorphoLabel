"""Vector explanation of counted elements and anatomical reference roles."""
import tkinter as tk
from tkinter import ttk


class AnatomicalGuide(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,width=420,height=248,bg="#f5f9fc",highlightthickness=1,highlightbackground="#d4e1eb")
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",self._draw)

    def _draw(self,event):
        c=self.canvas;c.delete("all");w=max(320,event.width);ink="#20374b";muted="#52697b"
        c.create_text(16,16,anchor="nw",text="How the marks work",font=("Segoe UI",11,"bold"),fill=ink)
        c.create_text(16,42,anchor="nw",text="Example only · choose boundaries for your study",font=("Segoe UI",9),fill=muted)
        left=42;right=w-35;y=97;step=(right-left)/7
        c.create_line(left-18,y,right+10,y,fill="#acbdcb",width=2)
        for i in range(8):
            x=left+i*step
            c.create_line(x,y-7,x+7,y-23,fill="#acbdcb",width=2)
            c.create_line(x,y+7,x+7,y+22,fill="#acbdcb",width=2)
            c.create_oval(x-6,y-6,x+6,y+6,fill="#1976e9",outline="white",width=2)
            c.create_text(x,y-34,text=str(i+1),fill=muted,font=("Segoe UI",8))
        boundary=left+5*step
        c.create_polygon(boundary-9,y+14,boundary+9,y+14,boundary,y+2,fill="#20a447",outline="white")
        c.create_line(boundary,y+25,boundary,y+37,fill="#20a447",width=2)
        c.create_text(boundary,y+46,text="Boundary on element 6",fill="#23733c",font=("Segoe UI",9))
        c.create_line(16,164,w-16,164,fill="#d4e1eb")
        instructions=(
            ("1", "Elements", "Click each element once.", "#1976e9"),
            ("2", "Reference", "Tag a counted point, or place a separate mark.", "#20a447"),
            ("3", "Trait", "All = 8   ·   Before = 5   ·   From = 3", "#b76a17"),
        )
        for i,(number,title,copy,color) in enumerate(instructions):
            yy=183+i*24
            c.create_oval(16,yy-8,32,yy+8,fill=color,outline="")
            c.create_text(24,yy,text=number,fill="white",font=("Segoe UI",8,"bold"))
            c.create_text(40,yy,text=title,anchor="w",fill=ink,font=("Segoe UI",9,"bold"))
            c.create_text(108,yy,text=copy,anchor="w",fill=muted,font=("Segoe UI",9),width=w-124)
