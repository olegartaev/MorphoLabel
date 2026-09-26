from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.standardize_fish import standardized_master
from app.manifest import sha256

if __name__=="__main__":
 files=list(Path("orig_photos").rglob("*.nef")); selected=[files[0],files[len(files)//2],files[-1]]; rows=[]
 for source in selected:
  before=sha256(source);meta=standardized_master(source,True);assert before==meta["source_sha256"];assert meta["normalization_status"]=="REVIEW";assert meta["mirrored"] is False;w=meta["crop_bounds"][2]-meta["crop_bounds"][0];h=meta["crop_bounds"][3]-meta["crop_bounds"][1];assert w<6016 or h<4016;rows.append((source.name,w,h,round(meta["rotation_degrees"],2)))
 print("STANDARDIZED_EDITOR_E2E_PASS",rows)
