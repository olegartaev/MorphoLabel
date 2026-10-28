"""Build an inactive portable multiresolution model package from trained weights.

No training, project database access, registration or automatic activation.
Source standard MorphoLabel package already binds scientific schema.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ai_runtime.universal_multires import pipeline_components

def digest(data):return sha256(data).hexdigest()

def package_candidate(base_zip,detail_pth,native_pth,threshold_json,output, *,
                      retain_structures=(),full_size=(1536,512),
                      detail_size=(768,384),model_name="multires_candidate_v1"):
    import torch
    output=Path(output).resolve()
    if output.exists():raise FileExistsError("Refusing to overwrite model package")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,95}",model_name):
        raise ValueError("Invalid proposed model ID")
    with ZipFile(base_zip) as z:
        if not {"manifest.json","artifacts/model.json","artifacts/model.pth"}<=set(z.namelist()):
            raise ValueError("Missing base model package files")
        manifest=json.loads(z.read("manifest.json"))
        original_meta=z.read("artifacts/model.json")
        meta=json.loads(original_meta)
        base=z.read("artifacts/model.pth")
    if set(manifest.get("files",{}))!={"artifacts/model.json","artifacts/model.pth"}:
        raise ValueError("Expected exported STANDARD model package")
    if (digest(base)!=manifest["files"]["artifacts/model.pth"] or
        digest(original_meta)!=manifest["files"]["artifacts/model.json"]):
        raise ValueError("Base package checksum mismatch")
    if meta.get("inference_pipeline") is not None:raise ValueError("Base must be a legacy standard model")
    if meta.get("schema_digest")!=manifest.get("schema_digest") or meta.get("backend")!=manifest.get("backend"):
        raise ValueError("Original scientific schema or backend mismatch")
    ids=[str(s["id"]) for s in meta["structures"]]
    if not ids or len(set(ids))!=len(ids) or set(retain_structures)-set(ids):
        raise ValueError("Unknown/duplicated scientific structure channel")
    thresholds=json.loads(Path(threshold_json).read_text(encoding="utf-8"))
    if "tuned_thresholds" in thresholds:thresholds=thresholds["tuned_thresholds"]
    if set(thresholds)!=set(ids) or any(type(v) not in (int,float) or not 0<v<=1 for v in thresholds.values()):
        raise ValueError("Missing/invalid previously calibrated thresholds")
    base_state=torch.load(BytesIO(base),weights_only=True,map_location="cpu")
    if base_state.get("head.weight") is None or base_state["head.weight"].shape[0]!=len(ids):
        raise ValueError("Base checkpoint channel mismatch")
    detail=Path(detail_pth).read_bytes()
    detail_state=torch.load(BytesIO(detail),weights_only=True,map_location="cpu")
    if set(detail_state)!=set(base_state) or any(detail_state[k].shape!=base_state[k].shape for k in base_state):
        raise ValueError("Detail checkpoint tensor schema mismatch")
    extras={"detail.pth":detail}
    mode="tiled" if native_pth is None else "tiled_native"
    options={"name":"multires_heatmap_v1","version":1,"mode":mode,
             "detail":{"checkpoint":"detail.pth","sha256":digest(detail),
                       "input_size":list(detail_size)},
             "fusion_weight":.6,
             "tiles":{"nx":4,"ny":2,"width_fraction":.38,"height_fraction":.62}}
    if native_pth is not None:
        native=Path(native_pth).read_bytes()
        state=torch.load(BytesIO(native),weights_only=True,map_location="cpu")
        extracted={k[len("base."):]:v for k,v in state.items() if k.startswith("base.")}
        if set(extracted)!=set(base_state) or any(extracted[k].shape!=base_state[k].shape for k in base_state):
            raise ValueError("Native checkpoint tensor schema mismatch")
        options["native"]={"checkpoint":"native.pth","sha256":digest(native),
                           "input_size":list(full_size),"state_prefix":"base."}
        options["retain_detail_structures"]=list(retain_structures)
        extras["native.pth"]=native
    meta["inference_pipeline"]=options
    meta["thresholds"]={k:float(v) for k,v in thresholds.items()}
    meta["model_id"]=model_name
    pipeline_components(meta)
    files={"artifacts/model.pth":base,
           "artifacts/model.json":json.dumps(meta,indent=2,ensure_ascii=False,sort_keys=True).encode()}
    files.update({"artifacts/"+k:v for k,v in extras.items()})
    manifest["model_id"]=model_name
    manifest["files"]={name:digest(data) for name,data in files.items()}
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,"w",ZIP_DEFLATED,compresslevel=6) as out:
        for name,data in files.items():out.writestr(name,data)
        out.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2))
    with ZipFile(output) as z:
        if z.testzip() is not None:raise ValueError("New model package CRC failed")
    return {"sha256":digest(output.read_bytes()),"file":str(output),
            "channels":len(ids),"mode":mode,"inactive":True,
            "auxiliary_files":list(extras)}

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--base-package",type=Path,required=True)
    a.add_argument("--detail-weights",type=Path,required=True)
    a.add_argument("--native-weights",type=Path)
    a.add_argument("--thresholds",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    a.add_argument("--retain-detail",action="append",default=[])
    a.add_argument("--model-id",default="multires_candidate_v1")
    x=a.parse_args()
    print(json.dumps(package_candidate(x.base_package,x.detail_weights,x.native_weights,
         x.thresholds,x.output,retain_structures=x.retain_detail,
         model_name=x.model_id),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
