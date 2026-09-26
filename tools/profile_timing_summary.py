from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.timing_profile import summary
print(json.dumps(summary(),indent=2))
