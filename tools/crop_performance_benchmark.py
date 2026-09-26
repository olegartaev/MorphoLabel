"""Disposable, reproducible Crop performance benchmark for QA only.

It never writes the supplied project: project metadata is copied and developed
PNGs are hard-linked into a temporary project so the actual production paths
can be measured without duplicating large image caches.
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, tempfile, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.project_storage import Project
from app import crop_training, crop_parallel
from app.crop_auto import process

def _link(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    try: target.hardlink_to(source)
    except OSError: shutil.copy2(source, target)

def clone_training_project(source: Path, destination: Path, limit: int = 115) -> Project:
    original=Project.open(source); rows=list(original.crop_training_rows())[:limit]
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("project.yaml", "landmark_schema.csv"):
        shutil.copy2(source/name, destination/name)
    data=destination/"project_data";data.mkdir(exist_ok=True)
    shutil.copy2(original.path, data/"project.sqlite")
    for row in rows:_link(Path(row["developed_path"]), data/"cache"/"developed"/f"{row['image_id']}.png")
    # Copy only the active lightweight Crop ridge artifact.  Never clone the
    # unrelated multi-gigabyte RTMPose checkpoint history into a QA project.
    active=original.active_model("crop") or {}
    rel=active.get("path")
    if rel:
        source_model=original.data_root / str(rel)
        target_model=data / str(rel)
        if (source_model / "model.npz").exists():
            target_model.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_model / "model.npz", target_model / "model.npz")
            if (source_model / "model_manifest.json").exists():
                shutil.copy2(source_model / "model_manifest.json", target_model / "model_manifest.json")
    return Project.open(destination)

def run(source: Path, limit: int, apply_count: int, application_only: bool = False) -> dict:
    root=Path(tempfile.mkdtemp(prefix="simm_crop_perf_")); result={"temporary_project":str(root)}
    if not application_only:
        serial=clone_training_project(source,root/"serial",limit)
        original_auto=crop_parallel.auto_config
        original_tune=crop_parallel.tune_and_prepare
        crop_parallel.auto_config=lambda *a,**k:{"workers":1,"max_in_flight":1,"executor_type":"ThreadPoolExecutor"}
        crop_parallel.tune_and_prepare=lambda *a,**k:(crop_parallel.auto_config(),{})
        try: baseline=crop_training.train_project(serial)
        finally:
            crop_parallel.auto_config=original_auto;crop_parallel.tune_and_prepare=original_tune
        cold_project=clone_training_project(source,root/"cold",limit);cold=crop_training.train_project(cold_project);warm=crop_training.train_project(cold_project)
        result["training"]={"baseline":baseline["timings"],"cold":cold["timings"],"warm":warm["timings"],"feature_workers":cold["feature_config"]["workers"]}
    # Isolate a real Apply-to-remaining subset by deleting only their crop rows
    # in this disposable DB; source rows and images are never altered.
    def fresh_apply(name):
        candidate=clone_training_project(source,root/name,limit)
        ids=[row["image_id"] for row in candidate.crop_training_rows()[:apply_count]]
        with sqlite3.connect(candidate.path) as db:
            db.executemany("DELETE FROM crops WHERE image_id=?",[(ident,) for ident in ids])
            db.executemany("DELETE FROM crop_predictions WHERE image_id=?",[(ident,) for ident in ids])
        return Project.open(root/name),ids
    historical,ids=fresh_apply("apply_historical")
    started=time.perf_counter();old=process(historical,image_ids=ids,materialize_learned=True);old_elapsed=time.perf_counter()-started
    optimized,ids=fresh_apply("apply_proposal")
    started=time.perf_counter();applied=process(optimized,image_ids=ids);elapsed=time.perf_counter()-started
    result["application"]={"baseline":{"attempted":old["attempted"],"success":old["success"],"failed":old["failed"],"elapsed_s":old_elapsed,"images_per_s":old["success"]/old_elapsed if old_elapsed else 0,"timings":old["timings"]},"optimized":{"attempted":applied["attempted"],"success":applied["success"],"failed":applied["failed"],"elapsed_s":elapsed,"images_per_s":applied["success"]/elapsed if elapsed else 0,"config":applied["config"],"timings":applied["timings"]}}
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("project",type=Path);parser.add_argument("--limit",type=int,default=115);parser.add_argument("--apply-count",type=int,default=24);parser.add_argument("--application-only",action="store_true");parser.add_argument("--output",type=Path);args=parser.parse_args()
    value=json.dumps(run(args.project,args.limit,args.apply_count,args.application_only),indent=2,sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(value+"\n",encoding="utf-8")
    print(value)
