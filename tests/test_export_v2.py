import tempfile,unittest,csv
from pathlib import Path
import app.export_v2 as ex

FIXTURE_SCHEMA=Path(__file__).resolve().parent / "fixtures" / "phoxinus" / "landmark_schema.csv"
from app.io import atomic_json_write

class ExportV2Tests(unittest.TestCase):
 def test_hash_lookup_and_explicit_missing_wide_state(self):
  ow,or_=ex.WORK,ex.REPORTS
  try:
   with tempfile.TemporaryDirectory() as root:
    root=Path(root);ex.WORK=root/"work";ex.REPORTS=root/"reports";ex.REPORTS.mkdir();
    with (ex.REPORTS/"source_manifest.csv").open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=["source_relpath","sha256"]);w.writeheader();w.writerow({"source_relpath":"orig_photos/s/a.nef","sha256":"abc"})
    atomic_json_write(ex.WORK/"s"/"landmarks"/"i.json",{"sample_id":"s","image_id":"i","source_relpath":"orig_photos/s/a.nef","profile_id":"Phoxinus_lateral_v1","profile_version":"1","points":{"1":{"point_code":"SnT","state":"missing","x_standardized":None,"y_standardized":None}}})
    ex.export_all(FIXTURE_SCHEMA);rows=list(csv.DictReader((ex.REPORTS/"landmarks_GM.csv").open()));self.assertEqual(rows[0]["source_sha256"],"abc");self.assertEqual(rows[0]["p01_state"],"missing");self.assertEqual(rows[0]["p01_x"],"")
  finally:ex.WORK,ex.REPORTS=ow,or_
if __name__=="__main__":unittest.main()
