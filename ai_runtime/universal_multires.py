"""Universal multiresolution point-heatmap inference for MorphoLabel.

Inference only: scientific trait rules live in the versioned project scheme,
trained weights remain domain-specific. No ground-truth-guided cropping,
modification of human annotations, or automatic model promotion.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
import re

PIPELINE="multires_heatmap_v1"
_CHECKPOINT=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.pth$")
_SHA=re.compile(r"^[0-9a-f]{64}$")

@dataclass(frozen=True)
class Tile:
    left:int
    top:int
    right:int
    bottom:int
    @property
    def width(self):return self.right-self.left
    @property
    def height(self):return self.bottom-self.top

def _starts(length,span,count):
    if length<8 or span<8 or span>length or not 1<=count<=16:
        raise ValueError("Invalid multiresolution tiling geometry")
    if count==1 or length==span:return [0]
    return sorted(set(round((length-span)*i/(count-1)) for i in range(count)))

def make_tiles(width,height,*,nx=4,ny=2,width_fraction=.38,height_fraction=.62):
    """Full image, deterministic overlap. Never uses annotations."""
    width,height,nx,ny=map(int,(width,height,nx,ny))
    if width<8 or height<8 or nx<1 or ny<1 or nx*ny>64:
        raise ValueError("Unsupported tiling configuration")
    if not all(isfinite(float(f)) and 0<float(f)<=1 for f in (width_fraction,height_fraction)):
        raise ValueError("Invalid tile fractions")
    cw=min(width,max(8,round(width*width_fraction)))
    ch=min(height,max(8,round(height*height_fraction)))
    return [Tile(x,y,x+cw,y+ch) for y in _starts(height,ch,ny)
            for x in _starts(width,cw,nx)]

def pipeline_components(metadata):
    p=metadata.get("inference_pipeline")
    if p is None:return {}
    if not isinstance(p,dict) or p.get("name")!=PIPELINE or p.get("version")!=1:
        raise ValueError("Unsupported multiresolution inference format")
    if p.get("mode") not in ("tiled","tiled_native"):
        raise ValueError("Unknown multiresolution inference mode")
    structures=list(metadata.get("structures") or ())
    ids=[str(s["id"]) for s in structures]
    if not ids or len(ids)!=len(set(ids)):
        raise ValueError("Invalid structure channel IDs")
    if metadata.get("output_stride",2)!=2:
        raise ValueError("Unsupported stride in multiresolution model")
    def validate_size(value):
        if not isinstance(value,list) or len(value)!=2 or any(type(k)!=int or k<32 or k>4096 for k in value):
            raise ValueError("Invalid model input dimensions")
    validate_size(metadata["input_size"])
    components={}
    for key in ("detail","native"):
        if key=="native" and p["mode"]!="tiled_native":
            if key in p:raise ValueError("Native declared for tiled-only mode")
            continue
        c=p.get(key)
        if not isinstance(c,dict) or not _CHECKPOINT.fullmatch(str(c.get("checkpoint",""))):
            raise ValueError("Unsafe or missing component checkpoint name")
        if not _SHA.fullmatch(str(c.get("sha256",""))):
            raise ValueError("Missing component checksum")
        validate_size(c.get("input_size"))
        if c.get("state_prefix","") not in ("","base."):
            raise ValueError("Unsupported checkpoint state prefix")
        components[key]=c
    tiles=p.get("tiles") or {}
    if not isinstance(tiles,dict) or set(tiles)-{"nx","ny","width_fraction","height_fraction"}:
        raise ValueError("Invalid tile options")
    make_tiles(1600,800,**tiles)
    w=p.get("fusion_weight",.6)
    if type(w) not in (int,float) or not isfinite(w) or not 0<=w<=2:
        raise ValueError("Invalid detail fusion weight")
    keep=p.get("retain_detail_structures",[])
    if not isinstance(keep,list) or len(keep)!=len(set(keep)) or set(keep)-set(ids):
        raise ValueError("Invalid structure retention policy")
    if keep and p["mode"]!="tiled_native":
        raise ValueError("Retention requires native component")
    paths={}
    for c in components.values():
        if c["checkpoint"] in paths and paths[c["checkpoint"]]!=c["sha256"]:
            raise ValueError("Contradictory component checksums")
        paths[c["checkpoint"]]=c["sha256"]
    return components

def component_files(metadata):
    return {c["checkpoint"]:c["sha256"] for c in pipeline_components(metadata).values()
            if c["checkpoint"]!="model.pth"}

def verify_component_files(metadata,model_directory):
    directory=Path(model_directory).resolve()
    files=component_files(metadata)
    for filename,expected in files.items():
        path=(directory/filename).resolve()
        if path.parent!=directory or not path.is_file():
            raise ValueError("High-resolution model component missing")
        h=sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda:f.read(1<<20),b""):h.update(chunk)
        if h.hexdigest()!=expected:
            raise ValueError("High-resolution model component checksum mismatch")
    return files

def geometry_to_grid(global_geometry,tile_geometry,tile,full_shape,detail_shape,*,stride=2,device=None):
    import torch
    fh,fw=map(int,full_shape);dh,dw=map(int,detail_shape)
    if min(fh,fw,dh,dw)<1:raise ValueError("Invalid heatmap dimensions")
    g,r=global_geometry,tile_geometry
    xs=(torch.arange(fw,device=device,dtype=torch.float32)+.5)*stride
    ys=(torch.arange(fh,device=device,dtype=torch.float32)+.5)*stride
    sx=(xs-g["offset_x"])/g["scale"];sy=(ys-g["offset_y"])/g["scale"]
    px=(sx-tile.left)*r["scale"]+r["offset_x"]
    py=(sy-tile.top)*r["scale"]+r["offset_y"]
    gx=(2*px/(stride*dw)-1)[None,:].expand(fh,-1)
    gy=(2*py/(stride*dh)-1)[:,None].expand(-1,fw)
    grid=torch.stack((gx,gy),-1)[None]
    x0=((sx-tile.left)/(.18*tile.width)).clamp(0,1) if tile.left else torch.ones_like(xs)
    x1=((tile.right-sx)/(.18*tile.width)).clamp(0,1) if tile.right<g["source_w"] else torch.ones_like(xs)
    y0=((sy-tile.top)/(.18*tile.height)).clamp(0,1) if tile.top else torch.ones_like(ys)
    y1=((tile.bottom-sy)/(.18*tile.height)).clamp(0,1) if tile.bottom<g["source_h"] else torch.ones_like(ys)
    wx=torch.minimum(x0,x1)*((sx>=tile.left)&(sx<=tile.right)).float()
    wy=torch.minimum(y0,y1)*((sy>=tile.top)&(sy<=tile.bottom)).float()
    return grid,(wy[:,None]*wx[None,:])[None,None]

def merge_logits(global_logits,tiles,geometry,*,fusion_weight=.6,stride=2):
    import torch
    from torch.nn import functional as F
    if global_logits.ndim!=4 or global_logits.shape[0]!=1:
        raise ValueError("Invalid global heatmap shape")
    if fusion_weight==0 or not tiles:return global_logits
    base=global_logits.float().sigmoid()
    acc=torch.zeros_like(base);denom=torch.zeros_like(base[:,:1])
    for tile,geo,pred in tiles:
        if pred.ndim!=4 or pred.shape[:2]!=base.shape[:2]:
            raise ValueError("Channel mismatch between full and detail models")
        grid,mask=geometry_to_grid(geometry,geo,tile,base.shape[-2:],
                                  pred.shape[-2:],stride=stride,device=base.device)
        patch=F.grid_sample(pred.to(base.device).float().sigmoid(),grid,
                            padding_mode="zeros",align_corners=False)
        acc+=patch*mask;denom+=mask
    avg=acc/denom.clamp_min(1e-8)
    factor=float(fusion_weight)*denom.clamp(max=1.)
    return torch.logit(((base+factor*avg)/(1.+factor)).clamp(1e-6,1-1e-6))

def _load_component(spec,directory,runner,channels,device):
    import torch
    state=torch.load(Path(directory)/spec["checkpoint"],map_location="cpu",weights_only=True)
    prefix=spec.get("state_prefix","")
    if prefix:
        if not any(str(k).startswith(prefix) for k in state):
            raise ValueError("Missing component state prefix")
        state={key[len(prefix):]:value for key,value in state.items() if key.startswith(prefix)}
    model=runner._model(channels,pretrained=False)
    model.load_state_dict(state,strict=True)
    return model.to(device).eval()

def predict_one(source_path,primary_model,metadata,metadata_path,device,runner,*,component_models=None):
    """Full+detail, optionally native full+selected detail channels, any schema."""
    from PIL import Image
    import torch
    components=pipeline_components(metadata)
    if not components:raise ValueError("Multiresolution inference metadata required")
    if component_models is None:
        verify_component_files(metadata,Path(metadata_path).parent)
    pipeline=metadata["inference_pipeline"]
    with Image.open(source_path) as im:source=im.convert("RGB")
    canvas,geo=runner._letterbox(source,tuple(metadata["input_size"]))
    with torch.no_grad():
        base=primary_model(runner._tensor(canvas)[None].to(device)).float()
    detail_spec=components["detail"]
    detail=(component_models["detail"] if component_models is not None else
            primary_model if detail_spec["checkpoint"]=="model.pth" and not detail_spec.get("state_prefix") else
            _load_component(detail_spec,Path(metadata_path).parent,runner,len(metadata["structures"]),device))
    patches=[]
    try:
        with torch.no_grad():
            for tile in make_tiles(*source.size,**pipeline.get("tiles",{})):
                crop=source.crop((tile.left,tile.top,tile.right,tile.bottom))
                patch_canvas,pg=runner._letterbox(crop,tuple(detail_spec["input_size"]))
                prediction=detail(runner._tensor(patch_canvas)[None].to(device)).float()
                patches.append((tile,pg,prediction))
        refined=merge_logits(base,patches,geo,fusion_weight=pipeline.get("fusion_weight",.6),
                             stride=int(metadata.get("output_stride",2)))
        refined=runner._decode_logits(refined,geo,metadata)
    finally:
        if component_models is None and detail is not primary_model:del detail
    if pipeline["mode"]=="tiled":return refined
    native_spec=components["native"]
    native=(component_models["native"] if component_models is not None else
            primary_model if native_spec["checkpoint"]=="model.pth" and not native_spec.get("state_prefix") else
            _load_component(native_spec,Path(metadata_path).parent,runner,len(metadata["structures"]),device))
    try:
        native_canvas,ng=runner._letterbox(source,tuple(native_spec["input_size"]))
        with torch.no_grad():
            native_logits=native(runner._tensor(native_canvas)[None].to(device)).float()
        primary=runner._decode_logits(native_logits,ng,metadata)
    finally:
        if component_models is None and native is not primary_model:del native
    kept=set(pipeline.get("retain_detail_structures",()))
    by_id={g["structure_id"]:g for g in refined}
    return [by_id[g["structure_id"]] if g["structure_id"] in kept else g for g in primary]
