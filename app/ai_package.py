"""Portable, model-only SIMM AI package import/export."""
from __future__ import annotations
import hashlib, json, shutil, zipfile
from pathlib import Path
from .crop_training import ACTIVE, MODELS, active_info
from .io import atomic_json_write
from .project_storage import schema_hash

class AIPackageError(ValueError): pass

def _digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _files(directory): return [p for p in Path(directory).rglob('*') if p.is_file()]
def _add_tree(archive, directory, prefix, manifest):
 for path in _files(directory):
  name=f"{prefix}/{path.relative_to(directory).as_posix()}"; archive.write(path,name); manifest[name]=_digest(path)

def export_ai_package(project, target):
 target=Path(target); landmark=project.active_model('landmark'); crop=active_info(); checksums={}; package={'format_version':1,'schema_sha256':schema_hash(project.schema_path),'landmark_model':None,'crop_model':None}
 with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
  if landmark:
   directory=Path(landmark['path']);directory=directory if directory.is_absolute() else project.data_root/directory
   if not directory.is_dir(): raise AIPackageError('active landmark model artifact is unavailable')
   package['landmark_model']={'metadata':landmark,'prefix':f"landmark/{landmark['model_id']}"};_add_tree(archive,directory,package['landmark_model']['prefix'],checksums)
  crop_id=crop.get('model_id')
  if crop_id:
   directory=MODELS/crop_id
   if not directory.is_dir(): raise AIPackageError('active crop model artifact is unavailable')
   package['crop_model']={'model_id':crop_id,'active_info':crop,'prefix':f"crop/{crop_id}"};_add_tree(archive,directory,package['crop_model']['prefix'],checksums)
  package['files']=checksums;archive.writestr('package.json',json.dumps(package,indent=2,sort_keys=True))
 return target

def _read(archive):
 try:return json.loads(archive.read('package.json'))
 except (KeyError,json.JSONDecodeError) as exc: raise AIPackageError('invalid AI package manifest') from exc

def import_ai_package(project, source):
 source=Path(source)
 with zipfile.ZipFile(source) as archive:
  package=_read(archive)
  if package.get('schema_sha256')!=schema_hash(project.schema_path): raise AIPackageError('AI package schema hash does not match current landmark_schema.csv')
  for name,digest in package.get('files',{}).items():
   try:data=archive.read(name)
   except KeyError as exc: raise AIPackageError(f'missing package file: {name}') from exc
   if hashlib.sha256(data).hexdigest()!=digest: raise AIPackageError(f'corrupt package file: {name}')
  landmark=package.get('landmark_model');crop=package.get('crop_model')
  if landmark and project.model_metadata(landmark['metadata']['model_id']): raise AIPackageError('landmark model ID already exists in this project')
  if crop and project.model_metadata(crop['model_id']): raise AIPackageError('crop model ID already exists in this project')
  def extract(prefix,destination):
   destination.mkdir(parents=True,exist_ok=False)
   for name in package.get('files',{}):
    if name.startswith(prefix+'/'):
     output=destination/name[len(prefix)+1:];output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(archive.read(name))
  imported=[]
  if landmark:
   metadata=landmark['metadata'];directory=project.data_root/'ai'/'models'/metadata['model_id'];extract(landmark['prefix'],directory)
   metrics=json.loads(metadata['metrics_json']) if metadata.get('metrics_json') else {}
   project.register_model(metadata['model_id'],'landmark',path=directory.relative_to(project.data_root).as_posix(),metrics=metrics,schema_digest=metadata['schema_sha256'],dataset_id=metadata.get('dataset_id'),parent_model_id=None,dataset_manifest_path=None);imported.append(metadata['model_id'])
  if crop:
   directory=project.data_root/'ai'/'imported_crop_models'/crop['model_id'];extract(crop['prefix'],directory)
   project.register_model(crop['model_id'],'crop',path=directory.relative_to(project.data_root).as_posix(),metrics={'package_active_info':crop.get('active_info',{})},schema_digest=package['schema_sha256']);imported.append(crop['model_id'])
 return tuple(imported)


def _zip_bytes(z, name, data, manifest):
 z.writestr(name,data);manifest[name]=hashlib.sha256(data).hexdigest()

def _portable_landmark_export(directory, model):
 portable_config=directory/"inference_config.py";checkpoint=directory/"best_engineering_validation.pth"
 if not portable_config.is_file():
  # Existing imports used the portable package name before canonical storage.
  try:legacy=json.loads((directory/"model.json").read_text(encoding="utf-8"))
  except (OSError,ValueError):legacy={}
  if (legacy.get("result") or {}).get("inference_config")=="config.py":portable_config=directory/"config.py"
 if not portable_config.is_file():
  raise AIPackageError("landmark model has no portable inference config; finalize or retrain it with the current MorphoLabel version")
 if not checkpoint.is_file() or checkpoint.stat().st_size<=0:
  raise AIPackageError("landmark model inference checkpoint is unavailable")
 try:source_info=json.loads((directory/"model.json").read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as exc:raise AIPackageError("landmark model metadata is unavailable") from exc
 portable_info={
  "model_id":model["model_id"],
  "backend":source_info.get("backend") or "rtmpose",
  "schema_sha256":model.get("schema_sha256") or source_info.get("schema_sha256"),
  "input_size":source_info.get("input_size") or [512,256],
  "result":{
   "checkpoint_path":"best_engineering_validation.pth",
   "checkpoint_sha256":_digest(checkpoint),
   "inference_config":"config.py",
   "inference_config_sha256":_digest(portable_config),
  },
 }
 files={
  "artifacts/config.py":portable_config.read_bytes(),
  "artifacts/best_engineering_validation.pth":checkpoint.read_bytes(),
  "artifacts/model.json":json.dumps(portable_info,indent=2,sort_keys=True).encode("utf-8"),
 }
 safe_metrics={"backend":portable_info["backend"],"input_size":portable_info["input_size"],"portable":True}
 return files,safe_metrics

def export_model_package(project, kind, target, model_id=None):
 """Export exactly one portable inference model, never training/project data."""
 if kind not in {"crop","landmark"}: raise AIPackageError("unsupported model type")
 model=project.model_metadata(model_id) if model_id else project.active_model(kind)
 if not model or model.get("kind")!=kind: raise AIPackageError(f"no {kind} model selected")
 directory=project.data_root/model["path"]
 if not directory.is_dir(): raise AIPackageError("model artifact is unavailable")
 if kind=="landmark":
  files,metrics=_portable_landmark_export(directory,model)
  export_metadata={"model_id":model["model_id"],"kind":"landmark","schema_sha256":model.get("schema_sha256"),"created_at":model.get("created_at"),"metrics_json":json.dumps(metrics,sort_keys=True)}
 else:
  # Crop model artifacts are already compact; redact training-image membership
  # from the exported manifest while preserving the weights and model contract.
  weights=directory/"model.npz";manifest_path=directory/"model_manifest.json"
  if not weights.is_file() or not manifest_path.is_file():raise AIPackageError("crop model artifact is incomplete")
  crop_manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
  for key in ("training_image_ids","train_indices","validation_indices"):crop_manifest.pop(key,None)
  files={"artifacts/model.npz":weights.read_bytes(),"artifacts/model_manifest.json":json.dumps(crop_manifest,indent=2,sort_keys=True).encode("utf-8")}
  metrics={"backend":crop_manifest.get("backend"),"metrics":crop_manifest.get("metrics",{}),"portable":True}
  export_metadata={"model_id":model["model_id"],"kind":"crop","schema_sha256":model.get("schema_sha256"),"created_at":model.get("created_at"),"metrics_json":json.dumps(metrics,sort_keys=True)}
 from .model_schemes import export_schemes
 schemes=export_schemes(project,model)
 # Model output identities were checked above; portable metadata binds to the
 # exact embedded CSV, including harmless display/role changes.
 if kind=="landmark":export_metadata["schema_sha256"]=schema_hash(project.schema_path)
 if kind=="landmark":
  portable_info=json.loads(files["artifacts/model.json"]);portable_info["schema_sha256"]=export_metadata["schema_sha256"]
  files["artifacts/model.json"]=json.dumps(portable_info,indent=2,sort_keys=True).encode("utf-8")
 manifest={"package_format_version":2,"model_type":kind,"model_id":model["model_id"],"created_at":model.get("created_at"),"schema_sha256":export_metadata.get("schema_sha256"),"backend":metrics.get("backend"),"training_statistics":metrics,"model_metadata":export_metadata,"project_schemes":schemes,"files":{}}
 with zipfile.ZipFile(Path(target),"w",zipfile.ZIP_DEFLATED) as z:
  for name,data in files.items():_zip_bytes(z,name,data,manifest["files"])
  z.writestr("manifest.json",json.dumps(manifest,indent=2,sort_keys=True))
 return Path(target)
def import_model_package(project, source, expected_kind):
 source=Path(source)
 try:z=zipfile.ZipFile(source)
 except zipfile.BadZipFile as exc:raise AIPackageError("corrupt model package") from exc
 with z:
  try:m=json.loads(z.read("manifest.json"))
  except Exception as exc:raise AIPackageError("invalid model manifest") from exc
  if m.get("package_format_version")!=2 or m.get("model_type")!=expected_kind:raise AIPackageError("wrong model package type")
  required={"artifacts/model.npz","artifacts/model_manifest.json"} if expected_kind=="crop" else {"artifacts/config.py","artifacts/best_engineering_validation.pth","artifacts/model.json"}
  if set(m.get("files",{}))!=required:raise AIPackageError("Model package has an incomplete or unexpected artifact set.")
  bundle=m.get("project_schemes")
  if bundle is not None:
   from .model_schemes import validate_schemes
   try:validate_schemes(bundle,expected_kind,m.get("schema_sha256"))
   except (ValueError,TypeError,KeyError) as exc:raise AIPackageError(str(exc)) from exc
  elif expected_kind=="landmark" and m.get("schema_sha256")!=schema_hash(project.schema_path):raise AIPackageError("Landmark model incompatible with current schema")
  for name,digest in m.get("files",{}).items():
   if not name.startswith("artifacts/") or name == "artifacts/" or ".." in Path(name).parts:raise AIPackageError(f"unsafe artifact path: {name}")
   try:data=z.read(name)
   except KeyError as exc:raise AIPackageError(f"missing package artifact: {name}") from exc
   if hashlib.sha256(data).hexdigest()!=digest:raise AIPackageError(f"checksum mismatch: {name}")
  if expected_kind=="crop":
   import io,numpy as np
   try:
    with np.load(io.BytesIO(z.read("artifacts/model.npz")),allow_pickle=False) as arrays:weights=arrays["weights"]
    if weights.shape not in {(769,4),(769,6)} or not np.isfinite(weights).all():raise ValueError("Invalid Crop weight dimensions or values.")
   except Exception as exc:raise AIPackageError(f"Invalid Crop weights: {exc}") from exc
  original=str(m.get("model_id") or "")
  reserved={"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}
  if not original or len(original)>160 or original in {".",".."} or original.rstrip(" .")!=original or any(ch in '<>:"/\\|?*' or ord(ch)<32 for ch in original) or original.split('.')[0].upper() in reserved:raise AIPackageError("Unsafe model ID: model files must stay inside this project's model folder.")
  local=original;counter=1
  while project.model_metadata(local) or (project.models_root/expected_kind/local).exists():counter+=1;local=f"imported_{original}_{counter}"
  destination=project.models_root/expected_kind/local
  from .model_publication import staged_model_directory
  with staged_model_directory(destination) as (tmp,publish):
   for name in m["files"]:
    out=tmp/name[len("artifacts/"):];out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(z.read(name))
   if expected_kind=="landmark":
    (tmp/"config.py").rename(tmp/"inference_config.py")
    info=json.loads((tmp/"model.json").read_text(encoding="utf-8"))
    info.setdefault("result",{})["inference_config"]="inference_config.py"
    atomic_json_write(tmp/"model.json",info)
   if project.model_metadata(local):raise FileExistsError(local)
   publish()
   metadata=m.get("model_metadata",{});metrics=json.loads(metadata.get("metrics_json") or "{}") if isinstance(metadata.get("metrics_json"),str) else metadata.get("metrics_json",{})
   metrics={**metrics,"origin":"imported","original_model_id":original,"imported_at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),"package_manifest":m}
   with project.atomic_model_import():
    if bundle is not None:
     from .model_schemes import apply_schemes
     apply_schemes(project,bundle)
    project.register_model(local,expected_kind,path=destination.relative_to(project.data_root).as_posix(),metrics=metrics,active=expected_kind=="crop",schema_digest=m.get("schema_sha256"),parent_model_id=None)
 return local
