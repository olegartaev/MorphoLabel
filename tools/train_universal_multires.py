"""Fine-tune an EXISTING generic multires Structure AI on VERIFIED annotations.

This creates only an INACTIVE portable ZIP. No SQLite writes, model activation,
image modifications, manually created labels or automatic deployment.

Only run against an EXPLICIT COPY of an existing user project; opening an
XRayProject may run its schema migration code. Source project is out of scope.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import sys
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from ai_runtime.universal_multires import pipeline_components
from ai_runtime.universal_multires_training_data import build_tile_manifest

def hash_bytes(v):return sha256(v).hexdigest()

def inspect_source_package(package):
    with ZipFile(package) as z:
        if z.testzip() is not None:raise ValueError("Input model ZIP is corrupt")
        names=[n for n in z.namelist() if not n.endswith("/")]
        if len(names)!=len(set(names)):raise ValueError("Duplicate ZIP entries")
        data={name:z.read(name) for name in names if name.startswith("artifacts/")}
        manifest=json.loads(z.read("manifest.json"))
    if set(data)!=set(manifest.get("files") or {}):
        raise ValueError("Model ZIP file manifest mismatch")
    if any(hash_bytes(raw)!=manifest["files"][name] for name,raw in data.items()):
        raise ValueError("Original model package SHA256 mismatch")
    meta=json.loads(data["artifacts/model.json"])
    p=meta.get("inference_pipeline") or {}
    if p.get("mode")!="tiled_native":
        raise ValueError("Fine-tuning requires a previously working multires native/detail model")
    specs=pipeline_components(meta)
    if set(specs)!={"detail","native"}:
        raise ValueError("Two trained model branches are required")
    names=[str(s["id"]) for s in meta["structures"]]
    if set(meta.get("thresholds") or {})!=set(names):
        raise ValueError("Source calibration does not match structure channels")
    if meta["schema_digest"]!=manifest["schema_digest"]:
        raise ValueError("Source package scientific contract mismatch")
    return manifest,meta,data


def new_package(source_manifest,source_meta,source_data,
                detail_bytes,native_bytes,output,
                *,model_id,provenance):
    """Make one hash-locked portable package without mutating original weights."""
    import re
    output=Path(output)
    if output.exists():raise FileExistsError("Cannot overwrite model candidate")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,95}",model_id):
        raise ValueError("Invalid candidate ID")
    manifest=deepcopy(source_manifest)
    meta=deepcopy(source_meta)
    comps=pipeline_components(meta)
    detail_name=comps["detail"]["checkpoint"]
    native_name=comps["native"]["checkpoint"]
    if detail_name==native_name or "model.pth" in (detail_name,native_name):
        raise ValueError("Component files must be distinct from parent model")
    meta["inference_pipeline"]["detail"]["sha256"]=hash_bytes(detail_bytes)
    meta["inference_pipeline"]["native"]["sha256"]=hash_bytes(native_bytes)
    meta["model_id"]=model_id
    meta["multires_training"]=provenance
    pipeline_components(meta)
    files={
        "artifacts/model.pth":source_data["artifacts/model.pth"],
        "artifacts/"+detail_name:detail_bytes,
        "artifacts/"+native_name:native_bytes,
        "artifacts/model.json":json.dumps(meta,indent=2,sort_keys=True,
                                          ensure_ascii=False).encode("utf-8"),
    }
    manifest["model_id"]=model_id
    manifest["files"]={k:hash_bytes(v) for k,v in files.items()}
    manifest["training_statistics"]={
        "training_specimen_count":int(provenance["training_specimens"]),
        "validation_specimen_count":int(provenance["validation_specimens"]),
        "metrics":{"inference/unvalidated":True,
                   "training/multires":True,
                   "training/no_independent_holdout":True},
    }
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,"w",ZIP_DEFLATED,compresslevel=6) as zipf:
        for name,raw in files.items():zipf.writestr(name,raw)
        zipf.writestr("manifest.json",json.dumps(manifest,indent=2,sort_keys=True,
                                                 ensure_ascii=False))
    with ZipFile(output) as z:
        if z.testzip() is not None:raise ValueError("Candidate model ZIP CRC mismatch")
    return {"candidate":str(output),"sha256":hash_bytes(output.read_bytes()),
            "size":output.stat().st_size,"model_id":model_id}


def run(project_copy,source_model,output,*,epochs_native=18,epochs_detail=18,
        seed=42,device="cuda:0",lr=2e-5):
    import torch
    from app.xray_project import XRayProject
    from app.xray_structure_ai import (
        prepare_structure_training_dataset,export_structure_model_package,
        structure_schema_digest)
    from ai_runtime import xray_structure_runner as runner

    project_root=Path(project_copy).resolve()
    if not (project_root/"xray_project.sqlite3").is_file():
        raise FileNotFoundError("Explicit project COPY required")
    output=Path(output).resolve()
    if output.exists() or output.is_relative_to(project_root):
        raise ValueError("New candidate ZIP must be outside project copy and not exist")
    if not (12<=epochs_native<=120 and 12<=epochs_detail<=120):
        raise ValueError("Training epochs outside supported range")
    if not (0<lr<=1e-4):
        raise ValueError("Only low-rate warm-start fine-tuning is allowed")
    if str(device).startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not available in this Python environment")
    project=XRayProject(project_root)
    source=next((m for m in project.structure_models()
                 if m["model_id"]==source_model),None)
    if source is None:raise ValueError("Source multi-resolution model was not found")
    with tempfile.TemporaryDirectory(prefix="morpholabel_multires_training_") as tmp:
        scratch=Path(tmp)
        original_zip=scratch/"source.zip"
        export_structure_model_package(project,original_zip,source_model)
        original_manifest,original_meta,data=inspect_source_package(original_zip)
        if structure_schema_digest(project.scheme)!=original_meta["schema_digest"]:
            raise ValueError("Scientific schema changed since model was trained")
        meta_ids=[str(x["id"]) for x in original_meta["structures"]]
        if meta_ids!=[str(x["id"]) for x in project.scheme["structures"]]:
            raise ValueError("Structure channel order incompatible with scientific scheme")
        prepared=prepare_structure_training_dataset(project,scratch,seed=seed)
        manifest=json.loads(Path(prepared["manifest"]).read_text(encoding="utf-8"))
        tiles=build_tile_manifest(manifest,scratch/"tile_data")
        full_manifest=deepcopy(manifest)
        full_manifest["input_size"]=list(original_meta["inference_pipeline"]["native"]["input_size"])
        full_path=scratch/"native_manifest.json"
        full_path.write_text(json.dumps(full_manifest,ensure_ascii=False),encoding="utf-8")
        details=original_meta["inference_pipeline"]
        specs=pipeline_components(original_meta)
        detail_raw=data["artifacts/"+specs["detail"]["checkpoint"]]
        native_raw=data["artifacts/"+specs["native"]["checkpoint"]]
        detail_state=torch.load(BytesIO(detail_raw),weights_only=True,map_location="cpu")
        state=torch.load(BytesIO(native_raw),weights_only=True,map_location="cpu")
        prefix=specs["native"].get("state_prefix","")
        if prefix:
            if not all(k.startswith(prefix) for k in state):
                raise ValueError("Unexpected Native model state prefix")
            state={k[len(prefix):]:v for k,v in state.items()}
        parent_state=torch.load(BytesIO(data["artifacts/model.pth"]),
                                weights_only=True,map_location="cpu")
        if set(parent_state)!=set(detail_state) or set(parent_state)!=set(state):
            raise ValueError("Channel/tensor mismatch in original pretrained checkpoints")
        for key,value in parent_state.items():
            if value.shape!=detail_state[key].shape or value.shape!=state[key].shape:
                raise ValueError("Checkpoint architecture mismatch")
        detail_initial=scratch/"detail_initial.pth"
        native_initial=scratch/"native_initial.pth"
        torch.save(detail_state,detail_initial)
        torch.save(state,native_initial)
        common={"device":device,"batch_size":1,"workers":0,"mixed_precision":True,
                "pin_memory":True,"persistent_workers":False,"seed":seed,
                "learning_rate":lr,"fixed_thresholds":original_meta["thresholds"]}
        print(json.dumps({"stage":"PREPARED",
            "training_specimens":prepared["training_specimens"],
            "validation_specimens":prepared["validation_specimens"],
            "train_plates":prepared["training_plates"],
            "val_plates":prepared["validation_plates"],
            "tile_train":tiles["train_tiles"],"tile_val":tiles["validation_tiles"]}),flush=True)
        # Train distinct branches; full model first to reduce peak CUDA memory.
        native_result=runner.train({**common,
            "manifest":str(full_path),"initial_checkpoint":str(native_initial),
            "work_dir":str(scratch/"native_work"),"epochs":epochs_native})
        if torch.cuda.is_available():torch.cuda.empty_cache()
        detail_result=runner.train({**common,
            "manifest":str(tiles["manifest"]),
            "initial_checkpoint":str(detail_initial),
            "work_dir":str(scratch/"detail_work"),"epochs":epochs_detail})
        native_new=torch.load(native_result["checkpoint"],weights_only=True,map_location="cpu")
        buffer=BytesIO()
        torch.save({prefix+k:v for k,v in native_new.items()},buffer)
        detail_new=Path(detail_result["checkpoint"]).read_bytes()
        provenance={
            "training_specimens":prepared["training_specimens"],
            "validation_specimens":prepared["validation_specimens"],
            "training_source_plates":prepared["training_plates"],
            "validation_source_plates":prepared["validation_plates"],
            "dataset_hash":prepared["dataset_hash"],
            "tile_manifest_hash":tiles["manifest_sha256"],
            "source_model_id":source_model,"source_model_sha256":hash_bytes(original_zip.read_bytes()),
            "source_model_trained_on_overlapping_data_possible":True,
            "independent_validation_proven":False,
            "native_epochs_completed":json.loads(Path(native_result["metadata"]).read_text())["epochs_completed"],
            "detail_epochs_completed":json.loads(Path(detail_result["metadata"]).read_text())["epochs_completed"],
            "frozen_thresholds":True,"learning_rate":lr,
            "scientific_scheme_reused":True,
        }
        result=new_package(original_manifest,original_meta,data,
                           detail_new,buffer.getvalue(),output,
                           model_id="multires_retrained_"+sha256(
                               prepared["dataset_hash"].encode()).hexdigest()[:12],
                           provenance=provenance)
    return {**result,"training":provenance,
            "validation":"NOT_INDEPENDENT; import inactive and compare on untouched specimens"}


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--project-copy",type=Path,required=True)
    a.add_argument("--source-model",required=True)
    a.add_argument("--output",type=Path,required=True)
    a.add_argument("--epochs-native",type=int,default=18)
    a.add_argument("--epochs-detail",type=int,default=18)
    a.add_argument("--device",default="cuda:0")
    a.add_argument("--seed",type=int,default=42)
    args=a.parse_args()
    result=run(args.project_copy,args.source_model,args.output,
               epochs_native=args.epochs_native,epochs_detail=args.epochs_detail,
               device=args.device,seed=args.seed)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)

if __name__=="__main__":main()
