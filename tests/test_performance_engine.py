import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.ai_hardware import HardwareProfile
from app.performance_engine import PerformanceCache, benchmark_candidates, cpu_worker_candidates, hardware_fingerprint, performance_diagnostic, tune_batch_worker_workload, tune_workload, workload_tuning_key, ENGINE_VERSION

class Project:
    def __init__(self, root): self.data_root = Path(root)

def profile(cores=4, gpu=None, vram=None, accel="CPU"):
    return HardwareProfile("cpu", cores, cores, 8_000_000_000, gpu, vram, None, accel == "CUDA", None, accel)

class PerformanceEngineTests(unittest.TestCase):
    def test_engine_v2_invalidates_old_conservative_tuning(self):
        self.assertEqual("2",ENGINE_VERSION)

    def test_cpu_candidates_are_bounded(self):
        self.assertEqual(cpu_worker_candidates(profile(4)), (1, 2, 4))
        self.assertEqual(cpu_worker_candidates(profile(32)), (1, 2, 4, 8, 16, 32))
        mixed = HardwareProfile("cpu", 20, 28, 16 * 1024**3, None, None, None, False, None, "CPU")
        self.assertEqual(cpu_worker_candidates(mixed), (1, 2, 4, 8, 16, 20, 28))

    def test_hardware_discovery_is_cached_until_explicit_refresh(self):
        from unittest.mock import patch
        import app.ai_hardware as hardware
        value = profile(8)
        with patch("app.ai_hardware.persisted_hardware_profile", return_value=None), \
             patch("app.ai_hardware.detect_hardware", return_value=value) as detected:
            hardware._HARDWARE_PROFILE = None
            self.assertIs(value, hardware.get_hardware_profile())
            self.assertIs(value, hardware.get_hardware_profile())
            self.assertEqual(detected.call_count, 1)
            hardware.get_hardware_profile(refresh=True)
            self.assertEqual(detected.call_count, 2)
        hardware._HARDWARE_PROFILE = None
    def test_crop_auto_candidates_reach_full_machine_capacity(self):
        from unittest.mock import patch
        from app.crop_parallel import auto_config
        captured = {}
        def tuned(*_args, **kwargs):
            captured["candidates"] = kwargs["candidates"]
            return {"chosen": kwargs["candidates"][-1], "cache_hit": False, "results": []}
        with patch("app.crop_parallel.get_hardware_profile", return_value=HardwareProfile("cpu", 32, 32, 16 * 1024**3, None, None, None, False, None, "CPU")), patch("app.crop_parallel.tune_workload", side_effect=tuned):
            config = auto_config(Project(tempfile.mkdtemp()), sample=("probe",), prepare=lambda _: None)
        self.assertEqual(32, max(item["workers"] for item in captured["candidates"]))
        self.assertEqual(32, config["workers"])
    def test_tuner_chooses_highest_valid_throughput_and_survives_failures(self):
        result = benchmark_candidates([1, 2, 4], lambda c: (_ for _ in ()).throw(RuntimeError("OOM")) if c == 2 else {"items_per_sec": {1: 3, 4: 7}[c]}, safe_fallback=1)
        self.assertEqual(result["chosen"], 4); self.assertEqual(len(result["results"]), 3)
        rejected = benchmark_candidates([1, 2], lambda c: {"items_per_sec": c}, equivalence_guard=lambda c, r: c != 2, safe_fallback=1)
        self.assertEqual(rejected["chosen"], 1)

    def test_grouped_training_probe_uses_two_runtime_calls(self):
        calls=[]
        candidates=[{"batch_size":1,"workers":0},{"batch_size":8,"workers":0},{"batch_size":16,"workers":0}]
        def grouped(configs):
            calls.append([(item["batch_size"],item["workers"]) for item in configs])
            rows=[]
            for item in configs:
                batch,workers=item["batch_size"],item["workers"]
                speed={1:5.0,8:20.0,16:15.0}[batch] + (5.0 if batch==8 and workers==4 else 0.0)
                rows.append({"items_per_sec":speed,"peak_vram_mib":1000,"elapsed_seconds":0.1})
            return rows
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            result=tune_batch_worker_workload(Project(root),workload="grouped",model="m",input_size=(512,256),hardware=profile(8,"GPU",12000,"CUDA"),batch_candidates=candidates,worker_candidates=(0,1,4),probe=lambda _: (_ for _ in ()).throw(AssertionError("scalar probe should not run")),probe_many=grouped,safe_fallback={"batch_size":1,"workers":0})
        self.assertEqual((8,4),(result["chosen"]["batch_size"],result["chosen"]["workers"]))
        self.assertEqual(2,len(calls))
        self.assertEqual([(1,0),(8,0),(16,0)],calls[0])
        self.assertIn((8,4),calls[1])
        self.assertIn((16,4),calls[1])

    def test_close_training_candidates_are_rechecked_and_choose_safer_batch(self):
        calls=[]
        def grouped(configs):
            calls.append(tuple(item["batch_size"] for item in configs))
            return [{"items_per_sec": 100.0 if item["batch_size"] == 4 else 101.0,
                     "peak_vram_mib": 1000} for item in configs]
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            result=tune_batch_worker_workload(Project(root),workload="close-training",model="m",input_size=(512,256),hardware=profile(8,"GPU",12000,"CUDA"),batch_candidates=[{"batch_size":4,"workers":0},{"batch_size":8,"workers":0}],worker_candidates=(0,),probe=lambda _config:None,probe_many=grouped,safe_fallback={"batch_size":1,"workers":0})
        self.assertEqual([(4,8),(8,4)],calls)
        self.assertEqual(4,result["chosen"]["batch_size"])

    def test_successful_runtime_fallback_persists_safe_batch(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            cache=PerformanceCache(Project(root)); key=workload_tuning_key(workload="landmark_training",model="m",input_size=(512,256),hardware=profile(8,"GPU",12000,"CUDA"))
            self.assertTrue(cache.put(key,{"chosen":{"batch_size":8,"workers":2},"probes_succeeded":True,"results":[{"valid":True,"throughput":10.0}]}))
            self.assertTrue(cache.record_runtime_fallback(key,8,4))
            reopened=PerformanceCache(Project(root)).get(key)
        self.assertEqual(4,reopened["chosen"]["batch_size"])
        self.assertTrue(reopened["runtime_fallback"]["validated_by_completed_job"])

    def test_concurrent_machine_cache_updates_keep_both_processes(self):
        code=("from app.performance_engine import PerformanceCache; import sys; "
              "cache=PerformanceCache(); "
              "[cache.put(sys.argv[1]+str(i), {'value':i}) for i in range(10)]")
        with tempfile.TemporaryDirectory() as root:
            environment={**os.environ,"LOCALAPPDATA":root}
            processes=[subprocess.Popen([sys.executable,"-c",code,prefix],cwd=Path(__file__).resolve().parents[1],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for prefix in ("left","right")]
            for process in processes:
                stdout,stderr=process.communicate(timeout=10)
                self.assertEqual(0,process.returncode,stderr or stdout)
            with patch.dict(os.environ, {"LOCALAPPDATA": root}):
                self.assertEqual(20,len(PerformanceCache(Project(root)).read()))

    def test_all_failures_return_fallback(self):
        result = benchmark_candidates([1, 2], lambda _: (_ for _ in ()).throw(RuntimeError("OOM")), safe_fallback=1)
        self.assertEqual(result["chosen"], 1); self.assertFalse(result["probes_succeeded"])

    def test_total_probe_failure_is_not_cached(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            project=Project(root);calls=[]
            first=tune_workload(project,workload="retry-after-failure",model="m",input_size=(1,1),hardware=profile(),candidates=[1],probe=lambda c:(calls.append(c) or (_ for _ in ()).throw(RuntimeError("temporary"))),safe_fallback=1)
            self.assertFalse(first["probes_succeeded"])
            self.assertIsNone(PerformanceCache(project).get(first["tuning_key"]))
            second=tune_workload(project,workload="retry-after-failure",model="m",input_size=(1,1),hardware=profile(),candidates=[1],probe=lambda c:{"items_per_sec":2.0},safe_fallback=1)
            self.assertFalse(second["cache_hit"]);self.assertTrue(second["probes_succeeded"])

    def test_keys_change_with_hardware_and_workload_identity(self):
        a = profile(4); b = profile(8, "GPU", 12000, "CUDA")
        self.assertNotEqual(hardware_fingerprint(a), hardware_fingerprint(b))
        self.assertNotEqual(workload_tuning_key(workload="x", model="m", input_size=(1, 2), hardware=a), workload_tuning_key(workload="x", model="m2", input_size=(1, 2), hardware=a))
        self.assertNotEqual(workload_tuning_key(workload="x", model="m", input_size=(1, 2), hardware=a), workload_tuning_key(workload="x", model="m", input_size=(2, 2), hardware=a))

    def test_driver_cuda_ram_and_core_changes_invalidate_machine_key(self):
        baseline = profile(8, "GPU", 12288, "CUDA")
        variants = (
            HardwareProfile(**{**baseline.as_dict(), "gpu_driver": "new-driver"}),
            HardwareProfile(**{**baseline.as_dict(), "cuda_runtime": "new-cuda"}),
            HardwareProfile(**{**baseline.as_dict(), "ram_bytes": 4 * 1024**3}),
            HardwareProfile(**{**baseline.as_dict(), "logical_cores": 32}),
        )
        key = workload_tuning_key(workload="landmark_training", model="rtmpose_v001",
                                  input_size=(512, 256), hardware=baseline)
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertNotEqual(key, workload_tuning_key(
                    workload="landmark_training", model="rtmpose_v002",
                    input_size=(512, 256), hardware=changed))

    def test_checkpoint_versions_reuse_architecture_tuning_identity(self):
        hardware = profile(8, "GPU", 12_000, "CUDA")
        first = workload_tuning_key(workload="landmark_training", model="rtmpose_v001",
                                    input_size=(640, 320), variant="architecture-v1", hardware=hardware)
        second = workload_tuning_key(workload="landmark_training", model="rtmpose_v002",
                                     input_size=(640, 320), variant="architecture-v1", hardware=hardware)
        changed = workload_tuning_key(workload="landmark_training", model="rtmpose_v002",
                                      input_size=(768, 384), variant="architecture-v1", hardware=hardware)
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_hardware_model_resolution_and_variant_invalidate_cache_keys(self):
        base = profile(8, "RTX-like", 8192, "CUDA")
        variants = (
            profile(8, "RTX-like", 8192, "CPU"),
            profile(16, "RTX-like", 8192, "CUDA"),
            profile(8, "RTX-like", 16384, "CUDA"),
            HardwareProfile("cpu", 8, 8, 8_000_000_000, "RTX-like", 8192, "new-driver", True, None, "CUDA"),
            HardwareProfile("other-cpu", 8, 8, 16_000_000_000, "RTX-like", 8192, None, True, "12.x", "CUDA"),
        )
        key = workload_tuning_key(workload="review", model="m1", input_size=(512, 256), variant="v1", hardware=base)
        self.assertTrue(all(key != workload_tuning_key(workload="review", model="m1", input_size=(512, 256), variant="v1", hardware=item) for item in variants))
        self.assertNotEqual(key, workload_tuning_key(workload="review", model="m2", input_size=(512, 256), variant="v1", hardware=base))
        self.assertNotEqual(key, workload_tuning_key(workload="review", model="m1", input_size=(640, 320), variant="v1", hardware=base))
        self.assertNotEqual(key, workload_tuning_key(workload="review", model="m1", input_size=(512, 256), variant="v2", hardware=base))

    def test_corrupt_cache_recovers_and_diagnostic_is_read_only(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            project = Project(root); cache = PerformanceCache(project)
            cache.path.parent.mkdir(parents=True, exist_ok=True); cache.path.write_text("not-json", encoding="utf-8")
            self.assertEqual(cache.read_with_status()[1], "corrupt")
            result = tune_workload(project, workload="landmark_inference", model="m", input_size=(512, 256), hardware=profile(), candidates=[{"batch_size": 1}], probe=lambda _: {"items_per_sec": 1.0}, safe_fallback={"batch_size": 1})
            self.assertEqual(result["chosen"], {"batch_size": 1})
            before = cache.path.read_bytes(); diagnostic = performance_diagnostic(project, profile())
            self.assertEqual(diagnostic["cache_status"], "valid"); self.assertEqual(diagnostic["workloads"]["landmark_inference"], {"batch_size": 1})
            self.assertEqual(before, cache.path.read_bytes())
    def test_failed_cached_calibration_is_ignored(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            project=Project(root);hardware=profile(8,"GPU",12000,"CUDA")
            key=workload_tuning_key(workload="failed-cache",model="m",input_size=(512,256),hardware=hardware)
            PerformanceCache(project).put(key,{"chosen":{"batch_size":1,"workers":0},"probes_succeeded":False,"results":[]})
            calls=[]
            result=tune_workload(project,workload="failed-cache",model="m",input_size=(512,256),hardware=hardware,candidates=[1,2],probe=lambda c:(calls.append(c) or {"items_per_sec":float(c)}),safe_fallback=1)
            self.assertFalse(result["cache_hit"])
            self.assertEqual([1,2],calls)
            self.assertEqual(2,result["chosen"])

    def test_cache_reuse_and_restart(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            project = Project(root); calls = []
            first = tune_workload(project, workload="demo", model="m", input_size=(10, 10), hardware=profile(), candidates=[1, 2], probe=lambda c: (calls.append(c) or {"items_per_sec": c}), safe_fallback=1)
            second = tune_workload(project, workload="demo", model="m", input_size=(10, 10), hardware=profile(), candidates=[1, 2], probe=lambda _: (_ for _ in ()).throw(AssertionError("rerun")), safe_fallback=1)
            self.assertEqual(first["chosen"], 2); self.assertTrue(second["cache_hit"]); self.assertEqual(calls, [1, 2])
            self.assertGreaterEqual(first["calibration_elapsed_seconds"],0)
            self.assertEqual(first["calibration_elapsed_seconds"],second["calibration_elapsed_seconds"])
            self.assertTrue((Path(root) / "MorphoLabel" / "performance_engine_tuning.json").is_file())
            self.assertEqual(PerformanceCache(project).get(first["tuning_key"])["chosen"], 2)
    def test_performance_cache_is_owned_by_morpholabel_app_state(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LOCALAPPDATA": root}):
            cache=PerformanceCache()
            self.assertEqual(Path(root)/"MorphoLabel"/"performance_engine_tuning.json", cache.path)
            self.assertNotIn("SIMM", cache.path.parts)

    def test_grouped_probe_shape_failure_does_not_cache(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{"LOCALAPPDATA":root}):
            result=tune_batch_worker_workload(Project(root),workload="shape-failure",model="m",input_size=(512,256),hardware=profile(8,"GPU",12000,"CUDA"),batch_candidates=[{"batch_size":1,"workers":0},{"batch_size":2,"workers":0}],worker_candidates=(0,2),probe=lambda _config:None,probe_many=lambda _configs:[{"items_per_sec":1.0}],safe_fallback={"batch_size":1,"workers":0})
            self.assertFalse(result["probes_succeeded"])
            self.assertIsNone(PerformanceCache().get(result["tuning_key"]))

if __name__ == "__main__": unittest.main()
