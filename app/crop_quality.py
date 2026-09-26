"""Transparent, read-only quality classification for crop proposals."""
from __future__ import annotations
import math
from dataclasses import dataclass
from statistics import median
from .crop_training import latest_corrections

@dataclass(frozen=True)
class CropQuality:
 level:str
 score:int
 reasons:tuple[str,...]

def _reference():
 rows=latest_corrections();areas=[];ratios=[]
 for row in rows:
  try:
   w=float(row['x2'])-float(row['x1']);h=float(row['y2'])-float(row['y1'])
   if w>0 and h>0:areas.append(w*h);ratios.append(w/h)
  except (KeyError,ValueError):pass
 return (median(areas),median(ratios)) if areas else (None,None)

def assess_crop(bounds,width,height):
 """Classify only geometry; crop model exposes no probability, so no model confidence is assumed."""
 try:l,t,r,b=map(float,bounds)
 except (TypeError,ValueError):return CropQuality('red',0,('invalid crop rectangle',))
 if not all(math.isfinite(v) for v in (l,t,r,b)) or width<=0 or height<=0 or r<=l or b<=t:return CropQuality('red',0,('invalid crop rectangle',))
 reasons=[];score=100; margin=min(l,t,width-r,height-b)
 if margin<=0: return CropQuality('red',0,('crop touches image border',))
 if margin<min(width,height)*.01: reasons.append('very small safety margin');score-=35
 area=(r-l)*(b-t)/(width*height);ratio=(r-l)/(b-t)
 if area<.03 or area>.95: return CropQuality('red',max(0,score-55),('extreme crop size',))
 ref_area,ref_ratio=_reference()
 if ref_area is not None and (area<ref_area*.25 or area>ref_area*4): reasons.append('size differs strongly from accepted crops');score-=35
 if ref_ratio is not None and (ratio<ref_ratio*.4 or ratio>ref_ratio*2.5): reasons.append('aspect ratio differs from accepted crops');score-=30
 level='green' if score>=80 else 'yellow' if score>=45 else 'red'
 return CropQuality(level,max(0,score),tuple(reasons) or ('geometry checks passed',))
