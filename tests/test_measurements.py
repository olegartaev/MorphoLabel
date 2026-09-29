import csv
import tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
class _Raises:
 def __init__(self,t):self.t=t
 def __enter__(self):return self
 def __exit__(self,typ,value,tb):
  if typ is None: raise AssertionError("expected exception")
  return issubclass(typ,self.t)
class _Approx:
 def __init__(self,v,tol=1e-8):self.v=v;self.tol=tol
 def __eq__(self,x):return abs(x-self.v)<=self.tol
class pytest:
 raises=_Raises
 approx=_Approx
from app.measurements import *
from app.transforms import Transform
class Fake:
 def __init__(self,tmp):
  self.root=Path(tmp); self.schema=[{"id":1,"abbr":"A","name":"A"},{"id":2,"abbr":"B","name":"B"},{"id":3,"abbr":"C","name":"C"}]
  self.rows=[{"image_id":"i1","locality":"L1","sample_id":"L1","original_name":"one.png","relative_path":"source/one.png","excluded":False},{"image_id":"i2","locality":"L2","sample_id":"L2","original_name":"two.png","relative_path":"source/two.png","excluded":False}]
  self.points={"i1":{1:{"x_standardized":5,"y_standardized":5,"state":"manual"},2:{"x_standardized":8,"y_standardized":5,"state":"manual"}},"i2":{1:{"state":"missing"},2:{"x_standardized":8,"y_standardized":5,"state":"manual"}}}
  self.cal={"L1":{"scale":2,"calibration_data":{"mm_per_pixel":.5}},"L2":None}
  self.tr=Transform(100,100,0,50,50,10,20,80,70)
 def catalog_rows(self):return self.rows
 def locality_calibration(self,x):return self.cal.get(x)
 def crop_record(self,x):return {"transform_json":self.tr.__dict__}
 def load_landmarks(self,x):return self.points[x]
 def historical_abbr_for_numeric(self,landmark_id):
  row=next((item for item in self.schema if int(item["id"])==int(landmark_id)),None)
  return row["abbr"] if row else None
 def active_landmark_id_for_abbr(self,abbr):
  row=next((item for item in self.schema if str(item["abbr"])==str(abbr)),None)
  return int(row["id"]) if row else None
class MeasurementTests(unittest.TestCase):
 def test_schema_crud_and_validation(self):
  with tempfile.TemporaryDirectory() as tmp_path:
   p=Fake(tmp_path); assert load_measurements(p)==[]
   rows=save_measurements(p,[{"use":True,"abbr":"LEN","name":"Length","point1":1,"point2":2}]); assert load_measurements(p)==rows
   with pytest.raises(ValueError):validate_measurement({"abbr":"X","name":"X","point1":1,"point2":99},p.schema)
   with pytest.raises(ValueError):save_measurements(p,rows+[{"use":True,"abbr":"len","name":"Other","point1":1,"point2":3}])

 def test_transform_distance_na_csv_and_tab_export(self):
  with tempfile.TemporaryDirectory() as tmp_path:
   p=Fake(tmp_path); save_measurements(p,[{"use":True,"abbr":"LEN","name":"Length","point1":1,"point2":2}])
   values,mpp=values_for_image(p,p.rows[0]); assert mpp==.5 and values["LEN"]==pytest.approx(1.5)
   assert values_for_image(p,p.rows[1])[0]["LEN"]=="NA"
   report=export_measurements(p); data=list(csv.DictReader(report["path"].open(newline=""))); assert report["rows"]==2 and data[0]["LEN_mm"]=="1.50" and data[1]["LEN_mm"]=="NA"
   tab=Path(tmp_path)/"measurements.txt";export_measurements(p,target=tab,delimiter="\t");header=tab.read_text(encoding="utf-8").splitlines()[0];assert "\t" in header and "," not in header
   p.points["i1"][2]["x_standardized"]=11; assert values_for_image(p,p.rows[0])[0]["LEN"]==pytest.approx(3)
   p.cal["L1"]["calibration_data"]["mm_per_pixel"]=1; assert values_for_image(p,p.rows[0])[0]["LEN"]==pytest.approx(6)


if __name__=="__main__":
 unittest.main()
