import unittest
from pathlib import Path

class GuiRegressionSourceTests(unittest.TestCase):
 def test_photo_scrollbar_has_dedicated_frame(self):
  text=Path("app/editor_ready.py").read_text(encoding="utf-8")
  self.assertIn("photo_list_frame",text);self.assertIn("self.photo_scrollbar=ttk.Scrollbar(self.photo_list_frame",text)
 def test_main_editor_uses_tagged_image_not_delete_all(self):
  text=Path("app/editor_ready_v11.py").read_text(encoding="utf-8")
  self.assertIn('create_image(*self.pan, anchor="nw", image=self.photo, tags=("image",))',text);self.assertNotIn('self.canvas.delete("all")',text)

 def test_left_column_uses_resizable_photo_landmark_splitter(self):
  text=Path("app/editor_ready.py").read_text(encoding="utf-8")
  self.assertIn("self.left_split=tk.PanedWindow",text);self.assertIn("self.left_split.add(self.photo_pane,minsize=140)",text);self.assertIn("self.left_split.add(self.landmark_pane,minsize=220)",text)
 def test_landmark_list_has_its_own_scrollbar(self):
  text=Path("app/editor_ready.py").read_text(encoding="utf-8")
  self.assertIn("self.landmark_scrollbar=ttk.Scrollbar(self.landmark_list_frame",text);self.assertIn("yscrollcommand=self.landmark_scrollbar.set",text)
 def test_crop_training_progress_uses_explicit_dialog_master_and_gui_queue(self):
  text=Path("app/editor_ready_v15.py").read_text(encoding="utf-8")
  self.assertIn('tk.StringVar(master=dialog',text)
  self.assertIn('queue.Queue()',text)
  self.assertIn('"Selecting images..."',text)
  self.assertIn('"Opening crop editor..."',text)
if __name__=="__main__":unittest.main()


class GuiCanvasRuntimeTests(unittest.TestCase):
 def setUp(self):
  import tkinter as tk
  try:
   self.root=tk.Tk();self.root.withdraw()
  except tk.TclError as exc:
   self.skipTest(f"Tk display unavailable: {exc}")
 def tearDown(self):
  self.root.destroy()
 def test_landmark_overlay_count_is_stable_after_fifty_redraws(self):
  import tkinter as tk
  canvas=tk.Canvas(self.root,width=400,height=300);canvas.pack()
  for _ in range(50):
   canvas.delete("landmark_overlay")
   for point_id in (1,2,3):
    tags=("landmark_overlay","landmark_handle",f"landmark:{point_id}")
    canvas.create_oval(point_id*20,20,point_id*20+10,30,tags=tags)
    canvas.create_text(point_id*20+12,20,text=str(point_id),tags=("landmark_overlay","landmark_label",f"landmark:{point_id}"))
  self.assertEqual(len(canvas.find_withtag("landmark_overlay")),6)
  self.assertEqual(len(canvas.find_withtag("landmark:2")),2)
 def test_virtual_photo_list_uses_right_hand_colored_canvas_circle(self):
  from app.photo_list import PhotoListCanvas
  from tkinter import ttk
  frame=ttk.Frame(self.root);frame.pack(fill="both",expand=True)
  photos=PhotoListCanvas(frame,width=300,height=90,bg="white");photos.pack(side="left",fill="both",expand=True)
  scroll=ttk.Scrollbar(frame,orient="vertical",command=photos.yview);scroll.pack(side="right",fill="y");photos.configure(yscrollcommand=scroll.set)
  photos.set_rows([{"number":str(i+1),"cal":"C" if i==0 else "","text":f"L | image_{i}.nef ({i+1} | 20)","status":("red","yellow","green")[i%3]} for i in range(20)])
  self.root.update_idletasks();photos.selection_set(12);photos.see(12);self.root.update()
  self.assertEqual(scroll.master,frame)
  self.assertEqual(scroll.winfo_height(),photos.winfo_height())
  self.assertEqual(photos.curselection(),(12,))
  fills={photos.itemcget(i,"fill") for i in photos.find_withtag("photo_list_render") if photos.type(i)=="oval"}
  self.assertTrue(fills & {"#d93025","#e6a700","#188038"})
 def test_virtual_photo_list_draws_crop_square_and_excluded_cross(self):
  from app.photo_list import PhotoListCanvas
  photos=PhotoListCanvas(self.root,width=300,height=60,bg="white");photos.pack()
  photos.set_rows([{"number":"1","has_crop":True,"text":"A | crop.nef (1 | 2)","status":"green"},{"number":"2","excluded":True,"text":"A | excluded.nef (2 | 2)","status":"excluded","tooltip":"Excluded: Bent specimen"}])
  self.root.update()
  rectangles=[item for item in photos.find_withtag("photo_list_render") if photos.type(item)=="rectangle"]
  texts=[photos.itemcget(item,"text") for item in photos.find_withtag("photo_list_render") if photos.type(item)=="text"]
  self.assertTrue(rectangles);self.assertIn("×",texts)
