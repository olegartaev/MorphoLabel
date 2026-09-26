"""Plain-language review-batch metrics; calibration uses mm where available."""
from statistics import median
from .io import atomic_json_write
from .paths import REPORTS

def summarize_review(records: list[dict]) -> dict:
    image_total=len(records); accepted=0; distances=[]; point_errors={}
    for record in records:
        image_distances=[]; ppm=record.get("pixels_per_mm")
        for point in record.get("points",{}).values():
            if point.get("predicted_x") is None or point.get("final_x") is None: continue
            d=((point["predicted_x"]-point["final_x"])**2+(point["predicted_y"]-point["final_y"])**2)**.5
            distances.append(d); image_distances.append(d); point_errors.setdefault(point.get("point_code","unknown"),[]).append(d)
        if image_distances and max(image_distances)==0: accepted+=1
    ordered=sorted(distances); p95=ordered[max(0,round(.95*len(ordered))-1)] if ordered else None
    result={"images_reviewed":image_total,"fish_accepted_zero_corrections":accepted,
      "fish_accepted_zero_corrections_percent":100*accepted/image_total if image_total else None,
      "landmarks_reviewed":len(distances),"landmarks_corrected":sum(d>0 for d in distances),
      "median_correction_px":median(distances) if distances else None,"p95_correction_px":p95,"maximum_correction_px":max(distances) if distances else None,
      "per_landmark_median_px":{k:median(v) for k,v in point_errors.items()},
      "status":"MORE HUMAN-REVIEW DATA REQUIRED" if not distances else "STABLE — MORE VALIDATION NEEDED"}
    atomic_json_write(REPORTS/"latest_review_report.json",result); return result
