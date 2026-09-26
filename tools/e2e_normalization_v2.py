from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.normalization_pipeline_v2 import normalize
from app.manifest import sha256

if __name__=="__main__":
 files=list(Path("orig_photos").rglob("*.nef"));rows=[]
 for source in (files[0],files[len(files)//2],files[-1]):
  before=sha256(source);m=normalize(source);assert m["source_sha256"]==before;assert m["normalization_status"]=="REVIEW";assert not m["mirrored"];c=m["crop_bounds"];assert c[2]-c[0]<6016 or c[3]-c[1]<4016;rows.append({"name":source.name,"crop":c,"qc":m["qc"]["reason"]})
 print({"e2e":"PASS","examples":rows})
