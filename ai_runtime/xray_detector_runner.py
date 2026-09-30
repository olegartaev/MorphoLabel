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

def train(payload):
    import torch
    from mmengine.config import Config
    from mmengine.runner import Runner
    cfg=Config.fromfile(str(_config_path()))
    work=Path(payload["work_dir"]);work.mkdir(parents=True,exist_ok=True)
    root=Path(payload["dataset_root"])
    epochs=max(10,int(payload.get("epochs",80)));batch=max(1,int(payload.get("batch_size",2)));workers=max(0,int(payload.get("workers",0)))
    device=str(payload.get("device") or ("cuda:0" if torch.cuda.is_available() else "cpu"))
    simple_train=[
        dict(type="LoadImageFromFile"),
        dict(type="LoadAnnotations",with_bbox=True),
        dict(type="RandomResize",scale=(640,640),ratio_range=(0.8,1.2),keep_ratio=True),
        dict(type="RandomFlip",prob=0.5),
        dict(type="Pad",size=(640,640),pad_val=dict(img=(114,114,114))),
        dict(type="PackDetInputs"),
    ]
    simple_test=[
        dict(type="LoadImageFromFile"),
        dict(type="LoadAnnotations",with_bbox=True),
        dict(type="Resize",scale=(640,640),keep_ratio=True),
        dict(type="Pad",size=(640,640),pad_val=dict(img=(114,114,114))),
        dict(type="PackDetInputs",meta_keys=("img_id","img_path","ori_shape","img_shape","scale_factor")),
    ]
    cfg.model.bbox_head.num_classes=1
    initial_checkpoint=str(payload.get("initial_checkpoint") or "").strip()
    if not initial_checkpoint:raise ValueError("X-ray detector training requires an initial pretrained or parent checkpoint")
    cfg.load_from=initial_checkpoint
    cfg.work_dir=str(work);cfg.randomness=dict(seed=int(payload.get("seed",42)))
    cfg.train_dataloader.batch_size=batch;cfg.train_dataloader.num_workers=workers;cfg.train_dataloader.persistent_workers=bool(workers)
    cfg.train_dataloader.dataset=_dataset(root,payload["train_json"],simple_train)
    cfg.val_dataloader.batch_size=max(1,min(batch,4));cfg.val_dataloader.num_workers=workers;cfg.val_dataloader.persistent_workers=bool(workers)
    cfg.val_dataloader.dataset=_dataset(root,payload["val_json"],simple_test)
    cfg.test_dataloader=cfg.val_dataloader
    cfg.val_evaluator=dict(type="CocoMetric",ann_file=str(payload["val_json"]),metric="bbox",format_only=False)
    cfg.test_evaluator=cfg.val_evaluator
    cfg.train_cfg=dict(type="EpochBasedTrainLoop",max_epochs=epochs,val_interval=max(1,epochs//8))
    lr=max(0.0001,0.004*batch/32.0)
    cfg.optim_wrapper.optimizer.lr=lr
    cfg.param_scheduler=[
        dict(type="LinearLR",start_factor=0.001,by_epoch=False,begin=0,end=100),
        dict(type="CosineAnnealingLR",eta_min=lr*0.05,begin=0,end=epochs,T_max=epochs,by_epoch=True),
    ]
    cfg.custom_hooks=[]
    cfg.default_hooks.checkpoint=dict(type="CheckpointHook",interval=max(1,epochs//5),max_keep_ckpts=2,save_best="coco/bbox_mAP",rule="greater")
    cfg.launcher="none"
    cfg.device=device
    config_path=work/"xray_rtmdet_config.py";cfg.dump(str(config_path))
    runner=Runner.from_cfg(cfg);runner.train()
    candidates=list(work.glob("best*.pth"))
    if not candidates:candidates=sorted(work.glob("epoch_*.pth"),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates:raise RuntimeError("MMDetection did not produce a checkpoint")
    return {"checkpoint":str(candidates[0]),"config":str(config_path),"metrics":{}}

def predict(payload):
    from mmdet.apis import init_detector, inference_detector
    model=init_detector(str(payload["config"]),str(payload["checkpoint"]),device=str(payload.get("device") or "cpu"))
    result=inference_detector(model,str(payload["image"]))
    instances=result.pred_instances.cpu()
    threshold=float(payload.get("score_threshold",0.25));detections=[]
    bboxes=instances.bboxes.numpy();scores=instances.scores.numpy();labels=instances.labels.numpy()
    for bbox,score,label in zip(bboxes,scores,labels):
        if int(label)!=0 or float(score)<threshold:continue
        detections.append({"bbox":[float(x) for x in bbox.tolist()],"score":float(score)})
    return {"detections":detections}

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else "info";payload=_input()
    if mode=="info":out=info()
    elif mode=="train":out=train(payload)
    elif mode=="predict":out=predict(payload)
    else:raise ValueError(f"Unknown X-ray detector mode: {mode}")
    print(json.dumps(out,ensure_ascii=False))

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}",file=sys.stderr);raise
