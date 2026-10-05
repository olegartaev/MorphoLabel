"""Validated, portable Landmark and measurement definitions; no image data."""
import hashlib
import tempfile
from pathlib import Path
from .project_storage import load_schema, schema_hash, landmark_model_schema_compatible
from .measurements import measurement_definitions_csv, parse_measurement_definitions, import_measurement_definitions


def export_schemes(project,model):
 if model['kind']=='landmark' and not landmark_model_schema_compatible(project,model):
  raise ValueError("The selected Landmark model was trained for a different landmark order. Restore its scheme before exporting.")
 # Keep exact CSV bytes (including BOM/CRLF) because model provenance uses
 # their SHA256, while parsing still uses abbreviation identity.
 scheme=project.schema_path.read_bytes().decode('utf-8')
 measurements=measurement_definitions_csv(project)
 return {name:{'csv':text,'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()} for name,text in (('landmarks',scheme),('measurements',measurements))}


def validate_schemes(bundle,kind,model_digest):
 if not isinstance(bundle,dict) or set(bundle)!={'landmarks','measurements'}:raise ValueError('Incomplete model scheme bundle.')
 for value in bundle.values():
  if not isinstance(value,dict) or not isinstance(value.get('csv'),str) or hashlib.sha256(value['csv'].encode('utf-8')).hexdigest()!=value.get('sha256'):raise ValueError('Model scheme checksum mismatch.')
 with tempfile.TemporaryDirectory(prefix='model_scheme_check_') as directory:
  path=Path(directory)/'schema.csv';path.write_bytes(bundle['landmarks']['csv'].encode('utf-8'))
  schema=load_schema(path)
  if kind=='landmark' and (not schema or schema_hash(path)!=model_digest):raise ValueError('Landmark model and embedded scheme disagree.')
 parse_measurement_definitions(bundle['measurements']['csv'],schema)
 return schema


def apply_schemes(project,bundle):
 with tempfile.TemporaryDirectory(prefix='model_scheme_apply_') as directory:
  path=Path(directory)/'schema.csv';path.write_bytes(bundle['landmarks']['csv'].encode('utf-8'))
  if not load_schema(path):return
  project.apply_landmark_schema(path)
  # An empty Crop scheme has no scientific definitions to replace.
  if project.schema:
   path=Path(directory)/'measurements.csv';path.write_bytes(bundle['measurements']['csv'].encode('utf-8'))
   import_measurement_definitions(project,path)
