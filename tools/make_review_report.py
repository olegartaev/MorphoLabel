from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.io import read_json
from app.paths import WORK
from app.review_report import summarize_review

if __name__ == "__main__":
    records=[read_json(path,{}) for path in WORK.glob("*/landmarks/*.json")]
    print(summarize_review(records)["status"])
