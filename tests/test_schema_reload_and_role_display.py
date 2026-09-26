from pathlib import Path
import tempfile, time, unittest
from types import SimpleNamespace
from app.project_storage import Project, load_schema, schema_file_signature
from app.profile import load_schema_profile
from app.editor_ready_v15 import ReadyEditorV15

class SchemaReloadRoleDisplayTests(unittest.TestCase):
 def test_project_schema_cache_reload_and_invalid_fallback(self):
  root=Path(tempfile.mkdtemp()); path=root/'landmark_schema.csv'
  path.write_text('id,abbr,name,role\n1,A,Alpha,BOTH\n',encoding='utf-8')
  project=Project(root); project._schema_cache=load_schema(path); project._schema_cache_signature=schema_file_signature(path)
  first=project.schema; self.assertIs(project.schema,first)
  time.sleep(0.01); path.write_text('id,abbr,name,role\n1,A,Renamed,GM\n',encoding='utf-8')
  changed=project.schema; self.assertEqual(changed[0]['name'],'Renamed'); self.assertEqual(changed[0]['role'],'GM')
  time.sleep(0.01); path.write_text('id,abbr,name,role\n1,A,Broken,INVALID\n',encoding='utf-8')
  self.assertEqual(project.schema[0]['name'],'Renamed')
 def test_compact_role_codes(self):
  editor=ReadyEditorV15.__new__(ReadyEditorV15)
  state=SimpleNamespace(present_ids={1},explicitly_missing_ids=set())
  for role,code in (("BOTH","BT"),("GM","GM"),("CLASSICAL","CL")):
   point=SimpleNamespace(number=1,code='A',name='Alpha',role=role)
   marker,text=editor._landmark_row_text(point,state)
   self.assertIn(f'{marker} {code} 1 A — Alpha',text); self.assertNotIn('[',text)
if __name__=='__main__': unittest.main()
