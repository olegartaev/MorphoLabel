"""Orientation caching preserves every model input and keeps random transforms fresh."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('torchvision'),'optional AI runtime')
class OrientationCacheTests(unittest.TestCase):
    def test_cached_inputs_are_bitwise_identical_with_fresh_augmentation(self):
        import torch
        from PIL import Image
        from ai_runtime.xray_orientation_runner import _Dataset,_transforms
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'crop.png';Image.effect_noise((420,190),80).convert('RGB').save(path)
            rows=[{'path':str(path),'head':1,'bottom':0}]
            for training in (False,True):
                dataset=_Dataset(rows,training)
                for seed in (13,28):
                    torch.manual_seed(seed);actual,target=dataset[0]
                    torch.manual_seed(seed)
                    with Image.open(path) as picture:expected=_transforms(training)(picture.convert('RGB'))
                    self.assertTrue(torch.equal(actual,expected))
                    self.assertEqual([1.,0.],target.tolist())
                self.assertEqual(1,len(dataset.resized))

    def test_cache_is_bounded_and_evicts_old_images(self):
        from PIL import Image
        from ai_runtime.xray_orientation_runner import _Dataset
        with tempfile.TemporaryDirectory() as td:
            rows=[]
            for i in range(4):
                path=Path(td)/f'{i}.png';Image.new('RGB',(32,19),(i,0,0)).save(path)
                rows.append({'path':str(path),'head':0,'bottom':0})
            dataset=_Dataset(rows);dataset.cache_limit=2
            for i in range(4):dataset[i]
            self.assertEqual([rows[2]['path'],rows[3]['path']],list(dataset.resized))
