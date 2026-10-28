"""Universal high-resolution training tiles for image-structure models.

Input: the existing verified, source-plate-grouped training manifest.
Output: derived, locally materialized image tiles and transformed annotations.

No fish-specific structures, no SQL writes, no new human labels, no splits
created from overlapping crops. This module does not train or activate models.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from math import isfinite
from PIL import Image

from ai_runtime.universal_multires import make_tiles

ALLOWED_VISIBILITY=frozenset(("complete","partial","absent","not_visible"))


def _check_manifest(manifest):
    if not isinstance(manifest,dict):
        raise ValueError("Training manifest must be a mapping")
    structures=manifest.get("structures") or []
    channels=[str(s["id"]) for s in structures]
    if not channels or len(channels)!=len(set(channels)):
        raise ValueError("Invalid or duplicated structure channels")
    names=set(channels)
    plates={};seen=set()
    for split in ("train","val"):
        rows=manifest.get(split) or ()
        if not rows:
            raise ValueError("Training and validation must both be nonempty")
        for row in rows:
            sid=str(row.get("specimen_id") or "")
            plate=str(row.get("image_id") or "")
            if not sid or not plate or sid in seen:
                raise ValueError("Duplicate or unnamed verified specimen/plate")
            seen.add(sid)
            if plate in plates and plates[plate]!=split:
                raise ValueError("Source plate must not span train and validation")
            plates[plate]=split
            original=Path(str(row.get("path") or ""))
            if not original.is_file():
                raise FileNotFoundError("Verified specimen crop is missing")
            visibility=row.get("visibility") or {}
            if set(visibility)-names:
                raise ValueError("Visibility includes unknown channels")
            if any(v not in ALLOWED_VISIBILITY for v in visibility.values()):
                raise ValueError("Unrecognized visibility state")
            for point in row.get("points") or ():
                if point.get("structure_id") not in names:
                    raise ValueError("Annotation channel absent from model")
                x,y=float(point["x"]),float(point["y"])
                if not isfinite(x) or not isfinite(y) or not 0<=x<=1 or not 0<=y<=1:
                    raise ValueError("Invalid normalized verified coordinates")
    return channels


def project_points(points,tile,width,height):
    """Transform original relative coordinates; overlap duplicates are deliberate."""
    output=[]
    for p in points:
        px,py=float(p["x"])*width,float(p["y"])*height
        if tile.left<=px<=tile.right and tile.top<=py<=tile.bottom:
            output.append({**p,
                "x":min(1.,max(0.,(px-tile.left)/tile.width)),
                "y":min(1.,max(0.,(py-tile.top)/tile.height))})
    return output


def build_tile_manifest(original,output_root,*,nx=4,ny=2,
                        width_fraction=.38,height_fraction=.62,
                        tile_input=(768,384)):
    """Write a new scratch-only ROI training dataset, never overwrite inputs."""
    channels=_check_manifest(original)
    if any(type(k)!=int or not 64<=k<=4096 for k in tile_input):
        raise ValueError("Invalid tile model input size")
    root=Path(output_root).resolve()
    if root.exists():
        raise FileExistsError("Refusing to overwrite an existing training directory")
    sources=[Path(row["path"]).resolve() for split in ("train","val")
             for row in original[split]]
    if any(src.is_relative_to(root) for src in sources):
        raise ValueError("Training output must not contain source images")
    root.mkdir(parents=True,exist_ok=False)
    images=root/"images";images.mkdir()
    groups={"train":[],"val":[]}
    files=[];cases=0
    for split in ("train","val"):
        for row in original[split]:
            with Image.open(row["path"]) as image:
                source=image.convert("RGB")
            w,h=source.size
            tiles=make_tiles(w,h,nx=nx,ny=ny,
                             width_fraction=width_fraction,
                             height_fraction=height_fraction)
            cases+=1
            for index,tile in enumerate(tiles):
                name=f"{split}_{cases:05d}_{index:02d}.png"
                path=images/name
                source.crop((tile.left,tile.top,tile.right,tile.bottom)).save(path)
                extra={k:v for k,v in row.items()
                       if k not in ("path","points")}
                extra["path"]=str(path)
                extra["points"]=project_points(row.get("points") or (),tile,w,h)
                extra["source_specimen_id"]=str(row["specimen_id"])
                extra["tile_index"]=index
                extra["specimen_id"]=f"{split}_{cases:05d}_{index:02d}"
                groups[split].append(extra)
                files.append(name)
    metadata={k:v for k,v in original.items() if k not in ("train","val")}
    metadata.update(groups)
    metadata["input_size"]=list(tile_input)
    metadata["tile_training_protocol"]={
        "name":"multires_train_tiles_v1",
        "nx":nx,"ny":ny,
        "width_fraction":width_fraction,
        "height_fraction":height_fraction,
        "source_specimens":cases,
        "source_channel_order":channels,
        "split_policy":"unchanged source plates",
    }
    target=root/"manifest.json"
    target.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"manifest":str(target),
            "train_tiles":len(groups["train"]),"validation_tiles":len(groups["val"]),
            "source_specimens":cases,
            "source_plates_train":len({r["image_id"] for r in original["train"]}),
            "source_plates_val":len({r["image_id"] for r in original["val"]}),
            "manifest_sha256":sha256(target.read_bytes()).hexdigest()}
