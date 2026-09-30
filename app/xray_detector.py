"""Train and run the project-local multi-specimen X-ray crop detector."""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import shutil
import subprocess

from PIL import Image

from .ai_delivery import ensure_ai_runtime
from .ai_hardware import get_hardware_profile, get_inference_config, get_training_config
from .process_utils import hidden_window_kwargs
from .runtime_paths import resource_path
from .xray_crop import display_preview, proposals_from_detector_boxes

DETECTOR_BACKEND="rtmdet_tiny_mmdet_3_2"
RTMDET_TINY_COCO_URL="https://download.openmmlab.com/mmdetection/v3.0/rtmdet/rtmdet_tiny_8xb32-300e_coco/rtmdet_tiny_8xb32-300e_coco_20220902_112414-78e30dcc.pth"
DATASET_MAX_DIM=1800
MIN_TRAINING_PLATES=3

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

def prepare_training_dataset(project,model_id,seed=42):
    plates=project.training_plates()
    if len(plates)<MIN_TRAINING_PLATES:
        raise ValueError(f"Need at least {MIN_TRAINING_PLATES} human-confirmed X-ray plates before training.")
    rng=random.Random(int(seed));order=list(plates);rng.shuffle(order)
    val_n=max(1,round(len(order)*0.2));val_ids={row["image_id"] for row in order[:val_n]}
    root=project.models_root/model_id/"dataset";images=root/"images";images.mkdir(parents=True,exist_ok=True)
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

def train_detector(project,seed=42,epochs=80,progress=None):
    model_id=project.next_crop_model_id();parent=project.active_crop_model();directory=project.models_root/model_id
    dataset=prepare_training_dataset(project,model_id,seed=seed)
    hardware=get_hardware_profile();settings=get_training_config(hardware=hardware)
    runtime,_=ensure_ai_runtime(project=project,progress=progress)
    if progress:progress("TRAINING",f"Training {model_id} from {len(dataset['plate_ids'])} confirmed plates…")
    parent_checkpoint=(str(project.root/parent["path"]) if parent else RTMDET_TINY_COCO_URL)
    payload={
        "dataset_root":str(dataset["root"]),"train_json":str(dataset["train_json"]),"val_json":str(dataset["val_json"]),
        "work_dir":str(directory/"work"),"device":settings["device"],"batch_size":int(settings["batch_size"]),
        "workers":max(0,int(settings["workers"])),"epochs":int(epochs),"seed":int(seed),
        "initial_checkpoint":parent_checkpoint,
    }
    result=_run(runtime,"train",payload,7200)
    checkpoint=Path(result["checkpoint"]);config=Path(result["config"])
    if not checkpoint.is_file() or not config.is_file():raise RuntimeError("X-ray detector training finished without a loadable model artifact.")
    final_checkpoint=directory/"model.pth";final_config=directory/"config.py"
    shutil.copy2(checkpoint,final_checkpoint);shutil.copy2(config,final_config)
    metrics={"backend":DETECTOR_BACKEND,"epochs":int(epochs),"device":settings["device"],"train_plates":dataset["train_plates"],"val_plates":dataset["val_plates"],
             "initialization":(parent or {}).get("model_id") or "rtmdet_tiny_coco_pretrained",**dict(result.get("metrics") or {})}
    project.register_crop_model(model_id,str(final_checkpoint.relative_to(project.root)),str(final_config.relative_to(project.root)),
                                (parent or {}).get("model_id"),metrics,dataset["plate_ids"],dataset["training_specimens"],activate=True)
    return {"trained":True,"model_id":model_id,"metrics":metrics,"training_plates":len(dataset["plate_ids"]),"training_specimens":dataset["training_specimens"]}

def _prediction_input(project,image_id):
    target=project.cache_root/"xray_detector"/f"{image_id}.png";target.parent.mkdir(parents=True,exist_ok=True)
    preview,scale,original_size=display_preview(project.source_image_path(image_id),DATASET_MAX_DIM)
    preview.convert("RGB").save(target,format="PNG")
    return target,scale,original_size

def predict_plate(project,image_id,model=None,score_threshold=0.25):
    model=model or project.active_crop_model()
    if not model:raise RuntimeError("Train an X-ray crop model before prediction.")
    runtime,_=ensure_ai_runtime(project=project)
    image_path,scale,_original=_prediction_input(project,image_id)
    payload={
        "config":str(project.root/model["config_path"]),"checkpoint":str(project.root/model["path"]),
        "image":str(image_path),"device":get_inference_config()["device"],"score_threshold":float(score_threshold),
    }
    result=_run(runtime,"predict",payload,600)
    boxes=[]
    for item in result.get("detections") or []:
        bbox=item.get("bbox") or []
        if len(bbox)!=4:continue
        boxes.append({"bbox":[float(v)/scale for v in bbox],"score":float(item.get("score",0.0))})
    proposals=proposals_from_detector_boxes(project.source_image_path(image_id),boxes)
    saved=project.replace_model_proposals(image_id,proposals,model["model_id"])
    return {"image_id":image_id,"detections":len(proposals),"model_id":model["model_id"],"saved":saved}

def predict_plates(project,image_ids,cancel=None,progress=None):
    model=project.active_crop_model()
    if not model:raise RuntimeError("Train an X-ray crop model before prediction.")
    ids=list(image_ids);success=[];failures=[]
    for index,image_id in enumerate(ids,1):
        if cancel is not None and cancel.is_set():break
        try:
            result=predict_plate(project,image_id,model=model);success.append(result)
        except Exception as exc:failures.append({"image_id":image_id,"reason":f"{type(exc).__name__}: {exc}"})
        if progress:progress(index,len(ids),image_id)
    return {"success":len(success),"successful_ids":[row["image_id"] for row in success],"failures":failures,"model_id":model["model_id"]}
