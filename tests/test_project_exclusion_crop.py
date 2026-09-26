import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from app.project_storage import Project
from app.results_export import parse_tps
from tests.current_fixtures import make_reviewed_crop


class ExclusionAndCropTests(unittest.TestCase):
 def setUp(self):
  self.tmp=Path(tempfile.mkdtemp());source=self.tmp/"source";(source/"A").mkdir(parents=True)
  (source/"A"/"one.jpg").write_bytes(b"one");(source/"A"/"two.jpg").write_bytes(b"two")
  schema=self.tmp/"schema.csv";schema.write_text("id,abbr,name\n1,A,A\n2,B,B\n",encoding="utf-8")
  self.project=Project.create("p",source,self.tmp,schema,source_layout="direct");self.rows=self.project.catalog_rows();self.cropped,self.uncropped=self.rows
  for row in self.rows:
   self.project.save_landmark(row["image_id"],1,10,20,"manual")
   self.project.save_landmark(row["image_id"],2,30,40,"manual")

 def tearDown(self): shutil.rmtree(self.tmp,ignore_errors=True)

 def test_crop_indicator_uses_saved_crop_record_not_cache(self):
  image_id=self.cropped["image_id"]
  self.assertFalse(self.project.crop_exists(image_id))
  (self.project.cache_root/"developed"/(image_id+".png")).write_bytes(b"cache")
  (self.project.cache_root/"standardized"/(image_id+".png")).write_bytes(b"cache")
  self.assertFalse(self.project.crop_exists(image_id))
  make_reviewed_crop(self.project,image_id,40,40)
  rows={row["image_id"]:row for row in self.project.catalog_rows()}
  self.assertTrue(rows[image_id]["has_crop"])
  self.assertFalse(rows[self.uncropped["image_id"]]["has_crop"])

 def test_exclude_preserves_landmarks_and_omits_only_tps(self):
  image_id=self.cropped["image_id"];before=self.project.load_landmarks(image_id)
  self.project.exclude_image(image_id,"Bent specimen","curved body")
  row=next(row for row in self.project.catalog_rows() if row["image_id"]==image_id)
  self.assertTrue(row["excluded"]);self.assertEqual(row["exclusion_reason"],"Bent specimen");self.assertEqual(row["status_color"],"excluded")
  self.assertEqual(self.project.load_landmarks(image_id),before)
  out=self.project.sync_results();blocks=parse_tps(out["tps"])
  self.assertEqual([block["ID"] for block in blocks],[self.uncropped["image_id"]])
  metadata={row["image_id"]:row for row in csv.DictReader(out["specimens"].open(encoding="ascii"))}
  self.assertEqual(metadata[image_id]["excluded"],"true");self.assertEqual(metadata[image_id]["exclusion_reason"],"Bent specimen")
  self.project.restore_image(image_id)
  restored=next(row for row in self.project.catalog_rows() if row["image_id"]==image_id)
  self.assertFalse(restored["excluded"]);self.assertEqual(self.project.load_landmarks(image_id),before)
  self.assertIn(image_id,[block["ID"] for block in parse_tps(self.project.sync_results()["tps"])])


if __name__ == "__main__": unittest.main()
