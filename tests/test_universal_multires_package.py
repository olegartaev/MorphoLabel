"""Portable multiresolution model packaging: synthetic non-fish schema."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile,ZIP_DEFLATED
import torch
from tools.package_universal_multires import package_candidate
from ai_runtime.universal_multires import component_files

class TestUniversalPackage(unittest.TestCase):
    def test_three_component_inactive_model(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);old=r/"old.zip";detail=r/"detail.pth";native=r/"native.pth"
            thresholds=r/"thresholds.json";out=r/"candidate.zip"
            state={"head.weight":torch.zeros(2,3,1,1),"encoder.weight":torch.zeros(3,3,3,3)}
            b=BytesIO();torch.save(state,b);data=b.getvalue()
            detail.write_bytes(data)
            b=BytesIO();torch.save({"base."+k:v for k,v in state.items()},b)
            native.write_bytes(b.getvalue())
            meta={"backend":"resnet18_heatmap_v1","model_id":"old",
                  "schema_digest":"a"*64,"input_size":[64,32],"output_stride":2,
                  "structures":[{"id":"leaf_vein","repeated":True},{"id":"cell","repeated":False}]}
            mb=json.dumps(meta).encode()
            manifest={"package_format":"test_v1","backend":meta["backend"],
                      "schema_digest":meta["schema_digest"],
                      "files":{"artifacts/model.pth":hashlib.sha256(data).hexdigest(),
                               "artifacts/model.json":hashlib.sha256(mb).hexdigest()}}
            with ZipFile(old,"w",ZIP_DEFLATED) as z:
                z.writestr("artifacts/model.pth",data)
                z.writestr("artifacts/model.json",mb)
                z.writestr("manifest.json",json.dumps(manifest))
            thresholds.write_text(json.dumps({"leaf_vein":.3,"cell":.5}))
            report=package_candidate(old,detail,native,thresholds,out,
                                     retain_structures=["leaf_vein"])
            self.assertTrue(report["inactive"])
            self.assertEqual(report["mode"],"tiled_native")
            with ZipFile(out) as z:
                self.assertIsNone(z.testzip())
                candidate=json.loads(z.read("artifacts/model.json"))
                self.assertEqual(set(component_files(candidate)),{"detail.pth","native.pth"})
                self.assertEqual(candidate["inference_pipeline"]["retain_detail_structures"],["leaf_vein"])
                self.assertEqual(candidate["thresholds"]["cell"],.5)
                self.assertEqual(len(z.namelist()),5)
    def test_legacy_package_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            x=Path(d)/"exists.zip";x.write_bytes(b"leave unchanged")
            with self.assertRaises(FileExistsError):
                package_candidate(x,x,None,x,x)
            self.assertEqual(x.read_bytes(),b"leave unchanged")

if __name__=="__main__":unittest.main()
