import csv
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from app.export_formats import COORDINATE_DECIMALS, export_landmark_csv_long, export_landmark_tps, export_landmark_wide
from app.measurements import MEASUREMENT_DECIMALS, SCALE_DECIMALS
from app.project_storage import Project


class ExportPrecisionContractTests(unittest.TestCase):
 def test_public_precision_constants(self):
  self.assertEqual(2,MEASUREMENT_DECIMALS)
  self.assertEqual(5,COORDINATE_DECIMALS)
  self.assertEqual(6,SCALE_DECIMALS)

 def test_landmark_exports_use_fixed_five_decimals(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);src=root/"source";src.mkdir();Image.new("RGB",(20,10)).save(src/"fish.jpg")
   schema=root/"schema.csv";schema.write_text("id,abbr,name,role\n1,A,Anterior,BOTH\n2,T,Tail,BOTH\n",encoding="utf-8")
   project=Project.create("p",src,root,schema,source_layout="direct");image_id=project.catalog_rows()[0]["image_id"]
   project.save_landmark(image_id,1,3.14159265,4.98765432,"manual","manual");project.save_landmark(image_id,2,8.3333333,4.1111111,"manual","manual")
   tps=export_landmark_tps(project,target=root/"coords.tps").read_text(encoding="ascii")
   self.assertIn("3.14159 4.98765",tps)
   rows=list(csv.DictReader(export_landmark_csv_long(project,target=root/"long.csv").open(encoding="utf-8")))
   self.assertEqual(("3.14159","4.98765"),(rows[0]["x_standardized"],rows[0]["y_standardized"]))
   wide=list(csv.DictReader(export_landmark_wide(project,target=root/"wide.csv").open(encoding="utf-8")))
   self.assertEqual("3.14159",wide[0]["x1"])


if __name__=="__main__":unittest.main()
