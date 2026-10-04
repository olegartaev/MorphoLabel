"""Presentation metadata for independently readable MorphoLabel modules."""
from __future__ import annotations
import json

BUILTIN_CREDITS={
    'landmarks':('Oleg Artaev','Crop, landmarks, measurements and export'),
    'xray_counts':('Oleg Artaev','X-ray crops, structures and calculated traits'),
}

_BACKEND_LABELS={
    'rtmpose':'RTMPose-M (MMPose)',
    'rtmdet_tiny_mmdet_3_2':'RTMDet-tiny (MMDetection)',
    'mobilenet_v3_small_imagenet_transfer_v1':'MobileNetV3-Small',
    'resnet18_heatmap_v1':'ResNet-18 heatmap',
    'numpy_ridge_image_regression':'NumPy ridge image regression',
}

def _metrics(model):
    if not model:return {}
    value=model.get('metrics')
    if isinstance(value,dict):return value
    raw=model.get('metrics_json')
    if isinstance(raw,str):
        try:
            value=json.loads(raw or '{}')
            return value if isinstance(value,dict) else {}
        except Exception:return {}
    return {}

def _backend_label(value,default):
    key=str(value or default or '')
    return _BACKEND_LABELS.get(key,key.replace('_',' ') if key else 'not available')

def _landmarks_ai(shell):
    from app.landmark_bootstrap import LANDMARK_BOOTSTRAP_ARCHITECTURE, LANDMARK_BOOTSTRAP_DATASET
    project=getattr(getattr(shell,'context',None),'project',None) if shell is not None else None
    active=None
    if project is not None:
        try:active=project.active_model_readonly('landmark')
        except Exception:active=None
    metrics=_metrics(active)
    backend=metrics.get('backend') or (metrics.get('model_info') or {}).get('backend') or 'rtmpose'
    architecture=_backend_label(backend,LANDMARK_BOOTSTRAP_ARCHITECTURE)
    if str(backend)=='rtmpose':architecture=f"{LANDMARK_BOOTSTRAP_ARCHITECTURE} (MMPose; {LANDMARK_BOOTSTRAP_DATASET} bootstrap)"
    active_text=f"; active model: {active['model_id']}" if active and active.get('model_id') else "; active model: none"
    return f"Landmark AI: {architecture}{active_text}. Crop: NumPy ridge image regression (non-neural)."

def _xray_ai(shell):
    from app.xray_detector import DETECTOR_BACKEND
    from app.xray_orientation import ORIENTATION_BACKEND
    from app.xray_structure_ai import STRUCTURE_BACKEND
    runtime=getattr(shell,'_active_module_runtime',None) if shell is not None and getattr(shell,'module_key',None)=='xray_counts' else None
    project=getattr(runtime,'project',None)
    crop=project.active_crop_model() if project is not None else None
    structure=project.active_structure_model() if project is not None else None
    crop_metrics=_metrics(crop)
    crop_backend=crop_metrics.get('backend') or DETECTOR_BACKEND
    orientation_backend=crop_metrics.get('orientation/backend') or ORIENTATION_BACKEND
    structure_backend=(structure or {}).get('backend') or _metrics(structure).get('backend') or STRUCTURE_BACKEND
    active=[]
    if crop and crop.get('model_id'):active.append(f"Crop {crop['model_id']}")
    if structure and structure.get('model_id'):active.append(f"Structures {structure['model_id']}")
    active_text="; active: "+", ".join(active) if active else "; active models: none loaded"
    return (
        f"AI: Crop — {_backend_label(crop_backend,DETECTOR_BACKEND)}; "
        f"orientation — {_backend_label(orientation_backend,ORIENTATION_BACKEND)}; "
        f"Structures — {_backend_label(structure_backend,STRUCTURE_BACKEND)}{active_text}."
    )

def module_credit_rows(registry,shell=None):
    rows=[]
    for spec in registry.available():
        author,scope=BUILTIN_CREDITS.get(spec.module_id,('See module documentation',spec.description)) if spec.source=='builtin' else ('See module documentation',spec.description)
        if spec.module_id=='landmarks':ai=_landmarks_ai(shell)
        elif spec.module_id=='xray_counts':ai=_xray_ai(shell)
        else:ai="AI: see module documentation."
        rows.append((spec.display_name,author,scope,ai))
    return tuple(rows)
