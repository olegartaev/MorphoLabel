from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.workflow import assert_no_split_leakage, make_sample_split, select_seed_queue

if __name__ == "__main__":
    queue = select_seed_queue(); split = make_sample_split(); assert_no_split_leakage(split)
    print(f"Prepared {len(queue['images'])} manual-seed images and non-leaking sample split.")
