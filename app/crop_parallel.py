"""Bounded, Tk-free crop computation executor."""
from __future__ import annotations
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from .ai_hardware import get_hardware_profile
from .performance_engine import (cpu_worker_candidates, hardware_fingerprint,
    tune_workload, workload_tuning_key, PerformanceCache, benchmark_candidates)

LOG = logging.getLogger("morphology.crop")

def _heuristic_config(profile):
    physical=profile.physical_cores or profile.logical_cores
    ram=(profile.ram_bytes or 0)/1024**3
    workers=max(2,min(8,physical//2 or 1))
    if ram and ram<8: workers=min(workers,2)
    return {"workers":workers,"max_in_flight":workers*2,"logical_cpus":profile.logical_cores,"physical_cpus":physical,"ram_gb":round(ram,1),"executor_type":"ThreadPoolExecutor"}

def auto_config(project=None, *, workload="image_crop_prepare", sample=None, prepare=None):
    """Return a bounded crop config, tuning measured preparation when supplied.

    Existing callers retain the conservative hardware heuristic.  A caller that
    can provide a bounded representative preparation probe gets a cached,
    throughput-selected worker/max-in-flight pair from the shared engine.
    """
    profile=get_hardware_profile(); fallback=_heuristic_config(profile)
    if project is None or not sample or prepare is None:
        return fallback
    candidates=[]
    for workers in cpu_worker_candidates(profile):
        # Keep in-flight work bounded for large RAW frames and avoid duplicate
        # candidate configurations.
        if profile.ram_bytes and profile.ram_bytes < 8*1024**3 and workers > 2:
            continue
        candidates.append({"workers":int(workers),"max_in_flight":int(workers*2)})
    if not candidates:
        candidates=[{"workers":1,"max_in_flight":1}]
    def probe(config):
        import time
        started=time.perf_counter(); completed=0
        for _item, result, error in bounded_map(sample, prepare, config=config):
            if error is None: completed += 1
        elapsed=max(time.perf_counter()-started,1e-9)
        return {"items_per_sec":completed/elapsed if completed else 0.0}
    tuned=tune_workload(project,workload=workload,variant="v2_full_cpu_capacity",candidates=candidates,probe=probe,safe_fallback={"workers":fallback["workers"],"max_in_flight":fallback["max_in_flight"]})
    chosen=tuned.get("chosen") or {"workers":fallback["workers"],"max_in_flight":fallback["max_in_flight"]}
    LOG.info("crop_auto_tuning fingerprint=%s cpu=%s ram_gb=%s gpu=%s cache_hit=%s candidates=%s chosen=%s results=%s", hardware_fingerprint(profile), profile.cpu_model, round((profile.ram_bytes or 0) / 1024**3, 1), profile.gpu_model or "None", bool(tuned.get("cache_hit", False)), candidates, chosen, tuned.get("results", ()))
    return {**fallback,"workers":int(chosen["workers"]),"max_in_flight":int(chosen["max_in_flight"]),"tuning_cache_hit":bool(tuned.get("cache_hit",False))}

def tune_and_prepare(project, *, workload, sample, worker, fallback=None):
    """Measure bounded real work once and return selected sample results.

    On a fresh machine key each candidate receives the same small input sample.
    Results from the winning candidate are returned to the caller, so that
    sample is committed/persisted rather than processed a further time by the
    production pass.  Project/SQLite work remains outside worker threads.
    """
    profile=get_hardware_profile(); fallback=fallback or _heuristic_config(profile)
    candidates=[{"workers":w,"max_in_flight":w*2} for w in cpu_worker_candidates(profile)
                if not (profile.ram_bytes and profile.ram_bytes < 8*1024**3 and w>2)] or [{"workers":1,"max_in_flight":1}]
    key=workload_tuning_key(workload=workload,variant="v1_real_bounded_sample",hardware=profile)
    cache=PerformanceCache(project);cached=cache.get(key)
    if cached and cached.get("chosen"):
        chosen=cached["chosen"]
        return {**fallback,"workers":int(chosen["workers"]),"max_in_flight":int(chosen["max_in_flight"]),"tuning_cache_hit":True},{}
    outputs={}
    def probe(config):
        started=time.perf_counter(); values={};completed=0
        for item,value,error in bounded_map(sample,worker,config=config):
            if error is not None: raise error
            values[item["image_id"] if isinstance(item,dict) else item]=value;completed+=1
        outputs[(config["workers"],config["max_in_flight"])]=values
        return {"items_per_sec":completed/max(time.perf_counter()-started,1e-9)}
    measured=benchmark_candidates(candidates,probe,safe_fallback={"workers":fallback["workers"],"max_in_flight":fallback["max_in_flight"]})
    measured.update({"cache_hit":False,"tuning_key":key,"hardware_fingerprint":hardware_fingerprint(profile)})
    cache.put(key,measured);chosen=measured.get("chosen") or {"workers":fallback["workers"],"max_in_flight":fallback["max_in_flight"]}
    config={**fallback,"workers":int(chosen["workers"]),"max_in_flight":int(chosen["max_in_flight"]),"tuning_cache_hit":False}
    return config,outputs.get((config["workers"],config["max_in_flight"]),{})

def bounded_map(items,worker,*,cancel=None,config=None):
 config=config or auto_config();iterator=iter(items);pending={};ex=ThreadPoolExecutor(max_workers=config['workers'],thread_name_prefix='crop-compute')
 try:
  def fill():
   while len(pending)<config['max_in_flight'] and not (cancel and cancel.is_set()):
    try:item=next(iterator)
    except StopIteration:return
    pending[ex.submit(worker,item)]=item
  fill()
  while pending:
   done,_=wait(pending,return_when=FIRST_COMPLETED)
   for future in done:
    item=pending.pop(future)
    try:yield item,future.result(),None
    except Exception as exc:yield item,None,exc
   fill()
 finally:
  ex.shutdown(wait=True,cancel_futures=False)
