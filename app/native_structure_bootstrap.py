"""Initialize and qualify the Native Full + ROI Detail pipeline for any point scheme.

An older checkpoint is only an initialization, never a selectable inference mode.
All writes here belong to the disposable training project and worker directory.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import zipfile


def initialize_parent(project, source, scratch, *, seed, device, initial_epochs=60):
    from .xray_structure_ai import train_structure_model, export_structure_model_package, STRUCTURE_BACKEND
    if source is None:
        from .ai_starters import local_starter, SETUP_HELP
        if not local_starter("structure"):raise RuntimeError(SETUP_HELP)
        print(json.dumps({"stage":"INITIALIZING","detail":"Initializing Native + Detail image features"}),flush=True)
        result=train_structure_model(project,seed=seed,epochs=initial_epochs,parent_model_id="",device_override=device)
        source=next(m for m in project.structure_models() if m["model_id"]==result["model_id"])
    if source.get("backend")!=STRUCTURE_BACKEND:
        raise ValueError("Native Full + ROI Detail needs a compatible ResNet18 point checkpoint.")
    package=Path(scratch)/"context.zip"
    export_structure_model_package(project,package,source["model_id"])
    with zipfile.ZipFile(package) as archive:
        manifest=json.loads(archive.read("manifest.json"))
        data={name:archive.read(name) for name in manifest["files"]}
    meta=json.loads(data["artifacts/model.json"])
    if meta.get("inference_pipeline") is not None:raise ValueError("Invalid Native + Detail parent")
    # Separate copies are trained on the full image and on deterministic tiles.
    weights=data["artifacts/model.pth"];digest=hashlib.sha256(weights).hexdigest()
    meta["inference_pipeline"]={"name":"multires_heatmap_v1","version":1,"mode":"tiled_native",
        "native":{"checkpoint":"native.pth","sha256":digest,"input_size":[1536,512]},
        "detail":{"checkpoint":"detail.pth","sha256":digest,"input_size":[768,384]},
        "tiles":{"nx":4,"ny":2,"width_fraction":.38,"height_fraction":.62},
        "fusion_weight":.6,"retain_detail_structures":[]}
    data["artifacts/native.pth"]=weights;data["artifacts/detail.pth"]=weights
    return manifest,meta,data


def select_detail_channels(metadata, source_data, native_bytes, detail_bytes, manifest, scratch, device):
    """Choose per-channel Native/ROI outputs on validation plates, never test data.

Ties retain Native Full. The deterministic tiling never uses truth coordinates.
This is calibration, not independent validation or automatic model activation.
"""
    import torch
    from ai_runtime import xray_structure_runner as runner
    from ai_runtime.universal_multires import predict_one, _load_component
    from .xray_structure_ai import _comparison_match
    meta=deepcopy(metadata);pipeline=meta["inference_pipeline"]
    folder=Path(scratch)/"selection";folder.mkdir()
    (folder/"model.pth").write_bytes(source_data["artifacts/model.pth"])
    (folder/pipeline["native"]["checkpoint"]).write_bytes(native_bytes)
    (folder/pipeline["detail"]["checkpoint"]).write_bytes(detail_bytes)
    pipeline["native"]["sha256"]=hashlib.sha256(native_bytes).hexdigest()
    pipeline["detail"]["sha256"]=hashlib.sha256(detail_bytes).hexdigest()
    primary=runner._model(len(meta["structures"]),pretrained=False)
    primary.load_state_dict(torch.load(folder/"model.pth",weights_only=True,map_location="cpu"));primary=primary.to(device).eval()
    models={key:_load_component(pipeline[key],folder,runner,len(meta["structures"]),device) for key in ("native","detail")}
    counts={str(s["id"]):{mode:[0,0,0] for mode in ("native","detail")} for s in meta["structures"]}
    for row in manifest["val"]:
        outputs={}
        predict_one(row["path"],primary,meta,folder/"model.json",device,runner,component_models=models,components_out=outputs)
        for sid,by_mode in counts.items():
            if row.get("visibility",{}).get(sid,"complete") in {"partial","not_visible"}:continue
            truth=[p for p in row["points"] if p["structure_id"]==sid]
            for mode,total in by_mode.items():
                predicted=next(g["points"] for g in outputs[mode] if g["structure_id"]==sid)
                tp,fp,fn,_=_comparison_match(predicted,truth)
                by_mode[mode]=[a+b for a,b in zip(total,(tp,fp,fn))]
    selected=choose_detail_channels(counts)
    del primary,models
    if device.startswith("cuda"):torch.cuda.empty_cache()
    return selected,counts


def choose_detail_channels(counts):
    def f1(stat):
        tp,fp,fn=stat
        return 2*tp/max(1,2*tp+fp+fn)
    return [sid for sid,stat in counts.items() if f1(stat["detail"])>f1(stat["native"])]
