import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import ai_hardware as hw

class HardwareCacheSafetyTests(unittest.TestCase):
    def test_environment_change_invalidates_saved_cuda_qualification(self):
        profile=hw.HardwareProfile('CPU',4,8,8*1024**3,'GPU',4096,'driver',True,'12.1','CUDA')
        with tempfile.TemporaryDirectory() as td, patch.dict('os.environ', {'LOCALAPPDATA':td}):
            with patch.object(hw, '_environment_signature', return_value={'machine':'first'}):
                hw.persist_machine_profile(profile)
                self.assertEqual(profile, hw.persisted_hardware_profile())
            with patch.object(hw, '_environment_signature', return_value={'machine':'changed'}):
                self.assertIsNone(hw.persisted_hardware_profile())
            hw.machine_profile_path().write_text('{broken',encoding='utf-8')
            self.assertIsNone(hw.persisted_hardware_profile())

    def test_corrupt_cuda_flag_is_not_truthy_gpu_support(self):
        self.assertIsNone(hw._hardware_profile_from_mapping({'cuda_available':'false'}))
        self.assertIsNone(hw._hardware_profile_from_mapping({'cuda_available':True,'logical_cores':float('inf')}))

    def test_discovered_gpu_without_backend_cuda_stays_cpu(self):
        profile=hw.HardwareProfile('CPU',2,4,4*1024**3,'GPU',4096,None,False,None,'CPU')
        config=hw.get_training_config(hardware=profile)
        self.assertEqual('cpu',config['device'])
        self.assertFalse(config['mixed_precision'])
        self.assertFalse(config['pin_memory'])

    def test_low_ram_limits_gpu_loader_processes(self):
        profile=hw.HardwareProfile('CPU',16,32,2*1024**3,'GPU',12288,None,True,'12.1','CUDA')
        config=hw.get_training_config(hardware=profile)
        self.assertEqual((1,0,False),(config['batch_size'],config['workers'],config['persistent_workers']))
