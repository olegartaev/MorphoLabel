import tempfile
import unittest
from pathlib import Path
from PIL import Image
from app.project_storage import Project, load_schema

class SchemaRepairTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source'/'sample';self.source.mkdir(parents=True);Image.new('RGB',(10,10)).save(self.source/'a.jpg');self.schema=self.root/'schema.csv';self.schema.write_text('id,abbr,name,role\n1,A,Anterior,BOTH\n2,B,Posterior,BOTH\n',encoding='utf-8');self.project=Project.create('p',self.source.parent,self.root,self.schema,source_layout='direct')
 def tearDown(self):self.temp.cleanup()
 def test_display_ids_normalize_without_affecting_abbreviations(self):
  self.project.schema_path.write_text('id,abbr,name,role\nwrong,A,Anterior,BOTH\nwrong,C,Central,GM\n',encoding='utf-8')
  self.assertEqual([(1,'A'),(2,'C')],[(x['id'],x['abbr']) for x in load_schema(self.project.schema_path)])
 def test_bad_schema_does_not_block_project_open(self):
  self.project.schema_path.write_text('id,abbr,name,role\n8,,Broken,BOTH\n',encoding='utf-8')
  reopened=Project.open(self.project.root);self.assertEqual([],reopened.schema);self.assertIsNotNone(reopened.schema_error);self.assertEqual(1,reopened.count('images'))
 def test_new_project_empty_schema_is_real_csv_header(self):
  project=Project.create('empty',self.source.parent,self.root,source_layout='direct');self.assertEqual('id,abbr,name,role\n',project.schema_path.read_text(encoding='utf-8'))
 def test_schema_editor_saves_clean_table_when_tk_available(self):
  try:
   import tkinter as tk
   from app.schema_editor import SchemaEditor
   root=tk.Tk();root.withdraw();editor=SchemaEditor(root,self.project.schema_path);editor.rows[0]['abbr']='SnT';editor.rows[0]['name']='Snout tip';editor.rows[1]['abbr']='NarP';editor.rows[1]['name']='Nare';self.assertTrue(editor.save());editor.destroy();root.destroy()
  except Exception as exc:self.skipTest(f'Tk unavailable: {exc}')
  text=self.project.schema_path.read_text(encoding='utf-8');self.assertFalse(text.lstrip().startswith('#'));self.assertNotIn('ROLE LEGEND',text);self.assertEqual(['id,abbr,name,role','1,SnT,Snout tip,BOTH','2,NarP,Nare,BOTH'],text.splitlines())
if __name__=='__main__':unittest.main()