from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.export_v2 import export_all
if __name__=="__main__":print(export_all())
