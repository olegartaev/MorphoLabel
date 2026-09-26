import shutil,tempfile,unittest
from pathlib import Path
from app.project_storage import Project
from tests.current_fixtures import make_reviewed_crop

class AnnotationControlsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());self.src=self.tmp/"src"
  for loc in ("A","B"):
   (self.src/loc/"orig").mkdir(parents=True)
  for name in ("img_10.nef","img_2.jpg","img_1.tiff"):(self.src/"A"/"orig"/name).write_bytes(b"x")
  (self.src/"B"/"orig"/"img_1.nef").write_bytes(b"x")
  schema=self.tmp/"schema.csv";schema.write_text("id,abbr,name\n1,A,A\n2,B,B\n3,C,C\n")
  self.p=Project.create("p",self.src,self.tmp,schema,source_layout="subfolder",source_image_subfolder="orig");self.rows=self.p.catalog_rows();self.a=self.rows[0]["image_id"];make_reviewed_crop(self.p,self.a,80,60)
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def fill(self):
  for ident in (1,2,3):self.p.save_landmark(self.a,ident,ident,ident,"manual")
 def test_red_yellow_green_and_reset_after_change(self):
  self.p.save_landmark(self.a,1,1,1,"auto",provenance="machine");self.assertEqual(self.p.annotation_status(self.a)["color"],"red")
  for ident in (1,2,3):self.p.save_landmark(self.a,ident,ident,ident,"auto",provenance="machine")
  self.assertEqual(self.p.annotation_status(self.a)["color"],"yellow")
  self.p.mark_checked(self.a);self.assertEqual(self.p.annotation_status(self.a)["color"],"green")
  self.p.save_landmark(self.a,1,10,10,"auto",provenance="machine");self.assertEqual(self.p.annotation_status(self.a)["color"],"yellow")
  self.p.replace_landmarks(self.a,{"1":{"x_standardized":1,"y_standardized":1,"state":"manual"}});self.assertEqual(self.p.annotation_status(self.a)["color"],"red")
 def test_all_human_points_are_green_without_checked(self):
  self.fill();self.assertEqual(self.p.annotation_status(self.a)["color"],"green")
 def test_partially_corrected_machine_set_stays_yellow_until_all_human(self):
  for ident in (1,2,3):self.p.save_landmark(self.a,ident,ident,ident,"auto",provenance="machine")
  self.p.save_landmark(self.a,1,1,1,"corrected",provenance="corrected_by_human");self.assertEqual(self.p.annotation_status(self.a)["color"],"yellow")
  for ident in (2,3):self.p.save_landmark(self.a,ident,ident,ident,"corrected",provenance="corrected_by_human")
  self.assertEqual(self.p.annotation_status(self.a)["color"],"green")
  self.p.replace_landmarks(self.a,{"1":{"x_standardized":1,"y_standardized":1,"state":"manual"}});self.assertEqual(self.p.annotation_status(self.a)["color"],"red")
 def test_restart_calibration_and_attributes(self):
  self.fill();self.p.mark_checked(self.a);self.p.set_locality_calibration("A",self.a,12.3,"mm",{"pixels_per_mm":12.3});self.p.set_attribute(self.a,"sex","female")
  (self.p.root/"attributes.csv").write_text("key,label,values\nsex,Sex,unknown|male|female\n")
  reopened=Project.open(self.p.root);self.assertEqual(reopened.annotation_status(self.a)["color"],"green");self.assertEqual(reopened.locality_calibration("A")["scale"],12.3);self.assertIsNone(reopened.locality_calibration("B"));self.assertEqual(reopened.attributes_for_image(self.a)["sex"],"female");self.assertEqual(reopened.attributes_schema()[0]["key"],"sex")
 def test_natural_indexes_and_schema_count(self):
  a=[r for r in self.rows if r["locality"]=="A"];self.assertEqual([r["original_name"] for r in a],["img_1.tiff","img_2.jpg","img_10.nef"]);self.assertEqual([(r["index_in_locality"],r["total_in_locality"]) for r in a],[(1,3),(2,3),(3,3)]);self.assertEqual(self.p.expected_landmarks(),3)

 def _eighteen(self):
  schema=self.tmp/"schema18.csv";schema.write_text("id,abbr,name\n"+"\n".join(f"{i},P{i},Point {i}" for i in range(1,19)))
  p=Project.create("p18",self.src,self.tmp,schema,source_layout="subfolder",source_image_subfolder="orig");make_reviewed_crop(p,p.catalog_rows()[0]["image_id"],80,60);return p
 def test_completeness_uses_schema_ids_and_reports_extras(self):
  p=self._eighteen(); rows=p.catalog_rows(); image_id=rows[0]["image_id"]
  with p.transaction() as c:
   for ident in range(19,25):c.execute("INSERT INTO landmark_schema(landmark_id,abbr,name) VALUES (?,?,?)",(ident,f"P{ident}",f"Legacy {ident}"))
  for ident in range(1,25):p.save_landmark(image_id,ident,ident,ident,"manual")
  status=p.annotation_status(image_id)
  self.assertEqual(status["expected"],18);self.assertEqual(status["placed"],18);self.assertEqual(status["missing_ids"],[]);self.assertEqual(status["extra_ids"],[]);self.assertEqual(status["color"],"green")
  row=p.catalog_rows()[0];self.assertEqual(row["status_image_id"],image_id);self.assertEqual(row["extra_ids"],[])
 def test_explicit_missing_is_distinct_from_unplaced(self):
  p=self._eighteen();image_id=p.catalog_rows()[0]["image_id"]
  p.save_landmark(image_id,1,1,1,"manual")
  p.save_landmark(image_id,2,None,None,"missing")
  status=p.annotation_status(image_id);self.assertNotIn(2,status["missing_ids"]);self.assertIn(2,status["explicitly_missing_ids"])
  self.assertEqual(status["color"],"red")

 def test_manual_missing_resolves_and_checked_accepts_it(self):
  p=self._eighteen();image_id=p.catalog_rows()[0]["image_id"]
  for ident in range(1,18):p.save_landmark(image_id,ident,ident,ident,"manual")
  status=p.annotation_status(image_id);self.assertEqual(status["resolved"],17);self.assertEqual(status["color"],"red")
  with self.assertRaises(ValueError):p.mark_checked(image_id)
  p.save_landmark(image_id,18,None,None,"missing",provenance="manual")
  status=p.annotation_status(image_id);self.assertEqual(status["resolved"],18);self.assertEqual(status["missing_ids"],[]);self.assertEqual(status["explicitly_missing_ids"],[18]);self.assertEqual(status["color"],"green")
  p.mark_checked(image_id);self.assertTrue(p.annotation_status(image_id)["verified"])
 def test_machine_with_manual_missing_is_yellow_then_green_after_checked(self):
  p=self._eighteen();image_id=p.catalog_rows()[0]["image_id"]
  for ident in range(1,18):p.save_landmark(image_id,ident,ident,ident,"auto",provenance="machine")
  p.save_landmark(image_id,18,None,None,"missing",provenance="manual")
  self.assertEqual(p.annotation_status(image_id)["color"],"yellow");p.mark_checked(image_id);self.assertEqual(p.annotation_status(image_id)["color"],"green")
 def test_coordinate_replaces_missing_and_remove_returns_unresolved(self):
  p=self._eighteen();image_id=p.catalog_rows()[0]["image_id"]
  for ident in range(1,18):p.save_landmark(image_id,ident,ident,ident,"manual")
  p.save_landmark(image_id,18,None,None,"missing",provenance="manual");p.save_landmark(image_id,18,18,18,"manual")
  state=p.annotation_status(image_id);self.assertEqual(state["explicitly_missing_ids"],[]);self.assertEqual(state["color"],"green")
  p.replace_landmarks(image_id,{str(i):{"x_standardized":i,"y_standardized":i,"state":"manual","provenance":"manual"} for i in range(1,18)})
  state=p.annotation_status(image_id);self.assertIn(18,state["missing_ids"]);self.assertEqual(state["color"],"red")
if __name__=="__main__":unittest.main()
