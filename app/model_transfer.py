"""Shared file-dialog naming for portable models."""
import re


def registered_active_model(project, kind):
    """Display registry metadata even when the current scheme blocks inference."""
    return next((model for model in project.models(kind) if model.get("active")), None)


def model_package_filename(model, fallback="model"):
    ident=str((model or {}).get("model_id") or fallback).strip()
    module=next((name for name in ("landmarks","xray") if fallback.startswith(name+"_")),None)
    if module and not ident.startswith(module+"_"):ident=module+"_"+ident
    safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", ident).rstrip(" .") or fallback
    if safe.split(".")[0].upper() in {"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}:safe="_"+safe
    return safe+".zip"
