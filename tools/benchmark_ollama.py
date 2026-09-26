"""Compact, deterministic benchmark for a locally installed Ollama model."""
from __future__ import annotations
import json, shutil, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "ollama_benchmark.json"
CASES = [
    ("arithmetic", "Reply with exactly: 42", "42"),
    ("python_syntax", "Reply with exactly valid Python: x = 2 + 3", "x = 2 + 3"),
    ("json", "Reply with exactly this JSON: {\"ok\": true}", '{"ok": true}'),
]

def available_models():
    out = subprocess.check_output(["ollama", "list"], text=True, stderr=subprocess.STDOUT)
    return [line.split()[0] for line in out.splitlines()[1:] if line.split()]

def main():
    if not shutil.which("ollama"):
        result={"available":False,"adequate":False,"reason":"ollama executable not found"}
    else:
        models=available_models(); model="gpt-oss:20b" if "gpt-oss:20b" in models else (models[0] if models else None)
        rows=[]
        for name,prompt,expected in CASES:
            started=time.monotonic()
            try:
                text=subprocess.check_output(["ollama","run",model,prompt], text=True, stderr=subprocess.STDOUT, timeout=180).strip()
                rows.append({"case":name,"passed":text==expected,"seconds":round(time.monotonic()-started,2)})
            except Exception as exc:
                rows.append({"case":name,"passed":False,"error":str(exc)[:300],"seconds":round(time.monotonic()-started,2)})
        result={"available":True,"model":model,"cases":rows,"adequate":all(row["passed"] for row in rows),"policy":"Use only for low-risk output that passes deterministic verification."}
    REPORT.parent.mkdir(exist_ok=True); REPORT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({key:result.get(key) for key in ("available","model","adequate")},ensure_ascii=False))

if __name__=="__main__": main()
