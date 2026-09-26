import shutil,tempfile,unittest
from pathlib import Path
from app.project_storage import Project

class LayoutCatalogTests(unittest.TestCase):
 def test_mixed_formats_locality_sort_and_exclusions(self):
  root=Path(tempfile.mkdtemp()); src=root/"src"; (src/"loc_A"/"orig").mkdir(parents=True); (src/"loc_A"/"png").mkdir(); (src/"_Points").mkdir()
  for name in ("img_10.nef","img_2.jpg","img_1.tiff"): (src/"loc_A"/"orig"/name).write_bytes(b"x")
  (src/"loc_A"/"png"/"derived.png").write_bytes(b"x"); (src/"_Points"/"v.1.png").write_bytes(b"x")
  schema=root/"schema.csv";schema.write_text("id,abbr,name\n1,A,Alpha\n")
  try:
   p=Project.create("p",src,root,schema,source_image_subfolder="orig",source_layout="subfolder"); rows=p.catalog_candidates()[0]
   self.assertEqual([r["path"] for r in rows],["loc_A/orig/img_1.tiff","loc_A/orig/img_2.jpg","loc_A/orig/img_10.nef"])
   self.assertEqual([(r["index_in_locality"],r["total_in_locality"]) for r in rows],[(1,3),(2,3),(3,3)])
   ids=[r["path"] for r in rows];self.assertEqual(p.count("images"),3);self.assertEqual(len(set(ids)),3)
   self.assertEqual(len(p.catalog_candidates()[1]),2)
  finally: shutil.rmtree(root,ignore_errors=True)
if __name__=="__main__":unittest.main()
