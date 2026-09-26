import csv,shutil,tempfile,unittest
from pathlib import Path
from app.project_storage import Project
from app.results_export import parse_tps

class ResultsExportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());self.raw=self.tmp/"raw";(self.raw/"A").mkdir(parents=True);(self.raw/"A"/"one.jpg").write_bytes(b"one");(self.raw/"A"/"two.jpg").write_bytes(b"two")
  schema=self.tmp/"schema.csv";schema.write_text("id,abbr,name\n"+"\n".join(f"{i},P{i},Point {i}" for i in range(1,19)),encoding="utf-8")
  self.project=Project.create("p",self.raw,self.tmp,schema,source_layout="direct");self.rows=self.project.catalog_rows();self.ready=self.rows[0];self.incomplete=self.rows[1]
  for ident in range(1,18):self.project.save_landmark(self.ready["image_id"],ident,ident+0.25,ident+0.5,"manual")
  self.project.save_landmark(self.ready["image_id"],18,None,None,"missing",provenance="manual")
  self.project.set_locality_calibration("A",self.ready["image_id"],10.,"mm",{"pixels_per_mm":10.})
  (self.project.root/"attributes.csv").write_text("key,label,values\nsex,Sex,unknown|male|female\nage,Age,juvenile|adult\n",encoding="utf-8");self.project.set_attribute(self.ready["image_id"],"sex","female")
 def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
 def test_new_project_layout_is_simple(self):
  self.assertTrue((self.project.data_root/"project.sqlite").exists());self.assertTrue((self.project.cache_root/"developed").is_dir());self.assertTrue((self.project.results_root).is_dir());self.assertFalse((self.project.root/"project.sqlite").exists())
 def test_tps_csv_order_missing_and_rebuild(self):
  out=self.project.sync_results();self.assertEqual(set(p.name for p in self.project.results_root.iterdir()),{"landmarks.tps","specimens.csv"})
  blocks=parse_tps(out["tps"]);self.assertEqual(len(blocks),1);block=blocks[0];self.assertEqual(len(block["coordinates"]),18);self.assertEqual(block["coordinates"][0],(1.25,1.5));self.assertEqual(block["coordinates"][-1],(-1.0,-1.0));self.assertEqual(block["IMAGE"],self.ready["original_name"]);self.assertEqual(block["ID"],self.ready["image_id"]);self.assertEqual(block["SCALE"],"0.1")
  rows=list(csv.DictReader(out["specimens"].open(encoding="ascii")));self.assertEqual(len(rows),2);ready=next(r for r in rows if r["image_id"]==self.ready["image_id"]);self.assertEqual((ready["locality"],ready["filename"],ready["skipped"],ready["calibration_mm_per_px"],ready["sex"]),("A","one.jpg","1","0.1","female"))
  out["tps"].unlink();self.assertFalse(out["tps"].exists());self.project.sync_results();self.assertEqual(len(parse_tps(out["tps"])),1)
  self.project.sync_results();self.assertEqual(set(p.name for p in self.project.results_root.iterdir()),{"landmarks.tps","specimens.csv"})
 def test_ui_state_survives_reopen(self):
  self.project.set_ui_state("photo_landmark_sash",321);self.assertEqual(Project.open(self.project.root).get_ui_state("photo_landmark_sash"),321)

if __name__=="__main__":unittest.main()
