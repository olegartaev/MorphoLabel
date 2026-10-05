"""Shared file-dialog naming for portable models."""
import re


def model_package_filename(model, fallback="model"):
    ident=str((model or {}).get("model_id") or fallback).strip()
    safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", ident).rstrip(" .") or fallback
    if safe.split(".")[0].upper() in {"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}:safe="_"+safe
    return safe+".zip"
