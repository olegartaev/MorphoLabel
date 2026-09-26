from pathlib import Path
import json,random
ROOT=Path(__file__).resolve().parents[1];report=ROOT/"reports"/"normalization_acceptance_review.json"
rows=json.loads(report.read_text(encoding="utf-8"));random.Random(20260815).shuffle(rows);selected=rows[:5]
(ROOT/"reports"/"visual_crop_acceptance_5.json").write_text(json.dumps(selected,indent=2),encoding="utf-8")
print(json.dumps({"examples":len(selected),"review":"reports/visual_crop_acceptance_5.json"}))
