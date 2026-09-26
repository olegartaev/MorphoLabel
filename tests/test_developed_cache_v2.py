import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from app.paths import ROOT
import app.developed_cache as base
from app.developed_cache_v2 import ensure

class CacheV2Tests(unittest.TestCase):
 def test_validated_real_cache_does_not_call_raw_decoder(self):
  root=ROOT/"work"/"test_cache_v2";root.mkdir(parents=True,exist_ok=True);source=root/"sample.nef";source.write_bytes(b"disposable source")
  _,_,target,meta_path,*_=base.paths(source);target.parent.mkdir(parents=True,exist_ok=True);meta_path.parent.mkdir(parents=True,exist_ok=True)
  Image.new("RGB",(20,20)).save(target);stat=source.stat();meta={"parameters_sha256":base._params_hash(),"source_size":stat.st_size,"source_mtime_ns":stat.st_mtime_ns,"developed_full_relpath":"work/sample.png"};meta_path.write_text(__import__('json').dumps(meta),encoding="utf-8");old=base.decode
  try:
   base.decode=lambda _: (_ for _ in ()).throw(AssertionError("raw decoder invoked on cache hit"));meta=ensure(source);self.assertTrue(meta["developed_full_relpath"].endswith(".png"))
  finally:base.decode=old;shutil.rmtree(root,ignore_errors=True)
if __name__=="__main__":unittest.main()
