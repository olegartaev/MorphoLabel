from pathlib import Path
import json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.developed_cache import ensure

ROOT=Path(__file__).resolve().parents[1]
if __name__=="__main__":
 rows=json.loads((ROOT/"reports"/"visual_crop_acceptance_5.json").read_text(encoding="utf-8"));summary=[]
 for row in rows:
  source=ROOT/row["source"];started=time.monotonic();meta=ensure(source);summary.append({"source":row["source"],"seconds":round(time.monotonic()-started,2),"developed_full":meta["developed_full_relpath"]})
 (ROOT/"reports"/"visual_crop_precache_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");print(json.dumps({"count":len(summary),"report":"reports/visual_crop_precache_summary.json"}))
