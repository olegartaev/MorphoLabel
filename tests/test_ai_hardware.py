import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.ai_hardware import HardwareProfile, detect_hardware, get_inference_config, get_training_config, run_metadata, compact_worker_candidates, cuda_batch_candidates, persist_machine_profile, machine_profile_path
from app.ai_runtime_resolver import AI_RUNTIME_INFO_TIMEOUT


class AIHardwareTests(unittest.TestCase):
 def _runner(self, gpu=None, runtime=None, info_timeouts=None):
  def call(command, input_text=None, timeout=None):
   if command[0] == "nvidia-smi":
    output = "" if gpu is None else f"{gpu[0]}, {gpu[1]}, 555.42\n"
    return subprocess.CompletedProcess(command, 0 if gpu else 1, output, "")
   if len(command) > 2 and command[2] == "info":
    if info_timeouts is not None:
     info_timeouts.append(timeout)
    return subprocess.CompletedProcess(command, 0, json.dumps(runtime or {}) + "\n", "")
   return subprocess.CompletedProcess(command, 0, "", "")
  return call

 def test_detection_without_gpu(self):
  profile = detect_hardware(command_runner=self._runner(), runtime_python="missing-python", runner_path="missing-runner")
  self.assertFalse(profile.cuda_available)
  self.assertEqual("CPU", profile.acceleration)
  self.assertIsNone(profile.gpu_model)

 def test_detection_with_gpu_and_runtime_cuda(self):
  with tempfile.TemporaryDirectory() as temp:
   runtime = Path(temp) / "python.exe"; runner = Path(temp) / "runner.py"; runtime.touch(); runner.touch()
   profile = detect_hardware(command_runner=self._runner(("RTX Test", "12288"), {"cuda_available": True, "cuda_runtime": "12.1", "device": "RTX Test"}), runtime_python=runtime, runner_path=runner)
  self.assertTrue(profile.cuda_available)
  self.assertEqual("RTX Test", profile.gpu_model)
  self.assertEqual(12288, profile.gpu_vram_mib)
  self.assertEqual("CUDA", profile.acceleration)

 def test_modules_can_request_recommended_configs_and_metadata(self):
  gpu = HardwareProfile("CPU", 4, 8, 16, "GPU", 8192, None, True, "12", "CUDA")
  training = get_training_config(hardware=gpu)
  inference = get_inference_config(hardware=gpu)
  record = run_metadata("training", hardware=gpu)
  self.assertEqual("cuda:0", training["device"])
  self.assertTrue(training["mixed_precision"])
  self.assertLessEqual(inference["batch_size"], training["batch_size"])
  self.assertEqual("cuda:0", record["selected"]["device"])

 def test_auto_profile_scales_with_gpu_and_cpu_capacity(self):
  low=HardwareProfile("CPU",4,8,16*1024**3,"GPU",4096,None,True,"12","CUDA",4096)
  high=HardwareProfile("CPU",20,28,64*1024**3,"GPU",24576,None,True,"12","CUDA",24576)
  self.assertLess(get_training_config(hardware=low)["batch_size"],get_training_config(hardware=high)["batch_size"])
  self.assertEqual(16,get_training_config(hardware=high)["batch_size"])
  workers=compact_worker_candidates(high)
  self.assertIn(20,workers);self.assertIn(28,workers)
  self.assertEqual((1,2,4,8,16,32,64),cuda_batch_candidates(high,maximum=64))

 def test_auto_defaults_cover_vram_and_low_ram_cpu_matrix(self):
  expected=((4096,2),(8192,4),(12288,8),(24576,16))
  for vram,batch in expected:
   with self.subTest(vram_mib=vram):
    hardware=HardwareProfile("CPU",4,8,16*1024**3,"GPU",vram,None,True,"12.1","CUDA",vram)
    config=get_training_config(hardware=hardware)
    self.assertEqual(("cuda:0",batch,True,True),(config["device"],config["batch_size"],config["mixed_precision"],config["pin_memory"]))
  laptop=HardwareProfile("Laptop CPU",2,4,4*1024**3,None,None,None,False,None,"CPU")
  cpu=get_training_config(hardware=laptop)
  self.assertEqual(("cpu",1,False,False),(cpu["device"],cpu["batch_size"],cpu["mixed_precision"],cpu["pin_memory"]))

 def test_first_launch_machine_profile_is_persisted(self):
  profile=HardwareProfile("CPU",8,16,32*1024**3,"GPU",12288,None,True,"12","CUDA",12000)
  with tempfile.TemporaryDirectory() as root, patch.dict("os.environ",{"LOCALAPPDATA":root}):
   payload=persist_machine_profile(profile)
   self.assertTrue(machine_profile_path().is_file())
   stored=json.loads(machine_profile_path().read_text(encoding="utf-8"))
   self.assertEqual("GPU",stored["hardware"]["gpu_model"])
   self.assertEqual(payload["training_default"]["device"],"cuda:0")

 def test_low_resource_profile_uses_cpu_without_touching_project_data(self):
  gpu = HardwareProfile("CPU", 4, 8, 16, "GPU", 8192, None, True, "12", "CUDA")
  config = get_training_config("low resource", hardware=gpu)
  self.assertEqual({"device": "cpu", "batch_size": 1, "workers": 0, "mixed_precision": False, "pin_memory": False, "persistent_workers": False, "profile": "low_resource"}, config)


 def test_runtime_cuda_probe_allows_cold_start_window(self):
  with tempfile.TemporaryDirectory() as temp:
   runtime = Path(temp) / "python.exe"; runner = Path(temp) / "runner.py"; runtime.touch(); runner.touch()
   timeouts = []
   profile = detect_hardware(command_runner=self._runner(("RTX Test", "12288"), {"cuda_available": True, "cuda_runtime": "12.1", "device": "RTX Test"}, timeouts), runtime_python=runtime, runner_path=runner)
  self.assertTrue(profile.cuda_available)
  self.assertEqual(60, AI_RUNTIME_INFO_TIMEOUT)
  self.assertEqual([AI_RUNTIME_INFO_TIMEOUT], timeouts)

if __name__ == "__main__": unittest.main()
