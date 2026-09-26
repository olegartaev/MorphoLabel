"""Read-only/derived end-to-end smoke test for first unattended-run plumbing."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.manifest import write_manifest
from app.paths import ORIGINALS
from app.standardize import provisional_standardize
from app.workflow import assert_no_split_leakage, make_sample_split, select_seed_queue
from app.dataset_v2 import export_training_dataset
from app.canonical_export import export_canonical_csv

if __name__ == "__main__":
    manifest=write_manifest(); assert manifest and all(row["sha256"] for row in manifest)
    source=next(ORIGINALS.rglob("*.nef")); master=provisional_standardize(source)
    assert master["normalization_status"]=="REVIEW" and master["mirrored"] is False
    queue=select_seed_queue(); split=make_sample_split(); assert_no_split_leakage(split)
    training=export_training_dataset("Phoxinus_lateral_v1"); csv=export_canonical_csv()
    print("E2E PASS",{"sources":len(manifest),"seed_queue":len(queue["images"]),"eligible_training":len(training["images"]),"canonical_csv":str(csv)})
