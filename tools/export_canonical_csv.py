from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.canonical_export import export_canonical_csv

if __name__ == "__main__": print(export_canonical_csv())
