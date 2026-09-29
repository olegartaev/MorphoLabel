"""Versioned, taxon-neutral trait schemes for the MorphoLabel X-ray module."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

SCHEMA_FORMAT_VERSION = 1
SCHEME_RESOURCE_DIR = Path(__file__).resolve().parent / "resources" / "xray_trait_schemes"

TRAIT_METHODS = (
    {"id":"count","label":"Count objects","icon":"count","help":"Count repeated anatomical elements, for example vertebrae or fin rays."},
    {"id":"count_to","label":"Count up to a reference","icon":"count_to","help":"Count repeated elements from the start of a series up to an anatomical reference."},
    {"id":"count_between","label":"Count between two references","icon":"count_between","help":"Count repeated elements between two anatomical references."},
    {"id":"position","label":"Position in a series","icon":"position","help":"Record which numbered element in a repeated series corresponds to a reference."},
    {"id":"presence","label":"Presence / absence","icon":"presence","help":"Record whether an anatomical feature is present on the image."},
    {"id":"distance","label":"Measure distance","icon":"distance","help":"Measure a straight-line distance between two annotated references."},
    {"id":"angle","label":"Measure angle","icon":"angle","help":"Measure an angle defined by annotated references."},
    {"id":"derived","label":"Calculated from other traits","icon":"derived","help":"Calculate this value from traits that are already part of the scheme."},
)
METHOD_BY_ID = {item["id"]: item for item in TRAIT_METHODS}

SHAPES = ("circle","triangle","diamond","square","cross","ring")
MARKER_COLORS = ("#1976e9","#20a447","#ef8a17","#7e57c2","#d9534f","#66727d")


def blank_scheme(name="Untitled X-ray trait scheme"):
    return {
        "format_version":SCHEMA_FORMAT_VERSION,
        "scheme_id":"custom",
        "name":str(name),
        "description":"",
        "reference":{},
        "structures":[],
        "traits":[],
    }


def normalize_scheme(scheme):
    value=deepcopy(scheme)
    if int(value.get("format_version",0)) != SCHEMA_FORMAT_VERSION:
        raise ValueError("Unsupported X-ray trait scheme format")
    value.setdefault("reference",{});value.setdefault("description","");value.setdefault("structures",[]);value.setdefault("traits",[])
    structure_ids=set();hotkeys=set()
    for index,structure in enumerate(value["structures"]):
        ident=str(structure.get("id","")).strip()
        if not ident or ident in structure_ids:raise ValueError("Every structure needs a unique id")
        structure_ids.add(ident)
        structure.setdefault("annotation","point");structure.setdefault("repeated",False);structure.setdefault("required",True)
        structure.setdefault("shape",SHAPES[index%len(SHAPES)]);structure.setdefault("color",MARKER_COLORS[index%len(MARKER_COLORS)])
        hotkey=str(structure.get("hotkey","")).strip()
        if hotkey:
            if hotkey in hotkeys:raise ValueError("Structure hotkeys must be unique")
            hotkeys.add(hotkey)
    trait_ids=set()
    for trait in value["traits"]:
        ident=str(trait.get("id","")).strip()
        if not ident or ident in trait_ids:raise ValueError("Every trait needs a unique id")
        trait_ids.add(ident)
        method=trait.get("method")
        if method not in METHOD_BY_ID:raise ValueError(f"Unsupported trait method: {method}")
        missing=set(trait.get("structures",()))-structure_ids
        if missing:raise ValueError(f"Trait {ident} refers to missing structures: {sorted(missing)}")
    for trait in value["traits"]:
        missing=set((trait.get("rule") or {}).get("depends_on",()))-trait_ids
        if missing:raise ValueError(f"Trait {trait['id']} depends on missing traits: {sorted(missing)}")
    return value


def load_scheme_file(path):
    """Read and validate one portable JSON trait scheme."""
    with Path(path).open("r",encoding="utf-8") as handle:
        return normalize_scheme(json.load(handle))


def save_scheme_file(scheme,path):
    """Write a normalized, human-readable portable JSON trait scheme."""
    target=Path(path)
    target.write_text(json.dumps(normalize_scheme(scheme),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return target


def bundled_scheme_catalog():
    """Discover bundled schemes from JSON resources; adding a file adds a scheme."""
    items=[]
    if not SCHEME_RESOURCE_DIR.is_dir():return ()
    for path in sorted(SCHEME_RESOURCE_DIR.glob("*.json")):
        scheme=load_scheme_file(path)
        items.append({
            "id":scheme["scheme_id"],
            "name":scheme["name"],
            "description":scheme.get("description",""),
            "trait_count":len(scheme["traits"]),
            "structure_count":len(scheme["structures"]),
            "trait_abbrs":tuple(item.get("abbr") or item["id"] for item in scheme["traits"]),
            "reference":deepcopy(scheme.get("reference") or {}),
            "path":path,
            "source":"Built-in scheme file",
        })
    return tuple(items)


def bundled_scheme(scheme_id):
    for item in bundled_scheme_catalog():
        if str(scheme_id)==item["id"]:
            return load_scheme_file(item["path"])
    raise KeyError(f"Unknown X-ray trait scheme: {scheme_id}")


def phoxinus_vertebral_preset():
    """Compatibility API; the scientific content lives only in the JSON resource."""
    return bundled_scheme("phoxinus_vertebral_counts")


# Compatibility aliases for early development callers.
preset_catalog=bundled_scheme_catalog
preset_scheme=bundled_scheme


def scheme_hash(scheme):
    payload=json.dumps(normalize_scheme(scheme),ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def structure_usage(scheme):
    normalized=normalize_scheme(scheme)
    usage={item["id"]:[] for item in normalized["structures"]}
    for trait in normalized["traits"]:
        for structure_id in trait.get("structures",()):
            usage.setdefault(structure_id,[]).append(trait["id"])
    return usage


def scheme_change_impact(old,new,annotation_counts=None):
    """Describe a scheme edit without mutating or discarding existing annotations."""
    old=normalize_scheme(old);new=normalize_scheme(new);annotation_counts=dict(annotation_counts or {})
    old_s={x["id"]:x for x in old["structures"]};new_s={x["id"]:x for x in new["structures"]}
    old_t={x["id"]:x for x in old["traits"]};new_t={x["id"]:x for x in new["traits"]}
    removed_structures=sorted(set(old_s)-set(new_s))
    changed_structure_semantics=sorted(
        ident for ident in set(old_s)&set(new_s)
        if any(old_s[ident].get(key)!=new_s[ident].get(key) for key in ("annotation","repeated"))
    )
    affected_annotations=sum(int(annotation_counts.get(ident,0) or 0) for ident in removed_structures+changed_structure_semantics)
    return {
        "added_traits":sorted(set(new_t)-set(old_t)),
        "archived_traits":sorted(set(old_t)-set(new_t)),
        "added_structures":sorted(set(new_s)-set(old_s)),
        "archived_structures":removed_structures,
        "changed_structure_semantics":changed_structure_semantics,
        "affected_annotations":affected_annotations,
        "safe_without_reannotation":not bool(changed_structure_semantics),
    }
