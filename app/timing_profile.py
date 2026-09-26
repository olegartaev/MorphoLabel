"""Small append-only stage timing profile for local bottleneck measurement."""
from __future__ import annotations
import json, statistics, time
from datetime import datetime, timezone
from pathlib import Path
from .paths import REPORTS
from .standardize import image_id

PATH=REPORTS/"preparation_timing.jsonl"
def record(source, stage, seconds, image_id_value=None):
 REPORTS.mkdir(exist_ok=True)
 ident = image_id_value if image_id_value is not None else image_id(Path(source))
 row={"timestamp":datetime.now(timezone.utc).isoformat(),"image_id":ident,"stage":stage,"ms":round(seconds*1000,3)}
 with PATH.open("a",encoding="utf-8") as f:f.write(json.dumps(row)+"\n");f.flush()
def summary():
 groups={}
 if PATH.exists():
  for line in PATH.read_text(encoding="utf-8").splitlines():
   row=json.loads(line);groups.setdefault(row["stage"],[]).append(row["ms"])
 return {stage:{"median_ms":round(statistics.median(values),3),"p90_ms":round(sorted(values)[max(0,int(len(values)*.9)-1)],3),"n":len(values)} for stage,values in sorted(groups.items())}
