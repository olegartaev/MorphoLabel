"""Display-only numbering for X-ray structure models."""
from __future__ import annotations
import json
import re


def structure_display_numbers(project, models):
    """Reserve legacy numbers and persistent local numbers, then fill gaps."""
    models=list(models)
    numbers={}
    reserved=set()
    # Canonical legacy IDs have priority if noncanonical variants share a number.
    for model in sorted(models,key=lambda row:(len(str(row["model_id"])),str(row["model_id"])) ,reverse=True):
        ident=str(model["model_id"])
        match=re.fullmatch(r"xray_structure_model_v(\d+)",ident)
        if match and int(match.group(1)) not in reserved:
            numbers[ident]=int(match.group(1));reserved.add(numbers[ident])
    pending=[]
    for model in sorted(models,key=lambda row:(str(row.get("created_at") or ""),str(row["model_id"]))):
        ident=str(model["model_id"])
        if ident in numbers:continue
        try:
            metadata=json.loads((project.root/str(model["metadata_path"])).read_text(encoding="utf-8"))
            number=metadata.get("display_number")
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            number=None
        if type(number) is int and number>0 and number not in reserved:
            numbers[ident]=number;reserved.add(number)
        else:pending.append(ident)
    candidate=max((int(re.fullmatch(r"xray_structure_model_v(\d+)",ident).group(1)) for ident in numbers if re.fullmatch(r"xray_structure_model_v(\d+)",ident)),default=0)+1
    for ident in pending:
        while candidate in reserved:candidate+=1
        numbers[ident]=candidate;reserved.add(candidate);candidate+=1
    return numbers
