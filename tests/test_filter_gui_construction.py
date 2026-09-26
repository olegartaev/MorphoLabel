import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from PIL import Image

from app.editor_ready_v15 import ReadyEditorV15
from app.project_storage import Project


class FilterGuiConstructionTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="simm_filter_gui_"))
        source = self.temp / "source"
        source.mkdir()
        Image.new("RGB", (240, 160), (40, 50, 60)).save(source / "fish.jpg")
        schema = self.temp / "schema.csv"
        schema.write_text("id,abbr,name,role\n" + "\n".join(f"{i},L{i},Landmark {i},BOTH" for i in range(1, 26)) + "\n", encoding="utf-8")
        self.project = Project.create("project", source, self.temp, schema, source_layout="direct")
        row = self.project.catalog_rows()[0]
        cache = self.project.cache_root / "standardized" / f"{row['image_id']}.png"
        cache.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (240, 160), (40, 50, 60)).save(cache)
        try:
            self.editor = ReadyEditorV15(project=self.project)
            self.editor.geometry("900x700")
            self.editor.update_idletasks()
            self.editor.update()
        except tk.TclError as exc:
            self.skipTest(str(exc))

    def tearDown(self):
        if hasattr(self, "editor"):
            try:
                self.editor.destroy()
            except tk.TclError:
                pass
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_filter_row_is_real_and_mapped_above_photo_list(self):
        bar = self.editor.photo_filter_bar
        widgets = bar.winfo_children()
        entries = [widget for widget in widgets if isinstance(widget, tk.Entry) or widget.winfo_class() == "TEntry"]
        clear = [widget for widget in widgets if str(widget.cget("text")) == "×"]
        self.assertEqual(2, len(entries))
        self.assertEqual(1, len(clear))
        self.assertTrue(bar.winfo_ismapped())
        self.assertTrue(all(widget.winfo_ismapped() and widget.winfo_manager() in {"pack", "grid"} for widget in entries + clear))
        self.assertLess(bar.winfo_y(), self.editor.photo_list_frame.winfo_y())
        self.assertEqual("pack", bar.winfo_manager())


if __name__ == "__main__":
    unittest.main()