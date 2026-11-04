"""CPU/no-network tests for frozen-to-fine-tuned portable multires candidates."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile,ZIP_DEFLATED

from tools.train_universal_multires import new_package,inspect_source_package


class TestTrainingPackage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        def sha(b):return hashlib.sha256(b).hexdigest()
        self.source={
            "artifacts/model.pth":b"primary unchanged",
            "artifacts/detail.pth":b"old detail",
            "artifacts/native.pth":b"old native",
        }
        self.meta={
            "model_id":"original","schema_digest":"a"*64,
            "input_size":[768,256],"output_stride":2,
            "structures":[{"id":"cell_center","repeated":True},
                          {"id":"leaf_tip","repeated":False}],
            "thresholds":{"cell_center":.30,"leaf_tip":.4},
            "inference_pipeline":{
                "name":"multires_heatmap_v1","version":1,"mode":"tiled_native",
                "detail":{"checkpoint":"detail.pth","sha256":sha(b"old detail"),
                          "input_size":[768,384]},
                "native":{"checkpoint":"native.pth","sha256":sha(b"old native"),
                          "input_size":[1536,512],"state_prefix":"base."},
                "retain_detail_structures":["cell_center"],
                "fusion_weight":.6,
                "tiles":{"nx":4,"ny":2,"width_fraction":.38,"height_fraction":.62},
            }
        }
        self.source["artifacts/model.json"]=json.dumps(self.meta).encode()
        self.manifest={
            "package_format":"morpholabel_structure_model_v1",
            "backend":"resnet18_heatmap_v1","schema_digest":"a"*64,
            "model_id":"original",
            "files":{k:sha(v) for k,v in self.source.items()}}
        self.pack=self.root/"source.zip"
        with ZipFile(self.pack,"w",ZIP_DEFLATED) as z:
            for k,v in self.source.items():z.writestr(k,v)
            z.writestr("manifest.json",json.dumps(self.manifest))
        self.prov={
            "training_specimens":42,"validation_specimens":11,
            "dataset_hash":"sample_hash","independent_validation_proven":False}

    def test_nonfish_model_retrained_package_is_inactive_and_hash_locked(self):
        manifest,meta,data=inspect_source_package(self.pack)
        dest=self.root/"new.zip"
        result=new_package(manifest,meta,data,b"new detail",b"new native",
                           dest,model_id="generic_v2",provenance=self.prov)
        self.assertEqual(result["model_id"],"generic_v2")
        with ZipFile(dest) as z:
            self.assertIsNone(z.testzip())
            updated=json.loads(z.read("artifacts/model.json"))
            m=json.loads(z.read("manifest.json"))
            self.assertEqual(updated["model_id"],"generic_v2")
            self.assertEqual(updated["thresholds"],self.meta["thresholds"])
            self.assertEqual(updated["inference_pipeline"]["retain_detail_structures"],
                             ["cell_center"])
            self.assertEqual(z.read("artifacts/model.pth"),self.source["artifacts/model.pth"])
            self.assertEqual(z.read("artifacts/detail.pth"),b"new detail")
            self.assertEqual(z.read("artifacts/native.pth"),b"new native")
            self.assertEqual(m["training_statistics"]["training_specimen_count"],42)
            self.assertTrue(m["training_statistics"]["metrics"]["inference/unvalidated"])
            for name,digest in m["files"].items():
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),digest)

    def test_source_zip_integrity(self):
        inspect_source_package(self.pack)
        corrupted=self.root/"corrupt.zip"
        with ZipFile(corrupted,"w",ZIP_DEFLATED) as z:
            z.writestr("manifest.json",json.dumps(self.manifest))
            for k,v in self.source.items():
                z.writestr(k,b"modified" if k=="artifacts/detail.pth" else v)
        with self.assertRaisesRegex(ValueError,"SHA256"):
            inspect_source_package(corrupted)

    def test_refuse_overwrite(self):
        target=self.root/"existing.zip";target.write_bytes(b"untouched")
        with self.assertRaises(FileExistsError):
            new_package(self.manifest,self.meta,self.source,b"more",b"native",
                        target,model_id="generic_v2",provenance=self.prov)
        self.assertEqual(target.read_bytes(),b"untouched")

if __name__=="__main__":unittest.main()
