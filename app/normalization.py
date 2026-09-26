"""Conservative, replaceable image-normalization backend.

It may propose a crop from background contrast, but never changes status to PASS
and never mirrors. Human review is mandatory for every automatic proposal.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
from .io import atomic_json_write
from .paths import sample_work, require_relative
from .standardize import decode, image_id
from .transforms import Transform
from .manifest import sha256

def propose_crop(image: Image.Image, margin_ratio: float=.05) -> tuple[int,int,int,int]:
    """Find non-background extent using the median-ish corner color; safe fallback is full frame."""
    rgb = image.convert("RGB")
    corners=[rgb.getpixel((0,0)),rgb.getpixel((rgb.width-1,0)),rgb.getpixel((0,rgb.height-1)),rgb.getpixel((rgb.width-1,rgb.height-1))]
    background=tuple(sorted(c[i] for c in corners)[len(corners)//2] for i in range(3))
    flat=Image.new("RGB",rgb.size,background); diff=ImageChops.difference(rgb,flat).convert("L").point(lambda v:255 if v>24 else 0)
    box=diff.getbbox()
    if not box: return (0,0,rgb.width,rgb.height)
    margin=round(max(rgb.width,rgb.height)*margin_ratio); left,top,right,bottom=box
    return max(0,left-margin),max(0,top-margin),min(rgb.width,right+margin),min(rgb.height,bottom+margin)

def apply_review_transform(source: Path, crop: tuple[int,int,int,int]|None=None, rotation_degrees: float=0.0, reason="automatic_conservative") -> dict:
    image=decode(source); crop=crop or propose_crop(image)
    # expand=True retains all rotated pixels; rotations are never mirrors.
    rotated=image.rotate(rotation_degrees, expand=True, resample=Image.Resampling.BICUBIC)
    # Crop only when not rotated; arbitrary rotated crop needs a more complete affine implementation.
    if rotation_degrees: crop=(0,0,rotated.width,rotated.height)
    master=rotated.crop(crop); identifier=image_id(source); output=sample_work(source.parent.name)/"standardized"/f"{identifier}.png"
    output.parent.mkdir(parents=True,exist_ok=True); master.save(output,format="PNG",compress_level=6)
    transform=Transform(image.width,image.height,rotation_degrees,image.width/2,image.height/2,crop[0],crop[1],master.width,master.height)
    data={"image_id":identifier,"source_relpath":require_relative(source),"source_sha256":sha256(source),"standardized_relpath":require_relative(output),"normalization_status":"REVIEW","qc_reason":reason,"crop_bounds":list(crop),"mirrored":False,"interpolation":"bicubic" if rotation_degrees else "none","transform":asdict(transform)}
    atomic_json_write(sample_work(source.parent.name)/"metadata"/f"{identifier}.json",data); return data

def make_qc_preview(source: Path, destination: Path) -> Path:
    image=decode(source); crop=propose_crop(image); shown=image.copy(); draw=ImageDraw.Draw(shown); draw.rectangle(crop,outline=(255,0,0),width=max(3,shown.width//500)); shown.thumbnail((1200,800)); destination.parent.mkdir(parents=True,exist_ok=True); shown.save(destination,"PNG"); return destination
