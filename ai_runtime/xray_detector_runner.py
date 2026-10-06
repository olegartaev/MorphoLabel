"""Isolated MMDetection runner for the MorphoLabel X-ray multi-object crop detector."""
from __future__ import annotations

import json
from pathlib import Path
import sys

def _input():
    raw=sys.stdin.read().strip()
    return json.loads(raw) if raw else {}

def _config_path():
    import mmdet
    root=Path(mmdet.__file__).resolve().parent
    candidates=(
        root/".mim"/"configs"/"rtmdet"/"rtmdet_tiny_8xb32-300e_coco.py",
        root.parent/"configs"/"rtmdet"/"rtmdet_tiny_8xb32-300e_coco.py",
    )
    for path in candidates:
        if path.is_file():return path
    raise RuntimeError("MMDetection RTMDet-tiny config is not installed in the managed AI runtime")

def info():
    import torch, mmdet, mmengine
    path=_config_path()
    return {"torch":torch.__version__,"mmdet":mmdet.__version__,"mmengine":mmengine.__version__,
            "cuda_available":bool(torch.cuda.is_available()),"config":str(path)}

def _dataset(dataset_root,ann_file,pipeline):
    return dict(type="CocoDataset",data_root=str(dataset_root)+"/",ann_file=Path(ann_file).name,
                data_prefix=dict(img=""),metainfo=dict(classes=("specimen",),palette=[(0,255,0)]),
                filter_cfg=dict(filter_empty_gt=False,min_size=1),pipeline=pipeline)

def _best_validation_metrics(work):
    """Read the best detector validation row written by MMEngine without rerunning inference."""
    best={};best_score=None
    for path in sorted(Path(work).rglob("scalars.json")):
        try:lines=path.read_text(encoding="utf-8").splitlines()
        except OSError:continue
        for line in lines:
            try:row=json.loads(line)
            except (TypeError,ValueError):continue
            score=row.get("coco/bbox_mAP")
            if not isinstance(score,(int,float)):continue
            if best_score is None or float(score)>best_score:
                best_score=float(score);best={}
                for key in ("coco/bbox_mAP","coco/bbox_mAP_50","coco/bbox_mAP_75","coco/bbox_mAP_s","coco/bbox_mAP_m","coco/bbox_mAP_l"):
                    value=row.get(key)
                    if isinstance(value,(int,float)):best[key]=float(value)
    return best


def _configure_initial_checkpoint(cfg, checkpoint):
    """The full detector checkpoint supplies the backbone as well as the neck.

    Upstream Tiny config otherwise downloads a second ImageNet backbone during
    init_weights(), before MMEngine loads our local full detector checkpoint.
    """
    cfg.model.backbone.init_cfg = None
    cfg.model.init_cfg = None
    cfg.load_from = checkpoint


def train(payload):
    import torch
    from mmengine.config import Config
    from mmengine.runner import Runner
    cfg=Config.fromfile(str(_config_path()))
    work=Path(payload["work_dir"]);work.mkdir(parents=True,exist_ok=True)
    root=Path(payload["dataset_root"])
    epochs=max(10,int(payload.get("epochs",80)));batch=max(1,int(payload.get("batch_size",2)));workers=max(0,int(payload.get("workers",0)))
    device=str(payload.get("device") or ("cuda:0" if torch.cuda.is_available() else "cpu"))
    # Never let scale augmentation exceed the final padded size. The previous
    # 1.2 upper ratio could produce e.g. 696 px tensors; RTMDet's CSPNeXt PAFPN
    # then received 88-vs-87 feature maps and failed during concatenation.
    simple_train=[
        dict(type="LoadImageFromFile"),
        dict(type="LoadAnnotations",with_bbox=True),
        dict(type="RandomResize",scale=(640,640),ratio_range=(0.8,1.0),keep_ratio=True),
        dict(type="RandomFlip",prob=0.5),
        dict(type="Pad",size=(640,640),pad_val=dict(img=(114,114,114))),
        dict(type="PackDetInputs"),
    ]
    simple_val=[
        dict(type="LoadImageFromFile"),
        dict(type="LoadAnnotations",with_bbox=True),
        dict(type="Resize",scale=(640,640),keep_ratio=True),
        dict(type="Pad",size=(640,640),pad_val=dict(img=(114,114,114))),
        dict(type="PackDetInputs",meta_keys=("img_id","img_path","ori_shape","img_shape","scale_factor")),
    ]
    simple_infer=[
        dict(type="LoadImageFromFile"),
        dict(type="Resize",scale=(640,640),keep_ratio=True),
        dict(type="Pad",size=(640,640),pad_val=dict(img=(114,114,114))),
        dict(type="PackDetInputs",meta_keys=("img_id","img_path","ori_shape","img_shape","scale_factor")),
    ]
    cfg.model.bbox_head.num_classes=1
    cfg.model.data_preprocessor.pad_size_divisor=32
    initial_checkpoint=str(payload.get("initial_checkpoint") or "").strip()
    if not initial_checkpoint:raise ValueError("X-ray detector training requires an initial pretrained or parent checkpoint")
    _configure_initial_checkpoint(cfg,initial_checkpoint)
    cfg.work_dir=str(work);cfg.randomness=dict(seed=int(payload.get("seed",42)))
    pin_memory=bool(payload.get("pin_memory"));persistent=bool(payload.get("persistent_workers")) and bool(workers)
    cfg.train_dataloader.batch_size=batch;cfg.train_dataloader.num_workers=workers;cfg.train_dataloader.persistent_workers=persistent;cfg.train_dataloader.pin_memory=pin_memory
    cfg.train_dataloader.dataset=_dataset(root,payload["train_json"],simple_train)
    cfg.val_dataloader.batch_size=max(1,min(batch,4));cfg.val_dataloader.num_workers=workers;cfg.val_dataloader.persistent_workers=persistent;cfg.val_dataloader.pin_memory=pin_memory
    cfg.val_dataloader.dataset=_dataset(root,payload["val_json"],simple_val)
    cfg.test_dataloader=dict(cfg.val_dataloader)
    cfg.test_dataloader.dataset=_dataset(root,payload["val_json"],simple_infer)
    cfg.val_evaluator=dict(type="CocoMetric",ann_file=str(payload["val_json"]),metric="bbox",format_only=False)
    cfg.test_evaluator=cfg.val_evaluator
    cfg.train_cfg=dict(type="EpochBasedTrainLoop",max_epochs=epochs,val_interval=max(1,epochs//8))
    lr=max(0.0001,0.004*batch/32.0)
    cfg.optim_wrapper.optimizer.lr=lr
    use_amp=bool(payload.get("mixed_precision")) and device.startswith("cuda") and torch.cuda.is_available()
    if use_amp:
        cfg.optim_wrapper.type="AmpOptimWrapper";cfg.optim_wrapper.loss_scale="dynamic"
    if device.startswith("cuda") and torch.cuda.is_available():
        torch.backends.cudnn.benchmark=True
        try:torch.set_float32_matmul_precision("high")
        except (AttributeError,RuntimeError):pass
    cfg.param_scheduler=[
        dict(type="LinearLR",start_factor=0.001,by_epoch=False,begin=0,end=100),
        dict(type="CosineAnnealingLR",eta_min=lr*0.05,begin=0,end=epochs,T_max=epochs,by_epoch=True),
    ]
    cfg.custom_hooks=[]
    cfg.default_hooks.checkpoint=dict(type="CheckpointHook",interval=max(1,epochs//5),max_keep_ckpts=2,save_best="coco/bbox_mAP",rule="greater")
    cfg.launcher="none"
    cfg.device=device
    if hasattr(cfg,"env_cfg") and cfg.env_cfg is not None:cfg.env_cfg.cudnn_benchmark=bool(device.startswith("cuda"))
    config_path=work/"xray_rtmdet_config.py";cfg.dump(str(config_path))
    runner=Runner.from_cfg(cfg);runner.train()
    candidates=list(work.glob("best*.pth"))
    if not candidates:candidates=sorted(work.glob("epoch_*.pth"),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise RuntimeError("MMDetection did not produce a checkpoint")
    return {"checkpoint":str(candidates[0]),"config":str(config_path),"metrics":_best_validation_metrics(work)}

def _detections(result,threshold):
    instances=result.pred_instances.cpu();detections=[]
    bboxes=instances.bboxes.numpy();scores=instances.scores.numpy();labels=instances.labels.numpy()
    for bbox,score,label in zip(bboxes,scores,labels):
        if int(label)!=0 or float(score)<threshold:continue
        detections.append({"bbox":[float(x) for x in bbox.tolist()],"score":float(score)})
    return detections

def predict_many(payload):
    import torch
    from mmdet.apis import init_detector, inference_detector
    device=str(payload.get("device") or "cpu");images=[str(value) for value in payload.get("images") or ()]
    if not images:raise ValueError("X-ray prediction requires at least one image")
    model=init_detector(str(payload["config"]),str(payload["checkpoint"]),device=device)
    # Do not wrap detector prediction in CUDA autocast. The managed mmcv NMS
    # extension receives RTMDet boxes/scores before this function can cast
    # them and requires Float, not Half. Batching and cuDNN autotuning remain
    # enabled, while training still uses AMP.
    if device.startswith("cuda") and torch.cuda.is_available():
        torch.backends.cudnn.benchmark=True
        try:torch.set_float32_matmul_precision("high")
        except (AttributeError,RuntimeError):pass
    threshold=float(payload.get("score_threshold",0.25))
    raw=inference_detector(model,images if len(images)>1 else images[0])
    results=raw if isinstance(raw,list) else [raw]
    return {"results":[{"detections":_detections(result,threshold)} for result in results]}

def predict(payload):
    copy=dict(payload);copy["images"]=[str(payload["image"])]
    return {"detections":predict_many(copy)["results"][0]["detections"]}

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else "info";payload=_input()
    if mode=="info":out=info()
    elif mode=="train":out=train(payload)
    elif mode=="predict":out=predict(payload)
    elif mode=="predict_many":out=predict_many(payload)
    else:raise ValueError(f"Unknown X-ray detector mode: {mode}")
    print(json.dumps(out,ensure_ascii=False))

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}",file=sys.stderr);raise
