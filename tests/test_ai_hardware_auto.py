import os,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from app.ai_hardware import HardwareProfile,auto_performance_config
class P:
 def __init__(self,d):self.data_root=Path(d)
class T(unittest.TestCase):
 def test_auto_cpu_vram_oom_cache(self):
  with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'LOCALAPPDATA': d}):
   p=P(d);mk=lambda cuda,vram:HardwareProfile('x',1,4,None,'gpu' if cuda else None,vram,None,cuda,None,'CUDA' if cuda else 'CPU')
   self.assertEqual(1,auto_performance_config(p,workload='x',model='cpu',input_size=(1,1),hardware=mk(False,None))['batch_size'])
   self.assertEqual(2,auto_performance_config(p,workload='x',model='low',input_size=(1,1),hardware=mk(True,4096))['batch_size'])
   self.assertEqual(8,auto_performance_config(p,workload='x',model='twelve',input_size=(1,1),hardware=mk(True,12288))['batch_size'])
   self.assertEqual(16,auto_performance_config(p,workload='x',model='high',input_size=(1,1),hardware=mk(True,24576))['batch_size'])
   h=mk(True,12288)
   def probe(b):
    if b==8: raise RuntimeError("CUDA out of memory")
    return {"peak_vram_mib":100}
   r=auto_performance_config(p,workload="x",model="oom",input_size=(1,1),hardware=h,probe=probe);self.assertEqual(4,r["batch_size"])
   cached=auto_performance_config(p,workload="x",model="oom",input_size=(1,1),hardware=h,probe=lambda b: (_ for _ in ()).throw(AssertionError("probe reused")));self.assertEqual("cache",cached["tuning_source"])
if __name__=='__main__':unittest.main()
