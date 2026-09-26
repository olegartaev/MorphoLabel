from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.dataset import export_training_dataset

if __name__ == "__main__":
    data=export_training_dataset("Phoxinus_lateral_v1")
    print(f"Exported {len(data['images'])} human-final images; no model training was started.")
