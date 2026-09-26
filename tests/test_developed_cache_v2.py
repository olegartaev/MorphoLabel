import unittest
from pathlib import Path
import app.developed_cache as base
from app.developed_cache_v2 import ensure

class CacheV2Tests(unittest.TestCase):
 def test_validated_real_cache_does_not_call_raw_decoder(self):
  source=Path("orig_photos/ob-altay_Katun_Nizh-Ujmon_RU_25/img_008662.nef");old=base.decode
  try:
   base.decode=lambda _: (_ for _ in ()).throw(AssertionError("raw decoder invoked on cache hit"));meta=ensure(source);self.assertTrue(meta["developed_full_relpath"].endswith(".png"))
  finally:base.decode=old
if __name__=="__main__":unittest.main()
