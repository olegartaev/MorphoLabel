"""Fast, review-oriented active learning for landmark predictions."""
from __future__ import annotations
import random
import math
from datetime import datetime, timezone
from .io import atomic_json_write
from .paths import REPORTS
from .workflow import image_catalog
from .landmark_review import build_review_context, review_warnings, warning_landmark_ids, _review_snapshot
from .annotation_check import HARD_KINDS
from .landmark_frames import landmark_prediction_frame_ready

_SWAP_KINDS=frozenset({"swap_suggestion","possible_swap","batch_vector_swap"})


def _emit_progress(progress,text,done=None,total=None):
    if progress is None:return
    try:progress(text,done,total)
    except TypeError:progress(text)


def _percentile(values,q=.9):
    values=sorted(float(value) for value in values if isinstance(value,(int,float)) and math.isfinite(value))
    if not values:return 0.0
    if len(values)==1:return values[0]
    position=max(0.0,min(1.0,float(q)))*(len(values)-1);lo=int(math.floor(position));hi=int(math.ceil(position))
    if lo==hi:return values[lo]
    weight=position-lo
    return values[lo]*(1.0-weight)+values[hi]*weight


def _ai_worst_first_eligible(project,snapshot,image_id,rows):
    status=snapshot.annotation_status(image_id) or {}
    if bool(status.get("verified")):return False
    # Review worst ranks completed AI predictions. Incomplete predictions stay
    # in the prediction-attention path until every non-human slot is resolved.
    if not bool(status.get("complete")):return False
    if not landmark_prediction_frame_ready(project,image_id):return False
    for row in rows.values():
        ai_origin=(row.get("provenance")=="machine" or row.get("model_id") is not None or row.get("prediction_run_id") is not None)
        x,y=row.get("x_standardized"),row.get("y_standardized")
        finite_point=(row.get("state")!="missing" and isinstance(x,(int,float)) and isinstance(y,(int,float)) and math.isfinite(x) and math.isfinite(y))
        if ai_origin and finite_point:return True
    return False


def _verified_error_calibration(snapshot):
    """Learn expected correction magnitude from already human-verified AI landmarks."""
    by_landmark={};by_model_landmark={};global_samples=[];positive=[];verified_images=0
    for image in snapshot.catalog_rows():
        image_id=str(image["image_id"]);status=snapshot.annotation_status(image_id) or {}
        if not status.get("verified"):continue
        width,height=snapshot.dimensions_by_id.get(image_id,(0,0));diag=math.hypot(width,height)
        if diag<=0:continue
        used=False
        for landmark_id,row in (snapshot.load_landmarks(image_id) or {}).items():
            values=(row.get("x_standardized"),row.get("y_standardized"),row.get("predicted_x"),row.get("predicted_y"))
            if not all(isinstance(value,(int,float)) and math.isfinite(value) for value in values):continue
            error=math.hypot(values[0]-values[2],values[1]-values[3])/diag
            confidence=row.get("confidence");confidence=float(confidence) if isinstance(confidence,(int,float)) and math.isfinite(confidence) else None
            sample=(confidence,error);landmark_id=int(landmark_id);model_id=str(row.get("model_id") or "")
            by_landmark.setdefault(landmark_id,[]).append(sample);by_model_landmark.setdefault((model_id,landmark_id),[]).append(sample);global_samples.append(sample)
            if error>1e-9:positive.append(error)
            used=True
        verified_images+=int(used)
    # Scale only makes unlike signals comparable. It is learned from real positive
    # corrections; the fallback is used only before enough correction history exists.
    scale=_percentile(positive,.9) if positive else .01
    scale=max(scale,1e-4)
    usable=any(len(samples)>=6 for samples in by_landmark.values()) or len(global_samples)>=20
    return {"by_landmark":by_landmark,"by_model_landmark":by_model_landmark,"global":global_samples,
            "scale":scale,"verified_images":verified_images,"sample_count":len(global_samples),"usable":usable}


def _empirical_point_risk(calibration,landmark_id,row):
    """P90 observed human correction near this point's confidence; no extra ML model."""
    landmark_id=int(landmark_id);model_id=str(row.get("model_id") or "")
    samples=calibration["by_model_landmark"].get((model_id,landmark_id),())
    if len(samples)<6:samples=calibration["by_landmark"].get(landmark_id,())
    if len(samples)<6:samples=calibration["global"] if len(calibration["global"])>=20 else ()
    if not samples:return None,0
    confidence=row.get("confidence")
    finite_conf=isinstance(confidence,(int,float)) and math.isfinite(confidence)
    with_conf=[sample for sample in samples if sample[0] is not None]
    if finite_conf and len(with_conf)>=6:
        # Tiny nearest-neighbour windows made P90 collapse to one extreme example.
        # Use at least eight verified examples when available, while still
        # preserving confidence locality for larger histories.
        window=min(len(with_conf),max(8,min(24,(len(with_conf)+1)//2)))
        nearest=sorted(with_conf,key=lambda sample:abs(sample[0]-float(confidence)))[:window]
    else:nearest=list(samples)
    return _percentile((sample[1] for sample in nearest),.9),len(nearest)


def _shape_descriptor(rows,width,height):
    if width<=0 or height<=0:return {}
    result={}
    for landmark_id,row in rows.items():
        if row.get("state")=="missing":continue
        x,y=row.get("x_standardized"),row.get("y_standardized")
        if isinstance(x,(int,float)) and isinstance(y,(int,float)) and math.isfinite(x) and math.isfinite(y):
            result[int(landmark_id)]=(float(x)/width,float(y)/height)
    return result


def _shape_distance(first,second):
    common=sorted(set(first)&set(second))
    if len(common)<3:return 0.0
    return math.sqrt(sum((first[i][0]-second[i][0])**2+(first[i][1]-second[i][1])**2 for i in common)/len(common))


def _diverse_take(ranked,size):
    """Light diversity tie-break: never jump far down the risk ranking."""
    if size is None:return list(ranked)
    wanted=max(0,int(size))
    if wanted==0:return []
    remaining=list(ranked);selected=[]
    while remaining and len(selected)<wanted:
        first=remaining[0]
        if not selected:
            chosen=first
        else:
            floor=float(first.get("risk_score",0.0))*.90
            same_class=[item for item in remaining[:8] if item.get("_priority_class")==first.get("_priority_class") and float(item.get("risk_score",0.0))>=floor]
            same_class=same_class or [first]
            def diversity(item):
                descriptor=item.get("_descriptor") or {}
                return min((_shape_distance(descriptor,other.get("_descriptor") or {}) for other in selected),default=0.0)
            chosen=max(same_class,key=lambda item:(diversity(item),-remaining.index(item)))
        selected.append(chosen);remaining.remove(chosen)
    return selected


def _review_reason(hard,swaps,geometry,learned_component,learned_risk,learned_id,learned_n,geometry_component,confidence_component,low_ids,rows):
    if hard:return "Hard check: "+str(hard[0].get("message") or hard[0].get("kind"))
    if swaps:return "Possible landmark swap: "+str(swaps[0].get("message") or "check landmark identities")
    if learned_risk is not None and learned_component>=max(geometry_component,confidence_component):
        return f"Correction history: LM{learned_id} risk ≈ {learned_risk*100:.2f}% of frame diagonal ({learned_n} similar verified predictions)"
    if geometry and geometry_component>=confidence_component:
        return "Unusual geometry: "+str(geometry[0].get("message") or geometry[0].get("kind"))
    if low_ids:
        value=rows.get(low_ids[0],{}).get("confidence")
        return f"Low AI confidence: LM{low_ids[0]} = {float(value):.3f}" if isinstance(value,(int,float)) and math.isfinite(value) else f"Low AI confidence: LM{low_ids[0]}"
    return "AI prediction selected for review"


def select_ai_worst_first(project,size=None,progress=None,image_ids=None):
    """Review worst v2: hard checks -> learned correction risk -> geometry/confidence -> light diversity."""
    _emit_progress(progress,"Reading verified human corrections…")
    snapshot=_review_snapshot(project);allowed=None if image_ids is None else {str(value) for value in image_ids}
    catalog=[row for row in snapshot.catalog_rows() if not row.get("excluded") and (allowed is None or str(row.get("image_id")) in allowed)]
    context=build_review_context(snapshot,catalog,dimensions_by_id=snapshot.dimensions_by_id)
    calibration=_verified_error_calibration(snapshot)
    if calibration["usable"]:
        _emit_progress(progress,f"Learning from {calibration['verified_images']} verified AI reviews ({calibration['sample_count']} landmark checks)…")
    elif calibration["sample_count"]:
        _emit_progress(progress,f"Correction history still small ({calibration['sample_count']} landmark checks) — using geometry + confidence for now.")
    else:_emit_progress(progress,"No correction history yet — using geometry + confidence.")

    eligible=[]
    for order,image in enumerate(catalog):
        image_id=str(image["image_id"]);rows=snapshot.load_landmarks(image_id) or {}
        if not _ai_worst_first_eligible(project,snapshot,image_id,rows):continue
        if image_id not in snapshot.dimensions_by_id:continue
        eligible.append((order,image,image_id,rows))

    ranked=[];total=len(eligible)
    for index,(order,image,image_id,rows) in enumerate(eligible,1):
        if index==1 or index%50==0 or index==total:_emit_progress(progress,f"Scoring unverified predictions: {index} / {total}",index,total)
        width,height=context.dimensions_by_id.get(image_id,(1,1))
        warnings=list(review_warnings(snapshot,image_id,width,height,context.dimensions_by_id,context=context))
        hard=[warning for warning in warnings if warning.get("kind") in HARD_KINDS]
        swaps=[warning for warning in warnings if warning.get("kind") in _SWAP_KINDS]
        geometry=[warning for warning in warnings if warning.get("kind") not in HARD_KINDS and warning.get("kind") not in _SWAP_KINDS]
        severity=max((float(w.get("distance",0))/max(float(w.get("tolerance",w.get("dispersion",1))),1e-12)
                      for w in geometry if isinstance(w.get("distance"),(int,float))),default=0.0)
        geometry_component=min(2.0,max(0.0,severity))

        point_risks=[]
        for landmark_id,row in rows.items():
            risk,count=_empirical_point_risk(calibration,landmark_id,row)
            if risk is not None:point_risks.append((risk,int(landmark_id),count))
        point_risks.sort(reverse=True)
        learned_risk,learned_id,learned_n=(point_risks[0] if point_risks else (None,None,0))
        # Keep real separation among high-risk images. The previous 2.0 cap
        # saturated most top candidates into one tie, after which diversity and
        # confidence tie-breaks could make the queue look nearly random.
        learned_component=max(0.0,learned_risk/calibration["scale"]) if learned_risk is not None else 0.0

        confidence=[(float(row["confidence"]),int(key)) for key,row in rows.items()
                    if isinstance(row.get("confidence"),(int,float)) and math.isfinite(row["confidence"])]
        confidence.sort();minimum=confidence[0][0] if confidence else float("inf");mean=sum(value for value,_ in confidence)/len(confidence) if confidence else float("inf")
        confidence_component=.75*max(0.0,min(1.0,1.0-minimum)) if confidence and 0.0<=minimum<=1.0 else 0.0
        low_ids=[identifier for _,identifier in confidence[:3]]

        critical=len(hard)+len(swaps)
        risk_score=3.0+critical if critical else max(learned_component,geometry_component,confidence_component)
        warning_ids=sorted({ident for warning in warnings for ident in warning_landmark_ids(warning)})
        learned_ids=[identifier for _,identifier,_ in point_risks[:3]]
        if hard or swaps:review_ids=warning_ids[:4]
        elif learned_component>=max(geometry_component,confidence_component) and learned_ids:review_ids=learned_ids
        elif geometry and warning_ids:review_ids=warning_ids[:4]
        else:review_ids=low_ids

        reason=_review_reason(hard,swaps,geometry,learned_component,learned_risk,learned_id,learned_n,geometry_component,confidence_component,low_ids,rows)
        ranked.append({
            "image_id":image_id,"name":image.get("source_relpath",image_id),"reason":reason,
            "risk_score":float(risk_score),"warnings":warnings,"warning_landmark_ids":warning_ids,
            "review_landmark_ids":review_ids,"low_confidence_landmark_ids":low_ids,
            "learned_risk":learned_risk,"learned_samples":learned_n,
            "_priority_class":1 if critical else 0,
            "_descriptor":_shape_descriptor(rows,width,height),
            "_sort":(-int(bool(critical)),-float(risk_score),-len(hard),-len(swaps),-len(geometry),minimum,mean,order,str(image_id)),
        })

    ranked.sort(key=lambda item:item["_sort"])
    _emit_progress(progress,"Selecting diverse high-risk cases…")
    chosen=_diverse_take(ranked,size)
    clean=[]
    for item in chosen:
        item=dict(item)
        for key in ("_priority_class","_descriptor","_sort"):item.pop(key,None)
        clean.append(item)
    return clean


def schedule_repeat_annotations(count: int=10, seed: int=20260814) -> dict:
    """Selects a blind revisit set; no point data is copied or fabricated."""
    images=image_catalog(); rng=random.Random(seed); rng.shuffle(images)
    result={"kind":"blind_repeat_annotation","seed":seed,"created_at":datetime.now(timezone.utc).isoformat(),"images":images[:min(count,len(images))]}
    atomic_json_write(REPORTS/"repeat_annotation_queue.json",result); return result

def select_review_batch(predictions: list[dict], size: int=20, seed: int=20260814, informative_fraction=.70) -> dict:
    """Select high-uncertainty items plus random audit; prediction inputs are never labels."""
    rng=random.Random(seed); total=min(size,len(predictions)); informative=min(round(total*informative_fraction),total)
    ranked=sorted(predictions,key=lambda row: row.get("uncertainty",0),reverse=True)
    chosen=ranked[:informative]; remaining=[row for row in predictions if row not in chosen]; rng.shuffle(remaining); chosen.extend(remaining[:total-len(chosen)])
    result={"kind":"active_review","seed":seed,"size":total,"informative_fraction":informative_fraction,"rule":"highest reported uncertainty plus random audit","images":chosen}
    atomic_json_write(REPORTS/"active_review_queue.json",result); return result
