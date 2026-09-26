"""Immutable model-version metadata. Training/inference adapters plug in elsewhere."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from .io import atomic_json_write, read_json
from .paths import ROOT

MODELS=ROOT/"models"

def create_model_package(profile_id: str, backend: str, dataset_manifest: str, metrics: dict|None=None) -> dict:
    prefix=f"{profile_id}_v"; existing=sorted(path.name for path in MODELS.glob(prefix+"*")) if MODELS.exists() else []
    version=f"{len(existing)+1:03d}"; model_id=prefix+version; directory=MODELS/model_id
    if directory.exists(): raise FileExistsError(f"Immutable model package already exists: {model_id}")
    directory.mkdir(parents=True)
    manifest={"model_id":model_id,"profile_id":profile_id,"backend":backend,"dataset_manifest":dataset_manifest,"created_at":datetime.now(timezone.utc).isoformat(),"metrics":metrics or {},"status":"metadata_only_untrained","runtime":"portable inference adapter required"}
    atomic_json_write(directory/"model_manifest.json",manifest); return manifest

def model_info(model_id: str) -> dict: return read_json(MODELS/model_id/"model_manifest.json",{})
