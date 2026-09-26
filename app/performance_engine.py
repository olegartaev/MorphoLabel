"""Generic, conservative performance tuning primitives for SIMM workloads."""
from __future__ import annotations

import hashlib
import json
import os
import time
import logging
import math
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .ai_hardware import HardwareProfile, get_hardware_profile
from .io import atomic_json_write

ENGINE_VERSION = "2"
CACHE_FILENAME = "performance_engine_tuning.json"
_CACHE_LOCK = threading.Lock()


@contextmanager
def _machine_cache_lock(path):
    """Serialize read/modify/write across independent SIMM processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        for attempt in range(40):
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if attempt == 39:
                    raise
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def model_architecture_identity(model):
    """Normalize checkpoint/version IDs to the stable model family identity."""
    import re
    value = "" if model is None else str(model)
    return re.sub(r"([_-])v\d+$", "", value, flags=re.IGNORECASE) or value



def hardware_fingerprint(hardware: HardwareProfile | None = None) -> str:
    """Return a stable fingerprint of the existing detected hardware profile."""
    profile = hardware or get_hardware_profile()
    fields = {
        "cpu_model": profile.cpu_model,
        "physical_cores": profile.physical_cores,
        "logical_cores": profile.logical_cores,
        "ram_bytes": profile.ram_bytes,
        "gpu_model": profile.gpu_model,
        "gpu_vram_mib": profile.gpu_vram_mib,
        "gpu_driver": profile.gpu_driver,
        "acceleration": profile.acceleration,
        "cuda_available": profile.cuda_available,
        "cuda_runtime": profile.cuda_runtime,
    }
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def workload_tuning_key(*, workload: str, model: str | None = None, input_size=None,
                        variant: str | None = None, hardware: HardwareProfile | None = None,
                        version: str = ENGINE_VERSION) -> str:
    """Build a versioned key; changing any workload or hardware identity changes it."""
    payload = {
        "engine_version": version,
        "workload": workload,
        "model": model_architecture_identity(model),
        "input_size": list(input_size) if input_size is not None else None,
        "variant": variant,
        "hardware_fingerprint": hardware_fingerprint(hardware),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def cpu_worker_candidates(hardware: HardwareProfile | None = None) -> tuple[int, ...]:
    """Return useful powers-of-two plus the machine capacity, never an arbitrary cap."""
    profile = hardware or get_hardware_profile()
    available = max(1, int(profile.logical_cores or profile.physical_cores or 1))
    values, candidate = [], 1
    while candidate <= available:
        values.append(candidate)
        candidate *= 2
    if values[-1] != available:
        values.append(available)
    return tuple(values)

def _metric_value(result, metric):
    if isinstance(result, dict):
        value = result.get(metric)
        if value is None and metric in {"items/sec", "items_per_second"}:
            value = result.get("items_per_sec", result.get("items_per_second"))
    else:
        value = result
    return float(value)


def _equivalent(guard, config, result):
    if guard is None:
        return True
    try:
        return bool(guard(config, result))
    except TypeError:
        return bool(guard(result))


def benchmark_candidates(candidates, probe, *, metric="items_per_sec",
                          equivalence_guard=None, safe_fallback=None):
    """Probe candidates, retaining failures and rejecting non-equivalent results."""
    records = []
    best = None
    for config in candidates:
        started = time.perf_counter()
        try:
            measured = probe(config)
            elapsed = time.perf_counter() - started
            if not _equivalent(equivalence_guard, config, measured):
                records.append({"config": config, "valid": False, "equivalent": False, "elapsed_seconds": elapsed})
                continue
            throughput = _metric_value(measured, metric)
            if not math.isfinite(throughput) or throughput <= 0:
                raise ValueError("non-positive or non-finite throughput")
            record = {"config": config, "valid": True, "equivalent": True, "throughput": throughput, "elapsed_seconds": elapsed}
            if isinstance(measured, dict):
                for key in ("items_per_sec", "peak_vram_mib"):
                    if key in measured:
                        record[key] = measured[key]
            records.append(record)
            if best is None or throughput > best["throughput"]:
                best = record
        except Exception as exc:
            records.append({"config": config, "valid": False, "equivalent": False, "elapsed_seconds": time.perf_counter() - started, "error": f"{type(exc).__name__}: {exc}"})
    chosen = best["config"] if best is not None else safe_fallback
    return {"chosen": chosen, "metric": metric, "results": records, "probes_succeeded": best is not None}


class PerformanceCache:
    """Atomic cache separate from the legacy ai_hardware tuning file."""
    def __init__(self, project=None):
        root = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        self.path = Path(root) / "SIMM" / CACHE_FILENAME

    def read_with_status(self):
        """Read the cache without ever treating corrupt data as usable."""
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}, "empty"
        except (OSError, json.JSONDecodeError):
            return {}, "corrupt"
        return (value, "valid") if isinstance(value, dict) else ({}, "corrupt")

    def read(self):
        return self.read_with_status()[0]

    def get(self, key):
        return self.read().get(key)

    def _mutate(self, change):
        with _CACHE_LOCK:
            try:
                with _machine_cache_lock(self.path):
                    cache = self.read()
                    if not change(cache):
                        return False
                    last_error = None
                    for delay in (0.0, 0.05, 0.20):
                        if delay:
                            time.sleep(delay)
                        try:
                            atomic_json_write(self.path, cache)
                            return True
                        except OSError as exc:
                            last_error = exc
            except OSError as exc:
                last_error = exc
        logging.getLogger(__name__).warning("SIMM performance-cache write failed for %s: %s", self.path, last_error)
        return False

    def put(self, key, value):
        return self._mutate(lambda cache: cache.__setitem__(key, value) or True)

    def record_runtime_fallback(self, key, attempted_batch, effective_batch):
        """Keep a successfully used smaller batch for the next launch."""
        attempted_batch, effective_batch = int(attempted_batch), int(effective_batch)
        if not key or effective_batch < 1 or effective_batch >= attempted_batch:
            return False

        def change(cache):
            entry = cache.get(key)
            if not isinstance(entry, dict) or not entry.get("probes_succeeded"):
                return False
            chosen = entry.get("chosen")
            if not isinstance(chosen, dict):
                return False
            prior = int(chosen.get("batch_size", attempted_batch))
            safe_batch = min(prior, effective_batch)
            if safe_batch >= prior:
                return False
            cache[key] = {**entry, "chosen": {**chosen, "batch_size": safe_batch},
                          "runtime_fallback": {"attempted_batch_size": attempted_batch,
                                               "effective_batch_size": safe_batch,
                                               "validated_by_completed_job": True}}
            return True

        return self._mutate(change)


def tune_workload(project, *, workload, probe, candidates, metric="items_per_sec",
                  model=None, input_size=None, variant=None, hardware=None,
                  equivalence_guard=None, safe_fallback=None):
    """Tune once per versioned workload/hardware key and reuse the measured result."""
    profile = hardware or get_hardware_profile()
    key = workload_tuning_key(workload=workload, model=model, input_size=input_size,
                              variant=variant, hardware=profile)
    cache = PerformanceCache(project)
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("probes_succeeded"):
        return {**cached, "cache_hit": True, "cache_saved": True, "tuning_key": key}
    started = time.perf_counter()
    result = benchmark_candidates(candidates, probe, metric=metric,
                                  equivalence_guard=equivalence_guard,
                                  safe_fallback=safe_fallback)
    result.update({"cache_hit": False, "tuning_key": key, "engine_version": ENGINE_VERSION,
                   "hardware_fingerprint": hardware_fingerprint(profile),
                   "calibration_elapsed_seconds": time.perf_counter() - started})
    # A transient OOM/runtime failure must not permanently poison this machine.
    if result.get("probes_succeeded"):
        result["cache_saved"] = cache.put(key, result)
    else:
        result["cache_saved"] = False
    return result

def _benchmark_many(candidates, probe_many, *, metric="items_per_sec",
                    equivalence_guard=None, safe_fallback=None):
    """Benchmark a candidate group in one expensive runtime invocation."""
    candidates = list(candidates)
    if not candidates:
        return {"chosen": safe_fallback, "metric": metric, "results": [], "probes_succeeded": False}
    started = time.perf_counter()
    try:
        measured_rows = list(probe_many(candidates))
    except Exception as exc:
        elapsed = time.perf_counter() - started
        records = [{"config": config, "valid": False, "equivalent": False,
                    "elapsed_seconds": elapsed, "error": f"{type(exc).__name__}: {exc}"}
                   for config in candidates]
        return {"chosen": safe_fallback, "metric": metric, "results": records, "probes_succeeded": False}
    if len(measured_rows) != len(candidates):
        elapsed = time.perf_counter() - started
        return {"chosen": safe_fallback, "metric": metric, "results": [
            {"config": config, "valid": False, "equivalent": False,
             "elapsed_seconds": elapsed,
             "error": "grouped performance probe returned a different candidate count"}
            for config in candidates], "probes_succeeded": False}
    records = []
    best = None
    for config, measured in zip(candidates, measured_rows):
        if not isinstance(measured, dict):
            measured = {}
        elapsed = float(measured.get("elapsed_seconds", 0.0))
        error = measured.get("error")
        if error:
            records.append({"config": config, "valid": False, "equivalent": False,
                            "elapsed_seconds": elapsed, "error": str(error)})
            continue
        try:
            if not _equivalent(equivalence_guard, config, measured):
                records.append({"config": config, "valid": False, "equivalent": False,
                                "elapsed_seconds": elapsed})
                continue
            throughput = _metric_value(measured, metric)
            if not math.isfinite(throughput) or throughput <= 0:
                raise ValueError("non-positive or non-finite throughput")
            record = {"config": config, "valid": True, "equivalent": True,
                      "throughput": throughput, "elapsed_seconds": elapsed}
            for key in ("items_per_sec", "peak_vram_mib"):
                if key in measured:
                    record[key] = measured[key]
            records.append(record)
            if best is None or throughput > best["throughput"]:
                best = record
        except Exception as exc:
            records.append({"config": config, "valid": False, "equivalent": False,
                            "elapsed_seconds": elapsed, "error": f"{type(exc).__name__}: {exc}"})
    chosen = best["config"] if best is not None else safe_fallback
    return {"chosen": chosen, "metric": metric, "results": records, "probes_succeeded": best is not None}


def tune_batch_worker_workload(project, *, workload, probe, batch_candidates, worker_candidates,
                               metric="items_per_sec", model=None, input_size=None, variant=None,
                               hardware=None, equivalence_guard=None, safe_fallback=None,
                               probe_many=None):
    """Tune batch first, then workers at the two fastest safe batches.

    This stays compact while avoiding both the old largest-batch mistake and
    the assumption that preprocessing workers help every batch size equally.
    """
    profile = hardware or get_hardware_profile()
    key = workload_tuning_key(workload=workload, model=model, input_size=input_size,
                              variant=variant, hardware=profile)
    cache = PerformanceCache(project)
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("probes_succeeded"):
        return {**cached, "cache_hit": True, "cache_saved": True, "tuning_key": key}
    started = time.perf_counter()

    bench = (lambda candidates: _benchmark_many(candidates, probe_many, metric=metric,
                                                equivalence_guard=equivalence_guard,
                                                safe_fallback=safe_fallback)) if probe_many is not None else (
            lambda candidates: benchmark_candidates(candidates, probe, metric=metric,
                                                   equivalence_guard=equivalence_guard,
                                                   safe_fallback=safe_fallback))
    first = bench(batch_candidates)
    records = list(first["results"])
    chosen = first.get("chosen") or safe_fallback
    first_valid = sorted(
        (row for row in records if row.get("valid") and row.get("equivalent")),
        key=lambda row: row["throughput"], reverse=True,
    )[:2]
    worker_configs = []
    seen = set()
    for row in first_valid:
        base = row["config"]
        best_batch = max(1, int(base.get("batch_size", 1)))
        for value in worker_candidates:
            workers = max(0, int(value))
            key_pair = (best_batch, workers)
            if workers == int(base.get("workers", 0)) or key_pair in seen:
                continue
            seen.add(key_pair)
            worker_configs.append({**base, "batch_size": best_batch, "workers": workers,
                                   "persistent_workers": bool(workers)})
    if worker_configs:
        second = bench(worker_configs)
        records.extend(second["results"])

    valid = [row for row in records if row.get("valid") and row.get("equivalent")]
    if valid:
        ranked = sorted(valid, key=lambda row: row["throughput"], reverse=True)
        if len(ranked) > 1 and ranked[1]["throughput"] >= ranked[0]["throughput"] * 0.97:
            # Recheck only a close pair; one noisy timing must not choose a
            # more expensive loader configuration for a negligible gain.
            close = bench([ranked[0]["config"], ranked[1]["config"]])
            records.extend(close["results"])
            failed = {json.dumps(row["config"], sort_keys=True)
                      for row in close["results"] if not row.get("valid")}
            valid = [row for row in records if row.get("valid") and row.get("equivalent")
                     and json.dumps(row["config"], sort_keys=True) not in failed]
        if valid:
            grouped = {}
            for row in valid:
                identity = json.dumps(row["config"], sort_keys=True)
                grouped.setdefault(identity, []).append(row)
            scores = [(sum(row["throughput"] for row in rows) / len(rows), rows[0]["config"])
                      for rows in grouped.values()]
            best_speed = max(score for score, _config in scores)
            near_best = [item for item in scores if item[0] >= best_speed * 0.97]
            chosen = min(near_best, key=lambda item: (
                int(item[1].get("batch_size", 1)), int(item[1].get("workers", 0)),
                bool(item[1].get("persistent_workers", False))))[1]
        else:
            chosen = safe_fallback
    else:
        chosen = safe_fallback
    result = {"chosen": chosen, "metric": metric, "results": records,
              "probes_succeeded": bool(valid), "cache_hit": False, "tuning_key": key,
              "engine_version": ENGINE_VERSION, "hardware_fingerprint": hardware_fingerprint(profile),
              "calibration_elapsed_seconds": time.perf_counter() - started}
    # Keep successful tuning across restarts, but retry later after total failure.
    if result.get("probes_succeeded"):
        result["cache_saved"] = cache.put(key, result)
    else:
        result["cache_saved"] = False
    return result


def performance_diagnostic(project, hardware: HardwareProfile | None = None) -> dict:
    """Return a compact, GUI-independent view of the authoritative AUTO cache.

    Missing workload entries are intentionally reported as ``not yet benchmarked``;
    this routine never triggers a benchmark or mutates project state.
    """
    profile = hardware or get_hardware_profile()
    cache = PerformanceCache(project)
    values, cache_status = cache.read_with_status()
    current = hardware_fingerprint(profile)
    entries = {}
    for raw_key, value in values.items():
        try:
            key = json.loads(raw_key)
        except (TypeError, ValueError):
            continue
        if key.get("hardware_fingerprint") != current or not isinstance(value, dict):
            continue
        workload = key.get("workload")
        if workload:
            entries[workload] = value.get("chosen") or {}

    labels = {
        "landmark_inference": "Landmark inference",
        "image_crop_prepare": "Image preparation",
        "landmark_project_scan": "Landmark QC",
        "landmark_worst_first": "Worst First",
        "landmark_training": "Training",
        "crop_inference": "Crop inference",
    }
    workloads = {name: entries.get(name) or "not yet benchmarked" for name in labels}
    lines = [
        "Performance mode: Auto",
        f"CPU: {profile.cpu_model} ({profile.physical_cores or 'Unknown'} physical / {profile.logical_cores} logical)",
        f"GPU: {profile.gpu_model or 'None'}",
        f"RAM: {round((profile.ram_bytes or 0) / 1024 ** 3, 1) if profile.ram_bytes else 'Unknown'} GB",
    ]
    for name, label in labels.items():
        chosen = workloads[name]
        if isinstance(chosen, dict):
            fields = ", ".join(f"{key}={value}" for key, value in chosen.items()) or "default"
            lines.append(f"{label}: tuned/cached, {fields}")
        elif isinstance(chosen, int) and name in {"landmark_project_scan", "landmark_worst_first"}:
            lines.append(f"{label}: tuned/cached, workers={chosen}")
        else:
            lines.append(f"{label}: {chosen}")
    lines.append(f"Cache status: {cache_status}")
    return {"mode": "Auto", "hardware": profile.as_dict(), "cache_status": cache_status,
            "workloads": workloads, "summary": "\n".join(lines)}
