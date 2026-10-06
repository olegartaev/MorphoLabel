"""Model-only X-ray detector/orientation ZIPs; registry membership stays local."""
from __future__ import annotations
import ast
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from .model_publication import staged_model_directory

PACKAGE_FORMAT="morpholabel-xray-crop-model-v1"
BACKEND="rtmdet_tiny_mmdet_3_2"
INFERENCE_CONTRACT={"version":1,"input":"display_preview_rgb_max1800","detector_boxes":"xyxy_preview_pixels","geometry":"hybrid_original_plate","orientation":"aligned_crop_percentile_0.5_99.5_rgb_mobilenet224"}
_SAFE_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class XRayCropPackageError(ValueError):pass


def _hash(data):return hashlib.sha256(data).hexdigest()


def _portable_config(path):
    # MMEngine dumps a self-contained Python config. Only inference assignments
    # are portable: remove all dataset roots, evaluator output paths and training
    # loader membership. Preserve model architecture and exact test transforms.
    source=Path(path).read_text(encoding="utf-8")
    tree=ast.parse(source);parts=[];names=set();pipeline=None
    def field(node,key):
        if isinstance(node,ast.Dict):
            return next((v for k,v in zip(node.keys,node.values) if isinstance(k,ast.Constant) and k.value==key),None)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="dict":
            return next((kw.value for kw in node.keywords if kw.arg==key),None)
        return None
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            name=node.targets[0].id
            if name=="test_dataloader":
                dataset=field(node.value,"dataset")
                pipeline=field(dataset,"pipeline")
            if name in {"model","default_scope","test_pipeline","tta_model","tta_pipeline","custom_imports"}:
                parts.append(ast.get_source_segment(source,node));names.add(name)
    if "model" not in names:raise XRayCropPackageError("Detector config has no self-contained model architecture.")
    # MMDetection inference uses test_dataloader.dataset.pipeline, which may
    # differ from the top-level training-base test_pipeline in cfg.dump().
    if pipeline is not None and not (isinstance(pipeline,ast.Name) and pipeline.id=="test_pipeline"):
        parts=[p for p in parts if not p.lstrip().startswith("test_pipeline")]
        parts.append("test_pipeline = "+ast.unparse(pipeline));names.add("test_pipeline")
    if "test_pipeline" in names:parts.append("test_dataloader = dict(dataset=dict(type='CocoDataset', metainfo=dict(classes=('specimen',)), pipeline=test_pipeline))")
    return ("\n".join(parts)+"\n").encode("utf-8")


def export_crop_model_package(project,target,model_id=None):
    model=next((m for m in project.crop_models() if m["model_id"]==model_id),None) if model_id else project.active_crop_model()
    if not model:raise XRayCropPackageError("No X-ray Crop model is selected.")
    checkpoint=project.root/model["path"];config=project.root/model["config_path"]
    if not checkpoint.is_file() or not checkpoint.stat().st_size or not config.is_file():raise XRayCropPackageError("Detector artifact is incomplete.")
    metrics=dict(model.get("metrics") or {})
    has_orientation=bool(metrics.get("orientation/enabled") or metrics.get("orientation/model_path") or metrics.get("orientation/meta_path"))
    files={"artifacts/model.pth":checkpoint.read_bytes(),"artifacts/config.py":_portable_config(config)}
    if has_orientation:
        for key,name in (("orientation/model_path","orientation_model.pth"),("orientation/meta_path","orientation.json")):
            path=project.root/str(metrics.get(key) or "")
            if not path.is_file() or not path.stat().st_size:raise XRayCropPackageError("Orientation artifact is incomplete.")
            files["artifacts/"+name]=path.read_bytes()
    safe_metrics={k:v for k,v in metrics.items() if not str(k).endswith(("_path","/model_path","/meta_path")) and k not in {"training_membership","validation_membership"}}
    safe_metrics["orientation/enabled"]=has_orientation
    manifest={"package_format":PACKAGE_FORMAT,"model_id":model["model_id"],"backend":BACKEND,"inference_contract":INFERENCE_CONTRACT,"orientation":has_orientation,"parent_model_id":model.get("parent_model_id"),"training_specimen_count":model.get("training_specimen_count",0),"training_plate_count":model.get("training_plate_count",0),"metrics":safe_metrics,"files":{n:_hash(d) for n,d in files.items()}}
    manifest["trait_scheme"]=project.scheme
    manifest["trait_scheme_sha256"]=_hash(json.dumps(project.scheme,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8"))
    manifest["orientation_policy"]=project.orientation_policy
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
        archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2))
    return target


def import_crop_model_package(project,source):
    try:
        with zipfile.ZipFile(source) as archive:
            manifest=json.loads(archive.read("manifest.json"))
            if manifest.get("package_format")!=PACKAGE_FORMAT or manifest.get("backend")!=BACKEND:raise XRayCropPackageError("Wrong X-ray Crop model package type/backend.")
            if manifest.get("inference_contract")!=INFERENCE_CONTRACT:raise XRayCropPackageError("Unsupported Crop inference contract.")
            scheme=manifest.get("trait_scheme")
            if scheme is not None:
                from .xray_schema import normalize_scheme
                if _hash(json.dumps(scheme,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8"))!=manifest.get("trait_scheme_sha256"):raise XRayCropPackageError("Trait scheme checksum mismatch.")
                normalize_scheme(scheme)
            if bool((manifest.get("metrics") or {}).get("orientation/enabled"))!=bool(manifest.get("orientation")):raise XRayCropPackageError("Orientation metadata and artifact declaration disagree.")
            names={"artifacts/model.pth","artifacts/config.py"}
            if manifest.get("orientation"):names|={"artifacts/orientation_model.pth","artifacts/orientation.json"}
            expected=manifest.get("files") or {}
            if set(expected)!=names or set(archive.namelist())!=names|{"manifest.json"} or len(archive.namelist())!=len(names)+1:raise XRayCropPackageError("Unexpected or missing Crop artifacts / unsafe package path.")
            payload={}
            for name,digest in expected.items():
                data=archive.read(name)
                if not data or _hash(data)!=digest:raise XRayCropPackageError(f"Checksum mismatch or empty artifact: {name}")
                payload[name]=data
            ast.parse(payload["artifacts/config.py"].decode("utf-8"))
            if manifest.get("orientation"):
                info=json.loads(payload["artifacts/orientation.json"])
                from .xray_orientation import ORIENTATION_BACKEND
                if info.get("backend")!=ORIENTATION_BACKEND:raise XRayCropPackageError("Unsupported orientation backend.")
    except (OSError,ValueError,KeyError,SyntaxError,zipfile.BadZipFile) as exc:
        if isinstance(exc,XRayCropPackageError):raise
        raise XRayCropPackageError(f"Invalid X-ray Crop model package: {exc}") from exc
    original=str(manifest.get("model_id") or "")
    if not _SAFE_ID.fullmatch(original) or original.endswith("."):raise XRayCropPackageError("Unsafe Crop model ID.")
    existing={m["model_id"] for m in project.crop_models()};local=original;counter=2
    while local in existing or (project.models_root/local).exists():local=f"imported_{original}_{counter}";counter+=1
    destination=project.models_root/local
    with staged_model_directory(destination) as (staging,publish):
        for name,data in payload.items():(staging/Path(name).name).write_bytes(data)
        metrics={**dict(manifest.get("metrics") or {}),"origin":"imported","original_model_id":original,"original_parent_model_id":manifest.get("parent_model_id"),"package_manifest":manifest,"previous_orientation_policy":project.orientation_policy}
        if manifest.get("orientation"):
            metrics.update({"orientation/enabled":True,"orientation/model_path":str((destination/"orientation_model.pth").relative_to(project.root)),"orientation/meta_path":str((destination/"orientation.json").relative_to(project.root))})
        if any(item["model_id"]==local for item in project.crop_models()):raise FileExistsError(local)
        publish()
        project.register_crop_model(local,str((destination/"model.pth").relative_to(project.root)),str((destination/"config.py").relative_to(project.root)),None,metrics,(),int(manifest.get("training_specimen_count") or 0),activate=True,trait_scheme=scheme,orientation_policy=manifest.get("orientation_policy"))
    return local
