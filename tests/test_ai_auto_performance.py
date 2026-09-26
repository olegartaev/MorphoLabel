import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ai_hardware import HardwareProfile, auto_performance_config, get_inference_config, get_training_config
from app.landmark_ai_service import LandmarkAIService, PredictionWriteResult


class AutoPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = SimpleNamespace(data_root=Path(self.temporary.name))
        self.localappdata_patch = patch.dict(os.environ, {"LOCALAPPDATA": self.temporary.name})
        self.localappdata_patch.start()

    def tearDown(self):
        self.localappdata_patch.stop()
        self.temporary.cleanup()

    def hardware(self, vram, cuda=True):
        return HardwareProfile("CPU", 8, 16, 32 * 1024**3, "GPU" if cuda else None, vram, None, cuda, "12.0" if cuda else None, "CUDA" if cuda else "CPU", vram)

    def test_low_vram_cuda_selects_smaller_safe_training_batch(self):
        self.assertLess(get_training_config(hardware=self.hardware(4096))["batch_size"], get_training_config(hardware=self.hardware(24576))["batch_size"])

    def test_high_vram_cuda_selects_larger_useful_training_batch(self):
        config=get_training_config(hardware=self.hardware(24576))
        self.assertGreaterEqual(config["batch_size"], 8); self.assertTrue(config["mixed_precision"]); self.assertTrue(config["pin_memory"])

    def test_simulated_training_oom_falls_back_to_safe_batch(self):
        def probe(batch):
            if batch >= 4: raise RuntimeError("CUDA out of memory")
            return {"peak_vram_mib": 1000}
        config=auto_performance_config(self.project,workload="training-oom",model="model",input_size=(512,256),training=True,hardware=self.hardware(12288),probe=probe)
        self.assertEqual(2, config["batch_size"])

    def test_training_configuration_probe_can_select_safe_workers(self):
        seen=[]
        def probe(config):
            seen.append(dict(config))
            if config["batch_size"] >= 16: raise RuntimeError("CUDA out of memory")
            if config["batch_size"] >= 8 and config["workers"] >= 4:
                return {"items_per_sec": 25.0, "peak_vram_mib": 2000}
            return {"items_per_sec": float(config["batch_size"] + config["workers"]), "peak_vram_mib": 1000}
        config=auto_performance_config(self.project,workload="training-config",model="model",input_size=(512,256),training=True,hardware=self.hardware(12288),probe=probe,probe_configurations=True,candidate_configurations=[{"batch_size":1,"workers":0},{"batch_size":8,"workers":0},{"batch_size":16,"workers":0}],staged_worker_candidates=(0,1,4,8))
        self.assertEqual((8,4),(config["batch_size"],config["workers"]))
        self.assertTrue(config["persistent_workers"]); self.assertTrue(config["pin_memory"])
        self.assertTrue(all(isinstance(item,dict) for item in seen))
        self.assertIn((8,4),[(item["batch_size"],item["workers"]) for item in seen])
        self.assertNotIn((16,4),[(item["batch_size"],item["workers"]) for item in seen])
    def test_inference_uses_batches_and_retries_after_simulated_oom(self):
        class Backend:
            model_id = "model"; schema_sha256 = "schema"
            def __init__(self): self.calls=[]
            def model_info(self): return {}
            def predict_readonly_many(self, requests):
                self.calls.append(len(requests))
                if len(requests) > 2: raise RuntimeError("CUDA out of memory")
                return tuple(SimpleNamespace(image_id=request.image_id, model_id="model") for request in requests)
        backend=Backend(); service=LandmarkAIService.__new__(LandmarkAIService)
        service.backend=backend
        service.project=SimpleNamespace(data_root=self.project.data_root, model_metadata=lambda _id: {"kind":"landmark","schema_sha256":"schema"}, register_model=lambda *_args, **_kwargs: None)
        service._request=lambda image_id: SimpleNamespace(image_id=image_id, schema_sha256="schema", schema=({"id": 1},), width=512, height=256)
        service._persist_prediction=lambda request, _prediction: PredictionWriteResult(request.image_id,Path("image"),1,0,"run",Path("manifest"))
        summary=service.predict_many(("1","2","3","4"))
        self.assertEqual([4,2,2],backend.calls);self.assertEqual(4,summary.succeeded)
    def test_inference_configuration_is_valid_for_cpu_only(self):
        config=get_inference_config(hardware=self.hardware(None, cuda=False))
        self.assertEqual("cpu",config["device"]);self.assertFalse(config["mixed_precision"]);self.assertFalse(config["pin_memory"])

    def test_cached_hardware_tuning_is_reused(self):
        calls=[]
        variant=f"unit-cache-{Path(self.temporary.name).name}"
        first=auto_performance_config(self.project,workload="training-cache",model="model",input_size=(512,256),training=True,hardware=self.hardware(12288),probe=lambda batch: calls.append(batch) or {},tuning_variant=variant)
        second=auto_performance_config(self.project,workload="training-cache",model="model",input_size=(512,256),training=True,hardware=self.hardware(12288),probe=lambda _batch: (_ for _ in ()).throw(AssertionError("probe reused")),tuning_variant=variant)
        self.assertEqual(first["batch_size"],second["batch_size"]);self.assertEqual("cache",second["tuning_source"]);self.assertTrue(calls)


    def test_validated_inference_cache_is_reused_without_probe(self):
        from app.ai_hardware import record_inference_batch
        hardware=self.hardware(12288)
        variant="unit-inference-no-probe"
        recorded=record_inference_batch(self.project,workload="landmark_inference",model="m",input_size=(512,256),batch_size=8,hardware=hardware,validated=True,tuning_variant=variant,benchmark_rows=[{"batch_size":8,"prefetch_workers":2,"prefetch_depth":2,"effective_batch_size":8,"scientifically_equivalent":True,"images_per_second":25.0,"rank_seconds":1.0}],calibration_elapsed_seconds=3.5)
        cached=auto_performance_config(self.project,workload="landmark_inference",model="m",input_size=(512,256),hardware=hardware,tuning_variant=variant)
        self.assertTrue(recorded["cache_saved"])
        self.assertEqual("cache",cached["tuning_source"])
        self.assertEqual((8,2,2),(cached["batch_size"],cached["prefetch_workers"],cached["prefetch_depth"]))

    def test_successful_inference_runtime_oom_updates_machine_cache(self):
        from app.ai_hardware import record_inference_batch
        hardware = self.hardware(12288)
        variant = "runtime-oom-cache-update"
        measured = record_inference_batch(
            self.project, workload="landmark_inference", model="m", input_size=(512, 256),
            batch_size=8, hardware=hardware, validated=True, tuning_variant=variant,
            benchmark_rows=[{"batch_size": 8, "effective_batch_size": 8,
                             "scientifically_equivalent": True, "images_per_second": 20.0}],
        )
        self.assertTrue(measured["cache_saved"])
        fallback = record_inference_batch(
            self.project, workload="landmark_inference", model="m", input_size=(512, 256),
            batch_size=4, attempted_batch=8, hardware=hardware, tuning_variant=variant,
        )
        cached = auto_performance_config(
            self.project, workload="landmark_inference", model="m", input_size=(512, 256),
            hardware=hardware, tuning_variant=variant,
        )
        self.assertTrue(fallback["cache_saved"])
        self.assertEqual(("cache", 4), (cached["tuning_source"], cached["batch_size"]))

    def test_validated_cache_write_failure_is_nonfatal(self):
        from unittest.mock import patch
        from app.ai_hardware import record_inference_batch
        with patch("app.performance_engine.atomic_json_write", side_effect=OSError("read-only cache")):
            result = record_inference_batch(self.project, workload="inference-cache-write", model="m", input_size=(512,256), batch_size=4, hardware=self.hardware(12288), validated=True,benchmark_rows=[{"batch_size":4,"images_per_second":10.0,"scientifically_equivalent":True}])
        self.assertEqual(4, result["batch_size"])
        self.assertFalse(result["cache_saved"])

    def test_inference_selects_fastest_measured_candidate(self):
        from app.ai_hardware import record_inference_batch
        hardware=self.hardware(12288)
        rows=[{"batch_size":4,"prefetch_workers":0,"prefetch_depth":1,"images_per_second":10.0,"scientifically_equivalent":True,"rank_seconds":2.0},{"batch_size":8,"prefetch_workers":2,"prefetch_depth":2,"images_per_second":21.0,"scientifically_equivalent":True,"rank_seconds":1.0},{"batch_size":16,"effective_batch_size":8,"images_per_second":30.0,"scientifically_equivalent":True,"rank_seconds":0.5}]
        selected=record_inference_batch(self.project,workload="landmark_inference",model="m",input_size=(512,256),batch_size=4,hardware=hardware,validated=True,tuning_variant="ranked-inference",benchmark_rows=rows,calibration_elapsed_seconds=3.5)
        self.assertEqual((8,2,2),(selected["batch_size"],selected["prefetch_workers"],selected["prefetch_depth"]))
        self.assertTrue(selected["cache_saved"])

    def test_inference_rejects_failed_and_non_equivalent_measurements(self):
        from app.ai_hardware import record_inference_batch
        from app.performance_engine import PerformanceCache
        hardware=self.hardware(12288)
        result=record_inference_batch(self.project,workload="landmark_inference",model="m",input_size=(512,256),batch_size=8,hardware=hardware,validated=True,tuning_variant="invalid-inference",benchmark_rows=[{"batch_size":8,"images_per_second":100.0,"scientifically_equivalent":False},{"batch_size":4,"error":"CUDA out of memory"}])
        self.assertEqual("fallback",result["tuning_source"])
        self.assertIsNone(PerformanceCache(self.project).get(result["tuning_key"]))

    def test_total_training_probe_failure_is_reported_as_fallback(self):
        result=auto_performance_config(self.project,workload="training-fallback",model="m",input_size=(512,256),training=True,hardware=self.hardware(12288),probe=lambda _config: (_ for _ in ()).throw(RuntimeError("probe failed")),probe_configurations=True)
        self.assertEqual("fallback",result["tuning_source"])
        self.assertEqual(1,result["batch_size"])
        self.assertTrue(result["tuning_errors"])

    def test_configuration_probe_requires_measured_items_per_sec(self):
        result = auto_performance_config(self.project, workload="training-metric", model="m", input_size=(512,256), training=True, hardware=self.hardware(12288), probe=lambda _config: {"samples_per_second": 999}, probe_configurations=True)
        self.assertEqual(1, result["batch_size"])
if __name__ == "__main__":
    unittest.main()
