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


def choose_family_detail_policy(scheme, cases):
    """Calibrate Standard/Native/Detail routes on development validation data.

    Evaluate the *final scientific traits* and retain dependent marker families
    together. Nothing here is independent test evidence or model promotion.
    All predictions are reused; no GPU inference occurs in this search.
    """
    from itertools import product
    from .xray_component_selection import structure_families, combine_marker_rows
    from .xray_structure_ai import summarize_structure_ai_human_comparison

    families = structure_families(scheme)
    specimens = len(cases)
    plates = len({str(row["image_id"]) for row in cases})
    if specimens < 12 or plates < 3 or not families:
        return {"detail": [], "standard": []}, {"status": "insufficient_development_validation",
                    "specimens": specimens, "plates": plates}
    def evaluate(modes):
        assigned = {sid: mode for family, mode in zip(families, modes) for sid in family}
        rows = []
        for case in cases:
            sources = {method: case[method] for method in ("standard", "native", "detail")}
            rows.append({
                "specimen_id": case["specimen_id"], "human": case["human"],
                "visibility": case["visibility"], "crop_size": case["crop_size"],
                "predicted": combine_marker_rows(scheme, sources, assigned),
            })
        return summarize_structure_ai_human_comparison(scheme, rows)

    def rank(report):
        s = report["summary"]
        trait_total = sum(int(row.get("correct") or 0) for row in report["traits"])
        return (int(s["all_traits_correct_specimens"]), trait_total, float(s.get("macro_f1") or 0))

    native = ("native",) * len(families)
    baseline = evaluate(native)
    best_modes, best_report = native, baseline
    original = {row["specimen_id"]: row for row in baseline["specimen_outcomes"]}
    original_traits = {row["trait_id"]: row for row in baseline["traits"]}
    # Exact search is bounded. Large custom schemes use one-family improvements.
    methods = ("native", "detail", "standard")
    choices = (product(methods, repeat=len(families))
               if len(families) <= 6 else
               (tuple(mode if j == i else "native" for j in range(len(families)))
                for i in range(len(families)) for mode in ("detail", "standard")))
    for modes in choices:
        if modes == native:
            continue
        report = evaluate(modes)
        # A once-fully-correct specimen must not become wrong. A method
        # cannot be chosen merely because it scores many isolated points.
        outcome = {row["specimen_id"]: row for row in report["specimen_outcomes"]}
        if any(row["evaluable"] and row["correct"] and
               not outcome[row_id]["correct"] for row_id, row in original.items()):
            continue
        by_trait = {row["trait_id"]: row for row in report["traits"]}
        if any(int(by_trait[tid].get("correct") or 0) < int(stat.get("correct") or 0)
               for tid, stat in original_traits.items()):
            continue
        if rank(report) > rank(best_report):
            best_modes, best_report = modes, report
    chosen = {method: [sid for family, mode in zip(families, best_modes)
                       if mode == method for sid in family]
              for method in ("detail", "standard")}
    evidence = {
        "status": "development_calibration_not_independent",
        "specimens": specimens, "plates": plates,
        "search": "exhaustive" if len(families) <= 6 else "single_family",
        "baseline_all_correct": baseline["summary"]["all_traits_correct_specimens"],
        "selected_all_correct": best_report["summary"]["all_traits_correct_specimens"],
        "baseline_trait_correct": sum(int(x.get("correct") or 0) for x in baseline["traits"]),
        "selected_trait_correct": sum(int(x.get("correct") or 0) for x in best_report["traits"]),
        "family_routes": {" / ".join(family): mode for family, mode in zip(families, best_modes)},
    }
    return chosen, evidence


def select_detail_channels(metadata, source_data, native_bytes, detail_bytes, manifest, scratch, device, *, scheme=None):
    """Run both trained methods once per validation image, then choose by family."""
    import torch
    from PIL import Image
    from ai_runtime import xray_structure_runner as runner
    from ai_runtime.universal_multires import predict_one, _load_component
    from .xray_structure_ai import _comparison_match, _comparison_prediction_rows
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
    counts={str(s["id"]):{mode:[0,0,0] for mode in ("native","detail","standard")} for s in meta["structures"]}
    cases=[]
    for row in manifest["val"]:
        outputs={}
        predict_one(row["path"],primary,meta,folder/"model.json",device,runner,component_models=models,components_out=outputs)
        with Image.open(row["path"]) as image:
            crop_size=image.size
        cases.append({
            "specimen_id": str(row["specimen_id"]), "image_id": str(row["image_id"]),
            "human": row["points"], "visibility": row.get("visibility") or {},
            "crop_size": crop_size,
            "native": _comparison_prediction_rows(outputs["native"]),
            "detail": _comparison_prediction_rows(outputs["detail"]),
            "standard": _comparison_prediction_rows(outputs["standard"]),
        })
        for sid,by_mode in counts.items():
            if row.get("visibility",{}).get(sid,"complete") in {"partial","not_visible"}:continue
            truth=[p for p in row["points"] if p["structure_id"]==sid]
            for mode,total in by_mode.items():
                predicted=next(g["points"] for g in outputs[mode] if g["structure_id"]==sid)
                tp,fp,fn,_=_comparison_match(predicted,truth)
                by_mode[mode]=[a+b for a,b in zip(total,(tp,fp,fn))]
    del primary,models
    if device.startswith("cuda"):torch.cuda.empty_cache()
    if scheme is None:
        # Backwards-compatible diagnostic path, not used by the application.
        selected=choose_detail_channels(counts)
        return selected, counts
    selected,science=choose_family_detail_policy(scheme,cases)
    return selected, {**counts, "_scientific_selection":science}


def choose_detail_channels(counts):
    def f1(stat):
        tp,fp,fn=stat
        return 2*tp/max(1,2*tp+fp+fn)
    return [sid for sid,stat in counts.items() if f1(stat["detail"])>f1(stat["native"])]
