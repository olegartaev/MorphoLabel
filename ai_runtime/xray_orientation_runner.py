"""Isolated lightweight orientation learner for X-ray crops."""
from __future__ import annotations

import json
from pathlib import Path
import random
import sys


def _input():
    raw=sys.stdin.read().strip();return json.loads(raw) if raw else {}


def _model(pretrained=False):
    import torch.nn as nn
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
    weights=MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    model=mobilenet_v3_small(weights=weights)
    for parameter in model.features.parameters():parameter.requires_grad=False
    for block in model.features[-2:]:
        for parameter in block.parameters():parameter.requires_grad=True
    model.classifier[-1]=nn.Linear(model.classifier[-1].in_features,2)
    return model


def _transforms(training=False):
    from torchvision import transforms
    base=[
        transforms.Resize((224,224)),
        transforms.ColorJitter(brightness=.12,contrast=.18) if training else transforms.Lambda(lambda image:image),
        transforms.RandomRotation(5,fill=128) if training else transforms.Lambda(lambda image:image),
        transforms.ToTensor(),
        transforms.Normalize((.485,.456,.406),(.229,.224,.225)),
    ]
    return transforms.Compose(base)


class _Dataset:
    def __init__(self,rows,training=False):
        self.rows=list(rows);self.transform=_transforms(training)
    def __len__(self):return len(self.rows)
    def __getitem__(self,index):
        import torch
        from PIL import Image
        row=self.rows[index]
        with Image.open(row["path"]) as image:picture=self.transform(image.convert("RGB"))
        target=torch.tensor([float(row["head"]),float(row["bottom"])],dtype=torch.float32)
        return picture,target


def _evaluate(model,loader,device,axes):
    import torch
    model.eval();counts={"head":0,"bottom":0,"joint":0,"n":0}
    with torch.no_grad():
        for images,targets in loader:
            images=images.to(device);targets=targets.to(device)
            probs=torch.sigmoid(model(images));preds=(probs>=.5).float();batch=targets.shape[0]
            head_ok=(preds[:,0]==targets[:,0]);bottom_ok=(preds[:,1]==targets[:,1])
            if axes.get("head"):counts["head"]+=int(head_ok.sum().item())
            if axes.get("bottom"):counts["bottom"]+=int(bottom_ok.sum().item())
            joint=torch.ones(batch,dtype=torch.bool,device=device)
            if axes.get("head"):joint &= head_ok
            if axes.get("bottom"):joint &= bottom_ok
            counts["joint"]+=int(joint.sum().item());counts["n"]+=int(batch)
    n=max(1,counts["n"]);metrics={"orientation/joint_accuracy":counts["joint"]/n}
    if axes.get("head"):metrics["orientation/head_accuracy"]=counts["head"]/n
    if axes.get("bottom"):metrics["orientation/bottom_accuracy"]=counts["bottom"]/n
    return metrics


def train_orientation(payload):
    import torch
    from torch.utils.data import DataLoader
    manifest=json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    train_rows=list(manifest.get("train") or ());val_rows=list(manifest.get("val") or ())
    if not train_rows or not val_rows:raise ValueError("Orientation training needs both train and validation examples.")
    seed=int(payload.get("seed",42));random.seed(seed);torch.manual_seed(seed)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)
    device=str(payload.get("device") or ("cuda:0" if torch.cuda.is_available() else "cpu"))
    axes=dict(manifest.get("axes") or {});epochs=max(8,int(payload.get("epochs",20)))
    model=_model(pretrained=True).to(device)
    train_loader=DataLoader(_Dataset(train_rows,True),batch_size=min(32,max(4,len(train_rows))),shuffle=True,num_workers=0)
    val_loader=DataLoader(_Dataset(val_rows,False),batch_size=min(64,max(4,len(val_rows))),shuffle=False,num_workers=0)
    params=[p for p in model.parameters() if p.requires_grad]
    optimizer=torch.optim.AdamW(params,lr=3e-4,weight_decay=1e-4)
    criterion=torch.nn.BCEWithLogitsLoss(reduction="none")
    use_amp=bool(payload.get("mixed_precision")) and device.startswith("cuda") and torch.cuda.is_available()
    scaler=torch.cuda.amp.GradScaler(enabled=use_amp)
    mask=torch.tensor([1.0 if axes.get("head") else 0.0,1.0 if axes.get("bottom") else 0.0],device=device)
    best_score=-1.0;best_state=None;best_metrics={}
    for _epoch in range(epochs):
        model.train()
        for images,targets in train_loader:
            images=images.to(device);targets=targets.to(device);optimizer.zero_grad(set_to_none=True)
            with torch.cuda.amp.autocast(enabled=use_amp):
                logits=model(images);losses=criterion(logits,targets)*mask
                loss=losses.sum()/max(1.0,float(mask.sum().item())*targets.shape[0])
            scaler.scale(loss).backward();scaler.step(optimizer);scaler.update()
        metrics=_evaluate(model,val_loader,device,axes);score=float(metrics["orientation/joint_accuracy"])
        if score>=best_score:
            best_score=score;best_metrics=metrics
            best_state={key:value.detach().cpu().clone() for key,value in model.state_dict().items()}
    if best_state is None:raise RuntimeError("Orientation training produced no checkpoint.")
    work=Path(payload["work_dir"]);work.mkdir(parents=True,exist_ok=True)
    checkpoint=work/"orientation_model.pth";torch.save(best_state,checkpoint)
    meta=work/"orientation.json";meta.write_text(json.dumps({
        "format":1,"backend":"mobilenet_v3_small_imagenet_transfer_v1","input_size":224,
        "axes":axes,"threshold":0.65,
    },ensure_ascii=False),encoding="utf-8")
    return {"checkpoint":str(checkpoint),"meta":str(meta),"metrics":best_metrics}


def predict_orientation_many(payload):
    import torch
    from torch.utils.data import DataLoader
    meta=json.loads(Path(payload["meta"]).read_text(encoding="utf-8"))
    device=str(payload.get("device") or ("cuda:0" if torch.cuda.is_available() else "cpu"))
    rows=[{"path":str(path),"head":0,"bottom":0} for path in payload.get("images") or ()]
    if not rows:return {"results":[],"threshold":float(meta.get("threshold",.65))}
    model=_model(pretrained=False)
    state=torch.load(str(payload["checkpoint"]),map_location="cpu",weights_only=True);model.load_state_dict(state);model.to(device);model.eval()
    loader=DataLoader(_Dataset(rows,False),batch_size=max(1,int(payload.get("batch_size") or 16)),shuffle=False,num_workers=0)
    results=[]
    with torch.no_grad():
        for images,_targets in loader:
            probs=torch.sigmoid(model(images.to(device))).cpu().numpy()
            for head,bottom in probs:
                results.append({"head_right_probability":float(head),"bottom_down_probability":float(bottom)})
    return {"results":results,"threshold":float(meta.get("threshold",.65))}


def main():
    mode=sys.argv[1] if len(sys.argv)>1 else "";payload=_input()
    if mode=="train_orientation":out=train_orientation(payload)
    elif mode=="predict_orientation_many":out=predict_orientation_many(payload)
    else:raise ValueError(f"Unknown X-ray orientation mode: {mode}")
    print(json.dumps(out,ensure_ascii=False))


if __name__=="__main__":
    try:main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}",file=sys.stderr);raise
