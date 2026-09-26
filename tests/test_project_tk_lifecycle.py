import unittest
import tkinter as tk
from PIL import Image, ImageTk

class ProjectTkLifecycleTests(unittest.TestCase):
 def test_explicit_master_survives_manager_destroy(self):
  try:
   manager = tk.Tk(); manager.withdraw()
  except tk.TclError as exc:
   self.skipTest(f"Tk display unavailable: {exc}")
  editor = tk.Tk(); editor.withdraw()
  canvas = tk.Canvas(editor, width=10, height=10); canvas.pack()
  manager.destroy()
  try:
   photo = ImageTk.PhotoImage(Image.new("RGB", (2, 2), "black"), master=canvas)
   canvas.create_image(0, 0, image=photo)
   self.assertIsNotNone(photo)
  finally:
   editor.destroy()

if __name__ == "__main__": unittest.main()
