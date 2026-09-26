from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.paths import ORIGINALS, REPORTS
from app.normalization import make_qc_preview

if __name__ == "__main__":
    sources=[sorted(folder.glob("*.nef"))[0] for folder in sorted(ORIGINALS.iterdir()) if folder.is_dir()]
    for index,source in enumerate(sources,1): make_qc_preview(source,REPORTS/"normalization_qc"/f"{index:02d}_{source.stem}.png")
    print(f"Wrote {len(sources)} REVIEW-only normalization QC previews")
