from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.paths import ORIGINALS, REPORTS
from app.standardize import preview

if __name__ == "__main__":
    selections = [sorted(folder.glob("*.nef"))[0] for folder in sorted(ORIGINALS.iterdir()) if folder.is_dir()]
    for number, source in enumerate(selections, 1):
        preview(source, REPORTS / "representative_previews" / f"{number:02d}_{source.stem}.png")
    print(f"Wrote {len(selections)} read-only-derived previews")
