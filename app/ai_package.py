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


def export_model_package(project, kind, target, model_id=None):
 """Export exactly one registered project-local model, no project data."""
 if kind not in {"crop","landmark"}: raise AIPackageError("unsupported model type")
 model=project.model_metadata(model_id) if model_id else project.active_model(kind)
 if not model or model.get("kind")!=kind: raise AIPackageError(f"no {kind} model selected")
 directory=project.data_root/model["path"]
 if not directory.is_dir(): raise AIPackageError("model artifact is unavailable")
 metrics=json.loads(model.get("metrics_json") or "{}")
 export_metadata={key:value for key,value in model.items() if key not in {"path","active"}}
 manifest={"package_format_version":2,"model_type":kind,"model_id":model["model_id"],"created_at":model.get("created_at"),"schema_sha256":model.get("schema_sha256"),"backend":metrics.get("backend"),"training_statistics":metrics,"model_metadata":export_metadata,"files":{}}
 with zipfile.ZipFile(Path(target),"w",zipfile.ZIP_DEFLATED) as z:
  _add_tree(z,directory,"artifacts",manifest["files"]);z.writestr("manifest.json",json.dumps(manifest,indent=2,sort_keys=True))
 return Path(target)
def import_model_package(project, source, expected_kind):
 source=Path(source)
 try:z=zipfile.ZipFile(source)
 except zipfile.BadZipFile as exc:raise AIPackageError("corrupt model package") from exc
 with z:
  try:m=json.loads(z.read("manifest.json"))
  except Exception as exc:raise AIPackageError("invalid model manifest") from exc
  if m.get("package_format_version")!=2 or m.get("model_type")!=expected_kind:raise AIPackageError("wrong model package type")
  if expected_kind=="landmark" and m.get("schema_sha256")!=schema_hash(project.schema_path):raise AIPackageError("Landmark model incompatible with current schema")
  for name,digest in m.get("files",{}).items():
   if not name.startswith("artifacts/") or name == "artifacts/" or ".." in Path(name).parts:raise AIPackageError(f"unsafe artifact path: {name}")
   try:data=z.read(name)
   except KeyError as exc:raise AIPackageError(f"missing package artifact: {name}") from exc
   if hashlib.sha256(data).hexdigest()!=digest:raise AIPackageError(f"checksum mismatch: {name}")
  original=m["model_id"];local=original;counter=1
  while project.model_metadata(local):counter+=1;local=f"imported_{original}_{counter}"
  destination=project.models_root/expected_kind/local
  tmp=destination.with_name(destination.name+".importing")
  if tmp.exists():shutil.rmtree(tmp)
  try:
   for name in m["files"]:
    out=tmp/name[len("artifacts/"):];out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(z.read(name))
   tmp.parent.mkdir(parents=True,exist_ok=True);tmp.replace(destination)
   metadata=m.get("model_metadata",{});metrics=json.loads(metadata.get("metrics_json") or "{}") if isinstance(metadata.get("metrics_json"),str) else metadata.get("metrics_json",{})
   metrics={**metrics,"origin":"imported","original_model_id":original,"imported_at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),"package_manifest":m}
   project.register_model(local,expected_kind,path=destination.relative_to(project.data_root).as_posix(),metrics=metrics,active=False,schema_digest=m.get("schema_sha256"),parent_model_id=None)
  except Exception:
   if tmp.exists():shutil.rmtree(tmp)
   raise
 return local
