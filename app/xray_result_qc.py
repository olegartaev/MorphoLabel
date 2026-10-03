"""Derived quality-control checks for X-ray trait results.

These checks are deliberately advisory. They flag measurements worth reviewing;
they never delete, replace, or exclude biological observations.
"""
from __future__ import annotations

import math
from pathlib import Path
from statistics import median
from datetime import datetime, timezone
import uuid

from .xray_schema import spatial_series_order


_COUNT_METHODS={"count","count_to","count_between","position"}
_NUMERIC_METHODS=_COUNT_METHODS|{"distance","angle"}
_RESULT_REVIEW_STATE_KEY="xray_result_review_queue"


def _issue_review_score(issue):
    """A reproducible priority score: severity first, then measured anomaly size."""
    score={"high":1000.0,"review":500.0,"info":100.0}.get(str(issue.get("severity") or ""),0.0)
    metric=issue.get("metric") or {};code=str(issue.get("code") or "")
    if code=="sample_outlier":
        z=metric.get("modified_z")
        if z is not None:score+=min(99.0,abs(float(z))*10.0)
        elif metric.get("mad",0)==0:
            value=float(metric.get("value") or 0);centre=float(metric.get("median") or 0)
            score+=min(99.0,abs(value-centre)/max(1.0,abs(centre))*10.0)
    elif code=="series_spacing":
        score+=min(99.0,abs(math.log(max(1e-9,float(metric.get("ratio") or 1.0))))*40.0)
    elif code=="repeat_count":score+=min(99.0,abs(float(metric.get("difference") or 0))*20.0)
    elif code=="repeat_position":score+=min(99.0,abs(float(metric.get("ratio") or 0))*20.0)
    return round(score,6)


def build_result_review_queue(issues):
    """Collapse checks to one review stop per specimen and rank worst first.

    The strongest anomaly determines the main priority. Additional independent
    flags add a bounded bonus, so a specimen with several real warning signals
    is reviewed before an otherwise similar specimen with only one.
    """
    by_specimen={}
    for issue in issues or ():
        specimen_id=str(issue.get("specimen_id") or "")
        if not specimen_id:continue
        raw_score=_issue_review_score(issue);severity=str(issue.get("severity") or "review")
        entry=by_specimen.get(specimen_id)
        if entry is None:
            entry={
                "specimen_id":specimen_id,"image_id":str(issue.get("image_id") or ""),
                "sample":str(issue.get("sample") or ""),"plate":str(issue.get("plate") or ""),
                "ordinal":int(issue.get("ordinal") or 0),"score":raw_score,"worst_score":raw_score,
                "severity":severity,"issue_count":0,"high_count":0,"review_count":0,
                "top_reason":str(issue.get("reason") or ""),
            }
            by_specimen[specimen_id]=entry
        entry["issue_count"]+=1
        if severity=="high":entry["high_count"]+=1
        elif severity=="review":entry["review_count"]+=1
        if raw_score>entry["worst_score"]:
            entry["worst_score"]=raw_score
            entry["severity"]=severity
            entry["top_reason"]=str(issue.get("reason") or "")
    for entry in by_specimen.values():
        extra_high=max(0,int(entry["high_count"])-1)
        extra_review=int(entry["review_count"])
        evidence_bonus=min(180.0,extra_high*40.0+extra_review*10.0+max(0,int(entry["issue_count"])-1)*2.0)
        entry["score"]=round(float(entry["worst_score"])+evidence_bonus,6)
    return sorted(
        by_specimen.values(),
        key=lambda row:(-row["score"],-row["high_count"],-row["issue_count"],row["sample"],row["plate"],row["ordinal"],row["specimen_id"]),
    )


def start_result_review_queue(project,issues):
    items=build_result_review_queue(issues)
    state={"format_version":1,"generation_id":uuid.uuid4().hex,"created_at":datetime.now(timezone.utc).isoformat(),
           "active":bool(items),"items":items,"position":0,"completed":[]}
    project.set_ui_state(_RESULT_REVIEW_STATE_KEY,state)
    return state


def result_review_queue(project):
    value=project.get_ui_state(_RESULT_REVIEW_STATE_KEY,{}) or {}
    if not isinstance(value,dict) or int(value.get("format_version") or 0)!=1:return None
    items=list(value.get("items") or ());position=int(value.get("position") or 0)
    if not value.get("active") or not items or not 0<=position<len(items):return None
    return value


def move_result_review_queue(project,step):
    value=result_review_queue(project)
    if value is None:return None,False
    position=int(value["position"])+int(step);items=value["items"]
    if position<0:position=0
    if position>=len(items):
        value["active"]=False;value["position"]=len(items)-1;project.set_ui_state(_RESULT_REVIEW_STATE_KEY,value)
        return value,True
    value["position"]=position;project.set_ui_state(_RESULT_REVIEW_STATE_KEY,value);return value,False


def complete_result_review_item(project):
    value=result_review_queue(project)
    if value is None:return None,False
    completed={int(index) for index in value.get("completed") or ()};completed.add(int(value["position"]))
    value["completed"]=sorted(completed);project.set_ui_state(_RESULT_REVIEW_STATE_KEY,value)
    return move_result_review_queue(project,1)


def clear_result_review_queue(project):
    project.set_ui_state(_RESULT_REVIEW_STATE_KEY,{"format_version":1,"active":False,"items":[],"position":0,"completed":[]})


def remove_result_review_image(project,image_id):
    """Remove every specimen from one excluded X-ray while preserving the rest of the queue."""
    value=result_review_queue(project)
    if value is None:return None
    image_id=str(image_id);old_items=list(value.get("items") or ());old_position=int(value.get("position") or 0)
    keep_indices=[index for index,item in enumerate(old_items) if str(item.get("image_id") or "")!=image_id]
    if len(keep_indices)==len(old_items):return value
    if not keep_indices:
        clear_result_review_queue(project);return None
    mapping={old:new for new,old in enumerate(keep_indices)}
    removed_before=sum(1 for index in range(min(old_position,len(old_items))) if index not in mapping)
    new_items=[old_items[index] for index in keep_indices]
    new_position=max(0,min(len(new_items)-1,old_position-removed_before))
    completed=[mapping[int(index)] for index in value.get("completed") or () if int(index) in mapping]
    value={**value,"items":new_items,"position":new_position,"completed":sorted(set(completed)),"active":True}
    project.set_ui_state(_RESULT_REVIEW_STATE_KEY,value)
    return value


def _sample(relative_path):
    parent=Path(str(relative_path)).parent.as_posix()
    return "Root" if parent in {"",".","/"} else parent


def _modified_z(values,value):
    values=[float(v) for v in values]
    if not values:return None,None,0.0
    centre=float(median(values))
    mad=float(median(abs(v-centre) for v in values))
    if mad<=1e-12:return None,centre,mad
    return 0.6745*(float(value)-centre)/mad,centre,mad


def _series_linearity(points):
    if len(points)<3:return 0.0
    xs=[float(p["x"]) for p in points];ys=[float(p["y"]) for p in points]
    mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
    sxx=sum((x-mx)**2 for x in xs);syy=sum((y-my)**2 for y in ys)
    sxy=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    trace=sxx+syy
    if trace<=1e-15:return 0.0
    disc=math.sqrt(max(0.0,(sxx-syy)**2+4.0*sxy*sxy))
    return (trace+disc)/(2.0*trace)


def _gap_issues(row,structure,points):
    """Flag conspicuous local gaps only when the repeated points form a series."""
    if len(points)<5:return []
    ordered=spatial_series_order(points)
    if _series_linearity(ordered)<0.78:return []
    gaps=[
        math.hypot(float(b["x"])-float(a["x"]),float(b["y"])-float(a["y"]))
        for a,b in zip(ordered,ordered[1:])
    ]
    positive=[gap for gap in gaps if gap>1e-12]
    if len(positive)<3:return []
    typical=float(median(positive))
    if typical<=1e-12:return []
    mad=float(median(abs(gap-typical) for gap in positive))
    issues=[]
    for index,gap in enumerate(gaps):
        ratio=gap/typical
        z=None if mad<=1e-12 else 0.6745*(gap-typical)/mad
        conspicuous=(ratio>=1.8 or ratio<=0.55) and (z is None or abs(z)>=3.5)
        if not conspicuous:continue
        long_gap=ratio>1.0
        severity="high" if ratio>=2.3 or ratio<=0.35 else "review"
        hint="possible missed marker or wrong sequence order" if long_gap else "possible duplicate / misplaced marker"
        issues.append({
            "severity":severity,"code":"series_spacing","specimen_id":row["specimen_id"],
            "image_id":row["image_id"],"sample":_sample(row["relative_path"]),
            "plate":Path(str(row["relative_path"])).name,"ordinal":int(row.get("ordinal") or 0),
            "target":str(structure.get("name") or structure["id"]),
            "reason":f"Gap {index+1}→{index+2} is {ratio:.2f}× the typical spacing; {hint}.",
            "metric":{"gap":gap,"typical_gap":typical,"ratio":ratio,"modified_z":z},
        })
    return issues


def _reference_role_issues(project,row,structures):
    issues=[]
    points=project.effective_annotations(row["specimen_id"],1,"human")
    for structure in structures:
        if str(structure.get("learning_relation") or "")!="role_on_structure":continue
        sid=str(structure["id"])
        refs=[point for point in points if str(point["structure_id"])==sid]
        if refs and any("role_source_annotation_id" not in point for point in refs):
            issues.append({
                "severity":"high","code":"detached_reference","specimen_id":row["specimen_id"],
                "image_id":row["image_id"],"sample":_sample(row["relative_path"]),
                "plate":Path(str(row["relative_path"])).name,"ordinal":int(row.get("ordinal") or 0),
                "target":str(structure.get("name") or sid),
                "reason":"This reference is defined as one element of a repeated series, but it is stored as a separate point. Check the reference marker.",
                "metric":{},
            })
    return issues


def _sample_outlier_issues(rows,traits,min_group_size):
    issues=[]
    groups={}
    for row in rows:
        if str(row.get("result_status") or "")!="verified":continue
        groups.setdefault(_sample(row["relative_path"]),[]).append(row)
    for sample,group in groups.items():
        if len(group)<int(min_group_size):continue
        for trait in traits:
            method=str(trait.get("method") or "")
            if method not in _NUMERIC_METHODS:continue
            tid=str(trait["id"]);values=[]
            for row in group:
                value=(row.get("trait_values") or {}).get(tid)
                if isinstance(value,(int,float)) and math.isfinite(float(value)):
                    values.append((row,float(value)))
            if len(values)<int(min_group_size):continue
            raw=[value for _row,value in values];centre=float(median(raw));mad=float(median(abs(value-centre) for value in raw))
            same=sum(abs(value-centre)<=1e-12 for value in raw)
            for row,value in values:
                z=None if mad<=1e-12 else 0.6745*(value-centre)/mad
                robust=bool(z is not None and abs(z)>3.5)
                flat_cluster=bool(
                    mad<=1e-12 and len(raw)>=6 and same/len(raw)>=0.8
                    and abs(value-centre)>1e-12
                )
                if not robust and not flat_cluster:continue
                severity="high" if z is not None and abs(z)>=5.0 else "review"
                if robust:
                    detail=f"value {value:g}; sample median {centre:g}; two-sided modified z = {z:.2f}"
                else:
                    detail=f"value {value:g}; sample median {centre:g}; {same}/{len(raw)} specimens share the median and this value lies outside that dominant cluster"
                issues.append({
                    "severity":severity,"code":"sample_outlier","specimen_id":row["specimen_id"],
                    "image_id":row["image_id"],"sample":sample,
                    "plate":Path(str(row["relative_path"])).name,"ordinal":int(row.get("ordinal") or 0),
                    "target":str(trait.get("abbr") or trait.get("name") or tid),
                    "reason":"Unusual result within this sample/folder: "+detail+". Review it; it may still be real biological variation.",
                    "metric":{"value":value,"median":centre,"mad":mad,"modified_z":z,"n":len(raw)},
                })
    return issues


def _repeatability_issues(project,structures):
    run=project.structure_repeatability()
    if not run or not run.get("schema_current"):return [],[]
    issues=[];biases=[]
    role_ids={str(item["id"]) for item in structures if str(item.get("learning_relation") or "")=="role_on_structure"}
    repeated_ids={str(item["id"]) for item in structures if bool(item.get("repeated"))}
    names={str(item["id"]):str(item.get("name") or item["id"]) for item in structures}
    count_diffs={sid:[] for sid in repeated_ids}
    for member in run.get("members") or ():
        specimen_id=str(member["specimen_id"])
        base=project._repeatability_annotations(run,member,1)
        again=project._repeatability_annotations(run,member,2)
        if base is None or again is None:continue
        specimen=project.specimen(specimen_id);image=project.source_image(specimen["image_id"])
        for sid in repeated_ids:
            a=[p for p in base if str(p["structure_id"])==sid];b=[p for p in again if str(p["structure_id"])==sid]
            diff=len(b)-len(a);count_diffs[sid].append(diff)
            if diff:
                issues.append({
                    "severity":"high","code":"repeat_count","specimen_id":specimen_id,"image_id":specimen["image_id"],
                    "sample":_sample(image["relative_path"]),"plate":Path(str(image["relative_path"])).name,
                    "ordinal":int(specimen.get("ordinal") or 0),"target":names.get(sid,sid),
                    "reason":f"Manual repeatability differs: Annotation 1 = {len(a)}, Annotation 2 = {len(b)} (difference {diff:+d}).",
                    "metric":{"annotation1":len(a),"annotation2":len(b),"difference":diff},
                })
            if len(a)==len(b) and len(a)>=3:
                base_order=sorted(a,key=lambda p:int(p.get("sort_order",0)))
                gaps=[math.hypot(float(y["x"])-float(x["x"]),float(y["y"])-float(x["y"])) for x,y in zip(base_order,base_order[1:])]
                typical=float(median([g for g in gaps if g>1e-12])) if any(g>1e-12 for g in gaps) else 0.0
                matched=project._repeatability_match_distances(a,b)
                if typical>0 and matched:
                    largest=max(matched);ratio=largest/typical
                    if ratio>=0.75:
                        issues.append({
                            "severity":"review","code":"repeat_position","specimen_id":specimen_id,"image_id":specimen["image_id"],
                            "sample":_sample(image["relative_path"]),"plate":Path(str(image["relative_path"])).name,
                            "ordinal":int(specimen.get("ordinal") or 0),"target":names.get(sid,sid),
                            "reason":f"Manual repeatability: one marker moved by {ratio:.2f}× the typical spacing between elements.",
                            "metric":{"max_repeat_distance":largest,"typical_spacing":typical,"ratio":ratio},
                        })
        for sid in role_ids:
            a=[p for p in base if str(p["structure_id"])==sid];b=[p for p in again if str(p["structure_id"])==sid]
            if len(a)==1 and len(b)==1 and int(a[0].get("sort_order",0))!=int(b[0].get("sort_order",0)):
                issues.append({
                    "severity":"high","code":"repeat_role","specimen_id":specimen_id,"image_id":specimen["image_id"],
                    "sample":_sample(image["relative_path"]),"plate":Path(str(image["relative_path"])).name,
                    "ordinal":int(specimen.get("ordinal") or 0),"target":names.get(sid,sid),
                    "reason":f"Manual repeatability chose a different position in the series: {int(a[0].get('sort_order',0))+1} vs {int(b[0].get('sort_order',0))+1}.",
                    "metric":{"annotation1_position":int(a[0].get("sort_order",0))+1,"annotation2_position":int(b[0].get("sort_order",0))+1},
                })
    for sid,diffs in count_diffs.items():
        if len(diffs)<5:continue
        nonzero=[value for value in diffs if value]
        if not nonzero:continue
        positive=sum(value>0 for value in nonzero);negative=sum(value<0 for value in nonzero)
        consistency=max(positive,negative)/len(nonzero)
        mean=sum(diffs)/len(diffs)
        if consistency>=0.8 and abs(mean)>=0.5:
            direction="higher" if mean>0 else "lower"
            biases.append({
                "structure_id":sid,"target":names.get(sid,sid),"n":len(diffs),"mean_difference":mean,
                "reason":f"Annotation 2 tends to be {direction} than Annotation 1 by {abs(mean):.2f} element(s) on average (n={len(diffs)}).",
            })
    return issues,biases


def build_result_qc(project,min_group_size=5):
    """Return transparent, non-destructive checks from current persisted data."""
    rows=list(project.trait_rows());scheme=project.scheme;structures=list(scheme.get("structures") or ());traits=list(scheme.get("traits") or ())
    verified=[row for row in rows if str(row.get("result_status") or "")=="verified"]
    issues=[]
    for row in verified:
        issues.extend(_reference_role_issues(project,row,structures))
        annotations=project.annotations(row["specimen_id"],1,"human")
        for structure in structures:
            if not bool(structure.get("repeated")):continue
            points=[point for point in annotations if str(point["structure_id"])==str(structure["id"])]
            issues.extend(_gap_issues(row,structure,points))
    issues.extend(_sample_outlier_issues(rows,traits,min_group_size))
    repeat_issues,biases=_repeatability_issues(project,structures);issues.extend(repeat_issues)
    severity_order={"high":0,"review":1,"info":2}
    issues.sort(key=lambda item:(severity_order.get(item["severity"],9),item.get("sample",""),item.get("plate",""),item.get("ordinal",0),item.get("target","")))
    return {
        "issues":issues,"biases":biases,
        "summary":{
            "verified_specimens":len(verified),
            "flagged_specimens":len({item["specimen_id"] for item in issues if item.get("specimen_id")}),
            "issue_count":len(issues),
            "high_count":sum(item["severity"]=="high" for item in issues),
            "repeatability_bias_count":len(biases),
            "min_group_size":int(min_group_size),
        },
    }