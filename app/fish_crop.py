"""Foreground component selection that rejects frame-edge artifacts/rulers."""
import numpy as np
from .standardize_v2 import _foreground

def interior_component(mask):
 h,w=mask.shape;seen=np.zeros_like(mask,bool);choices=[]
 for y,x in zip(*np.nonzero(mask)):
  if seen[y,x]:continue
  q=[(int(y),int(x))];seen[y,x]=True;g=[];touch=False
  while q:
   cy,cx=q.pop();g.append((cy,cx));touch|=cy<3 or cx<3 or cy>=h-3 or cx>=w-3
   for ny,nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
    if 0<=ny<h and 0<=nx<w and mask[ny,nx] and not seen[ny,nx]:seen[ny,nx]=True;q.append((ny,nx))
  if not touch:choices.append(g)
 if not choices:return np.empty((0,2))
 return np.asarray(max(choices,key=len),dtype=float)

def propose_interior_crop(image):
 mask,scale=_foreground(image);p=interior_component(mask)
 if len(p)<50:return (0,0,image.width,image.height),"no_confident_interior_component"
 ys,xs=p[:,0]/scale,p[:,1]/scale;margin=max(image.size)*.07
 crop=(max(0,int(xs.min()-margin)),max(0,int(ys.min()-margin)),min(image.width,int(xs.max()+margin)),min(image.height,int(ys.max()+margin)))
 return crop,"interior_foreground_component"
