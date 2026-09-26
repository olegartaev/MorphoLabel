from pathlib import Path
import tempfile, time, unittest
from app.project_storage import Project, load_schema, schema_file_signature
from app.profile import load_schema_profile

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
if __name__=='__main__': unittest.main()
