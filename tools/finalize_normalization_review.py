"""Local completion monitor for the normalization acceptance batch."""
from pathlib import Path
import json,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[1];reports=ROOT/"reports";review=reports/"normalization_acceptance_review.json"
deadline=time.monotonic()+8*3600
while not review.exists() and time.monotonic()<deadline: time.sleep(20)
if not review.exists(): raise SystemExit("normalization batch did not finish before monitor deadline")
rows=json.loads(review.read_text(encoding="utf-8"));tests=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests"],cwd=ROOT,capture_output=True,text=True)
result={"examples":len(rows),"all_review":all(r["status"]=="REVIEW" for r in rows),"tests_passed":tests.returncode==0,"test_summary":tests.stderr.splitlines()[-5:]}
(reports/"normalization_acceptance_ready.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps(result))
