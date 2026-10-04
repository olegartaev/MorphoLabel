import tempfile, unittest
from pathlib import Path
from app.schema_editor import SchemaEditor, ROLE_CODES

class SchemaEditorTests(unittest.TestCase):
 def test_role_codes_and_save_format(self):
  self.assertEqual(ROLE_CODES,{"BT":"BOTH","GM":"GM","CL":"CLASSICAL"})
 def test_validation_messages(self):
  self.assertTrue(Path('app/schema_editor.py').exists())
 def test_morphometry_role_opens_from_single_press(self):
  source=Path('app/schema_editor.py').read_text(encoding='utf-8')
  self.assertIn('self.table.bind("<ButtonPress-1>",self.table_press)',source)
  self.assertIn('if rowid and col=="#2":',source)
  self.assertIn('menu.tk_popup(event.x_root,event.y_root)',source)
  self.assertIn('def _set_role',source)
if __name__=='__main__':unittest.main()
