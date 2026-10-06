"""Tabular export of calculated X-ray traits without changing project data."""
from __future__ import annotations

import csv
from pathlib import Path
from .xray_specimen_identity import specimen_display_id


def _trait_columns(traits):
    """Readable unique export headers: abbreviations/ids without implementation prefixes."""
    used=set();columns=[]
    for trait in traits or ():
        base=str(trait.get("abbr") or trait["id"]).strip() or str(trait["id"])
        label=base
        if label in used:label=str(trait["id"])
        suffix=2;candidate=label
        while candidate in used:
            candidate=f"{label}_{suffix}";suffix+=1
        label=candidate;used.add(label);columns.append((str(trait["id"]),label))
    return columns


def export_trait_rows(project,target,verified_only=False):
    """Write current trait calculations for all specimens or verified rows only."""
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    scheme_record=project.active_scheme_record();traits=list(scheme_record["scheme"].get("traits") or ())
    trait_columns=_trait_columns(traits);rows=list(project.trait_rows())
    if verified_only:rows=[row for row in rows if str(row.get("result_status") or "")=="verified"]
    fields=("specimen_id","image_id","ordinal","relative_path","result_status","schema_version_id","specimen_code",
            *(label for _trait_id,label in trait_columns))
    with target.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore");writer.writeheader()
        for row in rows:
            values={field:row.get(field,"") for field in fields[:5]}
            values["schema_version_id"]=scheme_record["scientific_version_id"]
            values["specimen_code"]=specimen_display_id(row)
            trait_values=row.get("trait_values") or {}
            values.update({label:trait_values.get(trait_id) for trait_id,label in trait_columns})
            writer.writerow(values)
    return {"path":target,"rows":len(rows),"verified_only":bool(verified_only)}
