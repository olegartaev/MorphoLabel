from pathlib import Path
import csv, tempfile, unittest
from collections import Counter
from app.profile import load_schema_profile, read_schema_csv

class SchemaDelimiterTests(unittest.TestCase):
 def make(self,delimiter,bom=False):
  rows=[['id','abbr','name','role'],['1','A','Alpha','BOTH'],['2','B','Beta','gm'],['3','C','Gamma','Classical']]
  text='\n'.join(delimiter.join(row) for row in rows)+'\n# trailing comment\n'
  path=Path(tempfile.mkdtemp())/'schema.csv';path.write_text(text,encoding='utf-8-sig' if bom else 'utf-8');return path
 def test_supported_delimiters_and_bom(self):
  for delimiter in [',',';','\t','|']:
   for bom in [False,True]:
    path=self.make(delimiter,bom); detected,_,_=read_schema_csv(path); profile=load_schema_profile(path)
    self.assertEqual(detected,delimiter);self.assertEqual([x.role for x in profile.landmarks],['BOTH','GM','CLASSICAL'])
 def test_comments_before_inside_after(self):
  path=Path(tempfile.mkdtemp())/'schema.csv';path.write_text('# before\nid;abbr;name;role\n1;A;Alpha;BOTH\n# inside\n2;B;Beta;GM\n# after\n',encoding='utf-8')
  self.assertEqual(len(load_schema_profile(path).landmarks),2)
 def test_real_phoxinus_schema(self):
  path=Path(__file__).resolve().parents[1]/'landmark_schema.csv';profile=load_schema_profile(path)
  self.assertEqual(len(profile.landmarks),25);self.assertEqual(Counter(x.role for x in profile.landmarks),Counter({'BOTH':20,'CLASSICAL':5}))
if __name__=='__main__':unittest.main()
