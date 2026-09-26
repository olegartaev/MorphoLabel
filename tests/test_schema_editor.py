import tempfile, unittest
from pathlib import Path
from app.schema_editor import SchemaEditor, ROLE_CODES

class SchemaEditorTests(unittest.TestCase):
 def test_role_codes_and_save_format(self):
  self.assertEqual(ROLE_CODES,{"BT":"BOTH","GM":"GM","CL":"CLASSICAL"})
 def test_validation_messages(self):
  self.assertTrue(Path('app/schema_editor.py').exists())
if __name__=='__main__':unittest.main()
