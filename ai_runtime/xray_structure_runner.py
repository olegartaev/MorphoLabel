"""Isolated heatmap learner for variable-count X-ray structure markers."""
from __future__ import annotations

import json
import math
from pathlib import Path
import random
import sys


BACKEND = "resnet18_heatmap_v1"
FORMAT_VERSION = 1
TRAINING_OBJECTIVE = "per_structure_balanced_focal_v1"


def _input():
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def _model(channels, pretrained=False):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torchvision.models import ResNet18_Weights, resnet18

    class Block(nn.Module):
        def __init__(self, in_channels, out_channels):
            super().__init__()
            self.body = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True),
                nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True),
            )

        def forward(self, value):
            return self.body(value)

    class HeatmapNet(nn.Module):
        def __init__(self):
            super().__init__()
            weights = ResNet18_Weights.DEFAULT if pretrained else None
            encoder = resnet18(weights=weights)
            self.stem = nn.Sequential(encoder.conv1, encoder.bn1, encoder.relu)
            self.pool = encoder.maxpool
            self.layer1 = encoder.layer1
            self.layer2 = encoder.layer2
            self.layer3 = encoder.layer3
            self.layer4 = encoder.layer4
            self.d4 = Block(512 + 256, 256)
            self.d3 = Block(256 + 128, 128)
            self.d2 = Block(128 + 64, 64)
            self.d1 = Block(64 + 64, 64)
            self.head = nn.Conv2d(64, int(channels), 1)

        @staticmethod
        def _up(value, skip):
            return F.interpolate(value, size=skip.shape[-2:], mode="bilinear", align_corners=False)

        def forward(self, value):
            stem = self.stem(value)
            e1 = self.layer1(self.pool(stem))
            e2 = self.layer2(e1)
            e3 = self.layer3(e2)
            e4 = self.layer4(e3)
            value = self.d4(torch.cat((self._up(e4, e3), e3), dim=1))
            value = self.d3(torch.cat((self._up(value, e2), e2), dim=1))
            value = self.d2(torch.cat((self._up(value, e1), e1), dim=1))
            value = self.d1(torch.cat((self._up(value, stem), stem), dim=1))
            return self.head(value)

    return HeatmapNet()


def _letterbox(image, size):
    from PIL import Image

    target_w, target_h = (int(size[0]), int(size[1]))
    source_w, source_h = image.size
    scale = min(target_w / max(1, source_w), target_h / max(1, source_h))
    resized = image.resize(
        (max(1, round(source_w * scale)), max(1, round(source_h * scale))),
        Image.Resampling.BILINEAR,
    )
    canvas = Image.new("RGB", (target_w, target_h), (128, 128, 128))
    offset_x = (target_w - resized.width) // 2
    offset_y = (target_h - resized.height) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas, {
        "source_w": source_w, "source_h": source_h, "scale": scale,
        "offset_x": offset_x, "offset_y": offset_y,
    }


def _photo_augment(image):
    from PIL import ImageEnhance, ImageOps

    if random.random() < 0.50:
        image = ImageEnhance.Contrast(image).enhance(random.uniform(0.78, 1.28))
    if random.random() < 0.35:
        image = ImageEnhance.Brightness(image).enhance(random.uniform(0.88, 1.12))
    if random.random() < 0.25:
        gamma = random.uniform(0.75, 1.35)
        table = [max(0, min(255, round((value / 255.0) ** gamma * 255.0))) for value in range(256)]
        image = image.point(table * 3)
    if random.random() < 0.20:
        image = ImageOps.invert(image)
    return image


def _tensor(image):
    import torch
    import numpy as np

    array = np.asarray(image, dtype=np.float32) / 255.0
    value = torch.from_numpy(array.transpose(2, 0, 1))
    mean = torch.tensor((0.485, 0.456, 0.406), dtype=torch.float32)[:, None, None]
    std = torch.tensor((0.229, 0.224, 0.225), dtype=torch.float32)[:, None, None]
    return (value - mean) / std


def _gaussian(target, channel, cx, cy, sigma=2.0, supervision=None):
    import numpy as np

    height, width = target.shape[-2:]
    radius = max(1, int(math.ceil(3.0 * float(sigma))))
    center_x = max(0, min(width - 1, int(round(float(cx)))))
    center_y = max(0, min(height - 1, int(round(float(cy)))))
    left = max(0, center_x - radius)
    right = min(width, center_x + radius + 1)
    top = max(0, center_y - radius)
    bottom = min(height, center_y + radius + 1)
    if left >= right or top >= bottom:
        return
    ys = np.arange(top, bottom, dtype=np.float32)[:, None]
    xs = np.arange(left, right, dtype=np.float32)[None, :]
    patch = np.exp(-((xs - float(center_x)) ** 2 + (ys - float(center_y)) ** 2) / (2.0 * float(sigma) ** 2))
    target[channel, top:bottom, left:right] = np.maximum(target[channel, top:bottom, left:right], patch)
    if supervision is not None:
        supervision[channel, top:bottom, left:right] = 1.0


class _Dataset:
    def __init__(self, rows, structures, input_size, stride=2, training=False):
        self.rows = list(rows)
        self.structures = list(structures)
        self.channel = {item["id"]: index for index, item in enumerate(self.structures)}
        self.input_size = tuple(int(value) for value in input_size)
        self.stride = int(stride)
        self.training = bool(training)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        import numpy as np
        import torch
        from PIL import Image

        row = self.rows[index]
        with Image.open(row["path"]) as opened:
            source = opened.convert("RGB")
        image, geometry = _letterbox(source, self.input_size)
        if self.training:
            image = _photo_augment(image)
        out_w = self.input_size[0] // self.stride
        out_h = self.input_size[1] // self.stride
        heatmap = np.zeros((len(self.structures), out_h, out_w), dtype=np.float32)
        supervision = np.zeros_like(heatmap)
        visibility = dict(row.get("visibility") or {})
        states = {}
        for structure_id, channel in self.channel.items():
            state = str(visibility.get(structure_id, "complete") or "complete")
            if state not in {"complete", "partial", "not_visible", "absent"}:
                state = "complete"
            states[structure_id] = state
            if state in {"complete", "absent"}:
                supervision[channel, :, :] = 1.0
        for point in row.get("points") or ():
            structure_id = str(point.get("structure_id") or "")
            channel = self.channel.get(structure_id)
            if channel is None or states.get(structure_id) in {"not_visible", "absent"}:
                continue
            px = (float(point["x"]) * geometry["source_w"] * geometry["scale"] + geometry["offset_x"]) / self.stride
            py = (float(point["y"]) * geometry["source_h"] * geometry["scale"] + geometry["offset_y"]) / self.stride
            _gaussian(
                heatmap, channel, px, py,
                supervision=supervision if states.get(structure_id) == "partial" else None,
            )
        return _tensor(image), torch.from_numpy(heatmap), torch.from_numpy(supervision)


def _loss(logits, target, supervision=None):
    import torch

    prediction = torch.sigmoid(logits).clamp(1e-4, 1.0 - 1e-4)
    mask = torch.ones_like(target) if supervision is None else supervision.float()
    positive = target.eq(1.0).float() * mask
    negative = target.lt(1.0).float() * mask
    negative_weight = (1.0 - target).pow(4)
    positive_loss = -(prediction.log()) * (1.0 - prediction).pow(2) * positive
    negative_loss = -((1.0 - prediction).log()) * prediction.pow(2) * negative_weight * negative

    # Every schema structure is a separate learning task. Normalizing one global
    # loss by the total number of positive markers lets dense repeated structures
    # dominate rare references or shorter series. Normalize each output channel
    # independently, then average the supervised structure tasks.
    reduce_dims = (0, 2, 3)
    positive_counts = positive.sum(dim=reduce_dims)
    supervised_counts = mask.sum(dim=reduce_dims)
    positive_terms = positive_loss.sum(dim=reduce_dims)
    negative_terms = negative_loss.sum(dim=reduce_dims)
    with_positive = (positive_terms + negative_terms) / positive_counts.clamp(min=1.0)
    negative_only = negative_terms / supervised_counts.clamp(min=1.0)
    per_structure = torch.where(positive_counts > 0, with_positive, negative_only)
    valid = (supervised_counts > 0).float()
    return (per_structure * valid).sum() / valid.sum().clamp(min=1.0)


def _local_peaks(logits, thresholds, structures):
    import torch
    import torch.nn.functional as F

    probabilities = torch.sigmoid(logits)
    maxima = F.max_pool2d(probabilities, kernel_size=3, stride=1, padding=1)
    kept = probabilities.eq(maxima)
    output = []
    for channel, structure in enumerate(structures):
        threshold = float(thresholds.get(structure["id"], 0.30))
        scores = probabilities[0, channel]
        ys, xs = torch.where(kept[0, channel] & (scores >= threshold))
        points = [(float(scores[y, x].item()), int(x.item()), int(y.item())) for y, x in zip(ys, xs)]
        points.sort(reverse=True)
        if not structure.get("repeated"):
            points = points[:1]
        else:
            points = points[:96]
        output.append(points)
    return output


def _decode_one(model, path, meta, device, thresholds=None):
    import torch
    from PIL import Image

    input_size = tuple(meta["input_size"])
    stride = int(meta.get("output_stride", 2))
    structures = list(meta["structures"])
    with Image.open(path) as opened:
        source = opened.convert("RGB")
    canvas, geometry = _letterbox(source, input_size)
    value = _tensor(canvas).unsqueeze(0).to(device)
    with torch.no_grad():
        logits = model(value)
    thresholds = dict(thresholds or meta.get("thresholds") or {})
    peaks = _local_peaks(logits, thresholds, structures)
    rows = []
    for structure, points in zip(structures, peaks):
        decoded = []
        for score, out_x, out_y in points:
            fixed_x = (out_x + 0.5) * stride
            fixed_y = (out_y + 0.5) * stride
            source_x = (fixed_x - geometry["offset_x"]) / max(1e-9, geometry["scale"])
            source_y = (fixed_y - geometry["offset_y"]) / max(1e-9, geometry["scale"])
            x = source_x / max(1, geometry["source_w"])
            y = source_y / max(1, geometry["source_h"])
            if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                decoded.append({"x": float(x), "y": float(y), "score": float(score)})
        decoded.sort(key=lambda point: (point["x"], point["y"]))
        rows.append({"structure_id": structure["id"], "points": decoded})
    return rows


def _greedy_counts(predicted, truth, tolerance=0.020):
    remaining = list(truth)
    matched = 0
    for point in sorted(predicted, key=lambda item: float(item.get("score", 0.0)), reverse=True):
        if not remaining:
            break
        best = min(
            range(len(remaining)),
            key=lambda index: (float(point["x"]) - float(remaining[index]["x"])) ** 2
            + (float(point["y"]) - float(remaining[index]["y"])) ** 2,
        )
        distance = math.hypot(
            float(point["x"]) - float(remaining[best]["x"]),
            float(point["y"]) - float(remaining[best]["y"]),
        )
        if distance <= tolerance:
            matched += 1
            remaining.pop(best)
    return matched, len(predicted) - matched, len(remaining)


def _calibrate(model, rows, meta, device):
    structures = list(meta["structures"])
    grids = (0.12, 0.18, 0.24, 0.30, 0.38, 0.48, 0.60)
    cache = []
    very_low = {item["id"]: grids[0] for item in structures}
    for row in rows:
        cache.append((row, _decode_one(model, row["path"], meta, device, very_low)))
    thresholds = {}
    metrics = {}
    macro_f1_values = []
    for structure in structures:
        sid = structure["id"]
        evaluable = sum(
            1 for row, _decoded in cache
            if str((row.get("visibility") or {}).get(sid, "complete") or "complete") not in {"partial", "not_visible"}
        )
        best = None
        for threshold in grids:
            tp = fp = fn = 0
            for row, decoded in cache:
                visibility = str((row.get("visibility") or {}).get(sid, "complete") or "complete")
                if visibility in {"partial", "not_visible"}:
                    continue
                truth = [point for point in row.get("points") or () if point.get("structure_id") == sid]
                predicted_group = next((item for item in decoded if item["structure_id"] == sid), {"points": []})
                predicted = [point for point in predicted_group["points"] if float(point["score"]) >= threshold]
                if not structure.get("repeated"):
                    predicted = predicted[:1]
                a, b, c = _greedy_counts(predicted, truth)
                tp += a; fp += b; fn += c
            precision = tp / max(1, tp + fp)
            recall = tp / max(1, tp + fn)
            f1 = 2.0 * precision * recall / max(1e-9, precision + recall)
            candidate = (f1, recall, precision, -threshold)
            if best is None or candidate > best[0]:
                best = (candidate, threshold, precision, recall, f1)
        _key, threshold, precision, recall, f1 = best
        thresholds[sid] = float(threshold)
        metrics[f"structure/{sid}/precision"] = float(precision)
        metrics[f"structure/{sid}/recall"] = float(recall)
        metrics[f"structure/{sid}/f1"] = float(f1)
        metrics[f"structure/{sid}/evaluable_images"] = int(evaluable)
        if evaluable:
            macro_f1_values.append(float(f1))
    metrics["structure/macro_f1"] = sum(macro_f1_values) / max(1, len(macro_f1_values))
    metrics["structure/macro_evaluable_classes"] = int(len(macro_f1_values))
    return thresholds, metrics


def train(payload):
    import torch
    from torch.utils.data import DataLoader

    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    structures = list(manifest["structures"])
    train_rows = list(manifest.get("train") or ())
    val_rows = list(manifest.get("val") or ())
    if not structures or not train_rows or not val_rows:
        raise ValueError("Structure training needs structures plus non-empty train and validation splits.")
    seed = int(payload.get("seed", 42))
    random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    device = str(payload.get("device") or ("cuda:0" if torch.cuda.is_available() else "cpu"))
    input_size = tuple(manifest.get("input_size") or (768, 256))
    stride = 2
    initial = str(payload.get("initial_checkpoint") or "").strip()
    model = _model(len(structures), pretrained=not bool(initial))
    if initial:
        state = torch.load(initial, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
    model.to(device)
    train_dataset = _Dataset(train_rows, structures, input_size, stride, training=True)
    val_dataset = _Dataset(val_rows, structures, input_size, stride, training=False)
    batch_size = max(1, int(payload.get("batch_size") or 4))
    workers = max(0, int(payload.get("workers") or 0))
    train_loader = DataLoader(
        train_dataset, batch_size=batch_size, shuffle=True, num_workers=workers,
        pin_memory=bool(payload.get("pin_memory")), persistent_workers=bool(workers and payload.get("persistent_workers")),
    )
    val_loader = DataLoader(val_dataset, batch_size=max(1, min(batch_size, 8)), shuffle=False, num_workers=workers)
    epochs = max(12, int(payload.get("epochs") or 60))
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4 if initial else 3e-4, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=2e-6)
    use_amp = bool(payload.get("mixed_precision")) and device.startswith("cuda") and torch.cuda.is_available()
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)
    best_loss = None
    best_state = None
    patience = max(10, epochs // 4)
    stale = 0
    history = []
    for epoch in range(1, epochs + 1):
        model.train()
        train_total = 0.0
        for images, targets, supervision in train_loader:
            images = images.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)
            supervision = supervision.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.cuda.amp.autocast(enabled=use_amp):
                loss = _loss(model(images), targets, supervision)
            scaler.scale(loss).backward()
            scaler.step(optimizer); scaler.update()
            train_total += float(loss.detach().cpu())
        scheduler.step()
        model.eval()
        val_total = 0.0
        with torch.no_grad():
            for images, targets, supervision in val_loader:
                images = images.to(device, non_blocking=True)
                targets = targets.to(device, non_blocking=True)
                supervision = supervision.to(device, non_blocking=True)
                val_total += float(_loss(model(images), targets, supervision).detach().cpu())
        train_loss = train_total / max(1, len(train_loader))
        val_loss = val_total / max(1, len(val_loader))
        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss})
        if best_loss is None or val_loss < best_loss - 1e-6:
            best_loss = val_loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
        if stale >= patience:
            break
    if best_state is None:
        raise RuntimeError("Structure training produced no checkpoint.")
    model.load_state_dict(best_state); model.to(device); model.eval()
    meta = {
        "format_version": FORMAT_VERSION,
        "backend": BACKEND,
        "training_objective": TRAINING_OBJECTIVE,
        "input_size": list(input_size),
        "output_stride": stride,
        "structures": structures,
        "preprocessing": {
            "host_percentile_stretch": [0.5, 99.5],
            "letterbox": True,
            "spatial_flips": False,
            "training_photometric_augmentation": ["contrast", "brightness", "gamma", "intensity_inversion"],
        },
    }
    thresholds, quality = _calibrate(model, val_rows, meta, device)
    meta["thresholds"] = thresholds
    work = Path(payload["work_dir"]); work.mkdir(parents=True, exist_ok=True)
    checkpoint = work / "model.pth"
    torch.save(best_state, checkpoint)
    meta_path = work / "model.json"
    meta["validation"] = {"best_loss": float(best_loss), **quality}
    meta["epochs_completed"] = len(history)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "checkpoint": str(checkpoint), "metadata": str(meta_path),
        "metrics": {"structure/validation_loss": float(best_loss), "structure/training_objective": TRAINING_OBJECTIVE, **quality, "epochs_completed": len(history)},
    }


def predict_many(payload):
    import torch

    meta = json.loads(Path(payload["metadata"]).read_text(encoding="utf-8"))
    structures = list(meta.get("structures") or ())
    if not structures:
        raise ValueError("Structure model metadata has no output structures.")
    device = str(payload.get("device") or ("cuda:0" if torch.cuda.is_available() else "cpu"))
    model = _model(len(structures), pretrained=False)
    state = torch.load(str(payload["checkpoint"]), map_location="cpu", weights_only=True)
    model.load_state_dict(state); model.to(device); model.eval()
    results = []
    for path in payload.get("images") or ():
        results.append({"structures": _decode_one(model, str(path), meta, device)})
    return {"results": results}


def info():
    import torch
    import torchvision
    return {
        "torch": torch.__version__, "torchvision": torchvision.__version__,
        "cuda_available": bool(torch.cuda.is_available()), "backend": BACKEND,
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "info"
    payload = _input()
    if mode == "info":
        output = info()
    elif mode == "train":
        output = train(payload)
    elif mode == "predict_many":
        output = predict_many(payload)
    else:
        raise ValueError(f"Unknown X-ray structure mode: {mode}")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
