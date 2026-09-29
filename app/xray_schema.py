"""Versioned, taxon-neutral trait schemes for the MorphoLabel X-ray module."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

SCHEMA_FORMAT_VERSION = 1

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
MARKER_COLORS = ("#f28e2b","#22a06b","#3b82f6","#a855f7","#e15759","#7f8c8d")

def _structure(structure_id,name,*,repeated,hotkey,shape,color,description=""):
    return {
        "id":structure_id,"name":name,"annotation":"point","repeated":bool(repeated),
        "required":True,"hotkey":str(hotkey),"shape":shape,"color":color,"description":description,
    }

def phoxinus_vertebral_preset():
    """Built-in starter scheme reproducing the current legacy X-ray pipeline logic."""
    structures=[
        _structure("vertebra","Vertebrae",repeated=True,hotkey="1",shape="circle",color="#f28e2b",
                   description="Repeated vertebral centres used as the ordered vertebral series."),
        _structure("first_caudal","First caudal vertebra",repeated=False,hotkey="2",shape="triangle",color="#22a06b",
                   description="Reference identifying the first caudal vertebra in the ordered series."),
        _structure("preanal_pterygiophore","Pre-anal pterygiophores",repeated=True,hotkey="3",shape="diamond",color="#3b82f6",
                   description="Anal-fin proximal pterygiophores anterior to the first caudal vertebra."),
        _structure("last_predorsal","Last predorsal vertebra",repeated=False,hotkey="4",shape="square",color="#a855f7",
                   description="Reference used to obtain the predorsal vertebral count."),
    ]
    traits=[
        {"id":"tv","name":"Total vertebrae","abbr":"tv","method":"count","structures":["vertebra"],"rule":{"offset":4}},
        {"id":"abdv","name":"Abdominal vertebrae","abbr":"abdv","method":"count_to","structures":["vertebra","first_caudal"],"rule":{"reference":"first_caudal","side":"before","offset":4}},
        {"id":"caudv","name":"Caudal vertebrae","abbr":"caudv","method":"count_to","structures":["vertebra","first_caudal"],"rule":{"reference":"first_caudal","side":"from"}},
        {"id":"predv","name":"Predorsal vertebrae","abbr":"preDv","method":"count_to","structures":["vertebra","last_predorsal"],"rule":{"reference":"last_predorsal","side":"through","offset":4}},
        {"id":"preap","name":"Pre-anal pterygiophores","abbr":"preAp","method":"count","structures":["preanal_pterygiophore"],"rule":{}},
        {"id":"dac","name":"Abdominal − caudal vertebrae","abbr":"dac","method":"derived","structures":[],"rule":{"expression":"abdv-caudv","depends_on":["abdv","caudv"]}},
        {"id":"formv","name":"Vertebral formula","abbr":"formv","method":"derived","structures":[],"rule":{"expression":"abdv+'+'+caudv","depends_on":["abdv","caudv"]}},
    ]
    return {
        "format_version":SCHEMA_FORMAT_VERSION,
        "scheme_id":"phoxinus_vertebral_counts",
        "name":"Phoxinus vertebral counts",
        "description":"Starter scheme for vertebral and pre-anal pterygiophore counts on fish radiographs.",
        "reference":{
            "label":"Bogutskaya et al. (2020), Journal of Fish Biology 96:378–393",
            "doi":"10.1111/jfb.14210",
            "note":"Trait set follows the cited Phoxinus study; vertebral terminology there follows Naseka (1996).",
        },
        "structures":structures,"traits":traits,
    }

def preset_catalog():
    """Small user-facing catalog; factories stay in code, projects store concrete scheme versions."""
    scheme=phoxinus_vertebral_preset()
    return ({
        "id":scheme["scheme_id"],
        "name":scheme["name"],
        "description":scheme["description"],
        "trait_count":len(scheme["traits"]),
        "structure_count":len(scheme["structures"]),
        "trait_abbrs":tuple(item.get("abbr") or item["id"] for item in scheme["traits"]),
        "reference":deepcopy(scheme.get("reference") or {}),
    },)


def preset_scheme(preset_id):
    if str(preset_id)=="phoxinus_vertebral_counts":
        return phoxinus_vertebral_preset()
    raise KeyError(f"Unknown X-ray trait preset: {preset_id}")


def blank_scheme(name="Untitled X-ray trait scheme"):
    return {"format_version":SCHEMA_FORMAT_VERSION,"scheme_id":"custom","name":str(name),"description":"","reference":{},"structures":[],"traits":[]}

def normalize_scheme(scheme):
    value=deepcopy(scheme)
    if int(value.get("format_version",0)) != SCHEMA_FORMAT_VERSION:
        raise ValueError("Unsupported X-ray trait scheme format")
    value.setdefault("reference",{});value.setdefault("description","");value.setdefault("structures",[]);value.setdefault("traits",[])
    structure_ids=set();hotkeys=set()
    for structure in value["structures"]:
        ident=str(structure.get("id","")).strip()
        if not ident or ident in structure_ids:raise ValueError("Every structure needs a unique id")
        structure_ids.add(ident)
        structure.setdefault("annotation","point");structure.setdefault("repeated",False);structure.setdefault("required",True)
        structure.setdefault("shape","circle");structure.setdefault("color",MARKER_COLORS[len(structure_ids)%len(MARKER_COLORS)])
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
