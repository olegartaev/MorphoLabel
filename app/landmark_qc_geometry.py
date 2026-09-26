"""Shared geometry checks for landmark quality control."""
from __future__ import annotations
import math


def pair_vector_reversal_metrics(reference_first,reference_second,current_first,current_second,*,min_reference_length=2.0,cosine_threshold=-.85,length_ratio_min=.55,length_ratio_max=1.80):
    """Return translation-invariant evidence that a labelled landmark pair is reversed."""
    ref_vec=(reference_second[0]-reference_first[0],reference_second[1]-reference_first[1])
    cur_vec=(current_second[0]-current_first[0],current_second[1]-current_first[1])
    reference_length=math.hypot(*ref_vec);current_length=math.hypot(*cur_vec)
    if reference_length<=0 or current_length<=0:
        return {"reference_length":reference_length,"current_length":current_length,"pair_cos":1.0,"length_ratio":0.0,"vector_reversal":False}
    pair_cos=(ref_vec[0]*cur_vec[0]+ref_vec[1]*cur_vec[1])/(reference_length*current_length)
    length_ratio=current_length/reference_length
    vector_reversal=reference_length>float(min_reference_length) and float(length_ratio_min)<=length_ratio<=float(length_ratio_max) and pair_cos<=float(cosine_threshold)
    return {"reference_length":reference_length,"current_length":current_length,"pair_cos":pair_cos,"length_ratio":length_ratio,"vector_reversal":bool(vector_reversal)}
