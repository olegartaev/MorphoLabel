"""Project-local orientation learning for X-ray specimen crops.

Detector geometry and anatomical orientation remain separate modules: the detector
finds specimens, while this learner predicts which aligned crop edge is head and
which long edge is ventral. Human confirmation remains the source of truth.
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import shutil
import subprocess

import numpy as np
from PIL import Image

from .process_utils import hidden_window_kwargs
from .runtime_paths import resource_path
from .ai_starters import local_starter
from .xray_crop import aligned_crop, apply_orientation_defaults, normalize_orientation_policy

ORIENTATION_BACKEND="mobilenet_v3_small_imagenet_transfer_v1"
ORIENTATION_INPUT_SIZE=224
ORIENTATION_CONFIDENCE_THRESHOLD=0.65
MIN_ORIENTATION_SPECIMENS=6


def _run(runtime,mode,payload,timeout):
    runner=resource_path("ai_runtime","xray_orientation_runner.py")
    if not runner.is_file():raise RuntimeError(f"X-ray orientation runner is unavailable: {runner}")
    result=subprocess.run(
        [str(runtime),str(runner),str(mode)],input=json.dumps(payload),text=True,capture_output=True,
        check=False,timeout=timeout,**hidden_window_kwargs(),
    )
    if result.returncode:
        detail=(result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"X-ray orientation {mode} failed: {detail[-4000:]}")
    try:return json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
    except (ValueError,StopIteration) as exc:raise RuntimeError("X-ray orientation runner returned invalid JSON") from exc


def _display_ready(image):
    arr=np.asarray(image)
    if arr.ndim==3:arr=arr[...,:3].astype(np.float32).mean(axis=2)
    else:arr=arr.astype(np.float32)
    lo,hi=np.percentile(arr,(0.5,99.5))
    if hi<=lo:scaled=np.zeros(arr.shape,dtype=np.uint8)
    else:scaled=np.clip((arr-lo)/(hi-lo)*255.0,0,255).astype(np.uint8)
    return Image.fromarray(scaled).convert("RGB")


def _variant_rows(base_path,image,head_right,bottom_down):
    variants=(
        ("base",image,head_right,bottom_down),
        ("h",image.transpose(Image.Transpose.FLIP_LEFT_RIGHT),1-head_right,bottom_down),
        ("v",image.transpose(Image.Transpose.FLIP_TOP_BOTTOM),head_right,1-bottom_down),
        ("hv",image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).transpose(Image.Transpose.FLIP_TOP_BOTTOM),1-head_right,1-bottom_down),
    )
    rows=[]
    for suffix,picture,head,bottom in variants:
        path=base_path.with_name(base_path.stem+"_"+suffix+base_path.suffix);picture.save(path,format="PNG")
        rows.append({"path":str(path),"head":int(head),"bottom":int(bottom)})
    return rows


def prepare_orientation_dataset(project,root,seed=42):
    policy=normalize_orientation_policy(project.orientation_policy)
    axes={"head":policy["head"]!="none","bottom":policy["bottom"]!="none"}
    truth=list(project.orientation_training_rows())
    if not any(axes.values()):
        return {"enabled":False,"reason":"orientation_not_standardized","axes":axes,"training_specimens":0}
    if len(truth)<MIN_ORIENTATION_SPECIMENS:
        return {"enabled":False,"reason":"not_enough_verified_orientation","axes":axes,"training_specimens":len(truth)}
    by_plate={}
    for row in truth:by_plate.setdefault(str(row["image_id"]),[]).append(row)
    plate_ids=sorted(by_plate)
    if len(plate_ids)<2:
        return {"enabled":False,"reason":"need_two_verified_plates","axes":axes,"training_specimens":len(truth)}
    rng=random.Random(int(seed));rng.shuffle(plate_ids)
    val_n=max(1,round(len(plate_ids)*0.2));val_ids=set(plate_ids[:val_n])
    root=Path(root);images=root/"images";images.mkdir(parents=True,exist_ok=True)
    groups={"train":[],"val":[]};counter=0
    for image_id in plate_ids:
        source_path=project.source_image_path(image_id)
        with Image.open(source_path) as source:
            source.load()
            for row in by_plate[image_id]:
                crop=apply_orientation_defaults(row.get("crop") or {},policy)
                picture=_display_ready(aligned_crop(source,crop))
                head_right=1 if crop.get("head_side")=="right" else 0
                bottom_down=1 if crop.get("bottom_side")=="bottom" else 0
                counter+=1;base=images/f"{counter:05d}.png"
                groups["val" if image_id in val_ids else "train"].extend(_variant_rows(base,picture,head_right,bottom_down))
    manifest={"backend":ORIENTATION_BACKEND,"input_size":ORIENTATION_INPUT_SIZE,"axes":axes,"train":groups["train"],"val":groups["val"]}
    path=root/"orientation_manifest.json";path.write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")
    return {
        "enabled":True,"manifest":path,"axes":axes,"training_specimens":len(truth),
        "train_examples":len(groups["train"]),"val_examples":len(groups["val"]),
    }


def train_orientation_model(project,model_id,directory,runtime,settings,seed=42,progress=None):
    directory=Path(directory);scratch=directory.parent/f".{model_id}_orientation_tmp"
    shutil.rmtree(scratch,ignore_errors=True);scratch.mkdir(parents=True,exist_ok=True)
    try:
        dataset=prepare_orientation_dataset(project,scratch,seed)
        if not dataset.get("enabled"):
            return {
                "orientation/enabled":False,"orientation/reason":dataset.get("reason","disabled"),
                "orientation/training_specimens":int(dataset.get("training_specimens") or 0),
            }
        if progress:progress("ORIENTATION",f"Learning head / ventral side from {dataset['training_specimens']} verified crops…")
        result=_run(runtime,"train_orientation",{
            "pretrained_checkpoint":local_starter("orientation"),
            "manifest":str(dataset["manifest"]),"work_dir":str(scratch/"work"),
            "device":settings["device"],"seed":int(seed),"epochs":20,
            "mixed_precision":bool(settings.get("mixed_precision")),
        },3600)
        checkpoint=Path(result["checkpoint"]);meta=Path(result["meta"])
        if not checkpoint.is_file() or not meta.is_file():raise RuntimeError("Orientation training finished without a model artifact.")
        directory.mkdir(parents=True,exist_ok=True)
        final_checkpoint=directory/"orientation_model.pth";final_meta=directory/"orientation.json"
        shutil.copy2(checkpoint,final_checkpoint);shutil.copy2(meta,final_meta)
        metrics={
            "orientation/enabled":True,"orientation/backend":ORIENTATION_BACKEND,
            "orientation/training_specimens":dataset["training_specimens"],
            "orientation/train_examples":dataset["train_examples"],"orientation/val_examples":dataset["val_examples"],
            "orientation/model_path":str(final_checkpoint.relative_to(project.root)),
            "orientation/meta_path":str(final_meta.relative_to(project.root)),
            **dict(result.get("metrics") or {}),
        }
        return metrics
    finally:shutil.rmtree(scratch,ignore_errors=True)


def apply_orientation_prediction(crop,prediction,policy,model_id="",threshold=ORIENTATION_CONFIDENCE_THRESHOLD):
    value=apply_orientation_defaults(crop,policy);policy=normalize_orientation_policy(policy)
    confidences={};uncertain=[]
    if policy["head"]!="none" and "head_right_probability" in prediction:
        p=float(prediction["head_right_probability"]);value["head_side"]="right" if p>=0.5 else "left"
        confidences["head"]=max(p,1.0-p)
        if confidences["head"]<float(threshold):uncertain.append("head")
    if policy["bottom"]!="none" and "bottom_down_probability" in prediction:
        p=float(prediction["bottom_down_probability"]);value["bottom_side"]="bottom" if p>=0.5 else "top"
        confidences["bottom"]=max(p,1.0-p)
        if confidences["bottom"]<float(threshold):uncertain.append("bottom")
    value["orientation_source"]="model_review" if uncertain else "model"
    value["orientation_model_id"]=str(model_id or "")
    value["orientation_confidence"]=confidences;value["orientation_verified"]=False
    qc=list(value.get("qc") or ())
    if uncertain and "orientation_uncertain" not in qc:qc.append("orientation_uncertain")
    value["qc"]=qc
    if uncertain:value["confidence"]="review"
    return value


def predict_orientation_batch(project,model,items,runtime,scratch,settings):
    metrics=dict(model.get("metrics") or {})
    model_path=str(metrics.get("orientation/model_path") or "")
    meta_path=str(metrics.get("orientation/meta_path") or "")
    if not model_path or not meta_path:return items
    checkpoint=project.root/model_path;meta=project.root/meta_path
    if not checkpoint.is_file() or not meta.is_file():raise RuntimeError("The active crop model is missing its orientation component.")
    image_paths=[];references=[];root=Path(scratch)/"orientation";root.mkdir(parents=True,exist_ok=True)
    for plate_index,item in enumerate(items):
        image_id=item["image_id"];proposals=list(item.get("proposals") or ())
        with Image.open(project.source_image_path(image_id)) as source:
            source.load()
            for proposal_index,proposal in enumerate(proposals):
                path=root/f"{plate_index:03d}_{proposal_index:03d}.png"
                _display_ready(aligned_crop(source,proposal)).save(path,format="PNG")
                image_paths.append(str(path));references.append((item,proposal_index))
    if not image_paths:return items
    result=_run(runtime,"predict_orientation_many",{
        "checkpoint":str(checkpoint),"meta":str(meta),"images":image_paths,
        "device":settings["device"],"batch_size":max(1,min(64,int(settings.get("batch_size") or 8))),
    },max(300,20*len(image_paths)))
    predictions=list(result.get("results") or ())
    if len(predictions)!=len(references):raise RuntimeError("Orientation model returned an incomplete prediction batch.")
    for prediction,(item,index) in zip(predictions,references):
        item["proposals"][index]=apply_orientation_prediction(
            item["proposals"][index],prediction,project.orientation_policy,model.get("model_id",""),
            float(result.get("threshold") or ORIENTATION_CONFIDENCE_THRESHOLD),
        )
    return items
