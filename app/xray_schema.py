"""Versioned, taxon-neutral trait schemes for the MorphoLabel X-ray module."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import ast
import math
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
        structure.setdefault("reuse_from",[])
        structure["reuse_from"]=[str(item) for item in (structure.get("reuse_from") or ()) if str(item)]
        relation=str(structure.get("learning_relation") or "").strip()
        if relation and relation not in {"role_on_structure","independent"}:raise ValueError(f"Unsupported structure relationship: {relation}")
        if relation=="role_on_structure" and not structure["reuse_from"]:raise ValueError(f"Structure {ident} must name the series it belongs to")
        if relation=="independent" and structure["reuse_from"]:raise ValueError(f"Independent structure {ident} cannot reuse another annotation point")
        structure.setdefault("shape",SHAPES[index%len(SHAPES)]);structure.setdefault("color",MARKER_COLORS[index%len(MARKER_COLORS)])
        hotkey=str(structure.get("hotkey","")).strip()
        if hotkey:
            if hotkey in hotkeys:raise ValueError("Structure hotkeys must be unique")
            hotkeys.add(hotkey)
    for structure in value["structures"]:
        missing=set(structure.get("reuse_from") or ())-structure_ids
        if missing:raise ValueError(f"Structure {structure['id']} reuses missing structures: {sorted(missing)}")
        if structure.get("repeated") and structure.get("reuse_from"):
            raise ValueError(f"Repeated structure {structure['id']} cannot reuse another annotation point")
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


def _safe_derived(expression,values):
    """Evaluate simple arithmetic/string trait expressions without Python eval."""
    tree=ast.parse(str(expression or ""),mode="eval")
    def visit(node):
        if isinstance(node,ast.Expression):return visit(node.body)
        if isinstance(node,ast.Constant) and isinstance(node.value,(int,float,str)):return node.value
        if isinstance(node,ast.Name):
            if node.id not in values or values[node.id] is None:raise ValueError(node.id)
            return values[node.id]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=visit(node.operand);return +value if isinstance(node.op,ast.UAdd) else -value
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            left=visit(node.left);right=visit(node.right)
            if isinstance(node.op,ast.Add):
                if isinstance(left,str) or isinstance(right,str):return str(left)+str(right)
                return left+right
            if isinstance(node.op,ast.Sub):return left-right
            if isinstance(node.op,ast.Mult):return left*right
            return left/right
        raise ValueError("Unsupported derived trait expression")
    return visit(tree)


def compatible_reference_roles(scheme,base_structure_id):
    """Return single-marker roles that may share one existing point.

    Explicit reuse_from declarations are supported, while the common case is
    inferred from trait semantics: a start/stop reference used with a repeated
    primary series can reuse a point from that series.
    """
    scheme=normalize_scheme(scheme);base_structure_id=str(base_structure_id)
    structures={item["id"]:item for item in scheme.get("structures",())}
    if base_structure_id not in structures:return []
    allowed=set()
    for item in scheme.get("structures",()):
        if item.get("repeated"):continue
        relation=str(item.get("learning_relation") or "")
        if relation=="independent":continue
        if base_structure_id in set(item.get("reuse_from") or ()):allowed.add(item["id"])
    # Backward compatibility for older saved schemes that predate an explicit
    # biological relationship. New/edited schemes store the relationship.
    for trait in scheme.get("traits",()):
        ids=list(trait.get("structures") or ())
        if not ids or ids[0]!=base_structure_id:continue
        if trait.get("method") not in {"count_to","count_between","position"}:continue
        for ident in ids[1:]:
            item=structures.get(ident)
            if item is not None and not item.get("repeated") and not item.get("learning_relation"):allowed.add(ident)
    return [item for item in scheme.get("structures",()) if item["id"] in allowed and not item.get("repeated")]

def spatial_series_order(points):
    """Return a click-order-independent visual sequence along the series' main axis."""
    rows=[dict(row) for row in (points or ())]
    if len(rows)<2:return rows
    xs=[float(row.get("x",0.0)) for row in rows];ys=[float(row.get("y",0.0)) for row in rows]
    mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
    sxx=sum((x-mx)**2 for x in xs);syy=sum((y-my)**2 for y in ys);sxy=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    if sxx+syy<=1e-15:
        return sorted(rows,key=lambda row:(float(row.get("x",0.0)),float(row.get("y",0.0)),int(row.get("annotation_id",0) or 0)))
    angle=0.5*math.atan2(2.0*sxy,sxx-syy);ux=math.cos(angle);uy=math.sin(angle)
    if (abs(ux)>=abs(uy) and ux<0) or (abs(uy)>abs(ux) and uy<0):ux=-ux;uy=-uy
    vx,vy=-uy,ux
    return sorted(
        rows,
        key=lambda row:(
            (float(row.get("x",0.0))-mx)*ux+(float(row.get("y",0.0))-my)*uy,
            (float(row.get("x",0.0))-mx)*vx+(float(row.get("y",0.0))-my)*vy,
            int(row.get("annotation_id",0) or 0),
        ),
    )


def calculate_trait_values(scheme,annotations,unknown_structures=None,absent_structures=None):
    """Missing marks give missing values; explicit absence can give a real zero."""
    scheme=normalize_scheme(scheme);grouped={};unknown={str(value) for value in (unknown_structures or ())}
    absent={str(value) for value in (absent_structures or ())}
    structures={str(item["id"]):item for item in scheme.get("structures",())}
    for row in annotations or ():
        grouped.setdefault(str(row["structure_id"]),[]).append(dict(row))
    if not grouped and not absent:return {trait["id"]:None for trait in scheme["traits"]}
    for structure_id,rows in tuple(grouped.items()):
        if bool((structures.get(structure_id) or {}).get("repeated")):grouped[structure_id]=spatial_series_order(rows)
        else:rows.sort(key=lambda row:(int(row.get("sort_order",0)),int(row.get("annotation_id",0))))
    values={}
    def points(structure_id):return grouped.get(str(structure_id),[])
    def nearest_index(series,reference):
        if not series or not reference:return None
        rx=float(reference["x"]);ry=float(reference["y"])
        return min(range(len(series)),key=lambda i:(float(series[i]["x"])-rx)**2+(float(series[i]["y"])-ry)**2)
    for trait in scheme["traits"]:
        ident=trait["id"];method=trait["method"];ids=list(trait.get("structures") or ());rule=trait.get("rule") or {};value=None
        if any(str(structure_id) in unknown for structure_id in ids):
            values[ident]=None
            continue
        primary=points(ids[0]) if ids else []
        if method=="count":
            if primary or (ids and str(ids[0]) in absent):
                value=len(primary)+int(rule.get("offset",0) or 0)
        elif method in {"count_to","position"} and len(ids)>=2:
            refs=points(ids[1]);index=nearest_index(primary,refs[0] if refs else None)
            if index is not None:
                if method=="position":value=index+1+int(rule.get("offset",0) or 0)
                else:
                    side=str(rule.get("side") or "through")
                    count=index if side=="before" else len(primary)-index if side=="from" else index+1
                    value=count+int(rule.get("offset",0) or 0)
        elif method=="count_between" and len(ids)>=3:
            one=points(ids[1]);two=points(ids[2]);a=nearest_index(primary,one[0] if one else None);b=nearest_index(primary,two[0] if two else None)
            if a is not None and b is not None:value=abs(b-a)+1+int(rule.get("offset",0) or 0)
        elif method=="presence":
            if primary:value=1
            elif ids and str(ids[0]) in absent:value=0
        elif method=="distance" and len(ids)>=2:
            one=points(ids[0]);two=points(ids[1])
            if one and two:value=math.hypot(float(two[0]["x"])-float(one[0]["x"]),float(two[0]["y"])-float(one[0]["y"]))
        elif method=="angle" and len(ids)>=3:
            a=points(ids[0]);b=points(ids[1]);c=points(ids[2])
            if a and b and c:
                ax=float(a[0]["x"])-float(b[0]["x"]);ay=float(a[0]["y"])-float(b[0]["y"])
                cx=float(c[0]["x"])-float(b[0]["x"]);cy=float(c[0]["y"])-float(b[0]["y"])
                denom=max(1e-12,math.hypot(ax,ay)*math.hypot(cx,cy))
                value=math.degrees(math.acos(max(-1.0,min(1.0,(ax*cx+ay*cy)/denom))))
        elif method=="derived":
            if any(values.get(str(dependency)) is None for dependency in rule.get("depends_on",())):
                values[ident]=None
                continue
            try:value=_safe_derived(rule.get("expression",""),values)
            except (ValueError,TypeError,ZeroDivisionError):value=None
        values[ident]=value
    return values


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
        if any(old_s[ident].get(key)!=new_s[ident].get(key) for key in ("annotation","repeated","learning_relation","reuse_from"))
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
