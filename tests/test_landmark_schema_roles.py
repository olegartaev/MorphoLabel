import tempfile
import unittest
from pathlib import Path

from app.profile import get_landmarks_for_classical,get_landmarks_for_gm,load_schema_profile
from app.project_storage import load_schema

class LandmarkSchemaRoleTests(unittest.TestCase):
 def schema(self,text):
  path=Path(tempfile.mkdtemp())/'schema.csv';path.write_text(text,encoding='utf-8');return path
 def test_old_schema_defaults_both(self):
  profile=load_schema_profile(self.schema('id,abbr,name\n1,A,Alpha\n2,B,Beta\n'))
  self.assertEqual([p.role for p in profile.landmarks],['BOTH','BOTH'])
 def test_roles_and_filters(self):
  profile=load_schema_profile(self.schema('id,abbr,name,role\n1,A,Alpha,classical\n2,B,Beta,GM\n3,C,Gamma,BOTH\n'))
  self.assertEqual([p.role for p in profile.landmarks],['CLASSICAL','GM','BOTH'])
  self.assertEqual([p.number for p in get_landmarks_for_classical(profile)],[1,3])
  self.assertEqual([p.number for p in get_landmarks_for_gm(profile)],[2,3])
 def test_invalid_role_reports_row(self):
  with self.assertRaisesRegex(ValueError,r'row 3.*invalid role'):
   load_schema(self.schema('id,abbr,name,role\n1,A,Alpha,BOTH\n2,B,Beta,other\n'))
 def test_current_schema_has_25_both(self):
  rows=load_schema(Path('landmark_schema.csv'))
  self.assertEqual(len(rows),25);self.assertTrue(all(row['role'] in {'CLASSICAL','GM','BOTH'} for row in rows))
if __name__=='__main__': unittest.main()
