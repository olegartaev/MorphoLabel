"""Train and run the project-local multi-specimen X-ray crop detector."""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

from PIL import Image

from .ai_delivery import ensure_ai_runtime
from .ai_hardware import get_hardware_profile, get_inference_config, get_training_config, is_cuda_oom
from .process_utils import hidden_window_kwargs
from .runtime_paths import resource_path
from .xray_crop import HYBRID_ALGORITHM_VERSION, detect_specimens, display_preview, merge_detector_proposals, proposals_from_detector_boxes
from .xray_orientation import predict_orientation_batch, train_orientation_model

DETECTOR_BACKEND="rtmdet_tiny_mmdet_3_2"
RTMDET_TINY_COCO_URL="https://download.openmmlab.com/mmdetection/v3.0/rtmdet/rtmdet_tiny_8xb32-300e_coco/rtmdet_tiny_8xb32-300e_coco_20220902_112414-78e30dcc.pth"
DATASET_MAX_DIM=1800
MIN_TRAINING_PLATES=3

def detector_performance_settings(hardware=None):
    """Use the persisted first-run hardware profile for X-ray AI defaults."""
    hardware=hardware or get_hardware_profile()
    training=get_training_config(hardware=hardware)
    inference=get_inference_config(hardware=hardware).copy()
    # The managed mmcv NMS extension used by this detector expects Float
    # tensors. CUDA autocast makes RTMDet predictions Half before NMS and
    # fails with "expected scalar type Float but found Half". Keep AMP for
    # training (the expensive path), but use batched FP32 inference.
    inference["mixed_precision"]=False
    return {"hardware":hardware.as_dict(),"training":training,"inference":inference}

def _run(runtime,mode,payload,timeout):
    runner=resource_path("ai_runtime","xray_detector_runner.py")
    if not runner.is_file():raise RuntimeError(f"X-ray detector runner is unavailable: {runner}")
    result=subprocess.run([str(runtime),str(runner),str(mode)],input=json.dumps(payload),text=True,capture_output=True,check=False,timeout=timeout,**hidden_window_kwargs())
    if result.returncode:
        detail=(result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"X-ray detector {mode} failed: {detail[-4000:]}")
    try:return json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
    except (ValueError,StopIteration) as exc:raise RuntimeError("X-ray detector returned invalid JSON") from exc

def runtime_info(project=None):
    runtime,_=ensure_ai_runtime(project=project)
    return _run(runtime,"info",{},120)

def _dataset_preview(project,image_id,target):
    preview,scale,original_size=display_preview(project.source_image_path(image_id),DATASET_MAX_DIM)
    target.parent.mkdir(parents=True,exist_ok=True)
    preview.convert("RGB").save(target,format="PNG")
    return scale,original_size,preview.size

def prepare_training_dataset(project,model_id,seed=42,workspace_root=None):
    plates=project.training_plates()
    if len(plates)<MIN_TRAINING_PLATES:
        raise ValueError(f"Need at least {MIN_TRAINING_PLATES} human-confirmed X-ray plates before training.")
    rng=random.Random(int(seed));order=list(plates);rng.shuffle(order)
    val_n=max(1,round(len(order)*0.2));val_ids={row["image_id"] for row in order[:val_n]}
    root=Path(workspace_root) if workspace_root is not None else project.cache_root/"xray_training"/model_id
    root=root/"dataset";images=root/"images";images.mkdir(parents=True,exist_ok=True)
    groups={"train":{"images":[],"annotations":[]},"val":{"images":[],"annotations":[]}}
    ann_id=1
    for image_index,row in enumerate(plates,1):
        name=f"{image_index:05d}_{row['image_id']}.png";path=images/name
        scale,_original,preview_size=_dataset_preview(project,row["image_id"],path)
        group=groups["val" if row["image_id"] in val_ids else "train"]
        coco_image_id=image_index
        group["images"].append({"id":coco_image_id,"file_name":f"images/{name}","width":preview_size[0],"height":preview_size[1]})
        for specimen in row["specimens"]:
            bounds=(specimen.get("crop") or {}).get("bounds") or ()
            if len(bounds)!=4:continue
            x0,y0,x1,y1=[float(v)*scale for v in bounds]
            x0=max(0.0,min(preview_size[0]-1.0,x0));y0=max(0.0,min(preview_size[1]-1.0,y0))
            x1=max(x0+1.0,min(float(preview_size[0]),x1));y1=max(y0+1.0,min(float(preview_size[1]),y1))
            w=x1-x0;h=y1-y0
            group["annotations"].append({"id":ann_id,"image_id":coco_image_id,"category_id":1,"bbox":[x0,y0,w,h],"area":w*h,"iscrowd":0})
            ann_id+=1
    categories=[{"id":1,"name":"specimen"}]
    paths={}
    for key,payload in groups.items():
        data={"images":payload["images"],"annotations":payload["annotations"],"categories":categories}
        path=root/f"{key}.json";path.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8");paths[key]=path
    if not groups["train"]["annotations"] or not groups["val"]["annotations"]:
        raise ValueError("Training and validation splits both need at least one confirmed specimen.")
    return {
        "root":root,"train_json":paths["train"],"val_json":paths["val"],
        "plate_ids":[row["image_id"] for row in plates],
        "training_specimens":sum(len(row["specimens"]) for row in plates),
        "train_plates":len(groups["train"]["images"]),"val_plates":len(groups["val"]["images"]),
    }

def train_detector(project,seed=42,epochs=80,progress=None,parent_model_id=None):
    project.compact_disposable_ai_artifacts()
    if parent_model_id is None:
        parent=project.active_crop_model()
    elif not str(parent_model_id):
        parent=None
    else:
        parent=next((item for item in project.crop_models() if item["model_id"]==str(parent_model_id)),None)
        if parent is None:raise KeyError(f"Unknown X-ray Crop parent model: {parent_model_id}")
    model_id=project.next_crop_model_id();directory=project.models_root/model_id
    performance=detector_performance_settings();hardware_settings=performance["hardware"];settings=performance["training"]
    runtime,_=ensure_ai_runtime(project=project,progress=progress)
    parent_checkpoint=(str(project.root/parent["path"]) if parent else RTMDET_TINY_COCO_URL)
    with tempfile.TemporaryDirectory(prefix=f"morpholabel_xray_train_{model_id}_") as scratch:
        scratch=Path(scratch)
        dataset=prepare_training_dataset(project,model_id,seed=seed,workspace_root=scratch)
        if progress:progress("TRAINING",f"Training {model_id} from {len(dataset['plate_ids'])} confirmed plates…")
        base_batch=max(1,int(settings["batch_size"]))
        batch_attempts=[];value=base_batch
        while value>=1:
            if value not in batch_attempts:batch_attempts.append(value)
            if value==1:break
            value=max(1,value//2)
        result=None;used_batch=None
        for attempt_index,batch_size in enumerate(batch_attempts):
            payload={
                "dataset_root":str(dataset["root"]),"train_json":str(dataset["train_json"]),"val_json":str(dataset["val_json"]),
                "work_dir":str(scratch/f"work_b{batch_size}"),"device":settings["device"],"batch_size":batch_size,
                "workers":max(0,int(settings["workers"])),"epochs":int(epochs),"seed":int(seed),
                "mixed_precision":bool(settings.get("mixed_precision")),"pin_memory":bool(settings.get("pin_memory")),
                "persistent_workers":bool(settings.get("persistent_workers")),"initial_checkpoint":parent_checkpoint,
            }
            try:
                result=_run(runtime,"train",payload,7200);used_batch=batch_size;break
            except RuntimeError as exc:
                if not is_cuda_oom(exc) or attempt_index==len(batch_attempts)-1:raise
                if progress:progress("AUTO PERFORMANCE",f"GPU memory limit at batch {batch_size}; retrying with batch {batch_attempts[attempt_index+1]}…")
        if result is None or used_batch is None:raise RuntimeError("X-ray detector training did not complete.")
        checkpoint=Path(result["checkpoint"]);config=Path(result["config"])
        if not checkpoint.is_file() or not config.is_file():raise RuntimeError("X-ray detector training finished without a loadable model artifact.")
        directory.mkdir(parents=True,exist_ok=True)
        final_checkpoint=directory/"model.pth";final_config=directory/"config.py"
        shutil.copy2(checkpoint,final_checkpoint);shutil.copy2(config,final_config)
        metrics={"backend":DETECTOR_BACKEND,"epochs":int(epochs),"device":settings["device"],"train_plates":dataset["train_plates"],"val_plates":dataset["val_plates"],
                 "initialization":(parent or {}).get("model_id") or "rtmdet_tiny_coco_pretrained","batch_size":used_batch,
                 "workers":int(settings.get("workers") or 0),"mixed_precision":bool(settings.get("mixed_precision")),
                 "hardware":hardware_settings,**dict(result.get("metrics") or {})}
        metrics.update(train_orientation_model(project,model_id,directory,runtime,settings,seed=seed,progress=progress))
        training_plate_ids=list(dataset["plate_ids"]);training_specimens=int(dataset["training_specimens"])
    project.register_crop_model(model_id,str(final_checkpoint.relative_to(project.root)),str(final_config.relative_to(project.root)),
                                (parent or {}).get("model_id"),metrics,training_plate_ids,training_specimens,activate=True)
    project.compact_disposable_ai_artifacts()
    return {"trained":True,"model_id":model_id,"metrics":metrics,"training_plates":len(training_plate_ids),"training_specimens":training_specimens}

def _prediction_input(project,image_id,target):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    preview,scale,original_size=display_preview(project.source_image_path(image_id),DATASET_MAX_DIM)
    preview.convert("RGB").save(target,format="PNG")
    return target,scale,original_size

def _prediction_proposals(project,image_id,scale,detections):
    boxes=[]
    for item in detections or []:
        bbox=item.get("bbox") or []
        if len(bbox)!=4:continue
        boxes.append({"bbox":[float(v)/scale for v in bbox],"score":float(item.get("score",0.0))})
    source_path=project.source_image_path(image_id)
    rtmdet=proposals_from_detector_boxes(source_path,boxes)
    heuristic=detect_specimens(source_path)
    return merge_detector_proposals(heuristic,rtmdet)


def _save_prediction(project,model,image_id,proposals):
    saved=project.replace_model_proposals(image_id,proposals,model["model_id"],algorithm=HYBRID_ALGORITHM_VERSION)
    agreed=sum(1 for item in proposals if (item.get("detector_provenance") or {}).get("mode")=="agreed")
    review=sum(1 for item in proposals if str(item.get("confidence"))=="review")
    return {"image_id":image_id,"detections":len(proposals),"agreed":agreed,"review":review,
            "model_id":model["model_id"],"algorithm":HYBRID_ALGORITHM_VERSION,"saved":saved}

def predict_plate(project,image_id,model=None,score_threshold=0.25):
    model=model or project.active_crop_model()
    if not model:raise RuntimeError("Train an X-ray crop model before prediction.")
    result=predict_plates(project,[image_id],score_threshold=score_threshold,model=model)
    if result["success"]:return result["results"][0]
    failure=(result.get("failures") or [{"reason":"X-ray prediction failed"}])[0]
    raise RuntimeError(failure.get("reason") or "X-ray prediction failed")

def predict_plates(project,image_ids,cancel=None,progress=None,score_threshold=0.25,model=None):
    model=model or project.active_crop_model()
    if not model:raise RuntimeError("Train an X-ray crop model before prediction.")
    ids=list(image_ids);success=[];failures=[];runtime,_=ensure_ai_runtime(project=project)
    settings=detector_performance_settings()["inference"];chunk_size=max(1,int(settings.get("batch_size") or 1));index=0
    project.compact_disposable_ai_artifacts()
    with tempfile.TemporaryDirectory(prefix="morpholabel_xray_predict_") as scratch:
        scratch=Path(scratch)
        while index<len(ids):
            if cancel is not None and cancel.is_set():break
            chunk=ids[index:index+chunk_size];prepared=[]
            for image_id in chunk:
                try:
                    path,scale,_original=_prediction_input(project,image_id,scratch/f"{image_id}.png");prepared.append((image_id,path,scale))
                except Exception as exc:
                    failures.append({"image_id":image_id,"reason":f"{type(exc).__name__}: {exc}"})
                    if progress:progress(index+len(prepared)+1,len(ids),image_id)
            if not prepared:
                index+=len(chunk);continue
            payload={
                "config":str(project.root/model["config_path"]),"checkpoint":str(project.root/model["path"]),
                "images":[str(path) for _image_id,path,_scale in prepared],"device":settings["device"],
                "score_threshold":float(score_threshold),"mixed_precision":bool(settings.get("mixed_precision")),
            }
            try:
                result=_run(runtime,"predict_many",payload,max(600,120*len(prepared)))
            except RuntimeError as exc:
                if is_cuda_oom(exc) and chunk_size>1:
                    chunk_size=max(1,chunk_size//2)
                    if progress:progress(index,len(ids),f"GPU memory limit; retrying with batch {chunk_size}")
                    continue
                reason=f"{type(exc).__name__}: {exc}"
                for image_id,_path,_scale in prepared:failures.append({"image_id":image_id,"reason":reason})
                index+=len(chunk);continue
            returned=list(result.get("results") or []);pending=[]
            for offset,(image_id,_path,scale) in enumerate(prepared):
                row=returned[offset] if offset<len(returned) else {"error":"missing prediction result"}
                if row.get("error"):failures.append({"image_id":image_id,"reason":str(row["error"])})
                else:
                    try:pending.append({"image_id":image_id,"proposals":_prediction_proposals(project,image_id,scale,row.get("detections") or [])})
                    except Exception as exc:failures.append({"image_id":image_id,"reason":f"{type(exc).__name__}: {exc}"})
            if pending:
                try:
                    pending=predict_orientation_batch(project,model,pending,runtime,scratch,settings)
                    for item in pending:success.append(_save_prediction(project,model,item["image_id"],item["proposals"]))
                except Exception as exc:
                    reason=f"{type(exc).__name__}: {exc}"
                    for item in pending:failures.append({"image_id":item["image_id"],"reason":reason})
            for offset,(image_id,_path,_scale) in enumerate(prepared):
                if progress:progress(index+offset+1,len(ids),image_id)
            index+=len(chunk)
    return {"success":len(success),"successful_ids":[row["image_id"] for row in success],"failures":failures,
            "model_id":model["model_id"],"results":success,"inference_batch_size":chunk_size}
